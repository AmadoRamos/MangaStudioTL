"""Step 2 — mark the text sections, then read them with OCR.

Laid out as in the mockups: a docked 42 px control strip above the
canvas (view mode, page counter, zoom, clean/original — nothing floats
over the page any more), the scan itself on the dark canvas, a tool
dock on its right, and the rail carrying the mark list, the section
inspector and the anchored ``Continuar proceso`` action.

The tools are on the right rather than on the rail because the rail was
holding four things at once, and these are the ones the hand keeps
going back to while drawing: they belong next to the page.

While the OCR runs the rail turns into the progress report — a metered
row and a short log — and the primary action becomes ``Cancelar
proceso``. Cleaning is not waited for here: on the way to step 3 the
marked pages are handed to the App's background queue, which keeps
going while the chapter is translated and reports on the rail.
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from pathlib import Path
from dataclasses import replace

from PIL import Image, ImageTk

from src.config import (
    ACCENT_200,
    CANVAS_BG,
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DIVIDER,
    COLOR_TEXT,
    MARK_DEFAULT_COLOR,
    MARK_MIN_SIZE,
    MARK_PADDING_MAX,
    MARK_PADDING_MIN,
    MARK_STROKE_WIDTH,
    NEUTRAL_500,
    NEUTRAL_600,
    NEUTRAL_700,
    SIDEBAR_BG,
    SIDEBAR_SECTION_PAD,
)
from src.utils.inpainter import find_clean, has_clean
from src.utils.logger import get_logger
from src.utils.marks_store import Mark, MarksStore
from src.utils.ocr_engine import OcrEngine
from src.utils.pipeline_runner import PipelineRunner
from src.views import theme
from src.views.marks_canvas import MARK_PAD_DASH, MarksCanvas
from src.views.toolbar import StatusBar, Tooltip
from src.views.zoomed_canvas import (
    MAX_EFFECTIVE_SCALE,
    MIN_EFFECTIVE_SCALE,
    TALL_PAGE_FIT_LIMIT,
    ZOOM_STEP,
    resample_for,
)

log = get_logger("marks_view")

MODE_ALL = "all"
MODE_ONE = "one"

LOG_LINES = 3

#: Right-hand tool dock. Narrower than the rail: it holds one column of
#: buttons, and every pixel it takes comes off the page.
TOOLS_DOCK_WIDTH = 186


class MarksView(tk.Frame):
    """Step 2 view: marks + zoom + pipeline trigger."""

    def __init__(
        self,
        master: tk.Misc,
        workflow,  # WorkflowController
        sidebar,
        engine: OcrEngine,
        pipeline_runner: PipelineRunner,
    ) -> None:
        super().__init__(master, bg=COLOR_BG)
        self.workflow = workflow
        self._sidebar = sidebar
        self._engine = engine
        self._pipeline = pipeline_runner
        self._items: list[tuple[Path, Image.Image]] = list(workflow.items)
        self._stores: list[MarksStore] = list(workflow.stores)

        self._mode: str = MODE_ONE
        self._index: int = 0
        self._edit_state: bool = False
        self._marks_visible: bool = True
        self._current_color: str = MARK_DEFAULT_COLOR
        self._clean_cache: dict[int, Image.Image] = {}
        self._clean_available: dict[int, bool] = {}
        self._viewing_clean: bool = False
        self._running: bool = False
        self._advance_after: bool = False
        self._log_lines: list[str] = []

        # Strip (mode «Todas») rendering: pages laid out in strip
        # coordinates at ``_strip_scale``, rasterised one viewport band
        # at a time so the zoom ceiling costs canvas-sized bitmaps.
        self._strip_scale: float = 1.0
        self._notified_strip_scale: float = -1.0
        self._strip_fit_pending: bool = True
        self._strip_layout: list[tuple[float, float, int, int]] = []
        self._strip_content: tuple[int, int] = (1, 1)
        self._strip_photos: dict[int, ImageTk.PhotoImage] = {}
        self._strip_photo_ids: dict[int, int] = {}
        self._strip_draw_pending: bool = False
        self._expanded_pages: set[int] = {0}
        self._mark_ids_by_image: list[list[int]] = [[] for _ in self._items]
        self._mark_to_canvas: dict[tuple[int, int], int] = {}
        self._selected: tuple[int, int] | None = None
        self._hovered: tuple[int, int] | None = None
        self._drag: dict | None = None
        self._marks_canvas: MarksCanvas | None = None
        self._canvas = None
        self._scrollbar = None

        # Rail widgets, rebuilt whenever the mode or the pipeline state
        # changes. The tool buttons below them are the exception: they
        # live in the right-hand dock and are built once.
        self._marks_body: tk.Frame | None = None
        self._marks_count: tk.Label | None = None
        self._marks_list_sig: tuple | None = None
        self._tools_dock: tk.Frame | None = None
        self._edit_btn: tk.Button | None = None
        self._visibility_btn: tk.Button | None = None
        self._undo_btn: tk.Button | None = None
        self._clear_btn: tk.Button | None = None
        self._ocr_btn: tk.Button | None = None
        self._reocr_btn: tk.Button | None = None
        self._meter_ocr: theme.Meter | None = None
        self._meter_ocr_count: tk.Label | None = None
        self._pipeline_detail: tk.Label | None = None
        self._log_label: tk.Label | None = None
        self._inspector_body: tk.Frame | None = None
        self._inspector_for: int | None = None
        self._geom_vars: dict[str, tk.StringVar] = {}
        self._padding_var: tk.IntVar | None = None
        self._padding_label: tk.Label | None = None
        self._delete_btn: tk.Button | None = None
        self._rebuilding_inspector: bool = False

        self._build_ui()
        self._build_sidebar_sections()
        self._refresh_clean_availability()
        if self._mode == MODE_ALL:
            self._render_strip()
        else:
            self._build_single_canvas()
            self._load_current()
        self._bind_shortcuts()
        self._update_button_states()
        self._update_toolbar()
        self._pipeline.attach(
            self,
            on_step_start=self._on_pipeline_step_start,
            on_step_progress=self._on_pipeline_step_progress,
            on_step_done=self._on_pipeline_step_done,
            on_overall_done=self._on_pipeline_overall_done,
        )
        self._status.set("Listo para marcar", "info")

    # ------------------------------------------------------------------
    # Chrome
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._topbar = theme.TopBar(self)
        self._topbar.pack(side=tk.TOP, fill=tk.X)
        row = self._topbar.body

        self._mode_bar = theme.SegmentedBar(
            row, border_width=2, uniform_chars=theme.SEGMENT_CHARS,
        )
        self._mode_bar.pack(side=tk.LEFT, pady=6)
        self._mode_bar.add(
            MODE_ALL, "Todas", self._set_mode_all,
            tooltip="Todas las páginas en una tira vertical",
        )
        self._mode_bar.add(
            MODE_ONE, "Una", self._set_mode_one,
            tooltip="Trabajar con una página a la vez",
        )
        self._mode_bar.set_active(self._mode)

        self._page_label = theme.body(
            row, "", size=9, bg=COLOR_BG, fg=NEUTRAL_600,
        )
        self._page_label.pack(side=tk.LEFT, padx=12)

        self._topbar.gap()

        self._nav_bar = theme.SegmentedBar(row, border_width=2)
        self._nav_bar.add("prev", "◀", self._on_prev, tooltip="Página anterior")
        self._nav_bar.add("count", "1 / 1", None, width=7)
        self._nav_bar.add("next", "▶", self._on_next, tooltip="Página siguiente")

        self._zoom_bar = theme.SegmentedBar(row, border_width=2)
        self._zoom_bar.pack(side=tk.LEFT, padx=(0, 8), pady=6)
        self._zoom_bar.add("out", "−", self._on_zoom_out, tooltip="Alejar (Ctrl + rueda)")
        self._zoom_bar.add(
            "reset", "100%", self._on_zoom_reset, width=6,
            tooltip="Zoom actual · pulsa para ajustar a la ventana",
        )
        self._zoom_bar.add("in", "+", self._on_zoom_in, tooltip="Acercar (Ctrl + rueda)")

        self._fit_bar = theme.SegmentedBar(
            row, border_width=2, uniform_chars=theme.SEGMENT_CHARS,
        )
        self._fit_bar.pack(side=tk.LEFT, padx=(0, 8), pady=6)
        self._fit_bar.add(
            "window", "Ventana", self._on_fit_window,
            tooltip="La página entera dentro de la ventana",
        )
        self._fit_bar.add(
            "width", "Ancho", self._on_fit_width,
            tooltip="Ajustar al ancho y empezar arriba",
        )
        self._fit_bar.add(
            "height", "Alto", self._on_fit_height,
            tooltip="Ajustar al alto de la ventana",
        )

        self._clean_bar = theme.SegmentedBar(
            row, border_width=2, uniform_chars=theme.SEGMENT_CHARS,
        )
        self._clean_bar.pack(side=tk.LEFT, pady=6)
        self._clean_bar.add(
            "clean", "Limpia", lambda: self._set_clean_mode(True),
            tooltip="Ver la versión sin texto",
        )
        self._clean_bar.add(
            "original", "Original", lambda: self._set_clean_mode(False),
            tooltip="Ver la imagen original con las marcas",
        )
        self._clean_bar.set_active("original")

        # 4 px pipeline rule, only while the pipeline runs.
        self._progress_rule = theme.Meter(self, height=4)

        # The tools sit against the page, not on the rail: the rail was
        # carrying the step list, the mark tree, the section inspector
        # and six buttons at once, and the buttons are the part the hand
        # keeps going back to while drawing.
        self._stage = tk.Frame(self, bg=CANVAS_BG)
        self._stage.pack(side=tk.TOP, expand=True, fill=tk.BOTH)
        self._build_tools_dock()
        self._host = tk.Frame(self._stage, bg=CANVAS_BG)
        self._host.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

        self._status = StatusBar(self)
        self._status.pack(side=tk.BOTTOM, fill=tk.X)
        self._status.set_hint(
            "E editar · H ocultar · Z deshacer · V limpia/original · "
            "Supr eliminar · flechas ajustar · Mayús+flechas tamaño · "
            "Ctrl+rueda zoom · rueda desplazar · botón central mover"
        )

    def _build_tools_dock(self) -> None:
        """The right-hand tool dock: built once, outlives every rebuild.

        Unlike the rail sections, these buttons are not thrown away and
        recreated — ``_toggle_edit`` and ``_toggle_visibility`` restyle
        them in place, so the references have to stay valid.
        """
        dock = tk.Frame(self._stage, bg=SIDEBAR_BG, width=TOOLS_DOCK_WIDTH)
        dock.pack(side=tk.RIGHT, fill=tk.Y)
        dock.pack_propagate(False)
        theme.rule(dock, thickness=2, color=COLOR_DIVIDER, vertical=True).pack(
            side=tk.LEFT, fill=tk.Y,
        )
        body = tk.Frame(dock, bg=SIDEBAR_BG)
        body.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True,
            padx=SIDEBAR_SECTION_PAD, pady=14,
        )
        self._tools_dock = dock

        theme.kicker(body, "Herramientas", bg=SIDEBAR_BG).pack(
            fill=tk.X, pady=(0, 9),
        )
        self._edit_btn = self._tool_button(body, "Editar", "E", self._toggle_edit)
        self._visibility_btn = self._tool_button(
            body, "Ocultar", "H", self._toggle_visibility,
        )
        self._undo_btn = self._tool_button(body, "Deshacer", "Z", self._undo)
        self._clear_btn = self._tool_button(body, "Limpiar todo", "", self._clear_marks)

        theme.rule(body, thickness=2, color=COLOR_DIVIDER).pack(
            fill=tk.X, pady=(14, 0),
        )
        theme.kicker(body, "Texto", bg=SIDEBAR_BG).pack(fill=tk.X, pady=(12, 9))
        # OCR without leaving the step: the text can be checked here,
        # next to the page, before committing to the slow cleaning pass.
        self._ocr_btn = self._tool_button(
            body, "Extraer texto", "", self._extract_text,
            tooltip="Lee con Tesseract las marcas que aún no tienen texto",
        )
        self._reocr_btn = self._tool_button(
            body, "Re-extraer", "", self._extract_text_forced,
            tooltip="Vuelve a leer todas las marcas, incluso las que ya "
                    "tienen texto",
        )

    def _show_tools_dock(self, visible: bool) -> None:
        """Hidden while the pipeline runs — nothing here is safe to press."""
        if self._tools_dock is None:
            return
        if visible and not self._tools_dock.winfo_manager():
            self._tools_dock.pack(side=tk.RIGHT, fill=tk.Y, before=self._host)
        elif not visible and self._tools_dock.winfo_manager():
            self._tools_dock.pack_forget()

    def _bind_shortcuts(self) -> None:
        """The shortcuts printed next to the tool buttons."""
        self._bind_letter("e", self._toggle_edit)
        self._bind_letter("h", self._toggle_visibility)
        self._bind_letter("z", self._undo)
        self._bind_letter(
            "v", lambda: self._set_clean_mode(not self._viewing_clean),
        )
        self.bind_all("<Delete>", lambda _e: self._delete_from_key())
        for sequence, dx, dy in (
            ("<Left>", -1, 0), ("<Right>", 1, 0),
            ("<Up>", 0, -1), ("<Down>", 0, 1),
        ):
            self.bind_all(
                sequence,
                lambda e, a=dx, b=dy: self._nudge_selected(a, b, resize=False),
            )
            self.bind_all(
                f"<Shift-{sequence[1:]}",
                lambda e, a=dx, b=dy: self._nudge_selected(a, b, resize=True),
            )
        self.focus_set()

    def _bind_letter(self, key: str, action) -> None:
        """A bare letter must not fire while the user is typing a number."""
        self.bind_all(
            f"<KeyPress-{key}>",
            lambda _e: None if self._typing_in_field() else action(),
        )

    def _typing_in_field(self) -> bool:
        try:
            widget = self.focus_get()
        except Exception:
            return False
        return isinstance(widget, (tk.Entry, tk.Text))

    def _delete_from_key(self) -> None:
        if not self._typing_in_field():
            self._delete_selected()

    def _update_toolbar(self) -> None:
        total = len(self._items)
        if self._mode == MODE_ONE:
            self._page_label.configure(text=f"{self._index + 1} / {total}")
            self._nav_bar.set_text("count", f"{self._index + 1} / {total}")
            self._nav_bar.set_enabled("prev", self._index > 0)
            self._nav_bar.set_enabled("next", self._index < total - 1)
            if not self._nav_bar.winfo_manager():
                self._nav_bar.pack(
                    side=tk.LEFT, padx=(0, 8), pady=6,
                    before=self._zoom_bar,
                )
        else:
            self._page_label.configure(text=f"Tira vertical · {total} páginas")
            self._nav_bar.pack_forget()
        self._mode_bar.set_active(self._mode)
        self._clean_bar.set_active(
            "clean" if self._viewing_clean else "original",
        )
        any_clean = any(self._clean_available.values())
        self._clean_bar.set_enabled("clean", any_clean or self._viewing_clean)
        self._update_zoom_controls()

    # ------------------------------------------------------------------
    # Rail
    # ------------------------------------------------------------------

    def _build_sidebar_sections(self) -> None:
        self._sidebar.clear_view_sections()
        # The old widgets are gone; drop the references before anything
        # can call refresh on them.
        self._marks_body = None
        self._marks_count = None
        self._marks_list_sig = None
        # The tool buttons are not in here: they live in the right-hand
        # dock, which is built once and survives every rebuild.
        self._meter_ocr = None
        self._meter_ocr_count = None
        self._pipeline_detail = None
        self._log_label = None
        self._inspector_body = None
        self._inspector_for = None
        self._geom_vars = {}
        self._padding_var = None
        self._padding_label = None
        self._delete_btn = None

        self._show_tools_dock(not self._running)
        if self._running:
            self._build_pipeline_sections()
            return

        self._marks_body, self._marks_count = self._sidebar.section_with_count(
            "Marcas",
        )
        self._refresh_marks_list()

        self._sidebar.section_divider()

        self._inspector_body = self._sidebar.section("Sección seleccionada")
        self._inspector_for = None
        self._geom_vars = {}
        self._padding_var = None
        self._padding_label = None
        self._refresh_inspector()

        self._sidebar.set_footer(
            "Continuar proceso →", self._on_continue,
            hint="Extrae el texto y pasa a Traducir",
            secondary_text="← Atrás", secondary_command=self._on_back,
        )
        self._update_continue_label()

    def _tool_button(
        self,
        parent: tk.Misc,
        label: str,
        shortcut: str,
        command,
        tooltip: str = "",
    ) -> tk.Button:
        text = f"{label}   {shortcut}" if shortcut else label
        # «outline», not «secondary»: on their own strip, borderless
        # labels stop reading as something you can press. The two toggles
        # still flip to «ink» when they are on.
        btn = theme.button(
            parent, text, command,
            variant="outline", size=9, padx=10, pady=8, anchor=tk.W,
            tooltip=tooltip or None,
        )
        btn.pack(fill=tk.X, pady=(0, 6))
        return btn

    def _marks_signature(self) -> tuple:
        """Everything the rail list draws, so it can skip idle rebuilds.

        ``_refresh_marks_list`` runs on every zoom notch; rebuilding a
        chapter's worth of rows each time would make zooming crawl.
        """
        expanded = tuple(sorted(self._expanded_pages))
        rows = tuple(
            (
                idx,
                tuple(
                    (m.w, m.h, m.color, self._ocr_preview(idx, i) or "")
                    for i, m in enumerate(self._stores[idx])
                ),
            )
            for idx in expanded
            if 0 <= idx < len(self._stores)
        )
        return (
            self._index, self._selected, expanded,
            tuple(len(s) for s in self._stores), rows,
        )

    def _refresh_marks_list(self, *, force: bool = False) -> None:
        """Pages, each with its own marks nested underneath."""
        if self._marks_body is None:
            return
        signature = self._marks_signature()
        if not force and signature == self._marks_list_sig:
            return
        self._marks_list_sig = signature
        for widget in list(self._marks_body.winfo_children()):
            widget.destroy()

        total = self.workflow.total_marks()
        if self._marks_count is not None:
            self._marks_count.configure(text=str(total))
        if not self._stores:
            return
        for idx, store in enumerate(self._stores):
            self._page_row(idx, len(store))
            if idx in self._expanded_pages:
                self._page_marks(idx, store)
        if total == 0:
            theme.body(
                self._marks_body,
                "Activa «Editar» y arrastra sobre el texto.",
                size=8, bg=SIDEBAR_BG, fg=NEUTRAL_600, wrap=210,
            ).pack(fill=tk.X, pady=(8, 0))

    def _page_row(self, index: int, count: int) -> None:
        active = index == self._index
        bg = ACCENT_200 if active else SIDEBAR_BG
        fg = COLOR_TEXT if count else NEUTRAL_500
        row = tk.Frame(self._marks_body, bg=bg, padx=8, pady=6)
        row.pack(fill=tk.X, pady=1)
        # The caret only opens and closes the page; the rest of the row
        # turns to it. Two jobs, two targets.
        caret = theme.body(
            row, "▾" if index in self._expanded_pages else "▸",
            size=8, bg=bg, fg=NEUTRAL_600,
        )
        caret.pack(side=tk.LEFT, padx=(0, 6))
        caret.configure(cursor="hand2")
        caret.bind("<Button-1>", lambda _e, i=index: self._toggle_page(i))
        name = theme.body(
            row, f"{index + 1:02d} · página", size=8, bg=bg, fg=fg,
        )
        name.pack(side=tk.LEFT)
        value = theme.body(row, str(count), size=8, bg=bg, fg=fg)
        value.pack(side=tk.RIGHT)
        for widget in (row, name, value):
            widget.configure(cursor="hand2")
            widget.bind(
                "<Button-1>", lambda _e, i=index: self._open_page(i),
            )

    def _page_marks(self, index: int, store: MarksStore) -> None:
        if len(store) == 0:
            theme.body(
                self._marks_body, "sin marcas", size=8,
                bg=SIDEBAR_BG, fg=NEUTRAL_500,
            ).pack(fill=tk.X, padx=(22, 0), pady=(0, 2))
            return
        for mark_id, mark in enumerate(store):
            self._mark_row(index, mark_id, mark)

    def _ocr_preview(self, index: int, mark_id: int) -> str | None:
        """The text read for a mark, or ``None`` when there is none yet."""
        if not 0 <= index < len(self._stores):
            return None
        entry = self._stores[index].get_ocr(mark_id)
        if entry is None or not entry.text.strip():
            return None
        return entry.text.replace("\n", " ").strip()

    def _mark_row(self, index: int, mark_id: int, mark: Mark) -> None:
        selected = self._selected == (index, mark_id)
        bg = ACCENT_200 if selected else SIDEBAR_BG
        row = tk.Frame(self._marks_body, bg=bg, padx=8, pady=4)
        row.pack(fill=tk.X, padx=(18, 0), pady=1)
        label = theme.body(
            row, f"{mark_id + 1} · {mark.w}×{mark.h}",
            size=8, bg=bg, fg=COLOR_TEXT,
        )
        label.pack(side=tk.LEFT)
        # A tick for the marks that already carry text, so «no se extrajo
        # nada» is visible here instead of two steps later.
        preview = self._ocr_preview(index, mark_id)
        badge = theme.body(
            row, "✓" if preview else "·", size=8, bg=bg,
            fg=COLOR_ACCENT if preview else NEUTRAL_500,
        )
        badge.pack(side=tk.LEFT, padx=(6, 0))
        Tooltip(
            badge,
            preview if preview else "Sin texto todavía · «Extraer texto»",
        )
        chip = tk.Frame(row, bg=mark.color, width=12, height=12)
        chip.pack(side=tk.RIGHT)
        for widget in (row, label, badge, chip):
            widget.configure(cursor="hand2")
            widget.bind(
                "<Button-1>",
                lambda _e, i=index, mid=mark_id: self._set_selected(i, mid),
            )

    def _toggle_page(self, index: int) -> str:
        if index in self._expanded_pages:
            self._expanded_pages.discard(index)
        else:
            self._expanded_pages.add(index)
        self._refresh_marks_list()
        return "break"

    def _open_page(self, index: int) -> None:
        self._expanded_pages.add(index)
        self._set_active_image(index)
        self._refresh_marks_list()

    # --- selected-section inspector -------------------------------------

    def _selected_mark_id(self) -> int | None:
        """The selected mark, when it belongs to the active page.

        Both view modes answer: the rail lists the same marks in each,
        so the inspector has to act on them in each.
        """
        if not self._selected or not self._stores:
            return None
        page, mark_id = self._selected
        if page != self._index:
            return None
        if not 0 <= mark_id < len(self._stores[page]):
            return None
        return mark_id

    def _active_size(self) -> tuple[int, int]:
        """Pixel size of the page the inspector is editing."""
        if self._marks_canvas is not None and self._marks_canvas._image is not None:
            return self._marks_canvas._image.size
        return self._strip_source(self._index).size

    def _apply_mark_geometry(self, mark_id: int, mark: Mark) -> bool:
        """Write a geometry through whichever renderer is on screen."""
        if self._marks_canvas is not None:
            return self._marks_canvas.update_mark(mark_id, mark)
        iw, ih = self._active_size()
        w = max(MARK_MIN_SIZE, min(mark.w, iw))
        h = max(MARK_MIN_SIZE, min(mark.h, ih))
        changed = self._stores[self._index].update_at(
            mark_id,
            replace(
                mark,
                x=max(0, min(mark.x, iw - w)), y=max(0, min(mark.y, ih - h)),
                w=w, h=h,
            ),
        )
        if changed:
            self._render_all_marks()
            self._update_continue_label()
        return changed

    def _reveal_selection(self) -> None:
        if self._marks_canvas is not None:
            self._marks_canvas.reveal_selected()
            return
        mark_id = self._selected_mark_id()
        if mark_id is None:
            return
        mark = self._stores[self._index].marks[mark_id]
        _, sy = self._image_to_strip(self._index, mark.x, mark.y)
        self._scroll_strip_to(sy)

    def _refresh_inspector(self) -> None:
        """Geometry and delete for the selected box, rebuilt only on change."""
        if self._inspector_body is None:
            return
        mark_id = self._selected_mark_id()
        if mark_id != self._inspector_for:
            # Destroying a focused entry fires <FocusOut>, which would
            # otherwise commit the outgoing mark's numbers onto the one
            # just selected.
            self._rebuilding_inspector = True
            try:
                for widget in list(self._inspector_body.winfo_children()):
                    widget.destroy()
            finally:
                self._rebuilding_inspector = False
            self._geom_vars = {}
            self._padding_var = None
            self._padding_label = None
            self._delete_btn = None
            self._inspector_for = mark_id
            if mark_id is None:
                theme.body(
                    self._inspector_body,
                    "Elige una marca de la lista o haz clic sobre ella "
                    "en la página.",
                    size=8, bg=SIDEBAR_BG, fg=NEUTRAL_600, wrap=210,
                ).pack(fill=tk.X)
                return
            self._build_inspector(mark_id)
            if mark_id is not None:
                self._sidebar.reveal(self._inspector_body)
        if mark_id is not None:
            self._sync_geom_vars(mark_id)

    def _build_inspector(self, mark_id: int) -> None:
        body = self._inspector_body
        total = len(self._stores[self._index])
        head = tk.Frame(body, bg=SIDEBAR_BG)
        head.pack(fill=tk.X, pady=(0, 8))
        theme.body(
            head, f"Marca {mark_id + 1}", size=9, bg=SIDEBAR_BG,
            fg=COLOR_TEXT, weight="bold",
        ).pack(side=tk.LEFT)
        theme.body(
            head, f"{mark_id + 1} / {total}", size=8,
            bg=SIDEBAR_BG, fg=NEUTRAL_600,
        ).pack(side=tk.RIGHT)

        grid = tk.Frame(body, bg=SIDEBAR_BG)
        grid.pack(fill=tk.X)
        grid.grid_columnconfigure(0, weight=1, uniform="geom")
        grid.grid_columnconfigure(1, weight=1, uniform="geom")
        for i, (key, label) in enumerate(
            (("x", "X"), ("y", "Y"), ("w", "Ancho"), ("h", "Alto")),
        ):
            self._geom_field(grid, key, label, i // 2, i % 2)
        self._build_padding_slider(body, mark_id)

        # The delete button goes directly under the fields: the rail is
        # short, and burying the destructive action below a paragraph of
        # help puts it off screen exactly when it is wanted.
        self._delete_btn = theme.button(
            body, "Eliminar marca   Supr", self._delete_selected,
            variant="secondary", size=8, padx=8, pady=7, anchor=tk.W,
            tooltip="Borra la marca junto con su OCR y su traducción",
        )
        self._delete_btn.pack(fill=tk.X, pady=(2, 0))
        theme.body(
            body,
            "Arrastra para mover · tiradores para redimensionar"
            if self._mode == MODE_ONE
            else "Cambia a «Una» para arrastrar los tiradores",
            size=8, bg=SIDEBAR_BG, fg=NEUTRAL_600, wrap=210,
        ).pack(fill=tk.X, pady=(6, 0))

    def _build_padding_slider(self, body: tk.Misc, mark_id: int) -> None:
        """The erase margin, on a slider rather than a number field.

        It is not geometry — it is how far past the box the cleaning
        reaches, and it is the rectangle the dashed line draws. A slider
        because the useful answer is found by looking at the page, not by
        knowing the number: drag until the dashed line clears the
        rotulado.
        """
        current = self._stores[self._index].marks[mark_id].erase_padding
        self._padding_label = theme.field_label(
            body, f"Margen · {current} px",
        )
        self._padding_label.pack(fill=tk.X, pady=(2, 2))
        self._padding_var = tk.IntVar(value=current)
        theme.slider(
            body,
            from_=MARK_PADDING_MIN, to=MARK_PADDING_MAX,
            variable=self._padding_var,
            command=self._on_padding_change,
            bg=SIDEBAR_BG,
        ).pack(fill=tk.X)
        ends = tk.Frame(body, bg=SIDEBAR_BG)
        ends.pack(fill=tk.X)
        theme.body(
            ends, str(MARK_PADDING_MIN), size=8,
            bg=SIDEBAR_BG, fg=NEUTRAL_600,
        ).pack(side=tk.LEFT)
        theme.body(
            ends, str(MARK_PADDING_MAX), size=8,
            bg=SIDEBAR_BG, fg=NEUTRAL_600,
        ).pack(side=tk.RIGHT)
        theme.body(
            body,
            "El recuadro punteado es lo que se borrará. Súbelo si el "
            "rótulo se sale de la caja.",
            size=8, bg=SIDEBAR_BG, fg=NEUTRAL_600, wrap=210,
        ).pack(fill=tk.X, pady=(4, 8))

    def _on_padding_change(self, value: str) -> None:
        if self._rebuilding_inspector:
            return
        mark_id = self._selected_mark_id()
        if mark_id is None or mark_id != self._inspector_for:
            return
        try:
            typed = int(float(value))
        except (TypeError, ValueError):
            return
        if self._padding_label is not None:
            self._padding_label.configure(text=f"Margen · {typed} px")
        current = self._stores[self._index].marks[mark_id]
        padding = self._padding_to_store(current, typed)
        if padding == current.padding:
            # The slider fires on every pixel of the drag, and again when
            # it lands back on the value it started from.
            return
        self._apply_mark_geometry(mark_id, replace(current, padding=padding))

    def _geom_field(
        self, parent: tk.Misc, key: str, label: str, row: int, column: int,
    ) -> None:
        cell = tk.Frame(parent, bg=SIDEBAR_BG)
        cell.grid(
            row=row, column=column, sticky="ew",
            padx=(0, 6) if column == 0 else 0, pady=(0, 6),
        )
        theme.field_label(cell, label).pack(fill=tk.X)
        var = tk.StringVar()
        field = theme.entry(cell, var, bg=COLOR_BG)
        field.pack(fill=tk.X, ipady=3)
        field.bind("<Return>", lambda _e: self._commit_geometry())
        field.bind("<FocusOut>", lambda _e: self._commit_geometry())
        field.bind("<Escape>", lambda _e: self._refresh_inspector())
        self._geom_vars[key] = var

    def _sync_geom_vars(self, mark_id: int) -> None:
        mark = self._stores[self._index].marks[mark_id]
        for key, value in (
            ("x", mark.x), ("y", mark.y), ("w", mark.w), ("h", mark.h),
        ):
            var = self._geom_vars.get(key)
            # Leave the field the user is editing alone.
            if var is not None and var.get() != str(value):
                var.set(str(value))

    def _commit_geometry(self) -> None:
        if self._rebuilding_inspector:
            return
        mark_id = self._selected_mark_id()
        if mark_id is None:
            return
        if mark_id != self._inspector_for:
            # The fields still belong to the previous selection.
            return
        current = self._stores[self._index].marks[mark_id]
        values: dict[str, int] = {}
        for key, fallback in (
            ("x", current.x), ("y", current.y),
            ("w", current.w), ("h", current.h),
        ):
            var = self._geom_vars.get(key)
            try:
                values[key] = int(float(var.get())) if var is not None else fallback
            except (TypeError, ValueError):
                values[key] = fallback
        # ``replace`` keeps the margin: it has its own control.
        updated = replace(
            current,
            x=values["x"], y=values["y"], w=values["w"], h=values["h"],
        )
        if self._apply_mark_geometry(mark_id, updated):
            self._reveal_selection()
        # The canvas clamps to the image, so echo back what it accepted.
        self._sync_geom_vars(mark_id)

    @staticmethod
    def _padding_to_store(current: Mark, typed: int) -> int | None:
        """What to write for a margin the user left at the default.

        The field shows the resolved number, so a mark that never chose
        a margin displays the default. Writing that number back would
        turn «not set» into «set to exactly the default», which reads
        the same on screen but changes the page's signature and sends it
        back through LaMa for nothing.
        """
        typed = max(0, min(int(typed), MARK_PADDING_MAX))
        if current.padding is None and typed == current.erase_padding:
            return None
        return typed

    def _delete_selected(self) -> None:
        mark_id = self._selected_mark_id()
        if mark_id is None:
            return
        store = self._stores[self._index]
        had_ocr = store.has_ocr(mark_id) or store.has_translation(mark_id)
        if self._marks_canvas is not None:
            removed = self._marks_canvas.delete_mark(mark_id)
        else:
            removed = store.remove_at(mark_id)
            self._render_all_marks()
        if removed is None:
            return
        self._selected = None
        self._update_continue_label()
        self._refresh_marks_list()
        self._refresh_inspector()
        extra = " (y su OCR/traducción)" if had_ocr else ""
        self._status.set(f"Marca {mark_id + 1} eliminada{extra}", "info")

    def _on_geometry_drag(self, mark_id: int, mark: Mark) -> None:
        """Live read-out while a box is being dragged or resized."""
        self._status.set(
            f"Marca {mark_id + 1} · {mark.x},{mark.y} · {mark.w}×{mark.h}",
            "info",
        )

    def _nudge_selected(self, dx: int, dy: int, *, resize: bool) -> str | None:
        mark_id = self._selected_mark_id()
        if mark_id is None or self._typing_in_field():
            return None
        if self._marks_canvas is not None:
            self._marks_canvas.nudge(dx, dy, resize=resize)
        else:
            # The clamping rules belong to the canvas; the strip has no
            # canvas of its own, so borrow them rather than restate them.
            mark = self._stores[self._index].marks[mark_id]
            iw, ih = self._active_size()
            updated = (
                MarksCanvas._resized(mark, "se", dx, dy, iw, ih)
                if resize
                else MarksCanvas._moved(mark, dx, dy, iw, ih)
            )
            self._apply_mark_geometry(mark_id, updated)
        self._reveal_selection()
        return "break"

    # --- pipeline state -------------------------------------------------

    def _build_pipeline_sections(self) -> None:
        body = self._sidebar.section("Extracción en curso")

        self._meter_ocr, self._meter_ocr_count = self._meter_row(
            body, "OCR", "Tesseract", COLOR_ACCENT,
        )
        self._pipeline_detail = theme.body(
            body, "Preparando…", size=8, bg=SIDEBAR_BG,
            fg=NEUTRAL_600, wrap=210,
        )
        self._pipeline_detail.pack(fill=tk.X, pady=(4, 0))

        self._sidebar.section_divider()
        log_body = self._sidebar.section("Registro")
        self._log_label = theme.body(
            log_body, "\n".join(self._log_lines) or "—",
            size=8, bg=SIDEBAR_BG, fg=NEUTRAL_700, wrap=210,
        )
        self._log_label.pack(fill=tk.X)

        self._sidebar.set_footer(
            "Cancelar proceso", self._cancel_pipeline,
            hint="Lo hecho hasta ahora se conserva",
            variant="secondary",
        )

    def _meter_row(
        self, parent: tk.Misc, name: str, engine: str, color: str,
    ) -> tuple[theme.Meter, tk.Label]:
        head = tk.Frame(parent, bg=SIDEBAR_BG)
        head.pack(fill=tk.X, pady=(0, 5))
        theme.body(
            head, name, size=8, bg=SIDEBAR_BG, fg=COLOR_TEXT, weight="bold",
        ).pack(side=tk.LEFT)
        theme.body(
            head, f" · {engine}", size=8, bg=SIDEBAR_BG, fg=NEUTRAL_600,
        ).pack(side=tk.LEFT)
        count = theme.body(head, "0 / 0", size=8, bg=SIDEBAR_BG, fg=NEUTRAL_600)
        count.pack(side=tk.RIGHT)
        meter = theme.Meter(parent, height=6, color=color)
        meter.pack(fill=tk.X, pady=(0, 12))
        return meter, count

    def _push_log(self, message: str) -> None:
        stamp = time.strftime("%H:%M")
        self._log_lines.insert(0, f"{stamp} · {message}")
        del self._log_lines[LOG_LINES:]
        if self._log_label is not None:
            self._log_label.configure(text="\n".join(self._log_lines))

    # ------------------------------------------------------------------
    # Mode handling
    # ------------------------------------------------------------------

    def _set_mode_all(self) -> None:
        if self._mode == MODE_ALL:
            return
        self._mode = MODE_ALL
        self._teardown_canvas()
        self._render_strip()
        self._update_toolbar()
        self._refresh_marks_list()
        # The inspector's help line differs per mode, so force a rebuild
        # even when the same mark stays selected across the switch.
        self._inspector_for = -1
        self._refresh_inspector()

    def _set_mode_one(self) -> None:
        if self._mode == MODE_ONE:
            return
        self._mode = MODE_ONE
        self._teardown_canvas()
        self._build_single_canvas()
        self._load_current()
        self._update_toolbar()
        self._refresh_marks_list()
        self._inspector_for = -1
        self._refresh_inspector()

    def _teardown_canvas(self) -> None:
        for w in self._host.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self._canvas = None
        self._scrollbar = None
        self._marks_canvas = None
        self._strip_layout = []
        self._strip_photos = {}
        self._strip_photo_ids = {}
        self._mark_ids_by_image = [[] for _ in self._items]
        self._mark_to_canvas = {}

    def _build_single_canvas(self) -> None:
        self._marks_canvas = MarksCanvas(
            self._host, store=self._stores[self._index],
            on_change=self._on_canvas_change,
            on_select=self._on_canvas_select,
            on_hover=self._on_hover,
            on_hover_leave=self._on_hover_leave,
            on_geometry=self._on_geometry_drag,
        )
        self._marks_canvas.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # Render: single image
    # ------------------------------------------------------------------

    def _load_current(self) -> None:
        if not self._items or self._marks_canvas is None:
            return
        path, image = self._items[self._index]
        self._marks_canvas.set_store(self._stores[self._index])
        self._clean_available[self._index] = has_clean(path)
        if self._viewing_clean and self._clean_available.get(self._index, False):
            display = self._clean_cache.get(self._index)
            if display is None:
                display = self._load_clean_image(path)
                if display is not None:
                    self._clean_cache[self._index] = display
            if display is not None:
                self._marks_canvas.set_image(display)
                self._marks_canvas.set_marks_visible(False)
            else:
                self._marks_canvas.set_image(image)
                self._marks_canvas.set_marks_visible(self._marks_visible)
                self._viewing_clean = False
        else:
            self._marks_canvas.set_image(image)
            self._marks_canvas.set_marks_visible(self._marks_visible)
        self._marks_canvas.load_marks()
        self._update_continue_label()
        self._update_toolbar()
        self._refresh_marks_list()
        self._refresh_inspector()
        self._set_window_context(path)
        self._status.set(
            f"Página {self._index + 1}/{len(self._items)} · {path.name}", "info",
        )

    def _set_window_context(self, path: Path) -> None:
        app = getattr(self.winfo_toplevel(), "_app", None)
        if app is not None and hasattr(app, "set_context"):
            app.set_context(f"{path.parent.name} · {path.name}")

    def _on_prev(self) -> None:
        if self._mode != MODE_ONE or self._index <= 0:
            return
        self._index -= 1
        self._selected = None
        self._load_current()

    def _on_next(self) -> None:
        if self._mode != MODE_ONE or self._index >= len(self._items) - 1:
            return
        self._index += 1
        self._selected = None
        self._load_current()

    def _on_zoom_in(self) -> None:
        if self._marks_canvas is not None:
            self._marks_canvas.zoom_in()
            self._update_zoom_controls()
        elif self._mode == MODE_ALL:
            self._set_strip_scale(self._strip_scale * ZOOM_STEP)

    def _on_zoom_out(self) -> None:
        if self._marks_canvas is not None:
            self._marks_canvas.zoom_out()
            self._update_zoom_controls()
        elif self._mode == MODE_ALL:
            self._set_strip_scale(self._strip_scale / ZOOM_STEP)

    def _on_zoom_reset(self) -> None:
        self._on_fit_window()

    def _on_fit_window(self) -> None:
        self._fit("window")

    def _on_fit_width(self) -> None:
        self._fit("width")

    def _on_fit_height(self) -> None:
        self._fit("height")

    def _fit(self, kind: str) -> None:
        """Both view modes answer the same three fit buttons."""
        if self._marks_canvas is not None:
            if kind == "width":
                self._marks_canvas.fit_width()
            elif kind == "height":
                self._marks_canvas.fit_height()
            else:
                self._marks_canvas.fit_to_window()
            self._update_zoom_controls()
        elif self._mode == MODE_ALL:
            self._strip_fit(kind)

    def _update_zoom_controls(self) -> None:
        """Keep the percentage honest and grey out the unreachable ends."""
        if self._mode == MODE_ONE and self._marks_canvas is not None:
            percent = self._marks_canvas.zoom_percent()
            can_in = self._marks_canvas.can_zoom_in()
            can_out = self._marks_canvas.can_zoom_out()
        elif self._mode == MODE_ALL and self._canvas is not None:
            percent = self._strip_zoom_percent()
            can_in = self._strip_scale < MAX_EFFECTIVE_SCALE - 1e-4
            can_out = self._strip_scale > MIN_EFFECTIVE_SCALE + 1e-4
        else:
            for key in ("out", "reset", "in"):
                self._zoom_bar.set_enabled(key, False)
            for key in ("window", "width", "height"):
                self._fit_bar.set_enabled(key, False)
            self._zoom_bar.set_text("reset", "—")
            return
        self._zoom_bar.set_enabled("reset", True)
        for key in ("window", "width", "height"):
            self._fit_bar.set_enabled(key, True)
        self._zoom_bar.set_text("reset", f"{percent}%")
        self._zoom_bar.set_enabled("in", can_in)
        self._zoom_bar.set_enabled("out", can_out)

    # ------------------------------------------------------------------
    # Render: strip
    # ------------------------------------------------------------------

    def _render_strip(self) -> None:
        canvas_frame = tk.Frame(self._host, bg=CANVAS_BG)
        canvas_frame.pack(side=tk.TOP, expand=True, fill=tk.BOTH)
        self._canvas = tk.Canvas(
            canvas_frame, bg=CANVAS_BG, highlightthickness=0, bd=0,
        )
        self._scrollbar = tk.Scrollbar(
            canvas_frame, orient=tk.VERTICAL, command=self._canvas.yview,
        )
        # Every scroll — wheel, scrollbar, drag, programmatic — arrives
        # here, which is what tells the strip to re-rasterise its band.
        self._canvas.configure(
            yscrollcommand=self._on_strip_yscroll,
            xscrollcommand=self._on_strip_xscroll,
        )
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        self._canvas.bind("<ButtonPress-1>", self._strip_press)
        self._canvas.bind("<B1-Motion>", self._strip_drag)
        self._canvas.bind("<ButtonRelease-1>", self._strip_release)
        self._canvas.bind("<Motion>", self._strip_motion)
        self._canvas.bind("<Button-3>", self._strip_right)
        self._canvas.bind("<Shift-ButtonPress-1>", self._strip_pan_press)
        self._canvas.bind("<Shift-B1-Motion>", self._strip_pan_drag)
        self._canvas.bind("<Shift-ButtonRelease-1>", self._strip_pan_release)
        self._canvas.bind("<ButtonPress-2>", self._strip_pan_press)
        self._canvas.bind("<B2-Motion>", self._strip_pan_drag)
        self._canvas.bind("<ButtonRelease-2>", self._strip_pan_release)
        self._canvas.bind("<Control-MouseWheel>", self._strip_ctrl_wheel)
        self._canvas.bind("<Configure>", self._strip_configure)
        self._canvas.bind_all("<MouseWheel>", self._strip_mousewheel)

        self._marks_canvas = None
        self._strip_photos = {}
        self._strip_photo_ids = {}
        self._mark_ids_by_image = [[] for _ in self._items]
        self._mark_to_canvas = {}

        self._layout_strip()
        self._draw_strip()
        self._status.set(
            f"{len(self._items)} página(s) · desplázate para recorrerlas", "info",
        )

    # --- strip geometry -------------------------------------------------

    def _strip_source(self, idx: int) -> Image.Image:
        """The bitmap page ``idx`` is drawn from — clean one if showing."""
        path, img = self._items[idx]
        if not (self._viewing_clean and self._clean_available.get(idx, False)):
            return img
        cached = self._clean_cache.get(idx)
        if cached is None:
            cached = self._load_clean_image(path)
            if cached is not None:
                self._clean_cache[idx] = cached
        return cached if cached is not None else img

    def _strip_max_size(self) -> tuple[int, int]:
        """Widest and tallest page, in real pixels."""
        max_w = max_h = 1
        for idx in range(len(self._items)):
            w, h = self._strip_source(idx).size
            max_w = max(max_w, w)
            max_h = max(max_h, h)
        return max_w, max_h

    def _clamp_strip_scale(self, scale: float) -> float:
        return max(MIN_EFFECTIVE_SCALE, min(MAX_EFFECTIVE_SCALE, scale))

    def _layout_strip(self) -> None:
        """Place every page in strip coordinates at the current scale.

        Pages are centred on the widest one so a chapter that mixes
        portrait scans with a wide spread reads down a single axis —
        the single-page view has always centred, and the strip looked
        broken next to it.
        """
        if self._canvas is None or not self._items:
            self._strip_layout = []
            self._strip_content = (1, 1)
            return
        cw = max(self._canvas.winfo_width(), 1)
        ch = max(self._canvas.winfo_height(), 1)
        max_w, max_h = self._strip_max_size()

        if self._strip_fit_pending and cw > 1 and ch > 1:
            self._strip_fit_pending = False
            window = min(cw / max_w, ch / max_h, 1.0)
            # A webtoon strip fitted whole is an unreadable sliver, so
            # open on the width instead — same rule as a single page.
            self._strip_scale = (
                cw / max_w if window < TALL_PAGE_FIT_LIMIT else window
            )
        self._strip_scale = self._clamp_strip_scale(self._strip_scale)
        scale = self._strip_scale

        content_w = max(cw, int(round(max_w * scale)))
        layout: list[tuple[float, float, int, int]] = []
        y = 0.0
        for idx in range(len(self._items)):
            iw, ih = self._strip_source(idx).size
            sw = max(1, int(round(iw * scale)))
            sh = max(1, int(round(ih * scale)))
            layout.append(((content_w - sw) / 2.0, y, sw, sh))
            y += sh
        self._strip_layout = layout
        self._strip_content = (content_w, max(1, int(round(y))))
        self._canvas.configure(scrollregion=(0, 0, content_w, self._strip_content[1]))

        # The opening fit is only decided once the canvas has a real
        # size, well after the toolbar was first drawn — without this the
        # strip would keep reporting the placeholder 100 %.
        if abs(scale - self._notified_strip_scale) > 1e-6:
            self._notified_strip_scale = scale
            self._update_zoom_controls()

    def _draw_strip(self, *, fast: bool = False) -> None:
        """Rasterise only the band of the strip the canvas can show.

        A chapter of webtoon strips is hundreds of megapixels; scaling
        it whole would be gigabytes of bitmap for the two page slices
        actually on screen.
        """
        if self._canvas is None or not self._strip_layout:
            return
        cw = max(self._canvas.winfo_width(), 1)
        ch = max(self._canvas.winfo_height(), 1)
        top = self._canvas.canvasy(0)
        left = self._canvas.canvasx(0)
        bottom, right = top + ch, left + cw
        scale = self._strip_scale
        visible: set[int] = set()

        for idx, (x0, y0, sw, sh) in enumerate(self._strip_layout):
            vx0, vy0 = max(x0, left), max(y0, top)
            vx1, vy1 = min(x0 + sw, right), min(y0 + sh, bottom)
            if vx1 <= vx0 or vy1 <= vy0:
                continue
            src = self._strip_source(idx)
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
            self._strip_photos[idx] = photo
            px, py = x0 + sx0 * scale, y0 + sy0 * scale
            item = self._strip_photo_ids.get(idx)
            if item is None:
                item = self._canvas.create_image(
                    px, py, image=photo, anchor=tk.NW, tags=("page",),
                )
                self._strip_photo_ids[idx] = item
            else:
                self._canvas.itemconfigure(item, image=photo)
                self._canvas.coords(item, px, py)
            self._canvas.tag_lower(item)
            visible.add(idx)

        for idx in [i for i in self._strip_photo_ids if i not in visible]:
            self._canvas.delete(self._strip_photo_ids.pop(idx))
            self._strip_photos.pop(idx, None)
        self._render_all_marks()

    def _on_strip_yscroll(self, first: str, last: str) -> None:
        if self._scrollbar is not None:
            self._scrollbar.set(first, last)
        self._schedule_strip_draw()

    def _on_strip_xscroll(self, _first: str, _last: str) -> None:
        self._schedule_strip_draw()

    def _schedule_strip_draw(self) -> None:
        """Coalesce the redraws a single wheel notch can trigger."""
        if self._strip_draw_pending or self._mode != MODE_ALL:
            return
        self._strip_draw_pending = True
        self.after_idle(self._strip_draw_now)

    def _strip_draw_now(self) -> None:
        self._strip_draw_pending = False
        if self._mode == MODE_ALL and self._canvas is not None:
            try:
                self._draw_strip()
            except tk.TclError:
                pass

    def _strip_configure(self, _event: tk.Event) -> None:
        # Laying out is cheap (page sizes only); rasterising is not, so
        # that half waits for the resize drag to stop producing events.
        self._layout_strip()
        self._schedule_strip_draw()

    def _total_strip_height(self) -> int:
        return self._strip_content[1]

    # --- strip zoom ------------------------------------------------------

    def _strip_zoom_percent(self) -> int:
        return max(1, int(round(self._strip_scale * 100)))

    def _set_strip_scale(
        self, scale: float, *, focus: tuple[int, int] | None = None,
    ) -> None:
        """Change the strip's scale, holding a point of the page still.

        ``focus`` is a canvas pixel (the cursor for Ctrl+wheel, the
        middle of the view for the ± buttons).
        """
        if self._canvas is None:
            return
        scale = self._clamp_strip_scale(scale)
        old = self._strip_scale
        if abs(scale - old) < 1e-6 or old <= 0:
            return
        cw = max(self._canvas.winfo_width(), 1)
        ch = max(self._canvas.winfo_height(), 1)
        fx, fy = focus if focus is not None else (cw // 2, ch // 2)
        # Where the anchor sits in unscaled strip units.
        anchor_y = self._canvas.canvasy(fy) / old
        anchor_x = self._canvas.canvasx(fx) / old

        self._strip_scale = scale
        self._strip_fit_pending = False
        self._layout_strip()
        content_w, content_h = self._strip_content
        self._canvas.yview_moveto(
            max(0.0, anchor_y * scale - fy) / max(1, content_h),
        )
        self._canvas.xview_moveto(
            max(0.0, anchor_x * scale - fx) / max(1, content_w),
        )
        self._draw_strip()
        self._update_zoom_controls()

    def _strip_fit(self, kind: str) -> None:
        if self._canvas is None:
            return
        cw = max(self._canvas.winfo_width(), 1)
        ch = max(self._canvas.winfo_height(), 1)
        max_w, max_h = self._strip_max_size()
        if kind == "width":
            target = cw / max_w
        elif kind == "height":
            target = ch / max_h
        else:
            target = min(cw / max_w, ch / max_h, 1.0)
        self._set_strip_scale(target)

    def _strip_ctrl_wheel(self, event: tk.Event) -> str:
        step = ZOOM_STEP if event.delta > 0 else 1.0 / ZOOM_STEP
        self._set_strip_scale(
            self._strip_scale * step, focus=(event.x, event.y),
        )
        return "break"

    # --- strip coordinates ----------------------------------------------

    def _render_all_marks(self) -> None:
        for ids in self._mark_ids_by_image:
            for mid in ids:
                self._canvas.delete(mid)
        self._mark_ids_by_image = [[] for _ in self._items]
        self._mark_to_canvas = {}
        if not self._marks_visible or self._viewing_clean:
            return
        for img_idx in range(len(self._strip_layout)):
            for mark_id, mark in enumerate(self._stores[img_idx]):
                is_selected = self._selected == (img_idx, mark_id)
                outline = COLOR_ACCENT if is_selected else mark.color
                width = MARK_STROKE_WIDTH + (2 if is_selected else 0)
                x1, y1 = self._image_to_strip(img_idx, mark.x, mark.y)
                x2, y2 = self._image_to_strip(
                    img_idx, mark.x + mark.w, mark.y + mark.h,
                )
                if is_selected:
                    # The erased area, on the selection only — see the
                    # canvas for why it is not drawn on every mark.
                    pad = mark.erase_padding
                    px1, py1 = self._image_to_strip(
                        img_idx, mark.x - pad, mark.y - pad,
                    )
                    px2, py2 = self._image_to_strip(
                        img_idx, mark.x + mark.w + pad, mark.y + mark.h + pad,
                    )
                    # Only tracked for deletion; the hit map keeps pointing
                    # at the solid box, which is what a click means.
                    self._mark_ids_by_image[img_idx].append(
                        self._canvas.create_rectangle(
                            px1, py1, px2, py2,
                            outline=outline, width=1, fill="",
                            dash=MARK_PAD_DASH,
                            tags=("pad", f"img_{img_idx}", f"pad_{mark_id}"),
                        ),
                    )
                rid = self._canvas.create_rectangle(
                    x1, y1, x2, y2,
                    outline=outline, width=width, fill="",
                    tags=("mark", f"img_{img_idx}", f"mark_{mark_id}"),
                )
                self._mark_ids_by_image[img_idx].append(rid)
                self._mark_to_canvas[(img_idx, mark_id)] = rid

    def _image_to_strip(self, img_idx: int, x: float, y: float) -> tuple[float, float]:
        if not 0 <= img_idx < len(self._strip_layout):
            return 0.0, 0.0
        x0, y0, _, _ = self._strip_layout[img_idx]
        return x0 + x * self._strip_scale, y0 + y * self._strip_scale

    def _strip_to_image(
        self, sx: float, sy: float, img_idx: int | None = None,
    ) -> tuple[int, int, int] | None:
        """Map strip coordinates to ``(page, x, y)`` in real image pixels.

        With ``img_idx`` given the point is clamped into that page, which
        is what a drag that started on it should do even once the pointer
        wanders onto the neighbour.
        """
        if img_idx is None:
            img_idx = self._hit_test_image(sy)
            if img_idx is None:
                return None
        if not 0 <= img_idx < len(self._strip_layout):
            return None
        x0, y0, _, _ = self._strip_layout[img_idx]
        iw, ih = self._strip_source(img_idx).size
        ix = int(round((sx - x0) / self._strip_scale))
        iy = int(round((sy - y0) / self._strip_scale))
        return img_idx, max(0, min(ix, iw)), max(0, min(iy, ih))

    def _strip_mousewheel(self, event: tk.Event) -> None:
        if self._edit_state or self._mode != MODE_ALL or self._canvas is None:
            return
        delta = -1 if event.delta > 0 else 1
        self._canvas.yview_scroll(delta, "units")

    def _hit_test_image(self, strip_y: float) -> int | None:
        for idx, (_, y0, _, sh) in enumerate(self._strip_layout):
            if y0 <= strip_y < y0 + sh:
                return idx
        return None

    def _hit_test_mark(self, sx: float, sy: float) -> tuple[int, int] | None:
        located = self._strip_to_image(sx, sy)
        if located is None:
            return None
        img_idx, ix, iy = located
        for mark_id, mark in enumerate(self._stores[img_idx]):
            if mark.x <= ix <= mark.x + mark.w and mark.y <= iy <= mark.y + mark.h:
                return (img_idx, mark_id)
        return None

    def _strip_press(self, event: tk.Event) -> None:
        if self._viewing_clean:
            return
        sx = self._canvas.canvasx(event.x)
        sy = self._canvas.canvasy(event.y)
        if self._edit_state:
            located = self._strip_to_image(sx, sy)
            if located is None:
                return
            idx = located[0]
            self._set_active_image(idx, scroll=False)
            preview = self._canvas.create_rectangle(
                sx, sy, sx, sy,
                outline=self._current_color,
                width=MARK_STROKE_WIDTH, dash=(4, 2),
                tags=("preview",),
            )
            self._drag = {
                "image_index": idx,
                "start_x": sx, "start_y": sy,
                "preview_id": preview,
            }
            return
        clicked = self._hit_test_mark(sx, sy)
        if clicked is not None:
            self._set_selected(*clicked, reveal=False)
        else:
            located = self._strip_to_image(sx, sy)
            if located is not None:
                self._set_active_image(located[0], scroll=False)

    def _strip_drag(self, event: tk.Event) -> None:
        if self._drag is None:
            return
        self._canvas.coords(
            self._drag["preview_id"],
            self._drag["start_x"], self._drag["start_y"],
            self._canvas.canvasx(event.x), self._canvas.canvasy(event.y),
        )

    def _strip_release(self, event: tk.Event) -> None:
        if self._drag is None:
            return
        idx = self._drag["image_index"]
        self._canvas.delete(self._drag["preview_id"])
        start = (self._drag["start_x"], self._drag["start_y"])
        self._drag = None

        begin = self._strip_to_image(start[0], start[1], idx)
        end = self._strip_to_image(
            self._canvas.canvasx(event.x), self._canvas.canvasy(event.y), idx,
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
        mark_id = self._stores[idx].add(mark)
        self._set_active_image(idx, scroll=False)
        self._set_selected(idx, mark_id, reveal=False)
        self._render_all_marks()
        self._update_continue_label()
        self._refresh_marks_list()

    def _strip_motion(self, event: tk.Event) -> None:
        self._hovered = self._hit_test_mark(
            self._canvas.canvasx(event.x), self._canvas.canvasy(event.y),
        )

    def _strip_right(self, _event: tk.Event) -> None:
        if not self._edit_state:
            return
        if self._drag is not None:
            self._canvas.delete(self._drag["preview_id"])
            self._drag = None

    def _strip_pan_press(self, event: tk.Event) -> None:
        self._canvas.scan_mark(event.x, event.y)

    def _strip_pan_drag(self, event: tk.Event) -> None:
        self._canvas.scan_dragto(event.x, event.y, gain=1)
        self._schedule_strip_draw()

    def _strip_pan_release(self, _event: tk.Event) -> None:
        self._schedule_strip_draw()

    # ------------------------------------------------------------------
    # Selection / edit / visibility / undo
    # ------------------------------------------------------------------

    def _on_canvas_select(self, mark_id: int) -> None:
        if self._mode != MODE_ONE:
            return
        self._selected = (self._index, mark_id)
        self._refresh_marks_list()
        self._refresh_inspector()

    def _on_canvas_change(self) -> None:
        self._update_continue_label()
        self._refresh_marks_list()
        self._refresh_inspector()
        self._update_zoom_controls()

    def _on_hover(self, mark_id: int, text: str) -> None:
        return

    def _on_hover_leave(self) -> None:
        return

    def _set_active_image(self, img_idx: int, *, scroll: bool = True) -> None:
        if not 0 <= img_idx < len(self._items):
            return
        changed = img_idx != self._index
        self._index = img_idx
        self._expanded_pages.add(img_idx)
        if self._marks_canvas is not None and self._mode == MODE_ONE:
            self._load_current()
            return
        # In strip mode the pages are one long scroll, so picking one
        # from the rail has to take the view there — but a click *on* a
        # page is already there and must not jump to its top.
        if scroll:
            self._scroll_strip_to_page(img_idx)
        if changed:
            self._refresh_marks_list()
            self._refresh_inspector()

    def _set_selected(
        self, img_idx: int, mark_id: int, *, reveal: bool = True,
    ) -> None:
        if not 0 <= img_idx < len(self._stores):
            return
        if not 0 <= mark_id < len(self._stores[img_idx]):
            return
        turning = img_idx != self._index
        self._index = img_idx
        self._expanded_pages.add(img_idx)
        self._selected = (img_idx, mark_id)
        if self._mode == MODE_ONE:
            if turning:
                # The rail lists every page, so a mark can be picked from
                # one that is not on screen: turn to it before selecting.
                self._load_current()
            if self._marks_canvas is not None:
                self._marks_canvas.select(mark_id)
                if reveal:
                    self._marks_canvas.reveal_selected()
        else:
            self._render_all_marks()
            if reveal:
                self._reveal_selection()
        self._refresh_marks_list()
        self._refresh_inspector()

    def _scroll_strip_to_page(self, img_idx: int) -> None:
        if not self._strip_layout or not 0 <= img_idx < len(self._strip_layout):
            return
        self._scroll_strip_to(self._strip_layout[img_idx][1], force=True)

    def _scroll_strip_to(
        self, y: float, *, margin: int = 40, force: bool = False,
    ) -> None:
        """Put strip coordinate ``y`` near the top of the visible band.

        Unless ``force``, a point already comfortably on screen is left
        where it is — revealing a mark should not shuffle the page under
        someone who can already see it.
        """
        if self._canvas is None:
            return
        total = self._total_strip_height()
        if total <= 0:
            return
        if not force:
            top = self._canvas.canvasy(0)
            bottom = top + self._canvas.winfo_height()
            if top + margin <= y <= bottom - margin:
                return
        self._canvas.yview_moveto(max(0.0, (y - margin) / total))

    def _toggle_edit(self) -> None:
        if self._viewing_clean or self._running:
            return
        self._edit_state = not self._edit_state
        if self._marks_canvas is not None:
            self._marks_canvas.set_edit_mode(self._edit_state)
        if self._canvas is not None:
            try:
                self._canvas.configure(
                    cursor="crosshair" if self._edit_state else "",
                )
            except Exception:
                pass
        if self._edit_btn is not None:
            theme.restyle_button(
                self._edit_btn, "ink" if self._edit_state else "outline",
            )
            self._edit_btn.configure(
                text="Editando   E" if self._edit_state else "Editar   E",
            )

    def _toggle_visibility(self) -> None:
        self._marks_visible = not self._marks_visible
        if self._marks_canvas is not None:
            self._marks_canvas.set_marks_visible(self._marks_visible)
        if self._mode == MODE_ALL:
            self._render_all_marks()
        if self._visibility_btn is not None:
            theme.restyle_button(
                self._visibility_btn,
                "outline" if self._marks_visible else "ink",
            )
            self._visibility_btn.configure(
                text="Ocultar   H" if self._marks_visible else "Mostrar   H",
            )

    def _undo(self) -> None:
        if self._marks_canvas is not None and self._mode == MODE_ONE:
            removed = self._marks_canvas.undo()
            if removed is not None:
                self._selected = None
                self._update_continue_label()
                self._refresh_marks_list()
            return
        for idx in range(len(self._stores) - 1, -1, -1):
            if len(self._stores[idx]) > 0:
                self._stores[idx].remove_last()
                if self._selected and self._selected[0] == idx:
                    self._selected = None
                self._render_all_marks()
                self._update_continue_label()
                self._refresh_marks_list()
                return

    def _clear_marks(self) -> None:
        target_idx = self._index
        if not 0 <= target_idx < len(self._stores):
            return
        if len(self._stores[target_idx]) == 0:
            return
        if not theme.confirm(
            self,
            "Limpiar marcas",
            f"Se borrarán todas las marcas de la página {target_idx + 1}.",
            confirm_label="Borrar las marcas",
        ):
            return
        if self._mode == MODE_ONE and self._marks_canvas is not None:
            self._marks_canvas.clear()
        else:
            self._stores[target_idx].clear()
            self._render_all_marks()
        self._selected = None
        self._update_continue_label()
        self._refresh_marks_list()

    # ------------------------------------------------------------------
    # Clean / original toggle
    # ------------------------------------------------------------------

    def _set_clean_mode(self, viewing_clean: bool) -> None:
        if self._viewing_clean == viewing_clean:
            return
        if viewing_clean and not any(self._clean_available.values()):
            self._status.set(
                "Todavía no hay versiones limpias: ejecuta el proceso", "info",
            )
            return
        # Both halves below redraw from scratch, which would drop the
        # user back at the top of the page. Comparing the two versions is
        # the whole point of the toggle, so the view is put back exactly
        # where it was.
        keep = self._capture_view()
        self._viewing_clean = viewing_clean
        if viewing_clean:
            self._edit_state = False
            if self._marks_canvas is not None:
                self._marks_canvas.set_edit_mode(False)
        if self._mode == MODE_ONE:
            self._load_current()
        else:
            self._teardown_canvas()
            self._render_strip()
        self._restore_view(keep)
        self._update_toolbar()
        self._update_button_states()

    def _capture_view(self) -> object:
        """Where the user is looking, so a redraw can put them back."""
        if self._mode == MODE_ONE:
            if self._marks_canvas is None:
                return None
            return self._marks_canvas.viewport()
        if self._canvas is None:
            return None
        return float(self._canvas.canvasx(0)), float(self._canvas.canvasy(0))

    def _restore_view(self, state: object) -> None:
        if state is None:
            return
        if self._mode == MODE_ONE:
            if self._marks_canvas is not None:
                self._marks_canvas.set_viewport(state)  # type: ignore[arg-type]
            return
        if self._canvas is None:
            return
        # The strip canvas was only just created, so its scrollregion is
        # still the placeholder one until the geometry manager has run.
        try:
            self._host.update_idletasks()
        except tk.TclError:
            return
        x, y = state  # type: ignore[misc]
        width, height = self._strip_content
        self._canvas.xview_moveto(max(0.0, min(1.0, x / max(width, 1))))
        self._canvas.yview_moveto(max(0.0, min(1.0, y / max(height, 1))))
        self._schedule_strip_draw()

    def _refresh_clean_availability(self) -> None:
        for idx, (path, _) in enumerate(self._items):
            self._clean_available[idx] = has_clean(path)

    def _load_clean_image(self, path: Path) -> Image.Image | None:
        cp = find_clean(path)
        if cp is None:
            return None
        try:
            with Image.open(cp) as img:
                img.load()
                return img.copy()
        except Exception as exc:
            log.exception("No se pudo cargar limpia %s: %s", cp, exc)
            return None

    # ------------------------------------------------------------------
    # Continue / Back / Pipeline
    # ------------------------------------------------------------------

    def _on_continue(self) -> None:
        if self._pipeline.is_running():
            return
        if self.workflow.total_marks() == 0:
            self._status.set(
                "Marca al menos una sección antes de continuar.", "info",
            )
            return
        for s in self._stores:
            s.save()
        self.workflow.continue_step()  # triggers run_pipeline

    def _extract_text(self) -> None:
        """«Extraer texto»: OCR the marks that have none, and stay here."""
        pending = self._pipeline.pending_ocr(self._stores)
        if pending == 0:
            self._status.set(
                "Todas las marcas ya tienen texto. Usa «Re-extraer» para "
                "volver a leerlas.", "info",
            )
            return
        self.run_pipeline()

    def _extract_text_forced(self) -> None:
        """«Re-extraer»: read every mark again, reviewed text included."""
        total = self.workflow.total_marks()
        if total == 0:
            self._status.set("No hay marcas que leer", "info")
            return
        done = total - self._pipeline.pending_ocr(self._stores)
        if done and not theme.confirm(
            self,
            "Re-extraer el texto",
            f"{done} de {total} marca(s) ya tienen texto.\n"
            "Volver a leerlas reemplazará lo que haya, incluidas las "
            "correcciones hechas a mano.",
            confirm_label="Volver a leerlas",
        ):
            return
        self.run_pipeline(force_ocr=True)

    def run_pipeline(
        self, *, advance: bool = False, force_ocr: bool = False,
    ) -> None:
        """Read the pending marks, from the continue button or the rail.

        The workflow controller passes ``advance`` when the user pressed
        «Continuar proceso»: the step moves on by itself once the text is
        in. The two rail buttons leave it off so the text can be checked
        here first.
        """
        if self._pipeline.is_running():
            return
        if not self._engine.is_available():
            self._status.set(
                "Tesseract no está disponible: no se puede extraer el texto. "
                "Revisa logs/app.log para ver dónde se buscó.", "error",
            )
            return
        for s in self._stores:
            s.save()
        self._running = True
        self._advance_after = advance
        self._edit_state = False
        self._log_lines = []
        self._build_sidebar_sections()
        self._progress_rule.pack(
            side=tk.TOP, fill=tk.X, before=self._stage,
        )
        self._progress_rule.set(0.0)
        self._pipeline.run(
            items=self._items,
            stores=self._stores,
            ocr_lang="eng",
            force_ocr=force_ocr,
        )

    def _on_pipeline_step_start(self, step: int, total: int, label: str) -> None:
        self._status.set(f"OCR: {label}", "working")

    def _on_pipeline_step_progress(
        self, step: int, current: int, total: int, message: str,
    ) -> None:
        fraction = (current / total) if total else 0.0
        if self._meter_ocr is not None:
            self._meter_ocr.set(fraction)
        if self._meter_ocr_count is not None:
            self._meter_ocr_count.configure(text=f"{current} / {total}")
        self._progress_rule.set(fraction)
        if self._pipeline_detail is not None:
            self._pipeline_detail.configure(text=message)
        self._push_log(message)
        self._status.set(message, "working")

    def _on_pipeline_step_done(self, step: int, success: bool, message: str) -> None:
        if self._meter_ocr is not None:
            self._meter_ocr.set(1.0 if success else 0.0)
        self._push_log(message)

    def _on_pipeline_overall_done(self, success: bool, message: str) -> None:
        self._running = False
        advance = self._advance_after
        self._advance_after = False
        try:
            self._progress_rule.pack_forget()
        except Exception:
            pass
        self._refresh_clean_availability()
        if success and advance:
            # Hand the cleaning over before the view is destroyed: the
            # queue belongs to the App, so it keeps running through the
            # rest of the workflow.
            queued = self._start_background_clean()
            self._status.set(
                f"{message} · limpiando {queued} página(s) en segundo plano"
                if queued else message,
                "success",
            )
            from src.workflow.controller import WorkflowStep
            self.workflow.go_to(WorkflowStep.OCR_REVIEW)
            return
        if success:
            # Extraction on its own: report the tally and stay put, so
            # the text can be checked in the rail before continuing.
            read = sum(
                1 for s in self._stores for e in s.ocr_results.values()
                if e.text.strip()
            )
            message = f"{message}: {read} de {self.workflow.total_marks()} " \
                      "marca(s) con texto"
        self._status.set(message, "success" if success else "error")
        self._build_sidebar_sections()
        self._refresh_marks_list(force=True)
        self._update_button_states()

    def _start_background_clean(self) -> int:
        """Give the App every page whose clean version is missing or stale."""
        app = getattr(self.workflow, "app", None)
        if app is None or not hasattr(app, "start_background_clean"):
            return 0
        try:
            return app.start_background_clean()
        except Exception as exc:
            log.exception("No se pudo lanzar la limpieza: %s", exc)
            return 0

    def on_clean_page_done(self, image_index: int, success: bool) -> None:
        """A page finished cleaning while step 2 was still on screen.

        Happens when the user comes back to «Marcar» with the queue
        still running; the page has to pick up its new clean version
        without throwing away where they were looking.
        """
        if not success:
            return
        self._clean_cache.pop(image_index, None)
        self._clean_available[image_index] = True
        self._update_toolbar()
        self._update_button_states()
        if not self._viewing_clean:
            return
        if self._mode == MODE_ONE and image_index != self._index:
            return
        keep = self._capture_view()
        if self._mode == MODE_ONE:
            self._load_current()
        else:
            self._teardown_canvas()
            self._render_strip()
        self._restore_view(keep)

    def _cancel_pipeline(self) -> None:
        self._pipeline.cancel()
        self._running = False
        try:
            self._progress_rule.pack_forget()
        except Exception:
            pass
        self._build_sidebar_sections()
        self._update_button_states()

    def _on_back(self) -> None:
        self.workflow.back_step()

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _update_button_states(self) -> None:
        for btn in (self._edit_btn, self._visibility_btn):
            if btn is None:
                continue
            btn.configure(
                state=(tk.DISABLED if self._viewing_clean else tk.NORMAL),
            )
        any_marks = self.workflow.total_marks() > 0
        for btn in (self._undo_btn, self._clear_btn):
            if btn is None:
                continue
            btn.configure(state=(tk.NORMAL if any_marks else tk.DISABLED))
        can_ocr = any_marks and self._engine.is_available()
        for btn in (self._ocr_btn, self._reocr_btn):
            if btn is None:
                continue
            btn.configure(state=(tk.NORMAL if can_ocr else tk.DISABLED))
        self._update_continue_label()

    def _update_continue_label(self) -> None:
        if self._running:
            return
        total = self.workflow.total_marks()
        self._sidebar.set_footer_state(total > 0)
        if total == 0:
            self._sidebar.set_footer_hint(
                "Marca al menos una sección para continuar",
            )
        else:
            pending = self._pipeline.pending_ocr(self._stores)
            dirty = self.workflow.images_without_clean()
            detail = (
                f"OCR de {pending} sección(es)" if pending
                else "Todo el texto leído"
            )
            if dirty:
                detail += f" · {dirty} página(s) se limpian en segundo plano"
            self._sidebar.set_footer_hint(detail)

    def destroy(self) -> None:  # type: ignore[override]
        for sequence in (
            "<KeyPress-e>", "<KeyPress-h>", "<KeyPress-z>", "<KeyPress-v>",
            "<MouseWheel>", "<Delete>",
            "<Left>", "<Right>", "<Up>", "<Down>",
            "<Shift-Left>", "<Shift-Right>", "<Shift-Up>", "<Shift-Down>",
        ):
            try:
                self.unbind_all(sequence)
            except Exception:
                pass
        try:
            self._pipeline.detach()
        except Exception:
            pass
        try:
            self._pipeline.cancel()
        except Exception:
            pass
        super().destroy()
