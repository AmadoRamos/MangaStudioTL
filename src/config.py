"""Application-wide configuration constants.

The colour block below is the *Modernist* design system used by the
mockups (``Traductor de Manga - Mockups``, direction 3a): a light
paper-coloured shell, near-black ink, one red accent, squared corners
and 2 px rules — with the page itself sitting on a dark canvas.

The ``COLOR_*`` / ``NEUTRAL_*`` / ``ACCENT_*`` names are the tokens, and
every screen uses them directly.
"""

from pathlib import Path

WINDOW_TITLE: str = "Visor de Manga y Webcomic"
WINDOW_WIDTH: int = 1400
WINDOW_HEIGHT: int = 850
WINDOW_MIN_WIDTH: int = 1000
WINDOW_MIN_HEIGHT: int = 640

# --------------------------------------------------------------------
# Design tokens (modernist.css)
# --------------------------------------------------------------------

COLOR_BG: str = "#f3f2f2"
COLOR_SURFACE: str = "#eae9e9"
COLOR_TEXT: str = "#201e1d"
COLOR_ACCENT: str = "#ec3013"

# --color-divider: 40 % ink over the paper, flattened for Tk (which has
# no alpha on widget borders).
COLOR_DIVIDER: str = "#9f9d9d"

NEUTRAL_100: str = "#f8f4f4"
NEUTRAL_300: str = "#d7d3d3"
NEUTRAL_400: str = "#bab6b6"
NEUTRAL_500: str = "#9b9797"
NEUTRAL_600: str = "#7d7979"
NEUTRAL_700: str = "#605d5d"
NEUTRAL_900: str = "#2d2b2b"

ACCENT_100: str = "#fff2ef"
ACCENT_200: str = "#ffe0d9"
ACCENT_600: str = "#dd2b0f"
ACCENT_700: str = "#ae1800"
ACCENT_800: str = "#7c1405"

# The page always sits on the dark canvas (`background:#2d2b2b` in the
# mockups) so the scan itself is the brightest thing on screen.
CANVAS_BG: str = NEUTRAL_900

# --------------------------------------------------------------------
# Semantic colours
# --------------------------------------------------------------------
# These are not aliases: they say what the colour *means*, which the
# token name alone does not. Everything else uses the tokens directly.

BTN_FG: str = "#ffffff"
ERROR_COLOR: str = ACCENT_700
SUCCESS_COLOR: str = COLOR_ACCENT

SUPPORTED_EXTENSIONS: tuple[str, ...] = (".jpg", ".jpeg", ".png")

MARK_DEFAULT_COLOR: str = COLOR_ACCENT
MARK_COLORS: tuple[str, ...] = (
    COLOR_ACCENT,
    COLOR_TEXT,
    "#1a4fd6",
    "#0f8a4a",
    ACCENT_800,
    "#ffffff",
)
MARK_STROKE_WIDTH: int = 2
MARK_SELECTED_STROKE_WIDTH: int = MARK_STROKE_WIDTH + 2
# Selection reads as a heavier accent stroke, never a fill — the fill
# would hide the very text the mark is meant to frame.
MARK_SELECTED_FILL: str = ""
MARK_MIN_SIZE: int = 5
#: Range of a mark's own erase margin, and of the slider that sets it.
#: Not the same thing as INPAINT_DEFAULT_PADDING, which is context given
#: to LaMa and erases nothing; this one is how far past the box the
#: cleaning reaches.
MARK_PADDING_MIN: int = 0
MARK_PADDING_MAX: int = 100
MARK_SIDECAR_SUFFIX: str = ".marks.json"

OCR_LANGUAGES: dict[str, str] = {
    "Español + Inglés": "spa+eng",
    "Solo Español": "spa",
    "Solo Inglés": "eng",
}
OCR_DEFAULT_LANG_LABEL: str = "Español + Inglés"
OCR_MIN_CROP_HEIGHT: int = 30
OCR_SCALE_FACTOR: float = 2.0
OCR_TEMP_PREFIX: str = "visor_ocr_"
OCR_TESSERACT_CMD: str | None = None

CLEAN_SUFFIX: str = ".clean.png"
#: Cuántas versiones limpias guardan descodificadas los pasos 2 y 4. Una
#: página de webcomic ronda los 30 MB en memoria y los originales del
#: capítulo ya están cargados aparte, así que guardarlas todas duplicaba
#: el capítulo en RAM. Unas pocas cubren la página mirada y sus vecinas;
#: subirlo cambia memoria por no releer el PNG al desplazarse.
CLEAN_CACHE_PAGES: int = 4
INPAINT_PADDING_PX: int = 12
INPAINT_DEFAULT_PADDING: int = 64
INPAINT_MIN_PADDING: int = 16
INPAINT_MAX_PADDING: int = 256
INPAINT_CLUSTER_GAP: int = 32

SIDEBAR_WIDTH: int = 260
SIDEBAR_BG: str = COLOR_SURFACE
SIDEBAR_ACTIVE_BG: str = COLOR_ACCENT
SIDEBAR_FG: str = COLOR_TEXT
SIDEBAR_SUBTLE_FG: str = NEUTRAL_600
SIDEBAR_SECTION_PAD: int = 12
SIDEBAR_VIEW_PAD: int = 12
RECENT_PATHS_FILE: str = ".last_folder"

TRANSLATION_DIR_NAME: str = "traducciones"
TRANSLATION_SUFFIX: str = ".translated.png"
TRANSLATION_SIDECAR_SUFFIX: str = ".translation.json"
TRANSLATION_DEFAULT_SRC: str = "en"
TRANSLATION_DEFAULT_TGT: str = "es"
TRANSLATION_LANGS: dict[str, str] = {
    "Inglés": "en",
    "Español": "es",
    "Francés": "fr",
    "Alemán": "de",
    "Italiano": "it",
    "Portugués": "pt",
    "Japonés": "ja",
    "Coreano": "ko",
    "Chino (simplificado)": "zh",
    "Ruso": "ru",
}
TEXT_RENDER_DEFAULT_COLOR: tuple[int, int, int] = (0x20, 0x1E, 0x1D)
# Swatch row of the section inspector, in the mockup's order.
TEXT_COLOR_PRESETS: tuple[tuple[int, int, int], ...] = (
    (0x20, 0x1E, 0x1D),
    (0xFF, 0xFF, 0xFF),
    (0xEC, 0x30, 0x13),
    (0x1A, 0x4F, 0xD6),
    (0x0F, 0x8A, 0x4A),
    (0x7C, 0x14, 0x05),
    (0x9B, 0x97, 0x97),
)
TEXT_RENDER_MAX_PT: int = 72
TEXT_RENDER_MIN_PT: int = 8
TEXT_RENDER_LINE_SPACING: float = 1.15
TEXT_RENDER_PADDING_PX: int = 2
#: Cero es «sin contorno»: el ancho enciende y gradúa a la vez, así que no
#: hace falta un booleano al lado que pueda contradecirlo.
TEXT_RENDER_STROKE_WIDTH: int = 0
TEXT_RENDER_STROKE_COLOR: tuple[int, int, int] = (0xFF, 0xFF, 0xFF)
TEXT_RENDER_STROKE_MAX_PX: int = 12

# Default font configuration for the translator view.
TEXT_RENDER_DEFAULT_FAMILY: str = "Segoe UI"
TEXT_RENDER_FALLBACK_FAMILIES: tuple[str, ...] = (
    "Archivo Black",
    "Archivo",
    "Segoe UI",
    "Arial",
    "Calibri",
    "Tahoma",
    "Verdana",
    "DejaVu Sans",
    "Liberation Sans",
    "Helvetica",
    "Times New Roman",
    "Georgia",
    "Courier New",
)
TEXT_RENDER_USER_MAX_PT_MIN: int = 10
TEXT_RENDER_USER_MAX_PT_MAX: int = 96

#: Los perfiles son de quien rotula, no del capítulo: un archivo en la
#: raíz del proyecto, no un bloque dentro de cada sidecar.
TEXT_PROFILES_FILE: str = "text_profiles.json"

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
