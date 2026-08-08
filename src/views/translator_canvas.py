"""Canvas that displays a clean image with editable translated text boxes.

Subclasses :class:`ZoomedCanvas` for pan/zoom. Each mark rectangle is
rendered as a text box with the translation inside. What that box looks
like is ``resolve_box``'s answer, not this module's: the same function
the exporter calls, so the preview cannot drift from the PNG. It also
means the style reaching Tk is the one that exists on disk — Tk would
happily fake a slant that the exported PNG is not going to have.

Double-click on a box opens an inline ``Text`` editor placed on top of
the canvas. ``Enter`` (or ``Ctrl+Enter``) commits the edit;
``Escape`` cancels.

Laying a box out means a binary search over font sizes, and every step
of that search opens a font file. The overlay is redrawn on every pan
frame, so the result is cached against the :class:`TextBox` that
produced it: panning then only moves the text it already measured, and
a re-fit happens when — and only when — something that shapes the text
actually changes.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Callable

from src.config import COLOR_ACCENT, COLOR_TEXT
from src.utils.logger import get_logger
from src.utils.marks_store import MarksStore
from src.utils.text_renderer import (
    FitResult,
    RenderConfig,
    TextBox,
    _load_font,
    fit_text,
    resolve_box,
)
from src.views.zoomed_canvas import ZoomedCanvas

log = get_logger("translator_canvas")

ChangeCallback = Callable[[], None]
SelectCallback = Callable[[int], None]
EditCallback = Callable[[int, str], None]

#: Layouts kept around between redraws. One entry per box per variation
#: the user tried; a chapter page holds a handful, so the ceiling only
#: matters after a long session of nudging the same section.
_LAYOUT_CACHE_LIMIT = 240


def _rgb_to_hex(color: tuple[int, int, int]) -> str:
    r, g, b = (int(c) for c in color)
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _tk_font_for(
    size: int,
    family: str | None = None,
    *,
    bold: bool = False,
    italic: bool = False,
) -> tkfont.Font:
    """A Tk font for the preview.

    Tk *does* synthesise a slant and a weight the family does not have,
    and PIL does not — so the caller passes the style already resolved
    against the files on disk (:func:`resolve_style`). Otherwise the
    preview would show a cursiva that the exported PNG will not have.
    """
    fam = family or "Segoe UI"
    weight = "bold" if bold else "normal"
    slant = "italic" if italic else "roman"
    try:
        return tkfont.Font(
            family=fam, size=max(6, int(size)),
            weight=weight, slant=slant,
        )
    except Exception:
        try:
            return tkfont.Font(
                size=max(6, int(size)), weight=weight, slant=slant,
            )
        except Exception:
            return tkfont.nametofont("TkDefaultFont")


class _Layout:
    """A box laid out once, in image pixels, ready to be scaled and drawn.

    Everything the draw loop needs is measured here: the line widths and
    the left bearing of each line, which otherwise cost a ``getbbox``
    per line per frame.
    """

    __slots__ = ("font_size", "line_h", "lines")

    def __init__(self, fit: FitResult, font: object) -> None:
        self.font_size = fit.font_size
        try:
            ascent, descent = font.getmetrics()  # type: ignore[attr-defined]
        except Exception:
            ascent, descent = 12, 3
        self.line_h = (ascent + descent) * 1.15
        # (texto, ancho, desplazamiento izquierdo) en píxeles de imagen.
        self.lines: list[tuple[str, float, float]] = []
        for line in fit.lines:
            try:
                left, _top, right, _bottom = font.getbbox(line)  # type: ignore[attr-defined]
                self.lines.append((line, max(0.0, right - left), -float(left)))
            except Exception:
                try:
                    width = float(font.getlength(line))  # type: ignore[attr-defined]
                except Exception:
                    width = 0.0
                self.lines.append((line, width, 0.0))


class TranslatorCanvas(ZoomedCanvas):
    """A zoomable canvas with one editable text box per mark."""

    def __init__(
        self,
        master: tk.Misc,
        on_change: ChangeCallback | None = None,
        on_select: SelectCallback | None = None,
        on_text_edited: EditCallback | None = None,
    ) -> None:
        super().__init__(master, on_change=on_change)
        self._store: MarksStore | None = None
        self._on_select = on_select
        self._on_text_edited = on_text_edited

        self._box_canvas_ids: dict[int, list[int]] = {}
        self._editor: tk.Text | None = None
        self._editor_mark_id: int | None = None
        self._layouts: dict[TextBox, _Layout] = {}
        self._tk_fonts: dict[
            tuple[str | None, int, bool, bool], tkfont.Font
        ] = {}

        # The chapter-wide layer; updated via set_render_config.
        self._config = RenderConfig()
        self._selected_mark_id: int | None = None

        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<Double-1>", self._on_double_click)
        self._canvas.bind("<Button-3>", self._on_right_click)

    def set_store(self, store: MarksStore | None) -> None:
        self._cancel_editor()
        self._store = store
        # Safe to drop the fonts here: the boxes are about to be deleted
        # anyway, so nothing is left pointing at a collected Tcl font.
        self._layouts.clear()
        self._tk_fonts.clear()
        self._render_overlay()

    def set_render_config(self, config: RenderConfig) -> None:
        if config == self._config:
            return
        self._config = config
        self._render_overlay()

    def refresh(self) -> None:
        """Redraw the boxes after the store changed under our feet.

        The view edits the :class:`TranslationEntry` objects directly, so
        nothing here can notice on its own that a text, a font, a size or
        a colour moved.
        """
        self._render_overlay()

    def ensure_mark_visible(self, mark_id: int) -> None:
        """Pan so a section is on screen — what the rail's nav promises."""
        if self._store is None or not 0 <= mark_id < len(self._store):
            return
        mark = self._store.marks[mark_id]
        self.ensure_visible(mark.x, mark.y, mark.w, mark.h)

    def select(self, mark_id: int | None) -> None:
        if self._store is None:
            return
        if mark_id is not None and not 0 <= mark_id < len(self._store):
            mark_id = None
        self._selected_mark_id = mark_id
        self._render_overlay()

    def selected_mark_id(self) -> int | None:
        return self._selected_mark_id

    # ----------------------------------------------------- rendering

    def _render_overlay(self) -> None:
        for ids in self._box_canvas_ids.values():
            for cid in ids:
                self._canvas.delete(cid)
        self._box_canvas_ids = {}
        if self._store is None or self._image is None:
            return
        for mark_id, mark in enumerate(self._store):
            entry = self._store.get_translation(mark_id)
            if entry is None or not entry.text.strip():
                continue
            box = resolve_box(mark, entry, self._config)
            layout = self._layout_for(box)
            # The layout is measured in image pixels; the preview is
            # drawn in canvas pixels, so every size and offset is scaled
            # by the current zoom before it reaches the canvas.
            scale = self._effective_scale()
            tk_font = self._tk_font(
                max(6, int(round(layout.font_size * scale))), box.font_family,
                bold=box.bold, italic=box.italic,
            )
            x1, y1 = self.image_to_canvas(mark.x, mark.y)
            x2, y2 = self.image_to_canvas(mark.x + mark.w, mark.y + mark.h)
            line_h = layout.line_h * scale
            total_h = line_h * len(layout.lines)
            cx1 = x1 + 2
            cy1 = y1 + max(0.0, ((y2 - y1) - total_h) / 2)
            text_color = _rgb_to_hex(box.color)
            ids: list[int] = []
            for line, line_w, line_x_offset in layout.lines:
                tx = cx1 + ((x2 - x1) - 4 - line_w * scale) / 2
                cid = self._canvas.create_text(
                    tx + line_x_offset * scale, cy1,
                    text=line, fill=text_color,
                    font=tk_font, anchor=tk.NW,
                )
                ids.append(cid)
                cy1 += line_h
            # A translated section reads as an ink-framed bubble; the
            # selected one takes the accent, as in the mockups.
            is_selected = mark_id == self._selected_mark_id
            border = self._canvas.create_rectangle(
                x1, y1, x2, y2,
                outline=COLOR_ACCENT if is_selected else COLOR_TEXT,
                width=(3 if is_selected else 1),
            )
            ids.append(border)
            self._box_canvas_ids[mark_id] = ids

    def _layout_for(self, box: TextBox) -> _Layout:
        """The wrapped lines for a box, measured once per variation.

        Keyed on the whole box, so the style is part of the key: a bold
        is wider than its regular and the lines have to be re-measured.
        """
        layout = self._layouts.get(box)
        if layout is None:
            fit = fit_text(box)
            layout = _Layout(fit, _load_font(
                fit.font_size, family=box.font_family,
                bold=box.bold, italic=box.italic,
            ))
            if len(self._layouts) >= _LAYOUT_CACHE_LIMIT:
                self._layouts.clear()
            self._layouts[box] = layout
        return layout

    def _tk_font(
        self, size: int, family: str | None, *, bold: bool = False,
        italic: bool = False,
    ) -> tkfont.Font:
        """A Tk font per (family, style, píxel size).

        One per zoom step in practice. Never evicted mid-draw: a
        ``tkfont.Font`` that gets collected takes its Tcl named font with
        it, and the canvas items still pointing at it would go with it.
        The page change clears it.
        """
        key = (family, size, bold, italic)
        font = self._tk_fonts.get(key)
        if font is None:
            font = _tk_font_for(size, family=family, bold=bold, italic=italic)
            self._tk_fonts[key] = font
        return font

    # -------------------------------------------------------- selection

    def _hit_test(self, cx: int, cy: int) -> int | None:
        if self._store is None or self._image is None:
            return None
        ix, iy = self.canvas_to_image(cx, cy)
        for mark_id, mark in enumerate(self._store):
            if mark.x <= ix <= mark.x + mark.w and mark.y <= iy <= mark.y + mark.h:
                return mark_id
        return None

    def _on_click(self, event: tk.Event) -> None:
        self._cancel_editor()
        hit = self._hit_test(event.x, event.y)
        self._selected_mark_id = hit
        self._render_overlay()
        if hit is not None and self._on_select is not None:
            try:
                self._on_select(hit)
            except Exception as exc:
                log.exception("Error en on_select: %s", exc)

    def _on_double_click(self, event: tk.Event) -> None:
        hit = self._hit_test(event.x, event.y)
        if hit is None or self._store is None:
            return
        self._open_editor(hit)

    def _on_right_click(self, event: tk.Event) -> None:
        hit = self._hit_test(event.x, event.y)
        if hit is None or self._store is None:
            return
        self._selected_mark_id = hit
        self._render_overlay()
        self._open_editor(hit)

    # --------------------------------------------------------- editor

    def _open_editor(self, mark_id: int) -> None:
        if self._store is None or not 0 <= mark_id < len(self._store):
            return
        self._cancel_editor()
        mark = self._store.marks[mark_id]
        entry = self._store.get_translation(mark_id)
        initial = entry.text if entry else ""
        x1, y1 = self.image_to_canvas(mark.x, mark.y)
        x2, y2 = self.image_to_canvas(mark.x + mark.w, mark.y + mark.h)
        cw = max(int(x2 - x1), 60)
        ch = max(int(y2 - y1), 24)
        editor = tk.Text(
            self._canvas, width=1, height=1, wrap=tk.WORD,
            bg="#ffffff", fg="#000000",
            font=("Segoe UI", 10),
            bd=1, relief=tk.SOLID,
            insertbackground="#000000",
            padx=2, pady=2,
        )
        editor.place(x=x1, y=y1, width=cw, height=ch)
        editor.insert("1.0", initial)
        editor.mark_set(tk.INSERT, "end")
        editor.focus_set()
        editor._mark_id = mark_id  # type: ignore[attr-defined]
        editor.bind("<Escape>", lambda _e: self._cancel_editor())
        editor.bind("<Control-Return>", lambda _e: self._commit_editor())
        editor.bind("<FocusOut>", lambda _e: self._commit_editor())
        self._editor = editor
        self._editor_mark_id = mark_id

    def _commit_editor(self) -> None:
        if self._editor is None or self._editor_mark_id is None or self._store is None:
            return
        text = self._editor.get("1.0", "end-1c")
        mark_id = self._editor_mark_id
        self._cancel_editor()
        if self._on_text_edited is not None:
            try:
                self._on_text_edited(mark_id, text)
            except Exception as exc:
                log.exception("Error en on_text_edited: %s", exc)

    def _cancel_editor(self) -> None:
        if self._editor is not None:
            try:
                self._editor.destroy()
            except Exception:
                pass
        self._editor = None
        self._editor_mark_id = None
