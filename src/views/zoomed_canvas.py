"""Base class for canvases that display an image with zoom + pan support.

Used by :class:`MarksCanvas` (step 2: marks editing) and
:class:`TranslatorCanvas` (step 4: translation rendering). Provides:

* Pan with the wheel, with Shift+drag, or with the middle button.
* Zoom with Ctrl+wheel around the cursor position.
* ``fit_to_window()`` / ``fit_width()`` / ``fit_height()``.
* ``set_zoom(z)`` for programmatic zoom updates.

Subclasses override :meth:`_render_image` and :meth:`_render_overlay` to
draw their domain-specific content. The base class manages the
transform (offset, scale) and a single ``ImageTk.PhotoImage``.

Only the slice of the image the canvas can actually show is ever
rasterised, so the zoom ceiling costs canvas-sized bitmaps rather than
page-sized-times-zoom ones.
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Callable

from PIL import Image, ImageTk

from src.config import CANVAS_BG
from src.utils.logger import get_logger

log = get_logger("zoomed_canvas")

# Zoom limits are expressed against the image's own pixels, not against
# the fit-to-window factor. A manga page fits at roughly 0.3, so a bare
# ``MAX_ZOOM = 4`` used to cap the view at ~1.2x actual size — nowhere
# near enough to inspect a furigana-sized glyph.
MIN_EFFECTIVE_SCALE = 0.05
MAX_EFFECTIVE_SCALE = 8.0
ZOOM_STEP = 1.15
WHEEL_PAN_STEP = 90
#: Below this fit-to-window scale a page is a sliver nobody can read —
#: webtoon strips run 760x15000 — so the first view fits the width and
#: starts at the top instead.
TALL_PAGE_FIT_LIMIT = 0.25
#: Milliseconds of quiet before a fast (blocky) redraw is resharpened.
SHARPEN_DELAY_MS = 140


def resample_for(eff: float, fast: bool = False) -> int:
    """Cheap filters while the view is moving, good ones once it stops.

    Module level because the vertical strip in step 2 rasterises the
    same way without being a :class:`ZoomedCanvas`.
    """
    if fast:
        return Image.BILINEAR if eff < 1.0 else Image.NEAREST
    if eff < 1.0:
        return Image.LANCZOS
    if eff < 4.0:
        return Image.BILINEAR
    # Past 4x the honest thing to show is the pixels themselves.
    return Image.NEAREST


class ZoomedCanvas(tk.Frame):
    """A canvas with pan + zoom around an image."""

    def __init__(
        self,
        master: tk.Misc,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, bg=CANVAS_BG)
        self._on_change = on_change

        self._image: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._photo_id: int | None = None

        # Transform state. ``_base_scale`` is the scale that fits the
        # image into the canvas; ``_zoom`` is the user-controlled factor
        # multiplied on top. Effective scale is ``_base_scale * _zoom``.
        self._base_scale: float = 1.0
        self._zoom: float = 1.0
        self._notified_scale: float = -1.0
        self._offset_x: float = 0.0
        self._offset_y: float = 0.0
        self._img_w: int = 0
        self._img_h: int = 0
        self._canvas_scale_x: float = 1.0
        self._canvas_scale_y: float = 1.0

        self._needs_initial_fit: bool = False
        self._pan_active: bool = False
        self._pan_last: tuple[int, int] | None = None
        self._resize_after_id: str | None = None
        self._sharpen_after_id: str | None = None

        self._canvas = tk.Canvas(
            self, bg=CANVAS_BG, highlightthickness=0, bd=0,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas.bind("<Configure>", self._on_resize)
        # Three ways to move around, because the left button is busy
        # drawing marks: Shift+drag, the middle button, and the wheel.
        self._canvas.bind("<Shift-ButtonPress-1>", self._on_pan_press)
        self._canvas.bind("<Shift-B1-Motion>", self._on_pan_drag)
        self._canvas.bind("<Shift-ButtonRelease-1>", self._on_pan_release)
        self._canvas.bind("<ButtonPress-2>", self._on_pan_press)
        self._canvas.bind("<B2-Motion>", self._on_pan_drag)
        self._canvas.bind("<ButtonRelease-2>", self._on_pan_release)
        self._canvas.bind("<MouseWheel>", self._on_wheel)
        self._canvas.bind("<Shift-MouseWheel>", self._on_shift_wheel)
        # Ctrl+wheel for zoom on Windows / macOS.
        self._canvas.bind("<Control-MouseWheel>", self._on_ctrl_wheel)
        # Linux mouse wheel is <Button-4> / <Button-5> + state.
        self._canvas.bind("<Control-Button-4>", self._on_ctrl_wheel_linux)
        self._canvas.bind("<Control-Button-5>", self._on_ctrl_wheel_linux)
        self._canvas.bind("<Button-4>", self._on_wheel_linux)
        self._canvas.bind("<Button-5>", self._on_wheel_linux)

    # -------------------------------------------------------------- public

    def set_image(self, image: Image.Image | None) -> None:
        self._image = image
        if image is not None:
            self._img_w, self._img_h = image.size
        else:
            self._img_w = self._img_h = 0
        self._zoom = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        # The canvas may not be laid out yet, so the choice of opening
        # fit is deferred to the first transform that has real numbers.
        self._needs_initial_fit = True
        self._render_image()

    def viewport(self) -> tuple[float, float, float] | None:
        """The view as ``(escala efectiva, x, y)`` in image coordinates.

        ``x``/``y`` is the pixel of the source image sitting at the
        canvas' top-left corner. Saying it that way — instead of in raw
        offsets — is what lets the view survive a swap to another bitmap
        of the same page, which is how «Limpia / Original» is drawn.
        """
        if self._image is None:
            return None
        eff = self._effective_scale()
        if eff <= 0:
            return None
        return eff, -self._offset_x / eff, -self._offset_y / eff

    def set_viewport(self, state: tuple[float, float, float] | None) -> None:
        """Put the view back where :meth:`viewport` found it."""
        if self._image is None or state is None:
            return
        eff, ix, iy = state
        iw, ih = self._image.size
        if iw <= 0 or ih <= 0 or eff <= 0:
            return
        cw = max(self._canvas.winfo_width(), 1)
        ch = max(self._canvas.winfo_height(), 1)
        self._needs_initial_fit = False
        self._base_scale = self._fit_scale(cw, ch, iw, ih)
        self._zoom = self._clamp_zoom(eff / (self._base_scale or 1.0))
        new_eff = self._base_scale * self._zoom
        self._offset_x = -ix * new_eff
        self._offset_y = -iy * new_eff
        self._apply_transform()
        self._notify_change()

    def zoom(self) -> float:
        return self._zoom

    def zoom_percent(self) -> int:
        """Scale against the image's real pixels — what the user reads."""
        return max(1, int(round(self._effective_scale() * 100)))

    def can_zoom_in(self) -> bool:
        return self._zoom < self._zoom_bounds()[1] - 1e-4

    def can_zoom_out(self) -> bool:
        return self._zoom > self._zoom_bounds()[0] + 1e-4

    def set_zoom(self, z: float) -> None:
        z = self._clamp_zoom(z)
        if abs(z - self._zoom) < 1e-4:
            return
        self._zoom = z
        self._apply_transform()
        self._notify_change()

    def zoom_in(self) -> None:
        self._zoom_at_center(ZOOM_STEP)

    def zoom_out(self) -> None:
        self._zoom_at_center(1.0 / ZOOM_STEP)

    def reset_zoom(self) -> None:
        self.fit_to_window()

    def fit_to_window(self) -> None:
        self._needs_initial_fit = False
        self._zoom = 1.0
        self._offset_x = self._offset_y = 0.0
        self._apply_transform()
        self._notify_change()

    def fit_width(self) -> None:
        """Fill the canvas width and park at the top of the page."""
        self._fit(width=True)

    def fit_height(self) -> None:
        """Fill the canvas height and park at the left edge."""
        self._fit(width=False)

    def _fit(self, *, width: bool) -> None:
        if self._image is None:
            return
        self._needs_initial_fit = False
        cw = max(self._canvas.winfo_width(), 1)
        ch = max(self._canvas.winfo_height(), 1)
        iw, ih = self._image.size
        if iw <= 0 or ih <= 0:
            return
        base = self._fit_scale(cw, ch, iw, ih)
        target = (cw / iw) if width else (ch / ih)
        self._zoom = self._clamp_zoom(target / base)
        # Anchor the axis the fit does not constrain, so the user lands
        # at the start of the page rather than in its middle.
        if width:
            self._offset_y = 0.0
        else:
            self._offset_x = 0.0
        self._apply_transform()
        self._notify_change()

    def ensure_visible(
        self, x: int, y: int, w: int, h: int, *, margin: int = 40,
    ) -> None:
        """Pan the least amount that brings an image rectangle into view.

        Centres the rectangle when it is too big for the canvas, so
        picking a tall section from the rail always lands on something.
        """
        if self._image is None:
            return
        cw = max(self._canvas.winfo_width(), 1)
        ch = max(self._canvas.winfo_height(), 1)
        eff = self._effective_scale()
        left, top = x * eff, y * eff
        right, bottom = (x + w) * eff, (y + h) * eff

        self._offset_x = self._scroll_axis(
            self._offset_x, left, right, cw, margin,
        )
        self._offset_y = self._scroll_axis(
            self._offset_y, top, bottom, ch, margin,
        )
        self._apply_transform()

    @staticmethod
    def _scroll_axis(
        offset: float, low: float, high: float, extent: int, margin: int,
    ) -> float:
        span = high - low
        if span + 2 * margin > extent:
            # Too big to frame — centre it instead of pinning an edge.
            return (extent - span) / 2.0 - low
        if offset + low < margin:
            return margin - low
        if offset + high > extent - margin:
            return extent - margin - high
        return offset

    def can_pan_x(self) -> bool:
        return self._img_w * self._effective_scale() > self._canvas.winfo_width() + 1

    def can_pan_y(self) -> bool:
        return self._img_h * self._effective_scale() > self._canvas.winfo_height() + 1

    # ----------------------------------------------------------- internal

    def _notify_change(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception as exc:
                log.exception("Error en on_change: %s", exc)

    def _effective_scale(self) -> float:
        return self._base_scale * self._zoom

    @staticmethod
    def _fit_scale(cw: int, ch: int, iw: int, ih: int) -> float:
        """The scale at which the whole image fits, never magnifying."""
        return min(cw / iw, ch / ih, 1.0) or 1.0

    def _zoom_bounds(self) -> tuple[float, float]:
        """Zoom factors that keep the effective scale inside its limits."""
        base = self._base_scale if self._base_scale > 0 else 1.0
        low = MIN_EFFECTIVE_SCALE / base
        high = MAX_EFFECTIVE_SCALE / base
        # Fit-to-window stays reachable whatever the image measures.
        return min(low, 1.0), max(high, 1.0)

    def _clamp_zoom(self, z: float) -> float:
        low, high = self._zoom_bounds()
        return max(low, min(high, float(z)))

    def _on_resize(self, _event: object) -> None:
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except Exception:
                pass
        self._resize_after_id = self.after(50, self._apply_transform)

    def _apply_transform(self, *, fast: bool = False) -> None:
        """Recompute the photo and offsets, then redraw overlays."""
        if self._image is None:
            return
        cw = max(self._canvas.winfo_width(), 1)
        ch = max(self._canvas.winfo_height(), 1)
        iw, ih = self._image.size
        if iw <= 0 or ih <= 0:
            return

        self._img_w, self._img_h = iw, ih
        self._base_scale = self._fit_scale(cw, ch, iw, ih)
        if self._needs_initial_fit and cw > 1 and ch > 1:
            self._needs_initial_fit = False
            if self._base_scale < TALL_PAGE_FIT_LIMIT:
                self._zoom = self._clamp_zoom((cw / iw) / self._base_scale)
                self._offset_y = 0.0
        self._zoom = self._clamp_zoom(self._zoom)
        eff = self._base_scale * self._zoom
        full_w, full_h = iw * eff, ih * eff

        # Centre the image while it fits; clamp it to the edges once it
        # is bigger than the canvas, so panning can never lose the page.
        if full_w <= cw:
            self._offset_x = (cw - full_w) / 2.0
        else:
            self._offset_x = max(cw - full_w, min(0.0, self._offset_x))
        if full_h <= ch:
            self._offset_y = (ch - full_h) / 2.0
        else:
            self._offset_y = max(ch - full_h, min(0.0, self._offset_y))

        self._canvas_scale_x = self._canvas_scale_y = eff
        self._draw_viewport(cw, ch, iw, ih, eff, fast=fast)
        self._canvas.configure(scrollregion=(0, 0, cw, ch))
        self._render_overlay()

        # The fit scale moves whenever the image or the canvas changes
        # size, so the reported percentage would go stale after a load or
        # a window resize even though nobody touched the zoom.
        if abs(eff - self._notified_scale) > 1e-4:
            self._notified_scale = eff
            self._notify_change()

    def _draw_viewport(
        self, cw: int, ch: int, iw: int, ih: int, eff: float, *, fast: bool,
    ) -> None:
        """Rasterise only the slice of the image the canvas can show.

        Scaling the whole page and letting Tk clip it costs
        ``(iw*eff) * (ih*eff)`` pixels — at 8x a normal page is a quarter
        of a billion of them. Cropping first keeps the bitmap the size of
        the canvas however far in the user goes.
        """
        vis_x0 = max(0.0, -self._offset_x)
        vis_y0 = max(0.0, -self._offset_y)
        vis_x1 = min(iw * eff, vis_x0 + cw)
        vis_y1 = min(ih * eff, vis_y0 + ch)
        if vis_x1 <= vis_x0 or vis_y1 <= vis_y0:
            self._clear_photo()
            return

        sx0 = max(0, int(math.floor(vis_x0 / eff)))
        sy0 = max(0, int(math.floor(vis_y0 / eff)))
        sx1 = min(iw, int(math.ceil(vis_x1 / eff)))
        sy1 = min(ih, int(math.ceil(vis_y1 / eff)))
        if sx1 <= sx0 or sy1 <= sy0:
            self._clear_photo()
            return

        crop = self._image.crop((sx0, sy0, sx1, sy1))
        target = (
            max(1, int(round((sx1 - sx0) * eff))),
            max(1, int(round((sy1 - sy0) * eff))),
        )
        if target != crop.size:
            crop = crop.resize(target, self._resample(eff, fast))

        self._photo = ImageTk.PhotoImage(crop)
        if self._photo_id is None:
            self._photo_id = self._canvas.create_image(
                0, 0, image=self._photo, anchor=tk.NW, tags=("image",),
            )
        else:
            self._canvas.itemconfigure(self._photo_id, image=self._photo)
        self._canvas.coords(
            self._photo_id,
            self._offset_x + sx0 * eff,
            self._offset_y + sy0 * eff,
        )
        self._canvas.tag_lower(self._photo_id)

    _resample = staticmethod(resample_for)

    def _clear_photo(self) -> None:
        if self._photo_id is not None:
            self._canvas.delete(self._photo_id)
            self._photo_id = None
        self._photo = None

    def _schedule_sharpen(self) -> None:
        """Redraw with the good filter once the view settles."""
        if self._sharpen_after_id is not None:
            try:
                self.after_cancel(self._sharpen_after_id)
            except Exception:
                pass
        self._sharpen_after_id = self.after(SHARPEN_DELAY_MS, self._sharpen)

    def _sharpen(self) -> None:
        self._sharpen_after_id = None
        self._apply_transform()

    def _render_image(self) -> None:
        if self._photo_id is not None:
            self._canvas.delete(self._photo_id)
            self._photo_id = None
        self._canvas.delete("overlay")
        self._apply_transform()

    def _render_overlay(self) -> None:
        """Override in subclasses to draw marks/text on top of the image."""

    # --- coordinate mapping ------------------------------------------

    def image_to_canvas(self, x: int, y: int) -> tuple[float, float]:
        return (
            self._offset_x + x * self._canvas_scale_x,
            self._offset_y + y * self._canvas_scale_y,
        )

    def canvas_to_image(self, cx: float, cy: float) -> tuple[int, int]:
        if self._canvas_scale_x <= 0 or self._canvas_scale_y <= 0:
            return 0, 0
        ix = int((cx - self._offset_x) / self._canvas_scale_x)
        iy = int((cy - self._offset_y) / self._canvas_scale_y)
        if self._image is not None:
            iw, ih = self._image.size
            ix = max(0, min(ix, iw))
            iy = max(0, min(iy, ih))
        return ix, iy

    # --- pan ---------------------------------------------------------

    def _on_pan_press(self, event: tk.Event) -> None:
        self._pan_active = True
        self._pan_last = (event.x, event.y)
        self._canvas.configure(cursor="fleur")

    def _on_pan_drag(self, event: tk.Event) -> None:
        if not self._pan_active or self._pan_last is None:
            return
        dx = event.x - self._pan_last[0]
        dy = event.y - self._pan_last[1]
        self._pan_last = (event.x, event.y)
        self.pan_by(dx, dy)

    def _on_pan_release(self, _event: tk.Event) -> None:
        self._pan_active = False
        self._pan_last = None
        self._canvas.configure(cursor="")
        self._apply_transform()

    def pan_by(self, dx: float, dy: float) -> None:
        """Shift the view by canvas pixels. Clamped by ``_apply_transform``."""
        if self._image is None:
            return
        self._offset_x += dx
        self._offset_y += dy
        self._apply_transform(fast=True)
        self._schedule_sharpen()

    # --- wheel scrolling ---------------------------------------------

    def _on_wheel(self, event: tk.Event) -> str | None:
        if not self.can_pan_y():
            # Nothing to scroll here — let the strip or the rail have it.
            return None
        self.pan_by(0, WHEEL_PAN_STEP if event.delta > 0 else -WHEEL_PAN_STEP)
        return "break"

    def _on_shift_wheel(self, event: tk.Event) -> str | None:
        if not self.can_pan_x():
            return None
        self.pan_by(WHEEL_PAN_STEP if event.delta > 0 else -WHEEL_PAN_STEP, 0)
        return "break"

    def _on_wheel_linux(self, event: tk.Event) -> str | None:
        horizontal = bool(event.state & 0x0001)  # Shift
        if horizontal and not self.can_pan_x():
            return None
        if not horizontal and not self.can_pan_y():
            return None
        step = WHEEL_PAN_STEP if event.num == 4 else -WHEEL_PAN_STEP
        self.pan_by(step if horizontal else 0, 0 if horizontal else step)
        return "break"

    # --- zoom --------------------------------------------------------

    def _on_ctrl_wheel(self, event: tk.Event) -> str:
        # On Windows delta is +/- 120 per notch; macOS uses small floats.
        delta = event.delta
        if delta > 0:
            self._zoom_at(event.x, event.y, ZOOM_STEP)
        elif delta < 0:
            self._zoom_at(event.x, event.y, 1.0 / ZOOM_STEP)
        return "break"

    def _on_ctrl_wheel_linux(self, event: tk.Event) -> str:
        if event.num == 4:
            self._zoom_at(event.x, event.y, ZOOM_STEP)
        elif event.num == 5:
            self._zoom_at(event.x, event.y, 1.0 / ZOOM_STEP)
        return "break"

    def _zoom_at_center(self, factor: float) -> None:
        """Zoom around the middle of the canvas — what the ± buttons mean."""
        self._zoom_at(
            self._canvas.winfo_width() // 2,
            self._canvas.winfo_height() // 2,
            factor,
        )

    def _zoom_at(self, cx: int, cy: int, factor: float) -> None:
        if self._image is None:
            return
        new_zoom = self._clamp_zoom(self._zoom * factor)
        if abs(new_zoom - self._zoom) < 1e-4:
            return
        # Anchor the image point under (cx, cy) so it stays put under
        # the cursor while the scale changes.
        old_eff = self._effective_scale()
        ix = (cx - self._offset_x) / old_eff
        iy = (cy - self._offset_y) / old_eff
        self._zoom = new_zoom
        new_eff = self._effective_scale()
        self._offset_x = cx - ix * new_eff
        self._offset_y = cy - iy * new_eff
        self._apply_transform()
        self._notify_change()
