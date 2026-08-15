"""Persistence of image marks (rectangles) as JSON sidecar files.

Each image gets a sibling file ``<image>.marks.json`` with the marks
defined in the original image's pixel coordinates. The schema is:

    {
        "version": 5,
        "image": "page001.jpg",
        "clean_signature": "3f1a9c02b7d4e5f6",
        "marks": [
            {"x": 100, "y": 50, "w": 200, "h": 80, "color": "#ffcc00",
             "padding": 24, "uid": "A3F9K2", "model": "manga"}
        ],
        "ocr_results": {
            "0": {
                "text": "Hola mundo",
                "confidence": 87,
                "language": "spa+eng",
                "engine": "tesseract",
                "ran_at": "2026-08-03T15:30:00"
            }
        },
        "translations": {
            "0": {
                "text": "Hello world",
                "source_lang": "es",
                "target_lang": "en",
                "engine": "argos",
                "edited": false,
                "ran_at": "2026-08-04T10:00:00",
                "color": [0, 0, 0],
                "font_family": "Arial",
                "max_pt": 24,
                "bold": true,
                "profile": "Grito"
            }
        }
    }

``padding`` is optional and only written when the user tuned that box;
without it the mark uses ``INPAINT_PADDING_PX``. ``model`` va igual:
ausente es «el que valga para el capítulo», y solo aparece en las
secciones a las que se les ha elegido otro a mano.

``uid`` is the section's name for anything outside this file: seis
caracteres alfanuméricos que se generan al crearla y no cambian nunca.
El índice de la marca sirve dentro del sidecar, pero se corre en cuanto
alguien borra una sección anterior, así que el CSV del paso 3 —que sale
de la aplicación, se edita fuera y vuelve— viaja con el ``uid``.

The per-section overrides of a translation (``color``, ``font_family``,
``max_pt``, ``bold``, ``italic``) are optional in the same way: the key
is absent while nobody has touched it, which is what tells «sin tocar»
apart from «puesto a este valor a propósito».

``profile`` names one of the user's text profiles, which live in their
own file (``src/utils/text_profiles.py``) and not here: a profile
belongs to whoever letters the pages, not to one chapter. A name that no
longer exists reads as no profile at all.

``clean_signature`` fingerprints the boxes the ``.clean`` version on disk
was made from, so a page whose marks moved afterwards can be told apart
from one that is already up to date.
"""

from __future__ import annotations

import json
import re
import secrets
import string
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from src.config import INPAINT_PADDING_PX, MARK_SIDECAR_SUFFIX
from src.utils.logger import get_logger

log = get_logger("marks_store")

SCHEMA_VERSION = 7
_lock = threading.Lock()

#: Sin minúsculas ni ``0``/``O``/``1``/``I``: el id se lee en pantalla y
#: se teclea en una hoja de cálculo, y ahí un cero y una o son el mismo
#: error dos veces.
_UID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
UID_LENGTH = 6


def new_uid() -> str:
    """Un identificador de sección nuevo.

    ponytail: sin comprobar colisiones. Son 32^6 ≈ 1.000 millones de
    combinaciones contra los cientos de secciones de un capítulo; si
    alguna vez importa, el sitio donde mirar es :meth:`MarksStore.add`.
    """
    return "".join(secrets.choice(_UID_ALPHABET) for _ in range(UID_LENGTH))

#: Guión al final de renglón: en un globo estrecho es el maquetado
#: partiendo una palabra —«SOME-\nTHING»— muchas más veces que un
#: compuesto real, así que se va junto con el salto.
_HYPHEN_BREAK = re.compile(r"(\w)[-‐‑­][^\S\n]*\n\s*(\w)")
_WHITESPACE = re.compile(r"\s+")


def to_single_line(text: str) -> str:
    """Deja el texto de OCR en un solo renglón.

    Tesseract devuelve el recorte renglón a renglón, que es como está
    rotulado el globo, no como se lee la frase. Y Argos parte lo que
    recibe por ``\\n`` (``split_into_paragraphs`` es literalmente
    ``input_text.split("\\n")``) y traduce cada trozo por separado, sin
    el contexto del resto: «I DON'T\\nKNOW» le llega como dos frases y
    vuelve como dos traducciones sueltas.

    Une con espacio, que es lo correcto para los idiomas que ofrece el
    paso 2 (``spa``, ``eng``); para uno sin espacios entre palabras
    haría falta otra regla.
    """
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return _WHITESPACE.sub(" ", _HYPHEN_BREAK.sub(r"\1\2", normalized)).strip()


@dataclass(frozen=True)
class Mark:
    """A rectangle in the original image's pixel coordinates.

    ``padding`` is the extra margin, in image pixels, that LaMa erases
    around the box — the rotulado rarely stops exactly at the rectangle
    the user drew, and a globo with a thick outline needs more room than
    a caption. ``None`` means «use the chapter default», which is what
    every mark drawn before this field existed carries.

    ``uid`` se rellena solo al construir la marca, así que dibujarla no
    tiene que acordarse de nada; y ``replace`` lo conserva, que es lo
    que hace que mover o redimensionar una sección no la convierta en
    otra distinta para el CSV.

    ``model`` es qué red rellena *esta* sección. Cadena vacía —lo
    normal— es el modelo del capítulo, y el nombre corto de
    ``INPAINT_MODELS`` una excepción a mano: en una misma página conviven
    globos de fondo liso, donde el big-lama de siempre gana, y tramas,
    donde gana el afinado en manga. Un nombre que ya no exista se lee
    como «el del capítulo» y no deja la página sin limpiar.
    """

    x: int
    y: int
    w: int
    h: int
    color: str
    padding: int | None = None
    uid: str = field(default_factory=new_uid)
    model: str = ""

    @property
    def erase_padding(self) -> int:
        """The margin actually used, with the default resolved.

        Single place where ``None`` turns into a number, so the canvas
        drawing the dashed box and the mask that gets erased can never
        disagree about what the user is being shown.
        """
        if self.padding is None:
            return INPAINT_PADDING_PX
        return max(0, int(self.padding))

    def to_dict(self) -> dict:
        data = asdict(self)
        # «Not set» is written by leaving the key out: a chapter nobody
        # has tuned keeps exactly the sidecar it had before.
        if data.get("padding") is None:
            data.pop("padding", None)
        if not data.get("model"):
            data.pop("model", None)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Mark":
        raw = data.get("padding")
        try:
            padding = None if raw is None else max(0, int(raw))
        except (TypeError, ValueError):
            padding = None
        # Un sidecar de antes de que existiera el id estrena uno aquí;
        # ``MarksStore.load`` se encarga de que quede escrito.
        uid = str(data.get("uid") or "") or new_uid()
        return cls(
            x=int(data["x"]),
            y=int(data["y"]),
            w=int(data["w"]),
            h=int(data["h"]),
            color=str(data.get("color", "#ffcc00")),
            padding=padding,
            uid=uid,
            model=str(data.get("model") or ""),
        )


@dataclass(frozen=True)
class OcrEntry:
    """OCR result stored next to a mark.

    ``text`` es siempre un solo renglón: lo garantizan
    :meth:`from_dict` al leer y :meth:`MarksStore.set_ocr_result` al
    escribir, que son las dos únicas puertas de entrada.
    """

    text: str
    confidence: int
    language: str
    engine: str = "tesseract"
    ran_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "OcrEntry":
        return cls(
            # Los sidecars escritos antes de esta regla llevan el salto
            # de renglón dentro; se recogen al leerlos, no hace falta
            # volver a extraer el capítulo para que traduzca bien.
            text=to_single_line(str(data.get("text", ""))),
            confidence=int(data.get("confidence", 0)),
            language=str(data.get("language", "")),
            engine=str(data.get("engine", "tesseract")),
            ran_at=str(data.get("ran_at", "")),
        )


# Los tres leen «la clave no estaba» como ``None``, que en este esquema
# significa «sin tocar» y no «puesto al valor por defecto». Viven aquí
# porque aquí está el modelo, y los usan también los perfiles de texto.

def opt_bool(raw: Any) -> bool | None:
    """``None`` si la clave no estaba; un booleano si estaba."""
    if raw is None:
        return None
    return bool(raw)


def opt_int(raw: Any) -> int | None:
    """Un entero, o ``None`` si falta o si no hay forma de leerlo así."""
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _opt_ints(raw: Any, count: int) -> tuple[int, ...] | None:
    """Los ``count`` primeros enteros de una lista del JSON, o ``None``."""
    if not isinstance(raw, (list, tuple)) or len(raw) < count:
        return None
    try:
        return tuple(int(v) for v in raw[:count])
    except (TypeError, ValueError):
        return None


def opt_color(raw: Any) -> tuple[int, int, int] | None:
    """Un ``[r, g, b]`` del JSON como tupla, o ``None``."""
    return _opt_ints(raw, 3)  # type: ignore[return-value]


def opt_offset(raw: Any) -> tuple[int, int, int, int] | None:
    """Un ``[dx, dy, dw, dh]`` del JSON como tupla, o ``None``."""
    return _opt_ints(raw, 4)  # type: ignore[return-value]


@dataclass(frozen=True)
class TranslationEntry:
    """Translation result stored next to a mark.

    ``color``, ``font_family``, ``max_pt``, ``bold``, ``italic`` and the
    two ``stroke_*`` are the per-section overrides, and they are ``None``
    when nobody touched them. That is not the same as «puesto igual que el valor por
    defecto»: the difference is what lets the assigned text profile fill
    in the untouched fields without overwriting the ones the user chose.

    ``profile`` holds the profile's *name*, never a copy of its values —
    otherwise editing a profile could not reach the sections using it.

    ``box_offset`` is ``(dx, dy, dw, dh)`` against the mark, not absolute
    coordinates: the mark says *what gets erased* and the box says
    *where the text goes*, and storing the difference means a mark
    nudged in step 2 takes its text box with it. ``None`` is «the box is
    the mark», which is what every section starts as.
    """

    text: str
    source_lang: str
    target_lang: str
    engine: str = "argos"
    edited: bool = False
    ran_at: str = ""
    color: tuple[int, int, int] | None = None
    font_family: str | None = None
    max_pt: int | None = None
    bold: bool | None = None
    italic: bool | None = None
    #: Cero no es «sin tocar»: es «esta sección va sin contorno aunque su
    #: perfil lleve uno». El «sin tocar» sigue siendo ``None``.
    stroke_width: int | None = None
    stroke_color: tuple[int, int, int] | None = None
    profile: str | None = None
    box_offset: tuple[int, int, int, int] | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # Strip None values to keep sidecar JSON compact.
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "TranslationEntry":
        return cls(
            text=str(data.get("text", "")),
            source_lang=str(data.get("source_lang", "")),
            target_lang=str(data.get("target_lang", "")),
            engine=str(data.get("engine", "argos")),
            edited=bool(data.get("edited", False)),
            ran_at=str(data.get("ran_at", "")),
            color=opt_color(data.get("color")),
            font_family=(str(data["font_family"]) if data.get("font_family") else None),
            max_pt=opt_int(data.get("max_pt")),
            # Ausente es «sin tocar», que no es lo mismo que ``false``:
            # ``false`` es «esta sección va en redonda pase lo que pase».
            bold=opt_bool(data.get("bold")),
            italic=opt_bool(data.get("italic")),
            stroke_width=opt_int(data.get("stroke_width")),
            stroke_color=opt_color(data.get("stroke_color")),
            profile=(str(data["profile"]) if data.get("profile") else None),
            box_offset=opt_offset(data.get("box_offset")),
        )


def sidecar_path(image_path: Path) -> Path:
    """Return the path of the JSON file holding marks for ``image_path``."""
    return image_path.with_name(image_path.name + MARK_SIDECAR_SUFFIX)


class MarksStore:
    """Manages loading and saving mark files for a single image.

    Holds the current set of marks in memory and provides explicit
    ``save`` for persistence. A file lock guards concurrent writes.
    """

    def __init__(self, image_path: Path) -> None:
        self.image_path: Path = image_path
        self._marks: list[Mark] = []
        self._ocr: dict[int, OcrEntry] = {}
        self._translations: dict[int, TranslationEntry] = {}
        self._clean_signature: str = ""
        self._dirty: bool = False

    @property
    def marks(self) -> list[Mark]:
        return list(self._marks)

    @property
    def clean_signature(self) -> str:
        """Fingerprint of the marks the clean version on disk was made from."""
        return self._clean_signature

    @clean_signature.setter
    def clean_signature(self, value: str) -> None:
        value = str(value or "")
        if value == self._clean_signature:
            return
        self._clean_signature = value
        self._dirty = True
        self.save()

    @property
    def ocr_results(self) -> dict[int, OcrEntry]:
        return dict(self._ocr)

    @property
    def translations(self) -> dict[int, TranslationEntry]:
        return dict(self._translations)

    def __len__(self) -> int:
        return len(self._marks)

    def __iter__(self) -> Iterable[Mark]:
        return iter(self._marks)

    def add(self, mark: Mark) -> int:
        """Append ``mark`` and return its new id (its index)."""
        self._marks.append(mark)
        self._dirty = True
        self.save()
        return len(self._marks) - 1

    def update_at(self, mark_id: int, mark: Mark) -> bool:
        """Replace the geometry (or colour) of an existing mark.

        The OCR and translation attached to the mark are kept: moving or
        resizing a box does not invalidate the text somebody already
        reviewed, and re-running OCR is an explicit action.
        """
        if not 0 <= mark_id < len(self._marks):
            return False
        if self._marks[mark_id] == mark:
            return False
        self._marks[mark_id] = mark
        self._dirty = True
        self.save()
        return True

    def remove_at(self, mark_id: int) -> Mark | None:
        if not 0 <= mark_id < len(self._marks):
            return None
        removed = self._marks.pop(mark_id)
        # Everything after the hole moves down one slot, so the sidecar
        # entries have to move with it. Dropping only the out-of-range
        # keys would silently re-attach every later OCR result to its
        # neighbour's box.
        self._ocr = self._shift_down(self._ocr, mark_id)
        self._translations = self._shift_down(self._translations, mark_id)
        self._reindex_ocr()
        self._reindex_translations()
        self._dirty = True
        self.save()
        return removed

    @staticmethod
    def _shift_down(entries: dict[int, Any], removed_id: int) -> dict[int, Any]:
        shifted: dict[int, Any] = {}
        for idx, entry in entries.items():
            if idx == removed_id:
                continue
            shifted[idx - 1 if idx > removed_id else idx] = entry
        return shifted

    def remove_last(self) -> Mark | None:
        if not self._marks:
            return None
        return self.remove_at(len(self._marks) - 1)

    def clear(self) -> None:
        if not self._marks and not self._ocr and not self._translations:
            return
        self._marks.clear()
        self._ocr.clear()
        self._translations.clear()
        self._dirty = True
        self.save()

    def set_marks(self, marks: list[Mark]) -> None:
        self._marks = list(marks)
        self._reindex_ocr()
        self._reindex_translations()
        self._dirty = True
        self.save()

    def set_ocr_result(self, mark_id: int, entry: OcrEntry) -> None:
        if not 0 <= mark_id < len(self._marks):
            return
        # La única puerta de escritura: el que llame —Tesseract, el
        # pipeline o el usuario pegando en el paso 3— no tiene que
        # acordarse de la regla.
        single = to_single_line(entry.text)
        if single != entry.text:
            entry = replace(entry, text=single)
        if not entry.ran_at:
            entry = replace(
                entry, ran_at=datetime.now().isoformat(timespec="seconds"),
            )
        self._ocr[mark_id] = entry
        self._dirty = True
        self.save()

    def clear_ocr_results(self) -> None:
        if not self._ocr:
            return
        self._ocr.clear()
        self._dirty = True
        self.save()

    def get_ocr(self, mark_id: int) -> OcrEntry | None:
        return self._ocr.get(mark_id)

    def has_ocr(self, mark_id: int) -> bool:
        return mark_id in self._ocr

    def set_translation(self, mark_id: int, entry: TranslationEntry) -> None:
        if not 0 <= mark_id < len(self._marks):
            return
        if not entry.ran_at:
            # Only the timestamp is filled in. Rebuilding the entry from
            # a subset of its fields used to drop the look of the text —
            # colour, family, size — every time step 4 touched an entry
            # that had never been stamped.
            entry = replace(
                entry, ran_at=datetime.now().isoformat(timespec="seconds"),
            )
        self._translations[mark_id] = entry
        self._dirty = True
        self.save()

    def get_translation(self, mark_id: int) -> TranslationEntry | None:
        return self._translations.get(mark_id)

    def has_translation(self, mark_id: int) -> bool:
        return mark_id in self._translations

    def clear_translations(self) -> None:
        if not self._translations:
            return
        self._translations.clear()
        self._dirty = True
        self.save()

    def load(self) -> list[Mark]:
        path = sidecar_path(self.image_path)
        if not path.exists():
            log.debug("Sin archivo de marcas para %s", self.image_path.name)
            self._marks = []
            self._ocr = {}
            self._translations = {}
            self._clean_signature = ""
            return self._marks
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            log.exception("No se pudo leer %s: %s", path, exc)
            self._marks = []
            self._ocr = {}
            self._translations = {}
            self._clean_signature = ""
            return self._marks

        self._clean_signature = str(data.get("clean_signature", ""))
        raw_marks = data.get("marks", [])
        loaded: list[Mark] = []
        missing_uid = False
        for raw in raw_marks:
            try:
                loaded.append(Mark.from_dict(raw))
                missing_uid = missing_uid or not raw.get("uid")
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Marca invalida en %s: %s (%s)", path, raw, exc)
        self._marks = loaded

        raw_ocr = data.get("ocr_results", {})
        loaded_ocr: dict[int, OcrEntry] = {}
        for raw_key, raw_val in raw_ocr.items():
            try:
                idx = int(raw_key)
            except (TypeError, ValueError):
                continue
            try:
                loaded_ocr[idx] = OcrEntry.from_dict(raw_val)
            except Exception as exc:
                log.warning("OCR invalido en %s: %s (%s)", path, raw_val, exc)
        self._ocr = loaded_ocr

        raw_trans = data.get("translations", {})
        loaded_trans: dict[int, TranslationEntry] = {}
        for raw_key, raw_val in raw_trans.items():
            try:
                idx = int(raw_key)
            except (TypeError, ValueError):
                continue
            try:
                loaded_trans[idx] = TranslationEntry.from_dict(raw_val)
            except Exception as exc:
                log.warning("Traduccion invalida en %s: %s (%s)", path, raw_val, exc)
        self._translations = loaded_trans
        self._reindex_ocr()
        self._reindex_translations()
        self._dirty = False
        if missing_uid:
            # Los ids que acaba de estrenar un sidecar viejo se escriben
            # ya: si no, cada sesión le pondría otros distintos y el CSV
            # exportado hoy no encajaría con el capítulo de mañana.
            self._dirty = True
            self.save()
        log.info(
            "Cargadas %d marca(s), %d OCR y %d traduccion(es) de %s",
            len(self._marks),
            len(self._ocr),
            len(self._translations),
            path.name,
        )
        return self._marks

    def save(self) -> bool:
        if not self._dirty:
            return True
        path = sidecar_path(self.image_path)
        payload: dict[str, Any] = {
            "version": SCHEMA_VERSION,
            "image": self.image_path.name,
            "clean_signature": self._clean_signature,
            "marks": [m.to_dict() for m in self._marks],
            "ocr_results": {
                str(idx): entry.to_dict() for idx, entry in self._ocr.items()
            },
            "translations": {
                str(idx): entry.to_dict() for idx, entry in self._translations.items()
            },
        }
        with _lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + ".tmp")
                with tmp.open("w", encoding="utf-8") as fh:
                    json.dump(payload, fh, indent=2, ensure_ascii=False)
                tmp.replace(path)
            except OSError as exc:
                log.exception("No se pudo guardar %s: %s", path, exc)
                return False
        self._dirty = False
        log.debug(
            "Guardadas %d marca(s), %d OCR y %d traduccion(es) en %s",
            len(self._marks),
            len(self._ocr),
            len(self._translations),
            path.name,
        )
        return True

    def _reindex_ocr(self) -> None:
        """Drop OCR entries pointing at marks that no longer exist."""
        valid: dict[int, OcrEntry] = {}
        for idx, entry in self._ocr.items():
            if 0 <= idx < len(self._marks):
                valid[idx] = entry
        self._ocr = valid

    def _reindex_translations(self) -> None:
        """Drop translation entries pointing at marks that no longer exist."""
        valid: dict[int, TranslationEntry] = {}
        for idx, entry in self._translations.items():
            if 0 <= idx < len(self._marks):
                valid[idx] = entry
        self._translations = valid

    @staticmethod
    def has_marks(image_path: Path) -> bool:
        return sidecar_path(image_path).exists()
