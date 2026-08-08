"""Render translated text into image rectangles.

The renderer is used in two places:

1. Live preview inside the translator view (transparent background,
   optional stroke for legibility on busy art).
2. Final export (text drawn on the clean image, transparent
   background, no stroke).

``fit_font`` performs a binary search to find the largest font size
that makes the wrapped text fit inside a target box. The same helper
returns the list of lines that were chosen, so the preview canvas can
re-draw at the same scale.

Bold and italic are resolved to real files: PIL draws what is in the
file and synthesises nothing, so a family whose bold nobody installed
comes out regular. ``resolve_style`` answers that question ahead of the
draw, which is how the rail can say so instead of the page quietly
ignoring the toggle.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from src.config import (
    TEXT_RENDER_DEFAULT_COLOR,
    TEXT_RENDER_FALLBACK_FAMILIES,
    TEXT_RENDER_LINE_SPACING,
    TEXT_RENDER_MAX_PT,
    TEXT_RENDER_MIN_PT,
    TEXT_RENDER_PADDING_PX,
    TEXT_RENDER_STROKE,
)
from src.utils.logger import get_logger
from src.utils.marks_store import Mark, TranslationEntry
from src.utils.text_profiles import TextProfile

log = get_logger("text_renderer")


# --- Font discovery ------------------------------------------------------

def _windows_font_dir() -> Path:
    return Path(r"C:\Windows\Fonts")


def _mac_font_dirs() -> list[Path]:
    return [
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
        Path.home() / "Library" / "Fonts",
    ]


def _linux_font_dirs() -> list[Path]:
    return [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".fonts",
        Path.home() / ".local" / "share" / "fonts",
    ]


#: The four style slots a family can have on disk. PIL synthesises
#: neither weight nor slant — a "bold" with no file of its own is the
#: regular file drawn at the regular weight — so a style is only real if
#: there is a filename behind it.
STYLE_REGULAR = "regular"
STYLE_BOLD = "bold"
STYLE_ITALIC = "italic"
STYLE_BOLD_ITALIC = "bold_italic"

#: Where each style goes when its own file is missing. Bold italic keeps
#: the weight before the slant: in a globo, losing the bold is the more
#: visible of the two losses.
_STYLE_LADDER: dict[str, tuple[str, ...]] = {
    STYLE_REGULAR: (STYLE_REGULAR,),
    STYLE_BOLD: (STYLE_BOLD, STYLE_REGULAR),
    STYLE_ITALIC: (STYLE_ITALIC, STYLE_REGULAR),
    STYLE_BOLD_ITALIC: (
        STYLE_BOLD_ITALIC, STYLE_BOLD, STYLE_ITALIC, STYLE_REGULAR,
    ),
}

#: family -> style -> known filenames. Each style is a separate list on
#: purpose: keeping ``arialbd.ttf`` inside the regular list, as this map
#: used to, meant a page could silently come out bold because the regular
#: file happened to be missing.
#:
#: ``.ttc`` collections (Helvetica on macOS) hold every variant in one
#: file behind an index PIL does not address here, so they are listed as
#: regular only.
_FAMILY_FILES: dict[str, dict[str, list[str]]] = {
    "segoe ui": {
        STYLE_REGULAR: ["segoeui.ttf", "SegoeUI.ttf"],
        STYLE_BOLD: ["segoeuib.ttf"],
        STYLE_ITALIC: ["segoeuii.ttf"],
        STYLE_BOLD_ITALIC: ["segoeuiz.ttf"],
    },
    "arial": {
        STYLE_REGULAR: ["arial.ttf", "Arial.ttf", "ArialMT.ttf"],
        STYLE_BOLD: ["arialbd.ttf", "Arial Bold.ttf"],
        STYLE_ITALIC: ["ariali.ttf", "Arial Italic.ttf"],
        STYLE_BOLD_ITALIC: ["arialbi.ttf", "Arial Bold Italic.ttf"],
    },
    "calibri": {
        STYLE_REGULAR: ["calibri.ttf", "Calibri.ttf"],
        STYLE_BOLD: ["calibrib.ttf"],
        STYLE_ITALIC: ["calibrii.ttf"],
        STYLE_BOLD_ITALIC: ["calibriz.ttf"],
    },
    "tahoma": {
        STYLE_REGULAR: ["tahoma.ttf", "Tahoma.ttf"],
        STYLE_BOLD: ["tahomabd.ttf"],
    },
    "verdana": {
        STYLE_REGULAR: ["verdana.ttf", "Verdana.ttf"],
        STYLE_BOLD: ["verdanab.ttf"],
        STYLE_ITALIC: ["verdanai.ttf"],
        STYLE_BOLD_ITALIC: ["verdanaz.ttf"],
    },
    "helvetica": {
        STYLE_REGULAR: ["Helvetica.ttc", "HelveticaNeue.ttc"],
    },
    "times new roman": {
        STYLE_REGULAR: ["times.ttf", "Times.ttf", "TimesNewRoman.ttf"],
        STYLE_BOLD: ["timesbd.ttf"],
        STYLE_ITALIC: ["timesi.ttf"],
        STYLE_BOLD_ITALIC: ["timesbi.ttf"],
    },
    "georgia": {
        STYLE_REGULAR: ["georgia.ttf", "Georgia.ttf"],
        STYLE_BOLD: ["georgiab.ttf"],
        STYLE_ITALIC: ["georgiai.ttf"],
        STYLE_BOLD_ITALIC: ["georgiaz.ttf"],
    },
    "courier new": {
        STYLE_REGULAR: ["cour.ttf", "Courier.ttf", "CourierNew.ttf"],
        STYLE_BOLD: ["courbd.ttf"],
        STYLE_ITALIC: ["couri.ttf"],
        STYLE_BOLD_ITALIC: ["courbi.ttf"],
    },
    "dejavu sans": {
        STYLE_REGULAR: ["DejaVuSans.ttf"],
        STYLE_BOLD: ["DejaVuSans-Bold.ttf"],
        STYLE_ITALIC: ["DejaVuSans-Oblique.ttf"],
        STYLE_BOLD_ITALIC: ["DejaVuSans-BoldOblique.ttf"],
    },
    "liberation sans": {
        STYLE_REGULAR: ["LiberationSans-Regular.ttf"],
        STYLE_BOLD: ["LiberationSans-Bold.ttf"],
        STYLE_ITALIC: ["LiberationSans-Italic.ttf"],
        STYLE_BOLD_ITALIC: ["LiberationSans-BoldItalic.ttf"],
    },
}


def style_name(bold: bool, italic: bool) -> str:
    """The style slot two toggles add up to."""
    if bold and italic:
        return STYLE_BOLD_ITALIC
    if bold:
        return STYLE_BOLD
    if italic:
        return STYLE_ITALIC
    return STYLE_REGULAR


def _synthetic_names(base: str, style: str) -> list[str]:
    """Filenames to try for a family that is not in the map.

    The two naming conventions that cover almost everything: the Windows
    one-letter suffix (``arialbd``, ``segoeuii``) and the hyphenated
    PostScript-ish one (``Archivo-BoldItalic``).
    """
    if style == STYLE_BOLD:
        tails = ["b", "bd", "-Bold", "Bold", "-bold"]
    elif style == STYLE_ITALIC:
        tails = ["i", "-Italic", "Italic", "-italic", "-Oblique", "Oblique"]
    elif style == STYLE_BOLD_ITALIC:
        tails = [
            "z", "bi", "-BoldItalic", "BoldItalic", "-bolditalic",
            "-BoldOblique",
        ]
    else:
        tails = ["", "-Regular", "Regular", "-regular"]
    names: list[str] = []
    for tail in tails:
        names.append(f"{base}{tail}.ttf")
        names.append(f"{base}{tail}.otf")
        if style == STYLE_REGULAR and not tail:
            names.append(f"{base}.ttc")
    return names


def _candidate_font_paths(
    family: str, style: str = STYLE_REGULAR,
) -> list[Path]:
    """On-disk paths for ``family`` in ``style``, in priority order.

    Only that style: falling back to another one is the caller's job, so
    that whoever asks can also be told *which* style came back.
    """
    family_norm = (family or "").strip().lower()
    if not family_norm:
        return []

    if sys.platform.startswith("win"):
        roots = [_windows_font_dir()]
    elif sys.platform == "darwin":
        roots = _mac_font_dirs()
    else:
        roots = _linux_font_dirs()

    known = _FAMILY_FILES.get(family_norm)
    if known is not None:
        filenames = list(known.get(style, []))
    else:
        filenames = _synthetic_names(family_norm.replace(" ", ""), style)
    if not filenames:
        return []

    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            for fname in filenames:
                p = root / fname
                if p.is_file():
                    candidates.append(p)
        except OSError:
            continue

    return candidates


def list_available_families() -> list[str]:
    """Return the list of font family names that can be resolved on disk."""
    if sys.platform.startswith("win"):
        roots = [_windows_font_dir()]
    elif sys.platform == "darwin":
        roots = _mac_font_dirs()
    else:
        roots = _linux_font_dirs()
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        try:
            for entry in root.iterdir():
                if not entry.is_file():
                    continue
                if entry.suffix.lower() not in (".ttf", ".ttc", ".otf"):
                    continue
                stem = entry.stem
                norm = stem.lower()
                # Normalise: strip common weights/styles.
                for suffix in (
                    "-regular", "_regular", "regular",
                    "-bold", "_bold", "bold",
                    "-italic", "_italic", "italic",
                    "-light", "_light", "light",
                ):
                    if norm.endswith(suffix):
                        norm = norm[: -len(suffix)]
                norm = norm.replace("-", " ").replace("_", " ").strip()
                if norm:
                    seen.add(norm)
        except OSError:
            continue
    return sorted(seen)


def _resolve_font_path(
    family: str, style: str = STYLE_REGULAR,
) -> str | None:
    """Return the first resolvable TTF path for ``family`` or ``None``."""
    for path in _candidate_font_paths(family, style):
        try:
            if path.is_file():
                return str(path)
        except OSError:
            continue
    return None


def _iter_font_files(
    family: str | None, bold: bool, italic: bool,
) -> Iterable[tuple[str, str]]:
    """Yield ``(path, style)`` for the ask, best first.

    A family is exhausted before moving to the next one: a *Segoe UI*
    with no italic on disk should come out as Segoe UI, not as somebody
    else's italic. The slant is the smaller of the two lies.
    """
    families: list[str] = []
    if family:
        families.append(family)
    for fam in TEXT_RENDER_FALLBACK_FAMILIES:
        if family and fam.lower() == family.lower():
            continue
        families.append(fam)
    wanted = style_name(bold, italic)
    for fam in families:
        for style in _STYLE_LADDER[wanted]:
            path = _resolve_font_path(fam, style)
            if path is not None:
                yield path, style


def resolve_style(
    family: str | None, bold: bool, italic: bool,
) -> tuple[bool, bool]:
    """The style that will actually be drawn, after the fallbacks.

    Single place where «negrita» becomes a fact about a file on disk, so
    the preview, the export and the note in the rail cannot disagree
    about whether a family really has the variant. Asking for a bold
    that nobody installed comes back ``(False, False)``.
    """
    if not bold and not italic:
        return False, False
    for _path, style in _iter_font_files(family, bold, italic):
        return (
            style in (STYLE_BOLD, STYLE_BOLD_ITALIC),
            style in (STYLE_ITALIC, STYLE_BOLD_ITALIC),
        )
    return False, False


# --- Font loading --------------------------------------------------------

def _load_font(
    size: int,
    family: str | None = None,
    *,
    bold: bool = False,
    italic: bool = False,
) -> ImageFont.FreeTypeFont:
    for path, _style in _iter_font_files(family, bold, italic):
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


# --- Public types --------------------------------------------------------

@dataclass(frozen=True)
class TextBox:
    """A rectangle of text to be drawn on an image."""

    x: int
    y: int
    w: int
    h: int
    text: str
    color: tuple[int, int, int] = TEXT_RENDER_DEFAULT_COLOR
    align: str = "center"
    max_pt: int = TEXT_RENDER_MAX_PT
    min_pt: int = TEXT_RENDER_MIN_PT
    stroke: bool = TEXT_RENDER_STROKE
    stroke_color: tuple[int, int, int] = (255, 255, 255)
    stroke_width: int = 2
    font_family: str | None = None
    #: Asked for, not necessarily granted: a family with no bold file on
    #: disk comes out regular. ``resolve_style`` says which it will be.
    bold: bool = False
    italic: bool = False
    padding_px: int = TEXT_RENDER_PADDING_PX


@dataclass(frozen=True)
class FitResult:
    font_size: int
    lines: list[str]


@dataclass(frozen=True)
class RenderConfig:
    """Everything the resolver needs that is not the section itself.

    The first three fields are the chapter-wide layer: each has a
    per-section counterpart on
    :class:`~src.utils.marks_store.TranslationEntry` that stays ``None``
    until somebody touches it. ``profiles`` is the user's set of named
    looks, carried here so that whoever can draw a box can also resolve
    the one a section was assigned — a handful of entries, looked up by
    name.
    """

    font_family: str | None = None
    max_pt: int = TEXT_RENDER_MAX_PT
    color: tuple[int, int, int] = TEXT_RENDER_DEFAULT_COLOR
    profiles: tuple[TextProfile, ...] = ()

    def profile(self, name: str | None) -> TextProfile | None:
        """The profile called ``name``, or ``None`` if there is no such thing.

        A section can name a profile the user has since renamed or
        deleted; that reads as no profile, never as an error.
        """
        if not name:
            return None
        for profile in self.profiles:
            if profile.name == name:
                return profile
        return None

    def asked(self, entry: TranslationEntry, field: str):
        """What the section and its profile say about one field.

        The two strongest layers of the precedence rule, without the
        chapter-wide floor underneath — «¿ha elegido alguien esto?»,
        which is a different question from «¿con qué se dibuja?». The
        rail needs this one to know whether a «restablecer» has anything
        to undo, and to show a toggle as on because the profile says so.
        """
        value = getattr(entry, field)
        if value is None or value == "":
            profile = self.profile(entry.profile)
            value = getattr(profile, field) if profile is not None else None
        return value


def _first_set(*layers):
    """The first layer that actually says something.

    ``None`` is «sin tocar» and an empty string is a font family nobody
    chose; anything else — including ``False`` — is an answer.
    """
    for value in layers:
        if value is not None and value != "":
            return value
    return None


def resolve_box(
    mark: Mark, entry: TranslationEntry, config: RenderConfig,
) -> TextBox:
    """The box a section is actually drawn with.

    Precedence, strongest first::

        lo que la sección puso a mano  >  su perfil  >  RenderConfig

    ``None`` on the entry means «sin tocar», not «puesto igual que el
    perfil» — which is why assigning a profile must never fill those
    fields in. Editing a profile therefore reaches every section using
    it, but only in the fields that section left alone.

    The style that comes back is the one that will be *drawn*, not the
    one that was asked for: a family with no bold on disk yields
    ``bold=False``. That is the whole point of having one resolver — the
    preview, the exported PNG and the sidecar cannot disagree about a
    colour or a variant they did not each work out for themselves.
    """
    family = _first_set(config.asked(entry, "font_family"), config.font_family)
    bold, italic = resolve_style(
        family,
        bool(config.asked(entry, "bold")),
        bool(config.asked(entry, "italic")),
    )
    return TextBox(
        x=mark.x,
        y=mark.y,
        w=mark.w,
        h=mark.h,
        text=entry.text,
        color=_first_set(config.asked(entry, "color"), config.color),
        max_pt=_first_set(config.asked(entry, "max_pt"), config.max_pt),
        font_family=family,
        bold=bold,
        italic=italic,
    )


# --- fit_text / render ---------------------------------------------------

def fit_text(box: TextBox) -> FitResult:
    """Return the largest font size + wrapped lines that fit inside ``box``.

    Uses a binary search between ``min_pt`` and ``max_pt``.
    """
    if box.w <= 0 or box.h <= 0:
        return FitResult(font_size=box.min_pt, lines=[""])

    max_pt = max(box.min_pt + 1, int(box.max_pt))
    min_pt = max(1, int(box.min_pt))

    best_size = min_pt
    best_lines: list[str] = [""]
    lo, hi = min_pt, max_pt
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(
            mid, family=box.font_family, bold=box.bold, italic=box.italic,
        )
        lines = _wrap(box.text, font, box.w)
        if _fits_height(lines, font, box.h):
            best_size = mid
            best_lines = lines
            lo = mid + 1
        else:
            hi = mid - 1
    return FitResult(font_size=best_size, lines=best_lines)


def render_text(image: Image.Image, boxes: Iterable[TextBox]) -> Image.Image:
    """Draw each ``TextBox`` on a copy of ``image`` and return it."""
    out = image.copy()
    draw = ImageDraw.Draw(out)
    for box in boxes:
        _draw_box(draw, box)
    return out


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    if not text or not text.strip():
        return [""]

    raw_lines = text.replace("\r\n", "\n").split("\n")
    wrapped: list[str] = []
    for raw in raw_lines:
        if not raw.strip():
            wrapped.append("")
            continue
        current = ""
        for word in raw.split(" "):
            if not word:
                continue
            candidate = f"{current} {word}".strip() if current else word
            if _text_width(candidate, font) <= max_w:
                current = candidate
                continue
            if current:
                wrapped.append(current)
                current = word
            else:
                # Single word wider than the box: hard-break it.
                for piece in _hard_break(word, font, max_w):
                    wrapped.append(piece)
                current = ""
        if current:
            wrapped.append(current)
    return wrapped or [""]


def _hard_break(
    word: str,
    font: ImageFont.FreeTypeFont,
    max_w: int,
) -> list[str]:
    chunks: list[str] = []
    current = ""
    for ch in word:
        candidate = current + ch
        if current and _text_width(candidate, font) > max_w:
            chunks.append(current)
            current = ch
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _text_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    try:
        l, t, r, b = font.getbbox(text)
        return max(0, r - l)
    except Exception:
        try:
            return int(font.getlength(text))
        except Exception:
            return len(text) * 8


def _fits_height(
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    max_h: int,
) -> bool:
    if not lines:
        return True
    try:
        ascent, descent = font.getmetrics()
    except Exception:
        ascent, descent = 12, 3
    line_h = int((ascent + descent) * TEXT_RENDER_LINE_SPACING)
    return line_h * len(lines) <= max_h


def _draw_box(draw: ImageDraw.ImageDraw, box: TextBox) -> None:
    fit = fit_text(box)
    font = _load_font(
        fit.font_size, family=box.font_family,
        bold=box.bold, italic=box.italic,
    )
    try:
        ascent, descent = font.getmetrics()
    except Exception:
        ascent, descent = 12, 3
    line_h = int((ascent + descent) * TEXT_RENDER_LINE_SPACING)
    total_h = line_h * len(fit.lines)
    if box.align == "top":
        y_cursor = box.y
    elif box.align == "bottom":
        y_cursor = box.y + box.h - total_h
    else:
        y_cursor = box.y + max(0, (box.h - total_h) // 2)
    pad = max(0, int(box.padding_px))
    for line in fit.lines:
        try:
            l, t, r, b = font.getbbox(line)
            line_w = max(0, r - l)
            line_x_offset = -l
        except Exception:
            line_w = _text_width(line, font)
            line_x_offset = 0
        if box.align == "left":
            x = box.x + pad
        elif box.align == "right":
            x = box.x + box.w - pad - line_w
        else:
            x = box.x + (box.w - line_w) // 2
        try:
            draw.text(
                (x + line_x_offset, y_cursor),
                line,
                font=font,
                fill=box.color,
                stroke_width=(box.stroke_width if box.stroke else 0),
                stroke_fill=(box.stroke_color if box.stroke else None),
            )
        except TypeError:
            draw.text(
                (x + line_x_offset, y_cursor),
                line,
                font=font,
                fill=box.color,
            )
        y_cursor += line_h
