"""Canvas for displaying a single image with rectangle marks (step 2).

Subclasses :class:`ZoomedCanvas` so the user can zoom and pan. This
class owns the mark list (loaded from a :class:`MarksStore`) and the
editing logic: drawing new marks, selecting one by clicking it, moving
it, and resizing it from the eight handles drawn around the selection.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from typing import Callable

from src.config import (
    COLOR_BG,
    MARK_DEFAULT_COLOR,
    MARK_MIN_SIZE,
    MARK_SELECTED_FILL,
    MARK_SELECTED_STROKE_WIDTH,
    MARK_STROKE_WIDTH,
    SUCCESS_COLOR,
)
from src.utils.logger import get_logger
from src.utils.marks_store import Mark, MarksStore
from src.views.zoomed_canvas import (
    HANDLE_SIZE,
    HANDLES,
    ZoomedCanvas,
    handle_centers,
    move_rect,
    resize_rect,
)

log = get_logger("marks_canvas")

ChangeCallback = Callable[[], None]
SelectCallback = Callable[[int], None]
HoverCallback = Callable[[int, str], None]
LeaveCallback = Callable[[], None]
GeometryCallback = Callable[[int, Mark], None]

#: Dash pattern of the box showing the area that will be erased.
MARK_PAD_DASH = (4, 3)


class MarksCanvas(ZoomedCanvas):
    """A zoomable canvas that lets the user draw rectangle marks on an image."""

    def __init__(
        self,
        master: tk.Misc,
        store: MarksStore,
        on_change: ChangeCallback | None = None,
        on_select: SelectCallback | None = None,
        on_hover: HoverCallback | None = None,
        on_hover_leave: LeaveCallback | None = None,
        on_geometry: GeometryCallback | None = None,
    ) -> None:
        super().__init__(master, on_change=on_change)
        self._store: MarksStore = store
        self._on_select = on_select
        self._on_hover = on_hover
        self._on_hover_leave = on_hover_leave
        self._on_geometry = on_geometry

        self._mark_ids: list[int] = []
        #: The dashed «this is what gets erased» box, on the selection only.
        self._pad_id: int | None = None
        self._handle_ids: dict[str, int] = {}
        self._preview_id: int | None = None
        self._selected_mark_id: int | None = None
        self._hovered_mark_id: int | None = None
        self._edit_mode: bool = False
        self._marks_visible: bool = True
        self._current_color: str = MARK_DEFAULT_COLOR
        self._drag_start: tuple[int, int] | None = None
        self._transform: dict | None = None

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Motion>", self._on_motion)

    @property
    def store(self) -> MarksStore:
        return self._store

    def set_store(self, store: MarksStore) -> None:
        self._store = store
        self._selected_mark_id = None
        self._hovered_mark_id = None
        self._render_overlay()
        self._notify_change()

    def load_marks(self) -> None:
        self._store.load()
        self._selected_mark_id = None
        self._render_overlay()
        self._notify_change()

    def set_edit_mode(self, on: bool) -> None:
        self._edit_mode = on
        self._update_cursor()
        log.debug("Modo edicion -> %s", on)

    def is_edit_mode(self) -> bool:
        return self._edit_mode

    def set_marks_visible(self, on: bool) -> None:
        self._marks_visible = on
        self._render_overlay()

    def is_marks_visible(self) -> bool:
        return self._marks_visible

    def set_color(self, color: str) -> None:
        self._current_color = color

    def undo(self) -> Mark | None:
        if len(self._store) == 0:
            return None
        removed = self._store.remove_last()
        if removed is not None:
            if self._selected_mark_id is not None and self._selected_mark_id >= len(self._store):
                self._selected_mark_id = None
            self._hovered_mark_id = None
            self._render_overlay()
            self._notify_change()
        return removed

    def clear(self) -> None:
        self._store.clear()
        self._selected_mark_id = None
        self._hovered_mark_id = None
        self._render_overlay()
        self._notify_change()

    def mark_count(self) -> int:
        return len(self._store)

    def select(self, mark_id: int | None) -> None:
        if mark_id is not None and not 0 <= mark_id < len(self._store):
            mark_id = None
        self._selected_mark_id = mark_id
        self._render_overlay()

    def selected_mark_id(self) -> int | None:
        return self._selected_mark_id

    def refresh_mark(self, mark_id: int) -> None:
        if 0 <= mark_id < len(self._store):
            self._render_overlay()

    # ------------------------------------------------------- overlay

    def _render_overlay(self) -> None:
        for mid in self._mark_ids:
            self._canvas.delete(mid)
        self._mark_ids = []
        self._clear_pad()
        self._clear_handles()
        if not self._marks_visible or self._image is None:
            return
        for mark_id, mark in enumerate(self._store):
            x1, y1 = self.image_to_canvas(mark.x, mark.y)
            x2, y2 = self.image_to_canvas(mark.x + mark.w, mark.y + mark.h)
            is_selected = mark_id == self._selected_mark_id
            outline = SUCCESS_COLOR if is_selected else mark.color
            width = MARK_SELECTED_STROKE_WIDTH if is_selected else MARK_STROKE_WIDTH
            fill = MARK_SELECTED_FILL if is_selected else ""
            if is_selected:
                # Only the selection draws it: a page with sixteen globos
                # would be a wall of halos, and the margin is only being
                # read when it is the one being edited. Drawn before the
                # solid box so a tight margin does not cover it.
                self._pad_id = self._canvas.create_rectangle(
                    *self._pad_coords(mark),
                    outline=outline, width=1, fill="", dash=MARK_PAD_DASH,
                    tags=("pad", f"pad_{mark_id}"),
                )
            rid = self._canvas.create_rectangle(
                x1, y1, x2, y2,
                outline=outline, width=width, fill=fill,
                tags=("mark", f"mark_{mark_id}"),
            )
            self._mark_ids.append(rid)
        self._draw_handles()

    def _clear_pad(self) -> None:
        if self._pad_id is not None:
            self._canvas.delete(self._pad_id)
            self._pad_id = None

    def _pad_coords(self, mark: Mark) -> tuple[float, float, float, float]:
        """Canvas coordinates of the area LaMa will actually erase."""
        p = mark.erase_padding
        x1, y1 = self.image_to_canvas(mark.x - p, mark.y - p)
        x2, y2 = self.image_to_canvas(
            mark.x + mark.w + p, mark.y + mark.h + p,
        )
        return x1, y1, x2, y2

    # -------------------------------------------------------- handles

    def _clear_handles(self) -> None:
        for hid in self._handle_ids.values():
            self._canvas.delete(hid)
        self._handle_ids = {}

    def _selected_mark(self) -> Mark | None:
        mid = self._selected_mark_id
        if mid is None or not 0 <= mid < len(self._store):
            return None
        return self._store.marks[mid]

    def _handle_centers(self, mark: Mark) -> dict[str, tuple[float, float]]:
        x1, y1 = self.image_to_canvas(mark.x, mark.y)
        x2, y2 = self.image_to_canvas(mark.x + mark.w, mark.y + mark.h)
        return handle_centers(x1, y1, x2, y2)

    def _draw_handles(self) -> None:
        """Eight grips on the selection — the affordance for resizing."""
        mark = self._selected_mark()
        if mark is None or not self._marks_visible:
            return
        half = HANDLE_SIZE / 2
        for anchor, (cx, cy) in self._handle_centers(mark).items():
            self._handle_ids[anchor] = self._canvas.create_rectangle(
                cx - half, cy - half, cx + half, cy + half,
                outline=SUCCESS_COLOR, fill=COLOR_BG, width=2,
                tags=("handle", f"handle_{anchor}"),
            )

    def _hit_test_handle(self, cx: float, cy: float) -> str | None:
        mark = self._selected_mark()
        if mark is None or not self._marks_visible:
            return None
        # A little larger than the drawn grip, so it is not fiddly.
        reach = HANDLE_SIZE
        for anchor, (hx, hy) in self._handle_centers(mark).items():
            if abs(cx - hx) <= reach and abs(cy - hy) <= reach:
                return anchor
        return None

    def _inside_selection(self, cx: float, cy: float) -> bool:
        mark = self._selected_mark()
        if mark is None or not self._marks_visible:
            return False
        x1, y1 = self.image_to_canvas(mark.x, mark.y)
        x2, y2 = self.image_to_canvas(mark.x + mark.w, mark.y + mark.h)
        return x1 <= cx <= x2 and y1 <= cy <= y2

    # ------------------------------------------------------- editing

    def _update_cursor(self) -> None:
        self._canvas.configure(cursor="crosshair" if self._edit_mode else "")

    def _cursor_for(self, cx: int, cy: int) -> None:
        """Say what a drag would do before the user commits to it."""
        if self._transform is not None:
            return
        anchor = self._hit_test_handle(cx, cy)
        if anchor is not None:
            cursor = dict(HANDLES).get(anchor, "fleur")
        elif self._inside_selection(cx, cy):
            cursor = "fleur"
        elif self._edit_mode:
            cursor = "crosshair"
        elif self._hit_test_mark(cx, cy) is not None:
            cursor = "hand2"
        else:
            cursor = ""
        if self._canvas.cget("cursor") != cursor:
            self._canvas.configure(cursor=cursor)

    def _on_press(self, event: tk.Event) -> None:
        if self._image is None:
            return
        # Acting on the current selection always wins over drawing a new
        # mark on top of it: the grips are only visible there, so a
        # click on one can mean nothing else.
        anchor = self._hit_test_handle(event.x, event.y)
        if anchor is not None:
            self._begin_transform("resize", anchor, event)
            return
        if self._inside_selection(event.x, event.y):
            self._begin_transform("move", None, event)
            return
        if self._edit_mode:
            self._drag_start = (event.x, event.y)
            if self._preview_id is not None:
                self._canvas.delete(self._preview_id)
            self._preview_id = self._canvas.create_rectangle(
                event.x, event.y, event.x, event.y,
                outline=self._current_color,
                width=MARK_STROKE_WIDTH, dash=(4, 2),
            )
            return
        # Outside edit mode a click picks whatever box is under it, so
        # the inspector can be reached from the page as well as the rail.
        hit = self._hit_test_mark(event.x, event.y)
        if hit is not None and hit != self._selected_mark_id:
            self.select(hit)
            self._emit_select(hit)

    # ------------------------------------------------- move / resize

    def _begin_transform(
        self, mode: str, anchor: str | None, event: tk.Event,
    ) -> None:
        mark = self._selected_mark()
        if mark is None:
            return
        self._transform = {
            "mode": mode,
            "anchor": anchor,
            "origin": self.canvas_to_image(event.x, event.y),
            "mark": mark,
        }

    def _apply_transform_drag(self, event: tk.Event) -> Mark | None:
        if self._transform is None or self._image is None:
            return None
        ox, oy = self._transform["origin"]
        ix, iy = self.canvas_to_image(event.x, event.y)
        dx, dy = ix - ox, iy - oy
        mark: Mark = self._transform["mark"]
        iw, ih = self._image.size
        if self._transform["mode"] == "move":
            return self._moved(mark, dx, dy, iw, ih)
        return self._resized(mark, self._transform["anchor"], dx, dy, iw, ih)

    @staticmethod
    def _moved(mark: Mark, dx: int, dy: int, iw: int, ih: int) -> Mark:
        x, y, _w, _h = move_rect(
            (mark.x, mark.y, mark.w, mark.h), dx, dy, (iw, ih),
        )
        # ``replace`` rather than a fresh Mark: rebuilding field by field
        # is how a mark silently loses whatever it carries besides its
        # geometry — today its margin.
        return replace(mark, x=x, y=y)

    @staticmethod
    def _resized(
        mark: Mark, anchor: str | None, dx: int, dy: int, iw: int, ih: int,
    ) -> Mark:
        x, y, w, h = resize_rect(
            (mark.x, mark.y, mark.w, mark.h), anchor, dx, dy, (iw, ih),
            MARK_MIN_SIZE,
        )
        return replace(mark, x=x, y=y, w=w, h=h)

    def _drag_transform(self, event: tk.Event) -> None:
        updated = self._apply_transform_drag(event)
        if updated is None:
            return
        mark_id = self._selected_mark_id
        if mark_id is None:
            return
        # Redraw from the pending geometry without touching the store —
        # nothing is written until the button comes up.
        x1, y1 = self.image_to_canvas(updated.x, updated.y)
        x2, y2 = self.image_to_canvas(updated.x + updated.w, updated.y + updated.h)
        if 0 <= mark_id < len(self._mark_ids):
            self._canvas.coords(self._mark_ids[mark_id], x1, y1, x2, y2)
        if self._pad_id is not None:
            self._canvas.coords(self._pad_id, *self._pad_coords(updated))
        self._move_handles(updated)
        if self._on_geometry is not None:
            try:
                self._on_geometry(mark_id, updated)
            except Exception as exc:
                log.exception("Error en on_geometry: %s", exc)

    def _move_handles(self, mark: Mark) -> None:
        half = HANDLE_SIZE / 2
        for anchor, (cx, cy) in self._handle_centers(mark).items():
            hid = self._handle_ids.get(anchor)
            if hid is not None:
                self._canvas.coords(
                    hid, cx - half, cy - half, cx + half, cy + half,
                )

    def _end_transform(self, event: tk.Event) -> None:
        updated = self._apply_transform_drag(event)
        mark_id = self._selected_mark_id
        self._transform = None
        if updated is None or mark_id is None:
            return
        if self._store.update_at(mark_id, updated):
            log.debug(
                "Marca %d -> x=%d y=%d %dx%d",
                mark_id, updated.x, updated.y, updated.w, updated.h,
            )
        self._render_overlay()
        self._notify_change()

    # --- public geometry editing (used by the rail inspector) --------

    def update_mark(self, mark_id: int, mark: Mark) -> bool:
        """Write a new geometry for ``mark_id``, clamped to the image."""
        if self._image is None:
            return False
        iw, ih = self._image.size
        w = max(MARK_MIN_SIZE, min(mark.w, iw))
        h = max(MARK_MIN_SIZE, min(mark.h, ih))
        x = max(0, min(mark.x, iw - w))
        y = max(0, min(mark.y, ih - h))
        changed = self._store.update_at(
            mark_id, replace(mark, x=x, y=y, w=w, h=h),
        )
        if changed:
            self._render_overlay()
            self._notify_change()
        return changed

    def delete_mark(self, mark_id: int) -> Mark | None:
        removed = self._store.remove_at(mark_id)
        if removed is None:
            return None
        # Ids are indexes, so everything after the hole shifted down.
        if self._selected_mark_id is not None:
            if self._selected_mark_id == mark_id:
                self._selected_mark_id = None
            elif self._selected_mark_id > mark_id:
                self._selected_mark_id -= 1
        self._hovered_mark_id = None
        self._render_overlay()
        self._notify_change()
        return removed

    def nudge(self, dx: int, dy: int, *, resize: bool = False) -> bool:
        """Arrow-key editing: move the selection, or grow it with Shift."""
        mark = self._selected_mark()
        if mark is None or self._image is None or self._selected_mark_id is None:
            return False
        iw, ih = self._image.size
        if resize:
            updated = self._resized(mark, "se", dx, dy, iw, ih)
        else:
            updated = self._moved(mark, dx, dy, iw, ih)
        return self.update_mark(self._selected_mark_id, updated)

    def reveal_selected(self) -> None:
        """Scroll the selected mark into view."""
        mark = self._selected_mark()
        if mark is not None:
            self.ensure_visible(mark.x, mark.y, mark.w, mark.h)

    def _emit_select(self, mark_id: int) -> None:
        if self._on_select is None:
            return
        try:
            self._on_select(mark_id)
        except Exception as exc:
            log.exception("Error en on_select: %s", exc)

    # ---------------------------------------------------------- drawing

    def _on_drag(self, event: tk.Event) -> None:
        if self._transform is not None:
            self._drag_transform(event)
            return
        if not self._edit_mode or self._drag_start is None or self._preview_id is None:
            return
        x1, y1 = self._drag_start
        self._canvas.coords(self._preview_id, x1, y1, event.x, event.y)

    def _on_release(self, event: tk.Event) -> None:
        if self._transform is not None:
            self._end_transform(event)
            return
        if not self._edit_mode or self._drag_start is None:
            return
        x1, y1 = self._drag_start
        x2, y2 = event.x, event.y
        self._drag_start = None
        if self._preview_id is not None:
            self._canvas.delete(self._preview_id)
            self._preview_id = None

        ix1, iy1 = self.canvas_to_image(x1, y1)
        ix2, iy2 = self.canvas_to_image(x2, y2)
        if ix2 - ix1 < MARK_MIN_SIZE or iy2 - iy1 < MARK_MIN_SIZE:
            return

        mark = Mark(
            x=min(ix1, ix2),
            y=min(iy1, iy2),
            w=abs(ix2 - ix1),
            h=abs(iy2 - iy1),
            color=self._current_color,
        )
        mark_id = self._store.add(mark)
        self._selected_mark_id = mark_id
        self._render_overlay()
        self._notify_change()
        if self._on_select is not None:
            try:
                self._on_select(mark_id)
            except Exception as exc:
                log.exception("Error en on_select: %s", exc)

    def _on_motion(self, event: tk.Event) -> None:
        self._cursor_for(event.x, event.y)
        if self._on_hover is None:
            return
        mark_id = self._hit_test_mark(event.x, event.y)
        if mark_id is None:
            if self._hovered_mark_id is not None:
                self._hovered_mark_id = None
                try:
                    self._on_hover_leave()
                except Exception:
                    pass
            return
        if mark_id == self._hovered_mark_id:
            return
        self._hovered_mark_id = mark_id
        entry = self._store.get_ocr(mark_id)
        text = entry.text if entry else ""
        try:
            self._on_hover(mark_id, text)
        except Exception as exc:
            log.exception("Error en on_hover: %s", exc)

    def _hit_test_mark(self, cx: int, cy: int) -> int | None:
        if self._image is None:
            return None
        ix, iy = self.canvas_to_image(cx, cy)
        for mark_id, mark in enumerate(self._store):
            if mark.x <= ix <= mark.x + mark.w and mark.y <= iy <= mark.y + mark.h:
                return mark_id
        return None
