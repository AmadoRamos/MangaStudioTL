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

from dataclasses import replace

from src.config import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_TEXT,
    MARK_MIN_SIZE,
    NEUTRAL_500,
    SUCCESS_COLOR,
)
from src.utils.logger import get_logger
from src.utils.marks_store import MarksStore
from src.utils.text_renderer import (
    FitResult,
    RenderConfig,
    TextBox,
    _load_font,
    box_rect,
    fit_text,
    resolve_box,
)
from src.views.zoomed_canvas import (
    HANDLE_SIZE,
    HANDLES,
    Rect,
    ZoomedCanvas,
    handle_centers,
    move_rect,
    resize_rect,
)

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
        self._handle_ids: dict[str, int] = {}
        self._transform: dict | None = None
        self._editor: tk.Text | None = None
        self._editor_mark_id: int | None = None
        self._layouts: dict[TextBox, _Layout] = {}
        self._tk_fonts: dict[
            tuple[str | None, int, bool, bool], tkfont.Font
        ] = {}

        # The chapter-wide layer; updated via set_render_config.
        self._config = RenderConfig()
        self._selected_mark_id: int | None = None

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Motion>", self._on_motion)
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
        self._clear_handles()
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
            x1, y1 = self.image_to_canvas(box.x, box.y)
            x2, y2 = self.image_to_canvas(box.x + box.w, box.y + box.h)
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

        # Once the box has been dragged off its mark, the frame no longer
        # says where the globo was. Show it on the selection, dashed, so
        # there is something to place against.
        rect = self._selected_rect()
        if rect is not None and self._selected_mark_id is not None:
            mark = self._store.marks[self._selected_mark_id]
            if rect != (mark.x, mark.y, mark.w, mark.h):
                mx1, my1 = self.image_to_canvas(mark.x, mark.y)
                mx2, my2 = self.image_to_canvas(mark.x + mark.w, mark.y + mark.h)
                self._handle_ids["_mark"] = self._canvas.create_rectangle(
                    mx1, my1, mx2, my2,
                    outline=NEUTRAL_500, width=1, dash=(4, 3),
                )
        self._draw_handles()

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

    def _rect_of(self, mark_id: int) -> Rect | None:
        """The text box of a section, in image pixels."""
        if self._store is None or not 0 <= mark_id < len(self._store):
            return None
        return box_rect(
            self._store.marks[mark_id], self._store.get_translation(mark_id),
        )

    def _hit_test(self, cx: int, cy: int) -> int | None:
        """Which section's box is under the cursor.

        The box, not the mark: once the text has been dragged off the
        globo, clicking the text is what selects it.
        """
        if self._store is None or self._image is None:
            return None
        ix, iy = self.canvas_to_image(cx, cy)
        for mark_id in range(len(self._store)):
            rect = self._rect_of(mark_id)
            if rect is None:
                continue
            x, y, w, h = rect
            if x <= ix <= x + w and y <= iy <= y + h:
                return mark_id
        return None

    # ------------------------------------------------- move / resize

    def _selected_rect(self) -> Rect | None:
        if self._selected_mark_id is None:
            return None
        return self._rect_of(self._selected_mark_id)

    def _handle_centers(self, rect: Rect) -> dict[str, tuple[float, float]]:
        x, y, w, h = rect
        x1, y1 = self.image_to_canvas(x, y)
        x2, y2 = self.image_to_canvas(x + w, y + h)
        return handle_centers(x1, y1, x2, y2)

    def _clear_handles(self) -> None:
        for hid in self._handle_ids.values():
            self._canvas.delete(hid)
        self._handle_ids = {}

    def _draw_handles(self) -> None:
        """Eight grips on the selected box — the affordance for resizing."""
        rect = self._selected_rect()
        if rect is None:
            return
        half = HANDLE_SIZE / 2
        for anchor, (cx, cy) in self._handle_centers(rect).items():
            self._handle_ids[anchor] = self._canvas.create_rectangle(
                cx - half, cy - half, cx + half, cy + half,
                outline=SUCCESS_COLOR, fill=COLOR_BG, width=2,
            )

    def _move_handles(self, rect: Rect) -> None:
        half = HANDLE_SIZE / 2
        for anchor, (cx, cy) in self._handle_centers(rect).items():
            hid = self._handle_ids.get(anchor)
            if hid is not None:
                self._canvas.coords(
                    hid, cx - half, cy - half, cx + half, cy + half,
                )

    def _hit_test_handle(self, cx: float, cy: float) -> str | None:
        rect = self._selected_rect()
        if rect is None:
            return None
        # A little larger than the drawn grip, so it is not fiddly.
        for anchor, (hx, hy) in self._handle_centers(rect).items():
            if abs(cx - hx) <= HANDLE_SIZE and abs(cy - hy) <= HANDLE_SIZE:
                return anchor
        return None

    def _inside_selection(self, cx: float, cy: float) -> bool:
        rect = self._selected_rect()
        if rect is None:
            return False
        x, y, w, h = rect
        x1, y1 = self.image_to_canvas(x, y)
        x2, y2 = self.image_to_canvas(x + w, y + h)
        return x1 <= cx <= x2 and y1 <= cy <= y2

    def _on_motion(self, event: tk.Event) -> None:
        """Say what a drag would do before the user commits to it."""
        if self._transform is not None:
            return
        anchor = self._hit_test_handle(event.x, event.y)
        if anchor is not None:
            cursor = dict(HANDLES).get(anchor, "fleur")
        elif self._inside_selection(event.x, event.y):
            cursor = "fleur"
        elif self._hit_test(event.x, event.y) is not None:
            cursor = "hand2"
        else:
            cursor = ""
        if self._canvas.cget("cursor") != cursor:
            self._canvas.configure(cursor=cursor)

    def _on_press(self, event: tk.Event) -> None:
        self._cancel_editor()
        # Acting on the current selection wins over picking another box:
        # the grips are only drawn there, so a click on one can mean
        # nothing else.
        rect = self._selected_rect()
        if rect is not None:
            anchor = self._hit_test_handle(event.x, event.y)
            if anchor is not None:
                self._begin_transform(rect, "resize", anchor, event)
                return
            if self._inside_selection(event.x, event.y):
                self._begin_transform(rect, "move", None, event)
                return
        hit = self._hit_test(event.x, event.y)
        self._selected_mark_id = hit
        self._render_overlay()
        if hit is not None and self._on_select is not None:
            try:
                self._on_select(hit)
            except Exception as exc:
                log.exception("Error en on_select: %s", exc)

    def _begin_transform(
        self, rect: Rect, mode: str, anchor: str | None, event: tk.Event,
    ) -> None:
        self._transform = {
            "mode": mode,
            "anchor": anchor,
            "origin": self.canvas_to_image(event.x, event.y),
            "rect": rect,
        }

    def _dragged_rect(self, event: tk.Event) -> Rect | None:
        if self._transform is None or self._image is None:
            return None
        ox, oy = self._transform["origin"]
        ix, iy = self.canvas_to_image(event.x, event.y)
        dx, dy = ix - ox, iy - oy
        rect: Rect = self._transform["rect"]
        if self._transform["mode"] == "move":
            return move_rect(rect, dx, dy, self._image.size)
        return resize_rect(
            rect, self._transform["anchor"], dx, dy,
            self._image.size, MARK_MIN_SIZE,
        )

    def _on_drag(self, event: tk.Event) -> None:
        rect = self._dragged_rect(event)
        if rect is None or self._selected_mark_id is None:
            return
        # ponytail: only the frame follows the pointer; the text lands on
        # release. Re-laying it out per frame means a binary search over
        # font sizes per frame. Make the layout cache key on the box's
        # shape rather than its position if live text is ever wanted.
        ids = self._box_canvas_ids.get(self._selected_mark_id)
        if ids:
            x, y, w, h = rect
            x1, y1 = self.image_to_canvas(x, y)
            x2, y2 = self.image_to_canvas(x + w, y + h)
            self._canvas.coords(ids[-1], x1, y1, x2, y2)
        self._move_handles(rect)

    def _on_release(self, event: tk.Event) -> None:
        rect = self._dragged_rect(event)
        transform = self._transform
        mark_id = self._selected_mark_id
        self._transform = None
        if rect is None or transform is None or mark_id is None:
            return
        if rect == transform["rect"] or self._store is None:
            # A click that did not move anything.
            self._render_overlay()
            return
        entry = self._store.get_translation(mark_id)
        if entry is None:
            return
        mark = self._store.marks[mark_id]
        x, y, w, h = rect
        offset = (x - mark.x, y - mark.y, w - mark.w, h - mark.h)
        # Dragged exactly back onto the mark: that is «no offset», not an
        # offset of zero, so the rail's «restablecer» goes away with it.
        self._store.set_translation(
            mark_id,
            replace(
                entry,
                box_offset=None if offset == (0, 0, 0, 0) else offset,
                edited=True,
            ),
        )
        self._render_overlay()
        self._notify_change()

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
        entry = self._store.get_translation(mark_id)
        initial = entry.text if entry else ""
        # Over the box, not over the mark: the editor has to sit where
        # the text is going to end up.
        x, y, w, h = box_rect(self._store.marks[mark_id], entry)
        x1, y1 = self.image_to_canvas(x, y)
        x2, y2 = self.image_to_canvas(x + w, y + h)
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
