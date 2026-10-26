"""La cinta del paso 2: el capítulo entero en un solo desplazamiento.

Hermano de :class:`~src.views.marks_canvas.MarksCanvas`, que muestra una
página con zoom y paneo. Esta muestra todas, una debajo de otra, y por
eso no hereda de :class:`~src.views.zoomed_canvas.ZoomedCanvas`: el
transform de aquél es de *una* imagen, y aquí cada página tiene su sitio
en un eje común.

Lo que la hace distinta de dibujar el capítulo y ya está:

* **Solo se rasteriza la banda visible.** Un capítulo de webtoon son
  cientos de megapíxeles; escalarlo entero serían gigas de bitmap para
  las dos franjas de página que caben en pantalla.
* **Las marcas se recortan igual.** Dibujar las de todas las páginas en
  cada notch de rueda eran cientos de items de canvas por gesto, casi
  todos fuera de pantalla.
* **Colocar no es descodificar.** Para situar el desplazamiento hacen
  falta las medidas de todas las páginas, pero los píxeles solo de las
  que se ven: de ahí que ``size`` y ``source`` sean dos funciones
  distintas y no una.

Los píxeles no son suyos: se los da la vista por ``source``/``size``,
que es quien tiene la caché de limpias —la comparte con el modo «Una» y
la invalida cuando la tubería termina una página—.
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Callable

from PIL import Image, ImageTk

from src.config import (
    CANVAS_BG,
    COLOR_ACCENT,
    MARK_MIN_SIZE,
    MARK_SELECTED_FILL,
    MARK_SELECTED_STROKE_WIDTH,
    MARK_STROKE_WIDTH,
)
from src.utils.logger import get_logger
from src.utils.marks_store import Mark, MarksStore
from src.views.marks_canvas import MARK_PAD_DASH
from src.views.zoomed_canvas import (
    MAX_EFFECTIVE_SCALE,
    MIN_EFFECTIVE_SCALE,
    TALL_PAGE_FIT_LIMIT,
    ZOOM_STEP,
    resample_for,
)

log = get_logger("strip_canvas")

#: ``(page, mark_id)``.
MarkKey = tuple[int, int]
#: Dónde cae una página en coordenadas de cinta: ``(x, y, ancho, alto)``.
Placement = tuple[float, float, int, int]

SourceFn = Callable[[int], Image.Image]
SizeFn = Callable[[int], tuple[int, int]]
KeyCallback = Callable[[int, int], None]
PageCallback = Callable[[int], None]
HoverCallback = Callable[[MarkKey | None], None]
ChangeCallback = Callable[[], None]


class StripCanvas(tk.Frame):
    """Todas las páginas del capítulo en una tira vertical."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        items_count: int,
        stores: list[MarksStore],
        source: SourceFn,
        size: SizeFn,
        scale: float | None = None,
        color: str,
        on_select: KeyCallback | None = None,
        on_activate: PageCallback | None = None,
        on_mark_added: KeyCallback | None = None,
        on_hover: HoverCallback | None = None,
        on_scale_change: ChangeCallback | None = None,
    ) -> None:
        super().__init__(master, bg=CANVAS_BG)
        self._pages = items_count
        self._stores = stores
        self._source = source
        self._size = size
        self._on_select = on_select
        self._on_activate = on_activate
        self._on_mark_added = on_mark_added
        self._on_hover = on_hover
        self._on_scale_change = on_scale_change

        #: ``None`` es «encaja al primer dibujado que tenga medidas de
        #: verdad»: el lienzo todavía no sabe lo que mide.
        self._scale: float = scale if scale is not None else 1.0
        self._fit_pending: bool = scale is None
        self._notified_scale: float = -1.0
        self._layout: list[Placement] = []
        self._content: tuple[int, int] = (1, 1)
        self._photos: dict[int, ImageTk.PhotoImage] = {}
        self._photo_ids: dict[int, int] = {}
        self._draw_pending: bool = False
        self._mark_ids_by_page: list[list[int]] = [[] for _ in range(self._pages)]

        self._selected: MarkKey | None = None
        self._marks_visible: bool = True
        self._viewing_clean: bool = False
        self._edit_mode: bool = False
        self._current_color = color
        self._drag: dict | None = None

        self._canvas = tk.Canvas(
            self, bg=CANVAS_BG, highlightthickness=0, bd=0,
        )
        self._scrollbar = tk.Scrollbar(
            self, orient=tk.VERTICAL, command=self._canvas.yview,
        )
        # Every scroll — wheel, scrollbar, drag, programmatic — arrives
        # here, which is what tells the strip to re-rasterise its band.
        self._canvas.configure(
            yscrollcommand=self._on_yscroll,
            xscrollcommand=self._on_xscroll,
        )
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Motion>", self._on_motion)
        self._canvas.bind("<Button-3>", self._on_right_click)
        self._canvas.bind("<Shift-ButtonPress-1>", self._on_pan_press)
        self._canvas.bind("<Shift-B1-Motion>", self._on_pan_drag)
        self._canvas.bind("<Shift-ButtonRelease-1>", self._on_pan_release)
        self._canvas.bind("<ButtonPress-2>", self._on_pan_press)
        self._canvas.bind("<B2-Motion>", self._on_pan_drag)
        self._canvas.bind("<ButtonRelease-2>", self._on_pan_release)
        self._canvas.bind("<Control-MouseWheel>", self._on_ctrl_wheel)
        self._canvas.bind("<Configure>", self._on_configure)

    # ------------------------------------------------------------------
    # State the view owns and this widget only reacts to
    # ------------------------------------------------------------------

    def set_marks_visible(self, on: bool) -> None:
        self._marks_visible = on
        self.refresh_marks()

    def set_viewing_clean(self, on: bool) -> None:
        """Con la limpia en pantalla no hay marcas que dibujar ni crear."""
        self._viewing_clean = on

    def set_edit_mode(self, on: bool) -> None:
        """Dibujar marcas: el cursor en cruz y el clic que crea una."""
        self._edit_mode = on
        try:
            self._canvas.configure(cursor="crosshair" if on else "")
        except tk.TclError:
            pass

    def select(self, key: MarkKey | None) -> None:
        self._selected = key
        self.refresh_marks()

    def set_pages(self, count: int) -> None:
        """El capítulo no cambia de largo, pero la lista de ids sí."""
        self._pages = count
        self._mark_ids_by_page = [[] for _ in range(count)]

    # ------------------------------------------------------------------
    # Public drawing API
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Colocar y dibujar: lo que se llama al montarla."""
        self.layout()
        self.draw()

    def refresh_marks(self) -> None:
        """Volver a pintar el overlay sin tocar las páginas rasterizadas."""
        self._render_marks()

    def scale(self) -> float:
        return self._scale

    def is_drawing(self) -> bool:
        """Hay un rectángulo a medio dibujar, así que el papel no se mueve."""
        return self._drag is not None

    def zoom_percent(self) -> int:
        return max(1, int(round(self._scale * 100)))

    def can_zoom_in(self) -> bool:
        return self._scale < MAX_EFFECTIVE_SCALE - 1e-4

    def can_zoom_out(self) -> bool:
        return self._scale > MIN_EFFECTIVE_SCALE + 1e-4

    def zoom_by(self, step: float) -> None:
        self.set_scale(self._scale * step)

    def fit(self, kind: str) -> None:
        """``window`` | ``width`` | ``height``, sobre la página más grande."""
        cw = max(self._canvas.winfo_width(), 1)
        ch = max(self._canvas.winfo_height(), 1)
        max_w, max_h = self._max_page_size()
        if kind == "width":
            target = cw / max_w
        elif kind == "height":
            target = ch / max_h
        else:
            target = min(cw / max_w, ch / max_h, 1.0)
        self.set_scale(target)

    def set_scale(
        self, scale: float, *, focus: tuple[int, int] | None = None,
    ) -> None:
        """Change the strip's scale, holding a point of the page still.

        ``focus`` is a canvas pixel (the cursor for Ctrl+wheel, the
        middle of the view for the ± buttons).
        """
        scale = self._clamp_scale(scale)
        old = self._scale
        if abs(scale - old) < 1e-6 or old <= 0:
            return
        cw = max(self._canvas.winfo_width(), 1)
        ch = max(self._canvas.winfo_height(), 1)
        fx, fy = focus if focus is not None else (cw // 2, ch // 2)
        # Where the anchor sits in unscaled strip units.
        anchor_y = self._canvas.canvasy(fy) / old
        anchor_x = self._canvas.canvasx(fx) / old

        self._scale = scale
        self._fit_pending = False
        self.layout()
        content_w, content_h = self._content
        self._canvas.yview_moveto(
            max(0.0, anchor_y * scale - fy) / max(1, content_h),
        )
        self._canvas.xview_moveto(
            max(0.0, anchor_x * scale - fx) / max(1, content_w),
        )
        self.draw()
        self._notify_scale()

    def viewport(self) -> tuple[float, float, float]:
        """``(escala, x, y)``: lo que hace falta para volver aquí."""
        return (
            self._scale,
            float(self._canvas.canvasx(0)),
            float(self._canvas.canvasy(0)),
        )

    def set_viewport(self, state: tuple[float, float, float]) -> None:
        """Volver a una vista guardada: escala y desplazamiento."""
        scale, x, y = state
        self._scale = self._clamp_scale(scale)
        self._fit_pending = False
        self.layout()
        # El lienzo acaba de nacer, así que su scrollregion sigue siendo
        # la de mentira hasta que el gestor de geometría haya corrido.
        try:
            self.update_idletasks()
        except tk.TclError:
            return
        width, height = self._content
        self._canvas.xview_moveto(max(0.0, min(1.0, x / max(width, 1))))
        self._canvas.yview_moveto(max(0.0, min(1.0, y / max(height, 1))))
        self.schedule_draw()

    def scroll_lines(self, lines: int) -> None:
        """Lo que pide la rueda, que la vista enruta por el puntero."""
        self._canvas.yview_scroll(lines, "units")

    def scroll_to_page(self, page: int) -> None:
        """Llevar la cinta al principio de una página."""
        if not self._layout or not 0 <= page < len(self._layout):
            return
        self.scroll_to(self._layout[page][1], force=True)

    def scroll_to(
        self, y: float, *, margin: int = 40, force: bool = False,
    ) -> None:
        """Put strip coordinate ``y`` near the top of the visible band.

        Unless ``force``, a point already comfortably on screen is left
        where it is — revealing a mark should not shuffle the page under
        someone who can already see it.
        """
        total = self._content[1]
        if total <= 0:
            return
        if not force:
            top = self._canvas.canvasy(0)
            bottom = top + self._canvas.winfo_height()
            if top + margin <= y <= bottom - margin:
                return
        self._canvas.yview_moveto(max(0.0, (y - margin) / total))

    def reveal_mark(self, page: int, mark: Mark) -> None:
        _, sy = self.image_to_strip(page, mark.x, mark.y)
        self.scroll_to(sy)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _max_page_size(self) -> tuple[int, int]:
        """Widest and tallest page, in real pixels."""
        max_w = max_h = 1
        for idx in range(self._pages):
            w, h = self._size(idx)
            max_w = max(max_w, w)
            max_h = max(max_h, h)
        return max_w, max_h

    @staticmethod
    def _clamp_scale(scale: float) -> float:
        return max(MIN_EFFECTIVE_SCALE, min(MAX_EFFECTIVE_SCALE, scale))

    def layout(self) -> None:
        """Place every page in strip coordinates at the current scale.

        Pages are centred on the widest one so a chapter that mixes
        portrait scans with a wide spread reads down a single axis —
        the single-page view has always centred, and the strip looked
        broken next to it.
        """
        if not self._pages:
            self._layout = []
            self._content = (1, 1)
            return
        cw = max(self._canvas.winfo_width(), 1)
        ch = max(self._canvas.winfo_height(), 1)
        max_w, max_h = self._max_page_size()

        if self._fit_pending and cw > 1 and ch > 1:
            self._fit_pending = False
            window = min(cw / max_w, ch / max_h, 1.0)
            # A webtoon strip fitted whole is an unreadable sliver, so
            # open on the width instead — same rule as a single page.
            self._scale = (
                cw / max_w if window < TALL_PAGE_FIT_LIMIT else window
            )
        self._scale = self._clamp_scale(self._scale)
        scale = self._scale

        content_w = max(cw, int(round(max_w * scale)))
        layout: list[Placement] = []
        y = 0.0
        for idx in range(self._pages):
            iw, ih = self._size(idx)
            sw = max(1, int(round(iw * scale)))
            sh = max(1, int(round(ih * scale)))
            layout.append(((content_w - sw) / 2.0, y, sw, sh))
            y += sh
        self._layout = layout
        self._content = (content_w, max(1, int(round(y))))
        self._canvas.configure(
            scrollregion=(0, 0, content_w, self._content[1]),
        )

        # The opening fit is only decided once the canvas has a real
        # size, well after the toolbar was first drawn — without this the
        # strip would keep reporting the placeholder 100 %.
        self._notify_scale()

    def total_height(self) -> int:
        return self._content[1]

    def visible_band(self) -> tuple[float, float, float, float]:
        """Lo que la ventana abarca: left, top, right, bottom.

        En coordenadas de la cinta, que es donde está el layout. La usan
        el rasterizado y el overlay de marcas: los dos tienen que
        recortar por lo mismo.
        """
        cw = max(self._canvas.winfo_width(), 1)
        ch = max(self._canvas.winfo_height(), 1)
        top = self._canvas.canvasy(0)
        left = self._canvas.canvasx(0)
        return left, top, left + cw, top + ch

    def image_to_strip(
        self, page: int, x: float, y: float,
    ) -> tuple[float, float]:
        """Un píxel de una página, en coordenadas de la cinta."""
        if not 0 <= page < len(self._layout):
            return 0.0, 0.0
        x0, y0, _, _ = self._layout[page]
        return x0 + x * self._scale, y0 + y * self._scale

    def strip_to_image(
        self, sx: float, sy: float, page: int | None = None,
    ) -> tuple[int, int, int] | None:
        """Map strip coordinates to ``(page, x, y)`` in real image pixels.

        With ``page`` given the point is clamped into that page, which is
        what a drag that started on it should do even once the pointer
        wanders onto the neighbour.
        """
        if page is None:
            page = self.page_at(sy)
            if page is None:
                return None
        if not 0 <= page < len(self._layout):
            return None
        x0, y0, _, _ = self._layout[page]
        iw, ih = self._size(page)
        ix = int(round((sx - x0) / self._scale))
        iy = int(round((sy - y0) / self._scale))
        return page, max(0, min(ix, iw)), max(0, min(iy, ih))

    def page_at(self, strip_y: float) -> int | None:
        """Qué página ocupa esa altura de la cinta."""
        for idx, (_, y0, _, sh) in enumerate(self._layout):
            if y0 <= strip_y < y0 + sh:
                return idx
        return None

    def mark_at(self, sx: float, sy: float) -> MarkKey | None:
        """Qué marca hay bajo ese punto de la cinta, si hay alguna."""
        located = self.strip_to_image(sx, sy)
        if located is None:
            return None
        page, ix, iy = located
        for mark_id, mark in enumerate(self._stores[page]):
            if mark.x <= ix <= mark.x + mark.w and mark.y <= iy <= mark.y + mark.h:
                return (page, mark_id)
        return None

    # ------------------------------------------------------------------
    # Rasterising
    # ------------------------------------------------------------------

    def draw(self, *, fast: bool = False) -> None:
        """Rasterise only the band of the strip the canvas can show.

        A chapter of webtoon strips is hundreds of megapixels; scaling
        it whole would be gigabytes of bitmap for the two page slices
        actually on screen.
        """
        if not self._layout:
            return
        left, top, right, bottom = self.visible_band()
        scale = self._scale
        visible: set[int] = set()

        for idx, (x0, y0, sw, sh) in enumerate(self._layout):
            vx0, vy0 = max(x0, left), max(y0, top)
            vx1, vy1 = min(x0 + sw, right), min(y0 + sh, bottom)
            if vx1 <= vx0 or vy1 <= vy0:
                continue
            src = self._source(idx)
            iw, ih = src.size
            sx0 = max(0, int(math.floor((vx0 - x0) / scale)))
            sy0 = max(0, int(math.floor((vy0 - y0) / scale)))
            sx1 = min(iw, int(math.ceil((vx1 - x0) / scale)))
            sy1 = min(ih, int(math.ceil((vy1 - y0) / scale)))
            if sx1 <= sx0 or sy1 <= sy0:
                continue
            try:
                crop = src.crop((sx0, sy0, sx1, sy1))
                target = (
                    max(1, int(round((sx1 - sx0) * scale))),
                    max(1, int(round((sy1 - sy0) * scale))),
                )
                if target != crop.size:
                    crop = crop.resize(target, resample_for(scale, fast))
                photo = ImageTk.PhotoImage(crop)
            except Exception as exc:
                log.exception("Error rasterizando página %d: %s", idx, exc)
                continue
            self._photos[idx] = photo
            px, py = x0 + sx0 * scale, y0 + sy0 * scale
            item = self._photo_ids.get(idx)
            if item is None:
                item = self._canvas.create_image(
                    px, py, image=photo, anchor=tk.NW, tags=("page",),
                )
                self._photo_ids[idx] = item
            else:
                self._canvas.itemconfigure(item, image=photo)
                self._canvas.coords(item, px, py)
            self._canvas.tag_lower(item)
            visible.add(idx)

        for idx in [i for i in self._photo_ids if i not in visible]:
            self._canvas.delete(self._photo_ids.pop(idx))
            self._photos.pop(idx, None)
        self._render_marks()

    def schedule_draw(self) -> None:
        """Coalesce the redraws a single wheel notch can trigger."""
        if self._draw_pending:
            return
        self._draw_pending = True
        self.after_idle(self._draw_now)

    def _draw_now(self) -> None:
        self._draw_pending = False
        try:
            self.draw()
        except tk.TclError:
            pass

    def _notify_scale(self) -> None:
        if abs(self._scale - self._notified_scale) <= 1e-6:
            return
        self._notified_scale = self._scale
        if self._on_scale_change is not None:
            self._on_scale_change()

    # ------------------------------------------------------------------
    # Mark overlay
    # ------------------------------------------------------------------

    def _overlay_pages(self) -> list[int]:
        """Las páginas cuyas marcas hay que dibujar: las que se ven.

        :meth:`draw` rasteriza solo la banda visible, y esto recorría el
        capítulo entero: en 40 páginas con 15 globos eran ~600 items de
        canvas destruidos y recreados en cada notch de rueda, el 95 %
        fuera de pantalla. La seleccionada entra siempre aunque no se
        vea, porque su recuadro de borrado se sale de la página y es la
        única que dibuja uno.
        """
        left, top, right, bottom = self.visible_band()
        paginas = [
            idx for idx, (x0, y0, sw, sh) in enumerate(self._layout)
            if x0 < right and x0 + sw > left and y0 < bottom and y0 + sh > top
        ]
        if self._selected is not None:
            elegida = self._selected[0]
            if elegida not in paginas and 0 <= elegida < len(self._layout):
                paginas.append(elegida)
        return paginas

    def _render_marks(self) -> None:
        for ids in self._mark_ids_by_page:
            for mid in ids:
                self._canvas.delete(mid)
        self._mark_ids_by_page = [[] for _ in range(self._pages)]
        if not self._marks_visible or self._viewing_clean:
            return
        for page in self._overlay_pages():
            for mark_id, mark in enumerate(self._stores[page]):
                is_selected = self._selected == (page, mark_id)
                outline = COLOR_ACCENT if is_selected else mark.color
                width = (
                    MARK_SELECTED_STROKE_WIDTH if is_selected
                    else MARK_STROKE_WIDTH
                )
                x1, y1 = self.image_to_strip(page, mark.x, mark.y)
                x2, y2 = self.image_to_strip(
                    page, mark.x + mark.w, mark.y + mark.h,
                )
                if is_selected:
                    # The erased area, on the selection only — see the
                    # canvas for why it is not drawn on every mark.
                    pad = mark.erase_padding
                    px1, py1 = self.image_to_strip(
                        page, mark.x - pad, mark.y - pad,
                    )
                    px2, py2 = self.image_to_strip(
                        page, mark.x + mark.w + pad, mark.y + mark.h + pad,
                    )
                    # Only tracked for deletion; a click is answered by
                    # `mark_at`, which works off the geometry and not off
                    # the canvas items.
                    self._mark_ids_by_page[page].append(
                        self._canvas.create_rectangle(
                            px1, py1, px2, py2,
                            outline=outline, width=1, fill="",
                            dash=MARK_PAD_DASH,
                            tags=("pad", f"img_{page}", f"pad_{mark_id}"),
                        ),
                    )
                self._mark_ids_by_page[page].append(
                    self._canvas.create_rectangle(
                        x1, y1, x2, y2,
                        outline=outline, width=width,
                        fill=MARK_SELECTED_FILL if is_selected else "",
                        tags=("mark", f"img_{page}", f"mark_{mark_id}"),
                    ),
                )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_yscroll(self, first: str, last: str) -> None:
        self._scrollbar.set(first, last)
        self.schedule_draw()

    def _on_xscroll(self, _first: str, _last: str) -> None:
        self.schedule_draw()

    def _on_configure(self, _event: tk.Event) -> None:
        # Laying out is cheap (page sizes only); rasterising is not, so
        # that half waits for the resize drag to stop producing events.
        self.layout()
        self.schedule_draw()

    def _on_ctrl_wheel(self, event: tk.Event) -> str:
        step = ZOOM_STEP if event.delta > 0 else 1.0 / ZOOM_STEP
        self.set_scale(self._scale * step, focus=(event.x, event.y))
        return "break"

    def _on_press(self, event: tk.Event) -> None:
        if self._viewing_clean:
            return
        sx = self._canvas.canvasx(event.x)
        sy = self._canvas.canvasy(event.y)
        if self._edit_mode:
            located = self.strip_to_image(sx, sy)
            if located is None:
                return
            page = located[0]
            self._emit(self._on_activate, page)
            preview = self._canvas.create_rectangle(
                sx, sy, sx, sy,
                outline=self._current_color,
                width=MARK_STROKE_WIDTH, dash=(4, 2),
                tags=("preview",),
            )
            self._drag = {
                "page": page,
                "start_x": sx, "start_y": sy,
                "preview_id": preview,
            }
            return
        clicked = self.mark_at(sx, sy)
        if clicked is not None:
            self._emit(self._on_select, *clicked)
        else:
            located = self.strip_to_image(sx, sy)
            if located is not None:
                self._emit(self._on_activate, located[0])

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag is None:
            return
        self._canvas.coords(
            self._drag["preview_id"],
            self._drag["start_x"], self._drag["start_y"],
            self._canvas.canvasx(event.x), self._canvas.canvasy(event.y),
        )

    def _on_release(self, event: tk.Event) -> None:
        if self._drag is None:
            return
        page = self._drag["page"]
        self._canvas.delete(self._drag["preview_id"])
        start = (self._drag["start_x"], self._drag["start_y"])
        self._drag = None

        begin = self.strip_to_image(start[0], start[1], page)
        end = self.strip_to_image(
            self._canvas.canvasx(event.x), self._canvas.canvasy(event.y), page,
        )
        if begin is None or end is None:
            return
        x1, x2 = sorted((begin[1], end[1]))
        y1, y2 = sorted((begin[2], end[2]))
        if x2 - x1 < MARK_MIN_SIZE or y2 - y1 < MARK_MIN_SIZE:
            return
        mark = Mark(
            x=x1, y=y1, w=x2 - x1, h=y2 - y1, color=self._current_color,
        )
        mark_id = self._stores[page].add(mark)
        self._emit(self._on_mark_added, page, mark_id)

    def _on_motion(self, event: tk.Event) -> None:
        if self._on_hover is None:
            return
        hovered = self.mark_at(
            self._canvas.canvasx(event.x), self._canvas.canvasy(event.y),
        )
        try:
            self._on_hover(hovered)
        except Exception as exc:
            log.exception("Error en on_hover: %s", exc)

    def _on_right_click(self, _event: tk.Event) -> None:
        """Botón derecho mientras se dibuja: se cancela el rectángulo."""
        if not self._edit_mode or self._drag is None:
            return
        self._canvas.delete(self._drag["preview_id"])
        self._drag = None

    def _on_pan_press(self, event: tk.Event) -> None:
        self._canvas.scan_mark(event.x, event.y)

    def _on_pan_drag(self, event: tk.Event) -> None:
        self._canvas.scan_dragto(event.x, event.y, gain=1)
        self.schedule_draw()

    def _on_pan_release(self, _event: tk.Event) -> None:
        self.schedule_draw()

    @staticmethod
    def _emit(callback, *args) -> None:
        """Un callback de la vista que revienta no se lleva el lienzo."""
        if callback is None:
            return
        try:
            callback(*args)
        except Exception as exc:
            log.exception("Error en un callback de la cinta: %s", exc)
