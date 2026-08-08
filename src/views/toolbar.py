"""Tooltips and the footer status bar.

The buttons and toolbars this module used to host now live in
:mod:`src.views.theme`, which is the design system every screen builds
from. What remains is the hover tooltip — used by theme's own widgets —
and the footer strip below the canvas.
"""

from __future__ import annotations

import tkinter as tk

from src.config import (
    COLOR_BG,
    COLOR_DIVIDER,
    ERROR_COLOR,
    COLOR_TEXT,
    NEUTRAL_600,
)
# theme importa este módulo, pero siempre dentro de una función, así que
# el ciclo no se cierra al cargar. La fuente se pide en el momento de
# crear el widget porque la familia no se resuelve hasta theme.init().
from src.views import theme

TOOLTIP_DELAY_MS: int = 450
# Paper-on-ink: the tooltip is the system's colours turned around, so it
# reads as a layer above the surface instead of a patch of it.
TOOLTIP_BG: str = COLOR_TEXT
TOOLTIP_FG: str = COLOR_BG


class Tooltip:
    """A small floating label that appears after hovering a widget.

    Two usage modes:

    1. **Bound** (default): the tooltip is owned by a widget and shown on
       ``<Enter>`` / hidden on ``<Leave>`` or click. After ``delay_ms``
       of hovering, the label appears next to the pointer.
    2. **Programmatic** (``follow_pointer=False``): the tooltip is *not*
       bound to ``<Enter>``/``<Leave>``. The owner calls
       :meth:`show_at` to display it at a position and :meth:`hide` to
       remove it. Useful for hover tooltips on a Canvas where the
       pointer may move over many targets rapidly.

    Usage (bound):
        Tooltip(my_button, "Cancelar el OCR en curso")

    Usage (programmatic):
        tip = Tooltip(root, "", follow_pointer=False, delay_ms=200)
        tip.show_at(120, 80, "Texto de la marca #3")
        tip.hide()
    """

    def __init__(
        self,
        widget: tk.Misc,
        text: str = "",
        *,
        follow_pointer: bool = True,
        delay_ms: int = TOOLTIP_DELAY_MS,
    ) -> None:
        self._widget = widget
        self._text = text
        self._follow_pointer = follow_pointer
        self._delay_ms = delay_ms
        self._tip: tk.Toplevel | None = None
        self._after_id: str | None = None
        if follow_pointer:
            widget.bind("<Enter>", self._on_enter, add="+")
            widget.bind("<Leave>", self._on_leave, add="+")
            widget.bind("<Button-1>", self._on_leave, add="+")

    def set_text(self, text: str) -> None:
        self._text = text
        if self._tip is not None:
            for child in self._tip.winfo_children():
                child.configure(text=text)

    def show_at(self, x: int | None = None, y: int | None = None, text: str | None = None) -> None:
        """Display the tooltip at ``(x, y)`` (defaults to current pointer).

        If ``text`` is provided, the tooltip's text is updated first.
        The call is debounced by ``delay_ms`` so rapid calls collapse
        into a single render.
        """
        if text is not None:
            self._text = text
        self._cancel()
        if not self._text:
            return
        self._after_id = self._widget.after(self._delay_ms, lambda: self._render(x, y))

    def hide(self) -> None:
        """Cancel any pending show and destroy the tooltip if visible."""
        self._cancel()
        self._destroy_tip()

    def _on_enter(self, _event: object) -> None:
        self._cancel()
        if not self._text:
            return
        self._after_id = self._widget.after(self._delay_ms, self._show_at_pointer)

    def _on_leave(self, _event: object) -> None:
        self._cancel()
        self._destroy_tip()

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self._widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show_at_pointer(self) -> None:
        self._after_id = None
        self._render(None, None)

    def _render(self, x: int | None, y: int | None) -> None:
        self._after_id = None
        if self._tip is not None:
            self._destroy_tip()
        if not self._text:
            return
        try:
            if x is None:
                x = self._widget.winfo_pointerx() + 14
            if y is None:
                y = self._widget.winfo_pointery() + 22
        except Exception:
            return
        tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        label = tk.Label(
            tw,
            text=self._text,
            bg=TOOLTIP_BG,
            fg=TOOLTIP_FG,
            font=theme.body_font(9),
            padx=8,
            pady=5,
            bd=1,
            relief=tk.SOLID,
            justify=tk.LEFT,
        )
        label.pack()
        self._tip = tw

    def _destroy_tip(self) -> None:
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


class StatusBar(tk.Frame):
    """The footer strip: a 2 px rule and one line of consequence.

    Mirrors the mockups' bottom bar — a left-aligned message and,
    optionally, a right-aligned shortcut hint.
    """

    _LEVEL_FG: dict[str, str] = {
        "info": NEUTRAL_600,
        "working": COLOR_TEXT,
        "success": COLOR_TEXT,
        "error": ERROR_COLOR,
    }

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, bg=COLOR_BG, bd=0, highlightthickness=0)
        tk.Frame(self, bg=COLOR_DIVIDER, height=2).pack(side=tk.TOP, fill=tk.X)
        row = tk.Frame(self, bg=COLOR_BG)
        row.pack(side=tk.TOP, fill=tk.X)
        self._var = tk.StringVar(value="")
        self._label = tk.Label(
            row,
            textvariable=self._var,
            font=theme.body_font(9),
            bg=COLOR_BG,
            fg=NEUTRAL_600,
            anchor=tk.W,
            padx=14,
            pady=8,
        )
        self._label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._hint = tk.Label(
            row,
            text="",
            font=theme.body_font(9),
            bg=COLOR_BG,
            fg=NEUTRAL_600,
            anchor=tk.E,
            padx=14,
            pady=8,
        )
        self._hint.pack(side=tk.RIGHT)

    def set(self, text: str, level: str = "info") -> None:
        """Set the status text with a colour level.

        ``level`` is one of ``info``, ``success``, ``error``, ``working``.
        """
        self._var.set(text)
        self._label.configure(fg=self._LEVEL_FG.get(level, COLOR_TEXT))

    def set_hint(self, text: str) -> None:
        """Right-aligned shortcut list, as in the mockups' footer."""
        self._hint.configure(text=text)
