"""Modernist widget vocabulary for the Tk shell.

Port of the ``Traductor de Manga - Mockups`` design canvas (direction
3a). Every screen is built from the same small set of parts, so the
four steps read as one application:

* **Rules, not boxes** — 2 px ink for structural edges, 1 px divider
  inside a panel. No rounded corners, no drop shadows on flat surfaces.
* **One accent** — red is reserved for the active step, the primary
  action, the marks and anything that needs review. Everything else is
  ink on paper.
* **Kickers** — small uppercase labels name a region instead of a
  heavier heading.
* **Dark canvas** — the scan sits on ``CANVAS_BG`` so the page is the
  brightest thing on screen.

:func:`init` must run once after the Tk root exists: it resolves the
font stacks against what is actually installed and themes the ttk
widgets (the table, the scrollbars).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable, Iterable, Sequence

from PIL import Image, ImageTk

from src.config import (
    ACCENT_100,
    ACCENT_200,
    ACCENT_600,
    ACCENT_700,
    ACCENT_800,
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DIVIDER,
    COLOR_SURFACE,
    COLOR_TEXT,
    ERROR_COLOR,
    NEUTRAL_300,
    NEUTRAL_400,
    NEUTRAL_500,
    NEUTRAL_600,
    NEUTRAL_700,
    PROJECT_ROOT,
)

__all__ = [
    "init",
    "heading_font", "body_font", "mono_font",
    "kicker", "heading", "body", "rule",
    "icon", "ICON_SIZE",
    "button", "restyle_button", "set_icon", "set_icon_color", "set_enabled",
    "SegmentedBar", "SEGMENT_CHARS",
    "Meter", "DashedZone", "TopBar",
    "swatch", "tag", "card", "field_label", "entry", "text_area",
    "option_menu", "slider", "checkbox",
    "alert", "confirm", "center_on", "DIALOG_WIDTH",
]

# Font stacks. Archivo is the mockups' typeface; the rest are the
# closest grotesques that ship with the supported platforms.
_HEADING_STACK: tuple[str, ...] = (
    "Archivo", "Archivo Black", "Archivo Expanded",
    "Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI",
    "Helvetica Neue", "DejaVu Sans", "Arial",
)
_BODY_STACK: tuple[str, ...] = (
    "Archivo", "Segoe UI Variable Text", "Segoe UI",
    "Helvetica Neue", "DejaVu Sans", "Arial",
)
_MONO_STACK: tuple[str, ...] = (
    "Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New",
)

_heading_family: str = "Segoe UI"
_body_family: str = "Segoe UI"
_mono_family: str = "Courier New"


# ----------------------------------------------------------------------
# Setup
# ----------------------------------------------------------------------


def init(root: tk.Misc) -> None:
    """Resolve the font stacks and theme the ttk widgets."""
    global _heading_family, _body_family, _mono_family
    try:
        installed = {name.lower() for name in tkfont.families(root)}
    except Exception:
        installed = set()

    def pick(stack: Sequence[str], fallback: str) -> str:
        for family in stack:
            if family.lower() in installed:
                return family
        return fallback

    _heading_family = pick(_HEADING_STACK, "Segoe UI")
    _body_family = pick(_BODY_STACK, "Segoe UI")
    _mono_family = pick(_MONO_STACK, "Courier New")

    _init_ttk()


def _init_ttk() -> None:
    """Light theme for the Treeview + scrollbars used by steps 3 and 4."""
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(
        "Modernist.Treeview",
        background=COLOR_BG,
        fieldbackground=COLOR_BG,
        foreground=COLOR_TEXT,
        font=body_font(10),
        rowheight=30,
        borderwidth=0,
        relief=tk.FLAT,
    )
    style.map(
        "Modernist.Treeview",
        background=[("selected", ACCENT_200)],
        foreground=[("selected", COLOR_TEXT)],
    )
    style.configure(
        "Modernist.Treeview.Heading",
        background=COLOR_BG,
        foreground=NEUTRAL_600,
        font=heading_font(8),
        relief=tk.FLAT,
        borderwidth=0,
        padding=(8, 8),
    )
    style.map(
        "Modernist.Treeview.Heading",
        background=[("active", COLOR_SURFACE)],
    )
    style.configure(
        "Modernist.Vertical.TScrollbar",
        background=NEUTRAL_300,
        troughcolor=COLOR_SURFACE,
        bordercolor=COLOR_SURFACE,
        arrowcolor=NEUTRAL_700,
        relief=tk.FLAT,
        borderwidth=0,
    )
    style.map(
        "Modernist.Vertical.TScrollbar",
        background=[("active", NEUTRAL_400)],
    )
    # The rail sits on the darker surface, so its thumb needs more
    # contrast than the one on the table.
    style.configure(
        "Rail.Vertical.TScrollbar",
        background=NEUTRAL_500,
        troughcolor=COLOR_SURFACE,
        bordercolor=COLOR_SURFACE,
        arrowcolor=COLOR_SURFACE,
        arrowsize=10,
        relief=tk.FLAT,
        borderwidth=0,
        width=8,
    )
    style.map(
        "Rail.Vertical.TScrollbar",
        background=[("active", NEUTRAL_700)],
    )


# ----------------------------------------------------------------------
# Fonts
# ----------------------------------------------------------------------


def heading_font(size: int = 11, weight: str = "bold") -> tuple[str, int, str]:
    return (_heading_family, size, weight)


def body_font(size: int = 10, weight: str = "normal") -> tuple[str, int, str]:
    return (_body_family, size, weight)


def mono_font(size: int = 9) -> tuple[str, int, str]:
    return (_mono_family, size, "normal")


# ----------------------------------------------------------------------
# Text
# ----------------------------------------------------------------------


def kicker(
    parent: tk.Misc,
    text: str,
    *,
    bg: str | None = None,
    fg: str = NEUTRAL_600,
) -> tk.Label:
    """Small uppercase label that names a region (``.kick``)."""
    return tk.Label(
        parent,
        text=text.upper(),
        font=heading_font(8),
        bg=bg if bg is not None else _bg_of(parent),
        fg=fg,
        anchor=tk.W,
    )


def heading(
    parent: tk.Misc,
    text: str,
    *,
    size: int = 17,
    bg: str | None = None,
    fg: str = COLOR_TEXT,
    wrap: int | None = None,
) -> tk.Label:
    return tk.Label(
        parent,
        text=text,
        font=heading_font(size),
        bg=bg if bg is not None else _bg_of(parent),
        fg=fg,
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=wrap or 0,
    )


def body(
    parent: tk.Misc,
    text: str,
    *,
    size: int = 10,
    bg: str | None = None,
    fg: str = NEUTRAL_700,
    wrap: int | None = None,
    weight: str = "normal",
) -> tk.Label:
    return tk.Label(
        parent,
        text=text,
        font=body_font(size, weight),
        bg=bg if bg is not None else _bg_of(parent),
        fg=fg,
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=wrap or 0,
    )


def rule(
    parent: tk.Misc,
    *,
    thickness: int = 2,
    color: str = COLOR_DIVIDER,
    vertical: bool = False,
) -> tk.Frame:
    """A structural line. 2 px ink for edges, 1 px divider inside."""
    if vertical:
        return tk.Frame(parent, bg=color, width=thickness)
    return tk.Frame(parent, bg=color, height=thickness)


def _bg_of(widget: tk.Misc) -> str:
    try:
        return str(widget.cget("bg"))
    except Exception:
        return COLOR_BG


# ----------------------------------------------------------------------
# Icons
# ----------------------------------------------------------------------

#: Where the icon set lives. The files are Font Awesome «solid» exports
#: at 640×640, black on transparent.
ICON_DIR = PROJECT_ROOT / "src" / "assets" / "images"

#: Side, in pixels, of an icon inside a button.
ICON_SIZE = 30

# ponytail: la caché es lo único que sujeta cada PhotoImage —Tk recoge la
# imagen que nadie referencia y deja el botón en blanco—, así que está
# atada a la raíz Tk viva. Si algún día la app recrea la raíz, vaciarla.
_ICONS: dict[tuple[str, int, str], ImageTk.PhotoImage] = {}


def icon(
    name: str, *, size: int = ICON_SIZE, color: str = COLOR_TEXT,
) -> ImageTk.PhotoImage:
    """An icon from :data:`ICON_DIR`, escalado y teñido de *color*.

    El PNG es negro y un ``image=`` no obedece al ``fg`` del botón, así
    que el color se pinta aquí: se conserva el canal alfa del dibujo y se
    rellena el resto. Es lo que permite que un conmutador encendido
    —fondo tinta— siga teniendo un icono visible.

    Un nombre que no existe revienta: es una errata del programador, no
    una entrada de usuario.
    """
    key = (name, size, color)
    cached = _ICONS.get(key)
    if cached is None:
        source = Image.open(ICON_DIR / f"{name}.png").convert("RGBA")
        source = source.resize((size, size), Image.LANCZOS)
        tinted = Image.new("RGBA", source.size, color)
        tinted.putalpha(source.getchannel("A"))
        cached = _ICONS[key] = ImageTk.PhotoImage(tinted)
    return cached


# ----------------------------------------------------------------------
# Buttons
# ----------------------------------------------------------------------

_VARIANTS: dict[str, dict[str, str]] = {
    # bg, fg, hover, active, border ("" = no border)
    "primary": {
        "bg": COLOR_ACCENT, "fg": "#ffffff",
        "hover": ACCENT_600, "active": ACCENT_700, "border": "",
    },
    "ink": {
        "bg": COLOR_TEXT, "fg": COLOR_BG,
        "hover": "#3a3736", "active": "#000000", "border": "",
    },
    "ghost": {
        "bg": "", "fg": ACCENT_700,
        "hover": ACCENT_100, "active": ACCENT_200, "border": "",
    },
    # The default, and the only bordered variant: "solid" draws the
    # border with a relief because Windows never paints a Button's
    # highlight ring. A variant that used the ring instead lived here
    # once ("secondary") and rendered as plain text on every screen.
    "outline": {
        "bg": "", "fg": COLOR_TEXT,
        "hover": NEUTRAL_300, "active": NEUTRAL_400, "border": COLOR_TEXT,
        "solid": "1",
    },
}

#: Width, in characters, of every labelled segment of a bar. The longest
#: label in the strip can push it up, never down — so the controls of a
#: top bar line up whether they say «Una» or «Original».
SEGMENT_CHARS = 9


def button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None] | None = None,
    *,
    variant: str = "outline",
    tooltip: str | None = None,
    icon_name: str | None = None,
    icon_size: int = ICON_SIZE,
    size: int = 10,
    padx: int = 14,
    pady: int = 8,
    anchor: str = tk.CENTER,
    border_width: int = 1,
) -> tk.Button:
    """A flat squared button in one of the system variants.

    Con *icon_name* el botón lleva un icono de :func:`icon`, teñido según
    la variante y el estado. Sin *text*, el icono es el botón entero y el
    *tooltip* pasa a ser la única etiqueta que hay.
    """
    spec = _VARIANTS.get(variant, _VARIANTS["outline"])
    base_bg = spec["bg"] or _bg_of(parent)
    border = spec["border"]
    solid = bool(spec.get("solid"))
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        font=heading_font(size),
        bg=base_bg,
        fg=spec["fg"],
        activebackground=spec["active"],
        activeforeground=spec["fg"],
        disabledforeground=NEUTRAL_500,
        relief=tk.SOLID if solid else tk.FLAT,
        bd=border_width if solid else 0,
        padx=padx,
        pady=pady,
        anchor=anchor,
        cursor="hand2",
        highlightthickness=0 if solid else (border_width if border else 0),
        highlightbackground=border or base_bg,
        highlightcolor=border or base_bg,
    )
    btn._base_bg = base_bg  # type: ignore[attr-defined]
    btn._hover_bg = spec["hover"]  # type: ignore[attr-defined]
    btn._border_width = border_width  # type: ignore[attr-defined]
    btn._variant = variant  # type: ignore[attr-defined]
    btn._icon = icon_name  # type: ignore[attr-defined]
    btn._icon_size = icon_size  # type: ignore[attr-defined]
    btn._icon_color = None  # type: ignore[attr-defined]
    if icon_name:
        btn.configure(compound=tk.LEFT if text else tk.NONE)
        _paint_icon(btn)

    def on_enter(_e: object) -> None:
        if str(btn.cget("state")) != tk.DISABLED:
            btn.configure(bg=btn._hover_bg)  # type: ignore[attr-defined]

    def on_leave(_e: object) -> None:
        btn.configure(bg=btn._base_bg)  # type: ignore[attr-defined]

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    if tooltip:
        from src.views.toolbar import Tooltip
        # Se guarda: cuando el icono es la única etiqueta, cambiar de
        # estado significa reescribir el tooltip.
        btn._tip = Tooltip(btn, tooltip)  # type: ignore[attr-defined]
    return btn


def _paint_icon(btn: tk.Button) -> None:
    """Tiñe el icono del botón según su color, su variante y su estado.

    El único sitio que decide el color: ``disabledforeground`` no toca
    las imágenes, así que un botón icono-solo desactivado se vería igual
    que uno activo si no se repintara a mano. Desactivado gana siempre —
    un icono en acento y apagado sería una promesa falsa.
    """
    name = getattr(btn, "_icon", None)
    if not name:
        return
    spec = _VARIANTS.get(getattr(btn, "_variant", "outline"), _VARIANTS["outline"])
    if str(btn.cget("state")) == tk.DISABLED:
        color = NEUTRAL_500
    else:
        color = getattr(btn, "_icon_color", None) or spec["fg"]
    btn.configure(image=icon(
        name, size=getattr(btn, "_icon_size", ICON_SIZE), color=color,
    ))


def restyle_button(btn: tk.Button, variant: str) -> None:
    """Switch an existing button to another variant (keeps geometry)."""
    spec = _VARIANTS.get(variant, _VARIANTS["outline"])
    base_bg = spec["bg"] or _bg_of(btn.master)
    border = spec["border"]
    solid = bool(spec.get("solid"))
    # Keep the weight the button was built with, so restyling an outlined
    # action does not quietly thin its border.
    width = getattr(btn, "_border_width", 1)
    btn._base_bg = base_bg  # type: ignore[attr-defined]
    btn._hover_bg = spec["hover"]  # type: ignore[attr-defined]
    btn._variant = variant  # type: ignore[attr-defined]
    btn.configure(
        bg=base_bg, fg=spec["fg"],
        activebackground=spec["active"], activeforeground=spec["fg"],
        relief=tk.SOLID if solid else tk.FLAT,
        bd=width if solid else 0,
        highlightthickness=0 if solid else (width if border else 0),
        highlightbackground=border or base_bg,
        highlightcolor=border or base_bg,
    )
    _paint_icon(btn)


def set_icon(btn: tk.Button, name: str) -> None:
    """Cambia el dibujo del botón —el ojo por el ojo tachado—."""
    btn._icon = name  # type: ignore[attr-defined]
    _paint_icon(btn)


def set_icon_color(btn: tk.Button, color: str | None) -> None:
    """Tiñe el icono al margen de la variante; ``None`` la devuelve.

    Es cómo se enciende un conmutador de solo icono sin rellenar el
    fondo: el acento se lo lleva el dibujo, no la caja.
    """
    btn._icon_color = color  # type: ignore[attr-defined]
    _paint_icon(btn)


def set_enabled(btn: tk.Button, enabled: bool) -> None:
    """Activa o desactiva el botón, y repinta su icono para que se note."""
    btn.configure(state=tk.NORMAL if enabled else tk.DISABLED)
    _paint_icon(btn)


# ----------------------------------------------------------------------
# Segmented control (.fbar)
# ----------------------------------------------------------------------


class SegmentedBar(tk.Frame):
    """A bordered strip of small buttons where one option is active.

    Used for every canvas control in the mockups: view mode, zoom,
    clean/original, page navigation and the step-3 filters.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        bg: str = COLOR_BG,
        border: str = COLOR_TEXT,
        border_width: int = 2,
        pad: int = 3,
        uniform_chars: int = 0,
    ) -> None:
        super().__init__(
            master, bg=bg, bd=0,
            highlightthickness=border_width,
            highlightbackground=border, highlightcolor=border,
        )
        self._bg = bg
        self._pad = pad
        self._buttons: dict[str, tk.Button] = {}
        self._order: list[str] = []
        self._active: str | None = None
        # Labelled bars ask for a uniform width; the icon strips (± ◀ ▶)
        # leave it at zero and stay as tight as their glyphs.
        self._uniform = max(0, uniform_chars)
        self._width = self._uniform
        self._pinned: set[str] = set()

    def add(
        self,
        key: str,
        text: str,
        command: Callable[[], None] | None = None,
        *,
        tooltip: str | None = None,
        active: bool = False,
        width: int = 0,
    ) -> tk.Button:
        btn = tk.Button(
            self,
            text=text,
            command=command,
            font=heading_font(8),
            bg=self._bg,
            fg=COLOR_TEXT,
            activebackground=NEUTRAL_300,
            activeforeground=COLOR_TEXT,
            disabledforeground=NEUTRAL_500,
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=4,
            cursor="hand2",
            highlightthickness=0,
        )
        btn.pack(side=tk.LEFT, padx=(self._pad if not self._order else 1, self._pad))
        self._buttons[key] = btn
        self._order.append(key)
        if width:
            # A readout, not a label: pinned so the strip does not
            # shuffle when «100%» becomes «1000%» or page 9 becomes 10.
            btn.configure(width=width)
            self._pinned.add(key)
        elif self._uniform:
            btn.configure(width=self._width)
            self._even_out(text)

        def on_enter(_e: object) -> None:
            if self._active == key or str(btn.cget("state")) == tk.DISABLED:
                return
            btn.configure(bg=NEUTRAL_300)

        def on_leave(_e: object) -> None:
            if self._active == key:
                return
            btn.configure(bg=self._bg)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        if tooltip:
            from src.views.toolbar import Tooltip
            Tooltip(btn, tooltip)
        if active:
            self.set_active(key)
        return btn

    def set_active(self, key: str | None) -> None:
        self._active = key
        for name, btn in self._buttons.items():
            if name == key:
                btn.configure(bg=COLOR_TEXT, fg=COLOR_BG)
            else:
                btn.configure(bg=self._bg, fg=COLOR_TEXT)

    def _even_out(self, text: str) -> None:
        """Give every segment the width of the longest label.

        The width only ever grows. The step-3 filters carry a count that
        changes as the chapter is translated, and a strip that reflowed
        each time a number gained a digit would twitch under the cursor.
        """
        width = max(self._width, self._uniform, len(text))
        if width == self._width:
            return
        self._width = width
        for name, btn in self._buttons.items():
            if name not in self._pinned:
                btn.configure(width=width)

    def set_text(self, key: str, text: str) -> None:
        btn = self._buttons.get(key)
        if btn is not None:
            btn.configure(text=text)
            if self._uniform and key not in self._pinned:
                self._even_out(text)

    def set_enabled(self, key: str, enabled: bool) -> None:
        btn = self._buttons.get(key)
        if btn is not None:
            btn.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    def button(self, key: str) -> tk.Button | None:
        return self._buttons.get(key)


# ----------------------------------------------------------------------
# Meter (.progress rule)
# ----------------------------------------------------------------------


class Meter(tk.Frame):
    """A 6 px progress rule: a neutral track with a solid fill."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        height: int = 6,
        color: str = COLOR_ACCENT,
        track: str = NEUTRAL_300,
    ) -> None:
        super().__init__(master, bg=track, height=height, bd=0,
                         highlightthickness=0)
        self.pack_propagate(False)
        self._fill = tk.Frame(self, bg=color, bd=0, highlightthickness=0)
        self._fraction = 0.0
        self.set(0.0)

    def set(self, fraction: float) -> None:
        self._fraction = max(0.0, min(1.0, float(fraction)))
        if self._fraction <= 0:
            self._fill.place_forget()
        else:
            self._fill.place(x=0, y=0, relwidth=self._fraction, relheight=1.0)

    def set_color(self, color: str) -> None:
        self._fill.configure(bg=color)


# ----------------------------------------------------------------------
# Drop zone with a dashed border
# ----------------------------------------------------------------------


class DashedZone(tk.Frame):
    """A surface framed by a dashed rule, with content in ``body``.

    Tk cannot draw a dashed widget border, so the frame is painted on a
    canvas and the content lives in a canvas window that is re-laid on
    every resize.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        bg: str = COLOR_SURFACE,
        border: str = NEUTRAL_400,
        padx: int = 40,
    ) -> None:
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self._border = border
        self._padx = padx
        self._canvas = tk.Canvas(
            self, bg=bg, bd=0, highlightthickness=0, takefocus=0,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self.body = tk.Frame(self._canvas, bg=bg)
        self._window = self._canvas.create_window(
            padx, 0, window=self.body, anchor=tk.NW,
        )
        self._canvas.bind("<Configure>", self._relayout)
        self.body.bind("<Configure>", self._relayout)

    def _relayout(self, _event: object = None) -> None:
        try:
            width = self._canvas.winfo_width()
            height = self._canvas.winfo_height()
        except Exception:
            return
        if width <= 1 or height <= 1:
            return
        self._canvas.delete("frame")
        self._canvas.create_rectangle(
            1, 1, width - 2, height - 2,
            outline=self._border, width=2, dash=(6, 4), tags=("frame",),
        )
        body_h = self.body.winfo_reqheight()
        self._canvas.coords(
            self._window, self._padx, max(0, (height - body_h) // 2),
        )
        self._canvas.itemconfigure(
            self._window, width=max(1, width - self._padx * 2),
        )
        self._canvas.tag_lower("frame")


# ----------------------------------------------------------------------
# Docked bars
# ----------------------------------------------------------------------


class TopBar(tk.Frame):
    """The 42 px control strip that sits above the canvas.

    Children go into ``body``; the 2 px rule underneath is drawn here so
    every step gets the same edge.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        height: int = 42,
        bg: str = COLOR_BG,
        rule_color: str = COLOR_DIVIDER,
        rule_width: int = 2,
        padx: int = 14,
    ) -> None:
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self.body = tk.Frame(self, bg=bg, height=height)
        self.body.pack(side=tk.TOP, fill=tk.X, padx=padx)
        self.body.pack_propagate(False)
        self._rule = rule(self, thickness=rule_width, color=rule_color)
        self._rule.pack(side=tk.TOP, fill=tk.X)

    def gap(self) -> tk.Frame:
        """A flexible gap that pushes the rest of the row to the right."""
        f = tk.Frame(self.body, bg=_bg_of(self.body))
        f.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return f


# ----------------------------------------------------------------------
# Small parts
# ----------------------------------------------------------------------


def swatch(
    parent: tk.Misc,
    color: str,
    command: Callable[[], None] | None = None,
    *,
    size: int = 16,
    selected: bool = False,
    tooltip: str | None = None,
) -> tk.Frame:
    """A colour square. Selection is an accent ring, as in the mockups."""
    holder = tk.Frame(
        parent,
        bg=COLOR_ACCENT if selected else _bg_of(parent),
        padx=2, pady=2,
    )
    box = tk.Frame(
        holder, bg=color, width=size, height=size,
        highlightthickness=1,
        highlightbackground=COLOR_DIVIDER, highlightcolor=COLOR_DIVIDER,
        cursor="hand2" if command else "",
    )
    box.pack()
    holder._box = box  # type: ignore[attr-defined]
    if command is not None:
        for widget in (holder, box):
            widget.bind("<Button-1>", lambda _e: command())
    if tooltip:
        from src.views.toolbar import Tooltip
        Tooltip(box, tooltip)
    return holder


def tag(
    parent: tk.Misc,
    text: str,
    *,
    kind: str = "neutral",
    bg: str | None = None,
) -> tk.Label:
    """A compact status chip (``.tag``)."""
    palette = {
        "neutral": (NEUTRAL_300, COLOR_TEXT),
        "accent": (ACCENT_100, ACCENT_800),
        "solid": (COLOR_ACCENT, "#ffffff"),
        "ink": (COLOR_TEXT, COLOR_BG),
    }
    fill, fg = palette.get(kind, palette["neutral"])
    return tk.Label(
        parent, text=text, font=heading_font(8),
        bg=fill, fg=fg, padx=6, pady=2,
    )


def card(
    parent: tk.Misc,
    *,
    bg: str | None = None,
    border: str = COLOR_DIVIDER,
    border_width: int = 1,
    padx: int = 9,
    pady: int = 8,
) -> tk.Frame:
    """A bordered block used for the recent chapters and engine status."""
    frame = tk.Frame(
        parent,
        bg=bg if bg is not None else _bg_of(parent),
        padx=padx, pady=pady,
        highlightthickness=border_width,
        highlightbackground=border, highlightcolor=border,
        bd=0,
    )
    return frame


def field_label(parent: tk.Misc, text: str) -> tk.Label:
    return tk.Label(
        parent, text=text, font=body_font(9),
        bg=_bg_of(parent), fg=NEUTRAL_700, anchor=tk.W,
    )


def entry(
    parent: tk.Misc,
    textvariable: tk.Variable | None = None,
    *,
    bg: str = COLOR_SURFACE,
) -> tk.Entry:
    widget = tk.Entry(
        parent,
        textvariable=textvariable,
        font=body_font(10),
        bg=bg, fg=COLOR_TEXT,
        insertbackground=COLOR_ACCENT,
        relief=tk.FLAT, bd=0,
        highlightthickness=1,
        highlightbackground=COLOR_DIVIDER,
        highlightcolor=COLOR_ACCENT,
    )
    return widget


def text_area(
    parent: tk.Misc,
    *,
    height: int = 3,
    bg: str = COLOR_SURFACE,
) -> tk.Text:
    widget = tk.Text(
        parent,
        height=height,
        font=body_font(10),
        bg=bg, fg=COLOR_TEXT,
        insertbackground=COLOR_ACCENT,
        relief=tk.FLAT, bd=0, wrap=tk.WORD,
        padx=7, pady=5,
        highlightthickness=1,
        highlightbackground=COLOR_DIVIDER,
        highlightcolor=COLOR_ACCENT,
    )
    return widget


def option_menu(
    parent: tk.Misc,
    variable: tk.StringVar,
    values: Iterable[str],
    command: Callable[[str], None] | None = None,
) -> tk.OptionMenu:
    options = list(values) or [variable.get() or ""]
    widget = tk.OptionMenu(parent, variable, *options, command=command)
    widget.configure(
        font=body_font(10),
        bg=COLOR_SURFACE, fg=COLOR_TEXT,
        activebackground=NEUTRAL_300, activeforeground=COLOR_TEXT,
        relief=tk.FLAT, bd=0, anchor=tk.W, padx=8, pady=4,
        highlightthickness=1,
        highlightbackground=COLOR_DIVIDER, highlightcolor=COLOR_DIVIDER,
        indicatoron=False,
    )
    try:
        widget["menu"].configure(
            font=body_font(10), bg=COLOR_BG, fg=COLOR_TEXT,
            activebackground=COLOR_ACCENT, activeforeground="#ffffff",
            relief=tk.FLAT, bd=1,
        )
    except Exception:
        pass
    return widget


def slider(
    parent: tk.Misc,
    *,
    from_: int,
    to: int,
    variable: tk.Variable,
    command: Callable[[str], None] | None = None,
    bg: str | None = None,
) -> tk.Scale:
    background = bg if bg is not None else _bg_of(parent)
    return tk.Scale(
        parent,
        from_=from_, to=to,
        orient=tk.HORIZONTAL,
        variable=variable,
        command=command,
        bg=background,
        fg=COLOR_TEXT,
        troughcolor=NEUTRAL_300,
        activebackground=COLOR_ACCENT,
        highlightthickness=0,
        bd=0,
        showvalue=False,
        sliderrelief=tk.FLAT,
        sliderlength=14,
        width=10,
    )


def checkbox(
    parent: tk.Misc,
    text: str,
    variable: tk.BooleanVar,
    command: Callable[[], None] | None = None,
) -> tk.Checkbutton:
    return tk.Checkbutton(
        parent,
        text=text,
        variable=variable,
        command=command,
        font=body_font(10),
        bg=_bg_of(parent), fg=COLOR_TEXT,
        activebackground=_bg_of(parent), activeforeground=COLOR_TEXT,
        selectcolor=COLOR_BG,
        highlightthickness=0, bd=0, anchor=tk.W,
        cursor="hand2",
    )


# ----------------------------------------------------------------------
# Modal dialogs
# ----------------------------------------------------------------------

#: The mockups' dialog width. Height always follows the content.
DIALOG_WIDTH = 460


def center_on(window: tk.Toplevel, master: tk.Misc, width: int) -> None:
    """Place *window* over the top third of *master*'s window."""
    window.update_idletasks()
    height = window.winfo_reqheight()
    top = master.winfo_toplevel()
    x = top.winfo_rootx() + (top.winfo_width() - width) // 2
    y = top.winfo_rooty() + (top.winfo_height() - height) // 3
    window.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")


class _MessageDialog(tk.Toplevel):
    """One modal, whether it asks or only tells.

    An alert is this with the cancel button left out, which is why there
    is a single class: the two differ by one button, not by a layout.
    ``result`` is ``True`` only when the confirming button was pressed.
    """

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        message: str,
        *,
        kicker_text: str,
        kicker_fg: str,
        confirm_label: str,
        cancel_label: str | None,
    ) -> None:
        super().__init__(master, bg=COLOR_BG)
        self.result = False
        self.title(title)
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.configure(
            highlightthickness=2,
            highlightbackground=COLOR_TEXT, highlightcolor=COLOR_TEXT,
        )

        header = tk.Frame(self, bg=COLOR_BG, padx=18, pady=16)
        header.pack(fill=tk.X)
        kicker(header, kicker_text, fg=kicker_fg).pack(fill=tk.X, pady=(0, 5))
        heading(header, title, size=15, wrap=DIALOG_WIDTH - 36).pack(fill=tk.X)
        rule(self, thickness=2, color=COLOR_TEXT).pack(fill=tk.X)

        body_frame = tk.Frame(self, bg=COLOR_BG, padx=18, pady=16)
        body_frame.pack(fill=tk.BOTH, expand=True)
        body(
            body_frame, message, size=10, wrap=DIALOG_WIDTH - 36,
        ).pack(fill=tk.X)

        rule(self, thickness=2, color=COLOR_DIVIDER).pack(fill=tk.X)
        actions = tk.Frame(self, bg=COLOR_BG, padx=18, pady=14)
        actions.pack(fill=tk.X)
        button(
            actions, confirm_label, self._confirm,
            variant="primary", padx=16, pady=10,
        ).pack(side=tk.LEFT)
        if cancel_label is not None:
            button(
                actions, cancel_label, self._cancel,
                variant="outline", padx=16, pady=10,
            ).pack(side=tk.LEFT, padx=(9, 0))

        # Closing the window is «no», never «yes» — the X and Escape have
        # to agree with the cancel button or a confirmation is a trap.
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.bind("<Return>", lambda _e: self._confirm())
        center_on(self, master, DIALOG_WIDTH)
        self.grab_set()
        self.focus_set()
        self.wait_window(self)

    def _confirm(self) -> None:
        self.result = True
        self._close()

    def _cancel(self) -> None:
        self.result = False
        self._close()

    def _close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


def alert(
    master: tk.Misc,
    title: str,
    message: str,
    *,
    level: str = "info",
    button_label: str = "Entendido",
) -> None:
    """Say something and wait for the acknowledgement.

    ``level`` is the :class:`StatusBar` vocabulary, not a wider one:
    only ``error`` looks different, because in this system only ``error``
    has a colour of its own.
    """
    is_error = level == "error"
    _MessageDialog(
        master, title, message,
        kicker_text="Error" if is_error else "Aviso",
        kicker_fg=ERROR_COLOR if is_error else NEUTRAL_600,
        confirm_label=button_label,
        cancel_label=None,
    )


def confirm(
    master: tk.Misc,
    title: str,
    message: str,
    *,
    confirm_label: str,
    cancel_label: str = "Cancelar",
) -> bool:
    """Ask, and answer ``True`` only for the confirming button.

    ``confirm_label`` has no default on purpose: DESIGN.md §7 asks the
    button to say what it does, and «Sí» never does.
    """
    return _MessageDialog(
        master, title, message,
        kicker_text="Confirmar",
        kicker_fg=NEUTRAL_600,
        confirm_label=confirm_label,
        cancel_label=cancel_label,
    ).result
