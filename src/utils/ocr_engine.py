"""OCR engine wrapper around Tesseract via pytesseract.

Provides availability detection, language detection and a small
preprocessing step to improve recognition on tiny crops.
"""

from __future__ import annotations

import os
import shutil
import sys
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


@dataclass(frozen=True)
class OcrResult:
    """Result of an OCR pass on a single crop."""

    text: str
    confidence: int
    language: str


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


class OcrEngine:
    """Thin wrapper around Tesseract with availability checks."""

    def __init__(self) -> None:
        self._available: bool | None = None
        self._version: str | None = None
        self._languages: tuple[str, ...] = ()
        self._binary_path: str | None = None
        self._tessdata_path: str | None = None

    @staticmethod
    def is_module_available() -> bool:
        return _PIL_AVAILABLE

    @staticmethod
    def module_import_error() -> str | None:
        return _IMPORT_ERROR

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
        """Return True if the Tesseract binary is callable."""
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
        if not self.is_available():
            return None
        return self._version

    def available_languages(self) -> tuple[str, ...]:
        """Return the list of installed Tesseract languages."""
        if not self._languages:
            if not self.is_available() or pytesseract is None:
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
        """Return True if every code in ``lang`` is installed.

        ``lang`` may be a Tesseract string like ``"spa+eng"``.
        """
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
        """Run OCR on ``image`` and return the text + confidence."""
        if not self.is_available() or pytesseract is None:
            return OcrResult(text="", confidence=0, language=lang)
        if not self.is_language_available(lang):
            fallback = "eng" if self.is_language_available("eng") else self._first_available()
            if fallback:
                log.warning("Idioma '%s' no disponible, usando '%s'", lang, fallback)
                lang = fallback
            else:
                return OcrResult(text="", confidence=0, language=lang)

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
            return OcrResult(text=text, confidence=confidence, language=lang)
        except Exception as exc:
            log.exception("Error en OCR: %s", exc)
            return OcrResult(text="", confidence=0, language=lang)

    def _preprocess(self, image: Image.Image) -> Image.Image:
        img = image
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if img.size[1] < OCR_MIN_CROP_HEIGHT:
            new_w = max(1, int(img.size[0] * OCR_SCALE_FACTOR))
            new_h = max(1, int(img.size[1] * OCR_SCALE_FACTOR))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        return img

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
