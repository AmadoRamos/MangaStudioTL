"""Motor de OCR híbrido: RapidOCR primero, Tesseract de reserva.

Los dos leen el mismo recorte y se turnan por una regla sola: si
RapidOCR no devuelve texto, lee Tesseract. No es un empate de gustos,
sale de medir los dos sobre las 40 marcas de ``example/``:

===========================  ======  ========  =========
motor                           CER  mediana   perfectos
===========================  ======  ========  =========
híbrido                       0,049     0,000      21/40
tesseract (recorte ceñido)    0,065     0,046       9/40
rapidocr (con contexto)       0,067     0,010      20/40
===========================  ======  ========  =========

Medido con el stack del proyecto (OpenCV 4.11, NumPy 1.26, los que clava
``simple-lama-inpainting``). La cifra depende de él: con OpenCV 5.0 el
mismo código daba 0,042, porque RapidOCR preprocesa con OpenCV y dos
recortes de cuarenta cambian. La mediana y los perfectos no se movieron.

RapidOCR lee mucho mejor el rotulado de cómic —donde Tesseract confunde
``U`` con ``LI``, ``IS`` con ``15``, y salpica paréntesis en las fuentes
stencil— pero de vez en cuando no ve el texto y devuelve nada. Ese vacío
es la señal: es *detectable*, al revés que un ``LIGH...`` de Tesseract,
que se cuela como texto plausible. Ahí Tesseract acierta, y por eso se
queda.

RapidOCR corre sobre onnxruntime, que ya viaja en el paquete —lo arrastra
``minisbd``, dependencia de argostranslate—, así que solo suman sus
modelos ONNX.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from src.config import OCR_MIN_CROP_HEIGHT, OCR_SCALE_FACTOR, OCR_TESSERACT_CMD
from src.utils.logger import get_logger

log = get_logger("ocr_engine")

try:
    import pytesseract

    if OCR_TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = OCR_TESSERACT_CMD

    _PIL_AVAILABLE: bool = True
    _IMPORT_ERROR: str | None = None
except Exception as exc:
    pytesseract = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False
    _IMPORT_ERROR = str(exc)
    log.warning("pytesseract no disponible: %s", exc)

try:
    from rapidocr_onnxruntime import RapidOCR

    _RAPID_AVAILABLE: bool = True
    _RAPID_IMPORT_ERROR: str | None = None
except Exception as exc:
    RapidOCR = None  # type: ignore[assignment]
    _RAPID_AVAILABLE = False
    _RAPID_IMPORT_ERROR = str(exc)
    log.warning("rapidocr no disponible: %s", exc)


@dataclass(frozen=True)
class OcrResult:
    """Result of an OCR pass on a single crop."""

    text: str
    confidence: int
    language: str
    #: Quién lo leyó: ``"rapidocr"`` o ``"tesseract"``. Va al sidecar, que
    #: es lo único que permite saber luego por qué una página salió mejor
    #: o peor que la de al lado.
    engine: str = ""


_WINDOWS_COMMON_DIRS: tuple[str, ...] = (
    r"C:\Program Files\Tesseract-OCR",
    r"C:\Program Files (x86)\Tesseract-OCR",
    r"C:\Program Files\Tesseract",
    r"C:\Tools\Tesseract-OCR",
    r"C:\Tesseract-OCR",
)

_USERPROFILE_DIRS: tuple[str, ...] = (
    r"%LOCALAPPDATA%\Programs\Tesseract-OCR",
    r"%LOCALAPPDATA%\Tesseract-OCR",
)


def _candidate_tesseract_paths() -> list[Path]:
    """Return a list of candidate executable paths to check."""
    candidates: list[Path] = []
    exe_name = "tesseract.exe" if sys.platform == "win32" else "tesseract"

    for d in _WINDOWS_COMMON_DIRS:
        candidates.append(Path(d) / exe_name)

    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        candidates.append(Path(local_app) / "Programs" / "Tesseract-OCR" / exe_name)
        candidates.append(Path(local_app) / "Tesseract-OCR" / exe_name)

    userprofile = os.environ.get("USERPROFILE", "")
    if userprofile:
        candidates.append(Path(userprofile) / "scoop" / "apps" / "tesseract" / "current" / exe_name)

    return candidates


def find_tesseract() -> str | None:
    """Locate the tesseract executable. Returns the path or None."""
    which = shutil.which("tesseract")
    if which:
        return which
    for cand in _candidate_tesseract_paths():
        try:
            if cand.is_file():
                return str(cand)
        except OSError:
            continue
    return None


def reading_order(items: list[tuple[list, str]]) -> str:
    """Une las detecciones en orden de lectura: arriba-abajo, izq-derecha.

    RapidOCR devuelve las cajas en el orden en que salen de la red, que no
    es el de lectura: concatenarlas tal cual mezcla los renglones de un
    bocadillo. Dos cajas cuyos centros verticales caen dentro de la misma
    banda —seis décimas de la altura mediana— cuentan como un renglón y se
    ordenan por x.
    """
    if not items:
        return ""
    boxed = []
    for box, text in items:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        boxed.append(((min(ys) + max(ys)) / 2, min(xs), max(ys) - min(ys), text))
    median_h = sorted(b[2] for b in boxed)[len(boxed) // 2] or 1
    boxed.sort(key=lambda b: (round(b[0] / (median_h * 0.6)), b[1]))
    return " ".join(b[3] for b in boxed)


class OcrEngine:
    """RapidOCR con Tesseract de reserva, tras comprobar disponibilidad."""

    def __init__(self) -> None:
        self._available: bool | None = None
        self._version: str | None = None
        self._languages: tuple[str, ...] = ()
        self._binary_path: str | None = None
        self._tessdata_path: str | None = None
        self._rapid = None
        self._rapid_ok: bool | None = None
        self._rapid_lock = threading.Lock()

    @staticmethod
    def is_module_available() -> bool:
        return _PIL_AVAILABLE

    @staticmethod
    def module_import_error() -> str | None:
        return _IMPORT_ERROR

    # ------------------------------------------------------------------
    # RapidOCR
    # ------------------------------------------------------------------

    @staticmethod
    def is_rapid_module_available() -> bool:
        return _RAPID_AVAILABLE

    def rapid_available(self) -> bool:
        """True si RapidOCR carga. Los modelos ONNX viajan en el paquete."""
        if not _RAPID_AVAILABLE:
            return False
        if self._rapid_ok is not None:
            return self._rapid_ok
        with self._rapid_lock:
            if self._rapid_ok is not None:
                return self._rapid_ok
            try:
                log.info("Cargando RapidOCR...")
                self._rapid = RapidOCR()
                self._rapid_ok = True
                log.info("RapidOCR listo")
            except Exception as exc:
                self._rapid = None
                self._rapid_ok = False
                log.warning("RapidOCR no se pudo cargar: %s", exc)
        return self._rapid_ok

    def _recognize_rapid(self, image: Image.Image, lang: str) -> OcrResult:
        """Lee con RapidOCR. Devuelve texto vacío si no detecta nada."""
        import numpy as np

        res, _elapsed = self._rapid(np.array(image.convert("RGB")))
        if not res:
            return OcrResult(text="", confidence=0, language=lang, engine="rapidocr")
        text = reading_order([(line[0], line[1]) for line in res])
        scores = [float(line[2]) for line in res if len(line) > 2]
        confidence = int(100 * sum(scores) / len(scores)) if scores else 0
        return OcrResult(
            text=text.strip(), confidence=confidence, language=lang, engine="rapidocr",
        )

    def binary_path(self) -> str | None:
        if self._binary_path is None:
            self._ensure_binary()
        return self._binary_path

    def set_binary_path(self, path: Path | str) -> None:
        """Point the engine at a Tesseract binary the user picked.

        Used by step 3 when Tesseract is installed somewhere the
        automatic search does not look. Clears the cached probe so the
        next :meth:`is_available` re-tests the new binary.
        """
        candidate = Path(path)
        if not candidate.is_file():
            raise ValueError(f"No existe el ejecutable: {candidate}")
        if pytesseract is None:
            raise RuntimeError("pytesseract no está instalado")
        self._binary_path = str(candidate)
        pytesseract.pytesseract.tesseract_cmd = self._binary_path
        tessdata = candidate.parent / "tessdata"
        if tessdata.is_dir():
            self._tessdata_path = str(tessdata)
            os.environ["TESSDATA_PREFIX"] = self._tessdata_path
        self._available = None
        self._version = None
        self._languages = ()
        log.info("Ruta de Tesseract fijada manualmente: %s", self._binary_path)

    def _ensure_binary(self) -> bool:
        if pytesseract is None:
            return False
        path = find_tesseract()
        if path:
            self._binary_path = path
            pytesseract.pytesseract.tesseract_cmd = path
            tessdata = Path(path).parent / "tessdata"
            if tessdata.is_dir():
                self._tessdata_path = str(tessdata)
                os.environ.setdefault("TESSDATA_PREFIX", self._tessdata_path)
            return True
        return False

    def is_available(self) -> bool:
        """True si *algún* motor puede leer.

        Con RapidOCR instalado el OCR funciona aunque no haya Tesseract:
        sus modelos viajan en el paquete y no hay binario que buscar. Esto
        es lo que decide si los pasos 2→3 dejan continuar.
        """
        return self.rapid_available() or self.tesseract_available()

    def tesseract_available(self) -> bool:
        """True si el binario de Tesseract responde."""
        if self._available is not None:
            return self._available
        if not _PIL_AVAILABLE or pytesseract is None:
            self._available = False
            return False
        if not self._ensure_binary():
            self._available = False
            log.warning(
                "Tesseract no encontrado. %s",
                install_instructions(),
            )
            return False
        try:
            version = pytesseract.get_tesseract_version()
            self._version = str(version)
            self._available = True
            log.info(
                "Tesseract disponible: v%s (%s)",
                self._version,
                self._binary_path,
            )
        except Exception as exc:
            log.warning("Tesseract no disponible: %s", exc)
            self._available = False
        return self._available

    def version(self) -> str | None:
        """Versión de Tesseract, o ``None`` si no está."""
        if not self.tesseract_available():
            return None
        return self._version

    def available_languages(self) -> tuple[str, ...]:
        """Return the list of installed Tesseract languages."""
        if not self._languages:
            if not self.tesseract_available() or pytesseract is None:
                return ()
            try:
                langs = pytesseract.get_languages()
                self._languages = tuple(sorted(langs))
                log.info("Idiomas Tesseract: %s", ", ".join(self._languages) or "(ninguno)")
            except Exception as exc:
                log.warning("No se pudieron listar idiomas: %s", exc)
                self._languages = ()
        return self._languages

    def is_language_available(self, lang: str) -> bool:
        """Si se puede leer en ``lang``. ``lang`` es un código Tesseract.

        RapidOCR no elige idioma: su modelo lee alfabeto latino, que
        cubre español e inglés a la vez. Cuando está, cualquiera de las
        opciones del selector es legible y el capítulo no se atasca
        porque falte un ``traineddata``.
        """
        if self.rapid_available():
            return True
        installed = self.available_languages()
        if not installed:
            return False
        return all(part.strip() in installed for part in lang.split("+") if part.strip())

    def filter_languages(self, options: dict[str, str]) -> dict[str, str]:
        """Return only the entries whose codes are installed."""
        return {label: code for label, code in options.items() if self.is_language_available(code)}

    def recognize(
        self,
        image: Image.Image,
        lang: str = "eng",
    ) -> OcrResult:
        """Lee ``image``: RapidOCR, y Tesseract si aquel no vio nada.

        El vacío es la única señal fiable de que RapidOCR no ha leído: se
        calla en vez de inventar. Un texto suyo, aunque sea peor que el
        que daría Tesseract, no se descarta — en el banco acertaba más a
        menudo, y sin referencia no hay forma de saber cuál de los dos
        tiene razón en una marca concreta.
        """
        if self.rapid_available():
            try:
                result = self._recognize_rapid(image, lang)
                if result.text.strip():
                    return result
                log.debug("RapidOCR no leyó nada, probando con Tesseract")
            except Exception as exc:
                log.exception("Error en RapidOCR, probando con Tesseract: %s", exc)
        return self._recognize_tesseract(image, lang)

    def _recognize_tesseract(self, image: Image.Image, lang: str) -> OcrResult:
        """El camino de reserva, y el único cuando RapidOCR no está."""
        if not self.tesseract_available() or pytesseract is None:
            return OcrResult(text="", confidence=0, language=lang, engine="")
        if not self._tesseract_has_lang(lang):
            fallback = (
                "eng" if self._tesseract_has_lang("eng") else self._first_available()
            )
            if fallback:
                log.warning("Idioma '%s' no disponible, usando '%s'", lang, fallback)
                lang = fallback
            else:
                return OcrResult(text="", confidence=0, language=lang, engine="")

        try:
            prepared = self._preprocess(image)
            text = pytesseract.image_to_string(prepared, lang=lang)
            text = text.strip()
            try:
                data = pytesseract.image_to_data(
                    prepared,
                    lang=lang,
                    output_type=pytesseract.Output.DICT,
                )
                confs = [int(c) for c in data.get("conf", []) if str(c) != "-1"]
                confidence = int(sum(confs) / len(confs)) if confs else 0
            except Exception:
                confidence = 0
            return OcrResult(
                text=text, confidence=confidence, language=lang, engine="tesseract",
            )
        except Exception as exc:
            log.exception("Error en OCR: %s", exc)
            return OcrResult(text="", confidence=0, language=lang, engine="")

    def _preprocess(self, image: Image.Image) -> Image.Image:
        img = image
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if img.size[1] < OCR_MIN_CROP_HEIGHT:
            new_w = max(1, int(img.size[0] * OCR_SCALE_FACTOR))
            new_h = max(1, int(img.size[1] * OCR_SCALE_FACTOR))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        return img

    def _tesseract_has_lang(self, lang: str) -> bool:
        """Si Tesseract tiene el ``traineddata`` de cada código de ``lang``.

        Separado de :meth:`is_language_available` porque esa responde por
        el híbrido —y con RapidOCR delante siempre dice que sí—, mientras
        que aquí hace falta la verdad sobre el binario para elegir a qué
        idioma caer.
        """
        installed = self.available_languages()
        if not installed:
            return False
        return all(p.strip() in installed for p in lang.split("+") if p.strip())

    def _first_available(self) -> str:
        for lang in self.available_languages():
            if lang not in ("osd",):
                return lang
        return ""


def install_instructions() -> str:
    """Return a platform-aware hint for installing Tesseract."""
    if sys.platform.startswith("win"):
        return (
            "Instala Tesseract con:\n"
            "  winget install UB-Mannheim.TesseractOCR\n"
            "o descarga de https://github.com/UB-Mannheim/tesseract/releases\n"
            "Despues reinicia la aplicacion."
        )
    if sys.platform == "darwin":
        return "Tesseract se instala con: brew install tesseract tesseract-lang"
    return "Tesseract se instala con: sudo apt install tesseract-ocr tesseract-ocr-spa"
