"""Persistent left rail — the spine of the four-step workflow.

Follows the mockups' 260 px rail (direction 3a), top to bottom:

* a ``PASO n DE 4`` kicker and the row of the step you are on — a
  numbered chip on an accent band; the other three stay hidden,
* the sections the active view contributes (marks, languages, the
  section inspector…),
* an optional engine-status block,
* and a footer pinned to the bottom holding the step's primary action
  plus a one-line consequence hint.

Views talk to the rail through :meth:`view_sections_frame` and the
``make_*`` helpers (kept from the previous layout) plus
:meth:`set_footer` for the anchored action.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from src.config import (
    ACCENT_200,
    ACCENT_700,
    BTN_FG,
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DIVIDER,
    COLOR_TEXT,
    NEUTRAL_500,
    NEUTRAL_600,
    NEUTRAL_700,
    SIDEBAR_BG,
    SIDEBAR_SECTION_PAD,
    SIDEBAR_VIEW_PAD,
    SIDEBAR_WIDTH,
)
from src.utils.logger import get_logger
from src.views import theme

log = get_logger("sidebar")

STEPS: tuple[tuple[str, str], ...] = (
    ("Inicio", "Cargar imágenes"),
    ("Marcar", "Secciones de texto"),
    ("Traducir", "Revisión OCR"),
    ("Render", "Exportar PNG"),
)


class _StepRow(tk.Frame):
    """One row of the step rail: chip + label + sub-label."""

    def __init__(self, master: tk.Misc, number: int, label: str, sub: str) -> None:
        super().__init__(master, bg=SIDEBAR_BG)
        self._number = number
        self._chip = tk.Label(
            self, text=str(number), font=theme.heading_font(8),
            width=2, height=1, bg=SIDEBAR_BG, fg=NEUTRAL_500,
            highlightthickness=1,
            highlightbackground=NEUTRAL_500, highlightcolor=NEUTRAL_500,
        )
        self._chip.pack(side=tk.LEFT, padx=(12, 11), pady=10)
        text = tk.Frame(self, bg=SIDEBAR_BG)
        text.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=10)
        self._label = tk.Label(
            text, text=label, font=theme.heading_font(9),
            bg=SIDEBAR_BG, fg=NEUTRAL_500, anchor=tk.W,
        )
        self._label.pack(fill=tk.X)
        self._sub = tk.Label(
            text, text=sub, font=theme.body_font(8),
            bg=SIDEBAR_BG, fg=NEUTRAL_500, anchor=tk.W,
        )
        self._sub.pack(fill=tk.X)

    def set_state(self, state: str) -> None:
        """``state`` is one of ``done``, ``active``, ``pending``."""
        if state == "active":
            bg, fg, sub_fg = COLOR_ACCENT, BTN_FG, ACCENT_200
            chip_bg, chip_fg, chip_border = COLOR_ACCENT, BTN_FG, BTN_FG
            chip_text = str(self._number)
        elif state == "done":
            bg, fg, sub_fg = SIDEBAR_BG, NEUTRAL_700, NEUTRAL_600
            chip_bg, chip_fg, chip_border = COLOR_TEXT, COLOR_BG, COLOR_TEXT
            chip_text = "✓"
        else:
            bg, fg, sub_fg = SIDEBAR_BG, NEUTRAL_500, NEUTRAL_500
            chip_bg, chip_fg, chip_border = SIDEBAR_BG, NEUTRAL_500, NEUTRAL_500
            chip_text = str(self._number)
        self.configure(bg=bg)
        for child in self.winfo_children():
            if child is not self._chip:
                child.configure(bg=bg)
        self._label.configure(bg=bg, fg=fg)
        self._sub.configure(bg=bg, fg=sub_fg)
        self._chip.configure(
            text=chip_text, bg=chip_bg, fg=chip_fg,
            highlightbackground=chip_border, highlightcolor=chip_border,
        )


class Sidebar(tk.Frame):
    """Fixed-width left rail, persistent across the four steps."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_home: Callable[[], None] | None = None,
        on_open_manga: Callable[[], None] | None = None,
        on_open_webcomic: Callable[[], None] | None = None,
        on_open_files: Callable[[], None] | None = None,
        on_open_recent: Callable[[], None] | None = None,
        on_open_translator: Callable[[], None] | None = None,
        ocr_status: str = "",
        ocr_available: bool = False,
        inpaint_available: bool = False,
        inpaint_status: str = "",
        recent_label: str | None = None,
    ) -> None:
        super().__init__(master, bg=SIDEBAR_BG, width=SIDEBAR_WIDTH)
        self.pack_propagate(False)
        self._on_home = on_home
        self._on_open_files = on_open_files
        self._on_open_recent = on_open_recent

        self._active: str = "home"
        self._nav_buttons: dict[str, tk.Button] = {}
        self._recent_label: str | None = recent_label
        self._step_rows: list[_StepRow] = []

        self._ocr_available = ocr_available
        self._ocr_status = ocr_status
        self._inpaint_available = inpaint_available
        self._inpaint_status = inpaint_status

        self._footer_primary: tk.Button | None = None
        self._footer_secondary: tk.Button | None = None
        self._footer_hint: tk.Label | None = None

        self._clean_band: tk.Frame | None = None
        self._clean_meter: theme.Meter | None = None
        self._clean_detail: tk.Label | None = None

        self._build_steps()
        self._build_footer()
        self._build_engines()
        self._build_view_sections()
        self._build_clean_band()
        self.set_step_indicator(1)

    # ---------------------------------------------------------------- build

    def _build_steps(self) -> None:
        """Only the current step is on screen; the rest are built but
        unpacked.

        The four rows cost ~185 px of rail, and the three the user is not
        on say nothing that the kicker's ``de 4`` does not. They are kept
        alive rather than rebuilt so :meth:`set_step_indicator` is a
        pack/forget and nothing has to re-measure.
        """
        header = tk.Frame(self, bg=SIDEBAR_BG)
        header.pack(side=tk.TOP, fill=tk.X)
        self._step_kicker = theme.kicker(header, "Paso", bg=SIDEBAR_BG)
        self._step_kicker.pack(
            fill=tk.X, padx=SIDEBAR_SECTION_PAD, pady=(14, 10),
        )
        host = tk.Frame(self, bg=SIDEBAR_BG)
        host.pack(side=tk.TOP, fill=tk.X)
        self._steps_host = host
        for index, (label, sub) in enumerate(STEPS, start=1):
            self._step_rows.append(_StepRow(host, index, label, sub))
        theme.rule(self, thickness=2, color=COLOR_DIVIDER).pack(
            side=tk.TOP, fill=tk.X, pady=(12, 12),
        )

    def _build_footer(self) -> None:
        """Bottom-anchored action area. Packed early so it always fits."""
        self._footer = tk.Frame(self, bg=SIDEBAR_BG)
        self._footer.pack(side=tk.BOTTOM, fill=tk.X)
        self._footer_rule = theme.rule(
            self._footer, thickness=2, color=COLOR_DIVIDER,
        )
        self._footer_body = tk.Frame(self._footer, bg=SIDEBAR_BG)

    def _build_engines(self) -> None:
        self._engines = tk.Frame(self, bg=SIDEBAR_BG)
        self._engines_body: tk.Frame | None = None

    def _build_view_sections(self) -> None:
        """The middle band, which scrolls when a step contributes more
        than fits — a chapter's mark list easily outruns the rail."""
        holder = tk.Frame(self, bg=SIDEBAR_BG)
        holder.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._sections_holder = holder
        self._scroll = tk.Canvas(
            holder, bg=SIDEBAR_BG, bd=0, highlightthickness=0, takefocus=0,
        )
        self._scrollbar = ttk.Scrollbar(
            holder, orient=tk.VERTICAL, command=self._scroll.yview,
            style="Rail.Vertical.TScrollbar",
        )
        self._scroll.configure(yscrollcommand=self._scrollbar.set)
        self._scroll.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._view_sections_frame = tk.Frame(self._scroll, bg=SIDEBAR_BG)
        self._scroll_window = self._scroll.create_window(
            SIDEBAR_VIEW_PAD, 0, window=self._view_sections_frame, anchor=tk.NW,
        )
        self._view_sections_frame.bind("<Configure>", self._on_sections_resize)
        self._scroll.bind("<Configure>", self._on_scroll_resize)
        # Take the wheel only while the pointer is over the rail, and
        # hand the previous binding back on the way out — the canvas
        # views bind the wheel application-wide for their own scrolling.
        self._prev_wheel: str = ""
        self._sync_after_id: str | None = None
        self.bind("<Enter>", self._grab_wheel, add="+")
        self.bind("<Leave>", self._release_wheel, add="+")

    # -------------------------------------------------------- clean band

    def _build_clean_band(self) -> None:
        """The one place that reports LaMa's background progress.

        It lives on the rail rather than in a view because the cleaning
        outlives the step that started it: the user is in «Traducir» —
        or already in «Render» — while it runs, and a chapter that comes
        out unclean with nothing having said so reads as a bug.
        """
        band = tk.Frame(self, bg=SIDEBAR_BG)
        inner = tk.Frame(band, bg=SIDEBAR_BG)
        inner.pack(fill=tk.X, padx=SIDEBAR_SECTION_PAD, pady=(0, 12))
        theme.kicker(inner, "Limpieza · LaMa", bg=SIDEBAR_BG).pack(
            fill=tk.X, pady=(0, 7),
        )
        self._clean_meter = theme.Meter(inner, height=6, color=COLOR_TEXT)
        self._clean_meter.pack(fill=tk.X)
        self._clean_detail = theme.body(
            inner, "", size=8, bg=SIDEBAR_BG, fg=NEUTRAL_600,
            wrap=SIDEBAR_WIDTH - 2 * SIDEBAR_SECTION_PAD,
        )
        self._clean_detail.pack(fill=tk.X, pady=(6, 0))
        theme.rule(band, thickness=2, color=COLOR_DIVIDER).pack(
            side=tk.BOTTOM, fill=tk.X, pady=(0, 12),
        )
        self._clean_band = band

    def set_clean_progress(
        self, done: int, total: int, label: str = "",
    ) -> None:
        """Show the background cleaning, or hide the band when idle."""
        band = self._clean_band
        if band is None:
            return
        if total <= 0:
            if band.winfo_manager():
                band.pack_forget()
            return
        if not band.winfo_manager():
            band.pack(
                side=tk.TOP, fill=tk.X, before=self._sections_holder,
            )
        if self._clean_meter is not None:
            self._clean_meter.set(min(1.0, done / total))
        if self._clean_detail is not None:
            detail = f"{done} de {total} página(s)"
            if label:
                detail += f" · {label}"
            self._clean_detail.configure(text=detail)

    def _on_sections_resize(self, _event: object) -> None:
        self._schedule_sync()

    def _on_scroll_resize(self, event: tk.Event) -> None:
        self._scroll.itemconfigure(
            self._scroll_window, width=max(1, event.width - 2 * SIDEBAR_VIEW_PAD),
        )
        self._schedule_sync()

    def _schedule_sync(self) -> None:
        """Re-measure once the layout has settled, not mid-``<Configure>``."""
        if self._sync_after_id is not None:
            try:
                self.after_cancel(self._sync_after_id)
            except Exception:
                pass
        self._sync_after_id = self.after(30, self._sync_scroll)

    def _sync_scroll(self) -> None:
        self._sync_after_id = None
        needed = self._view_sections_frame.winfo_reqheight()
        available = self._scroll.winfo_height()
        self._scroll.configure(
            scrollregion=(0, 0, self._scroll.winfo_width(), needed),
        )
        overflows = needed > available + 1
        if overflows and not self._scrollbar.winfo_manager():
            self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        elif not overflows:
            if self._scrollbar.winfo_manager():
                self._scrollbar.pack_forget()
            self._scroll.yview_moveto(0.0)

    def reveal(self, widget: tk.Misc) -> None:
        """Scroll the rail so ``widget`` is fully in view.

        A long mark list pushes the sections below it off the bottom, so
        acting on one has to bring the panel that answers back on screen.
        """
        self.after_idle(lambda: self._reveal_now(widget))

    def _reveal_now(self, widget: tk.Misc) -> None:
        try:
            if not widget.winfo_exists():
                return
            # The scrollregion is refreshed on a 30 ms debounce, so right
            # after new sections are built it still describes the old,
            # shorter content and the move would fall short. Settle the
            # layout and resync before measuring anything.
            self._view_sections_frame.update_idletasks()
            self._sync_scroll()
            if not self._overflows():
                return
            total = max(1, self._view_sections_frame.winfo_reqheight())
            view_h = self._scroll.winfo_height()
            # Widget position inside the scrolled frame, not on screen.
            top = widget.winfo_rooty() - self._view_sections_frame.winfo_rooty()
            bottom = top + widget.winfo_reqheight()
            first = self._scroll.canvasy(0)
            if top < first:
                target = top
            elif bottom > first + view_h:
                target = min(bottom - view_h, total - view_h)
            else:
                return
            self._scroll.yview_moveto(max(0.0, target) / total)
        except Exception:
            pass

    def _overflows(self) -> bool:
        return (
            self._view_sections_frame.winfo_reqheight()
            > self._scroll.winfo_height() + 1
        )

    def _grab_wheel(self, _event: object = None) -> None:
        self._prev_wheel = self._scroll.bind_all("<MouseWheel>") or ""
        self._scroll.bind_all("<MouseWheel>", self._on_wheel)

    def _release_wheel(self, _event: object = None) -> None:
        if self._prev_wheel:
            self._scroll.bind_all("<MouseWheel>", self._prev_wheel)
        else:
            self._scroll.unbind_all("<MouseWheel>")
        self._prev_wheel = ""

    def _on_wheel(self, event: tk.Event) -> None:
        if not self._overflows():
            return
        self._scroll.yview_scroll(-1 if event.delta > 0 else 1, "units")

    # ----------------------------------------------------------- step rail

    def set_step_indicator(self, current_step: int, highest_reached: int = 0) -> None:
        """Show the row of ``current_step`` and hide the other three."""
        total = len(self._step_rows)
        current = min(max(int(current_step), 1), total)
        self._step_kicker.configure(text=f"PASO {current} DE {total}")
        for index, row in enumerate(self._step_rows, start=1):
            if index == current:
                row.set_state("active")
                if not row.winfo_manager():
                    row.pack(side=tk.TOP, fill=tk.X)
            elif row.winfo_manager():
                row.pack_forget()

    # alias used by newer call sites
    set_step = set_step_indicator

    # -------------------------------------------------------------- footer

    def set_footer(
        self,
        text: str,
        command: Callable[[], None] | None,
        *,
        hint: str | None = None,
        variant: str = "primary",
        secondary_text: str | None = None,
        secondary_command: Callable[[], None] | None = None,
        tooltip: str | None = None,
    ) -> tk.Button:
        """Anchor the step's primary action to the bottom of the rail."""
        self.clear_footer()
        self._footer_rule.pack(side=tk.TOP, fill=tk.X)
        self._footer_body.pack(
            side=tk.TOP, fill=tk.X, padx=SIDEBAR_SECTION_PAD, pady=12,
        )
        if secondary_text:
            self._footer_secondary = theme.button(
                self._footer_body, secondary_text, secondary_command,
                variant="outline", size=9, pady=7, anchor=tk.W,
            )
            self._footer_secondary.pack(fill=tk.X, pady=(0, 7))
        self._footer_primary = theme.button(
            self._footer_body, text, command,
            variant=variant, size=10, pady=11, anchor=tk.W,
            tooltip=tooltip,
        )
        self._footer_primary.pack(fill=tk.X)
        if hint:
            self._footer_hint = theme.body(
                self._footer_body, hint, size=8, bg=SIDEBAR_BG,
                fg=NEUTRAL_600, wrap=SIDEBAR_WIDTH - 2 * SIDEBAR_SECTION_PAD,
            )
            self._footer_hint.pack(fill=tk.X, pady=(7, 0))
        return self._footer_primary

    def clear_footer(self) -> None:
        for widget in list(self._footer_body.winfo_children()):
            try:
                widget.destroy()
            except Exception:
                pass
        self._footer_primary = None
        self._footer_secondary = None
        self._footer_hint = None
        self._footer_body.pack_forget()
        self._footer_rule.pack_forget()

    def footer_button(self) -> tk.Button | None:
        return self._footer_primary

    def set_footer_state(self, enabled: bool) -> None:
        if self._footer_primary is not None:
            self._footer_primary.configure(
                state=tk.NORMAL if enabled else tk.DISABLED,
            )

    def set_footer_text(self, text: str) -> None:
        if self._footer_primary is not None:
            self._footer_primary.configure(text=text)

    def set_footer_hint(self, text: str) -> None:
        if self._footer_hint is not None:
            self._footer_hint.configure(text=text)

    # ------------------------------------------------------------- engines

    def show_engines(
        self,
        *,
        visible: bool = True,
        translator_pair: str | None = None,
        translator_ready: bool = False,
        on_download_pair: Callable[[], None] | None = None,
    ) -> None:
        """Render (or hide) the ``Motores`` block above the footer."""
        if self._engines_body is not None:
            try:
                self._engines_body.destroy()
            except Exception:
                pass
            self._engines_body = None
        if not visible:
            self._engines.pack_forget()
            return

        self._engines.pack(side=tk.BOTTOM, fill=tk.X)
        body = tk.Frame(self._engines, bg=SIDEBAR_BG)
        theme.rule(body, thickness=2, color=COLOR_DIVIDER).pack(
            side=tk.TOP, fill=tk.X,
        )
        body.pack(fill=tk.X)
        inner = tk.Frame(body, bg=SIDEBAR_BG)
        inner.pack(fill=tk.X, padx=SIDEBAR_SECTION_PAD, pady=(12, 14))
        self._engines_body = body
        body = inner

        theme.kicker(body, "Motores", bg=SIDEBAR_BG).pack(
            fill=tk.X, pady=(0, 8),
        )
        self._engine_row(
            body, "Tesseract", self._ocr_status, self._ocr_available,
        )
        self._engine_row(
            body, "LaMa", self._inpaint_status, self._inpaint_available,
        )
        if translator_pair:
            if translator_ready:
                self._engine_row(body, "Argos", translator_pair, True)
            else:
                missing = theme.card(
                    body, bg=SIDEBAR_BG, border=COLOR_ACCENT, border_width=2,
                )
                missing.pack(fill=tk.X, pady=(4, 0))
                text = tk.Frame(missing, bg=SIDEBAR_BG)
                text.pack(side=tk.LEFT, fill=tk.X, expand=True)
                theme.body(
                    text, f"Argos {translator_pair}", size=8,
                    bg=SIDEBAR_BG, fg=COLOR_TEXT, weight="bold",
                ).pack(fill=tk.X)
                theme.body(
                    text, "falta el modelo", size=8,
                    bg=SIDEBAR_BG, fg=ACCENT_700,
                ).pack(fill=tk.X)
                theme.button(
                    missing, "⬇ Bajar", on_download_pair,
                    variant="primary", size=8, padx=8, pady=5,
                ).pack(side=tk.RIGHT, padx=(8, 0))

    def _engine_row(
        self, parent: tk.Misc, name: str, status: str, available: bool,
    ) -> None:
        row = tk.Frame(parent, bg=SIDEBAR_BG)
        row.pack(fill=tk.X, pady=(0, 5))
        # The dot for a missing engine is muted, not red — the red is
        # spent on the card that says what to do about it.
        tk.Frame(
            row, bg=COLOR_TEXT if available else NEUTRAL_500,
            width=7, height=7,
        ).pack(side=tk.LEFT, padx=(0, 7))
        theme.body(row, name, size=8, bg=SIDEBAR_BG, fg=NEUTRAL_700).pack(
            side=tk.LEFT,
        )
        theme.body(
            row, status, size=8, bg=SIDEBAR_BG,
            fg=COLOR_TEXT if available else ACCENT_700, weight="bold",
        ).pack(side=tk.LEFT, padx=(5, 0))

    # -------------------------------------------------------- view sections

    def view_sections_frame(self) -> tk.Frame:
        """Frame where the active view places its sections."""
        return self._view_sections_frame

    def clear_view_sections(self) -> None:
        for child in list(self._view_sections_frame.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass

    def section(self, title: str, *, pady: tuple[int, int] = (0, 12)) -> tk.Frame:
        """A titled block inside the view-sections area.

        Returns the body frame; the kicker is already packed above it.
        """
        container = tk.Frame(self._view_sections_frame, bg=SIDEBAR_BG)
        container.pack(side=tk.TOP, fill=tk.X, pady=pady)
        theme.kicker(container, title, bg=SIDEBAR_BG).pack(
            fill=tk.X, pady=(0, 8),
        )
        body = tk.Frame(container, bg=SIDEBAR_BG)
        body.pack(side=tk.TOP, fill=tk.X)
        return body

    def section_with_count(
        self, title: str, *, pady: tuple[int, int] = (0, 12),
    ) -> tuple[tk.Frame, tk.Label]:
        """Like :meth:`section` but with a figure right-aligned on the
        kicker line — ``MARCAS … 6``."""
        container = tk.Frame(self._view_sections_frame, bg=SIDEBAR_BG)
        container.pack(side=tk.TOP, fill=tk.X, pady=pady)
        head = tk.Frame(container, bg=SIDEBAR_BG)
        head.pack(fill=tk.X, pady=(0, 8))
        theme.kicker(head, title, bg=SIDEBAR_BG).pack(side=tk.LEFT)
        count = tk.Label(
            head, text="", font=theme.heading_font(9),
            bg=SIDEBAR_BG, fg=COLOR_TEXT,
        )
        count.pack(side=tk.RIGHT)
        body = tk.Frame(container, bg=SIDEBAR_BG)
        body.pack(side=tk.TOP, fill=tk.X)
        return body, count

    def section_divider(self) -> None:
        theme.rule(
            self._view_sections_frame, thickness=2, color=COLOR_DIVIDER,
        ).pack(side=tk.TOP, fill=tk.X, pady=(0, 12))

    # --- legacy helpers, kept so older call sites keep working ------------

    def make_section_header(
        self,
        title: str,
        toggle_target: tk.Widget | None = None,
        toggle_text_off: str = "▼",
        toggle_text_on: str = "▲",
    ) -> tuple[tk.Frame, tk.Label]:
        container = tk.Frame(self._view_sections_frame, bg=SIDEBAR_BG)
        top = tk.Frame(container, bg=SIDEBAR_BG)
        top.pack(side=tk.TOP, fill=tk.X)
        theme.kicker(top, title, bg=SIDEBAR_BG).pack(side=tk.LEFT)
        indicator = tk.Label(
            top, text="", font=theme.heading_font(9),
            bg=SIDEBAR_BG, fg=NEUTRAL_600,
        )
        indicator.pack(side=tk.RIGHT)
        return container, indicator

    def make_section_body(self, parent: tk.Widget) -> tk.Frame:
        body = tk.Frame(parent, bg=SIDEBAR_BG)
        body.pack(side=tk.TOP, fill=tk.X, pady=(8, 12))
        return body

    def make_pill_button(
        self,
        parent: tk.Widget,
        text: str,
        tooltip: str,
        command: Callable[[], None],
        anchor: str = tk.W,
        font: tuple | None = None,
    ) -> tk.Button:
        return theme.button(
            parent, text, command,
            variant="outline", tooltip=tooltip or None,
            size=9, padx=9, pady=7, anchor=anchor,
        )

    def make_toggle_button(
        self,
        parent: tk.Widget,
        text: str,
        tooltip: str,
        command: Callable[[], None],
    ) -> tk.Button:
        btn = self.make_pill_button(parent, text, tooltip, command)
        btn._toggle_state = False  # type: ignore[attr-defined]

        def on_click() -> None:
            btn._toggle_state = not btn._toggle_state  # type: ignore[attr-defined]
            theme.restyle_button(
                btn, "ink" if btn._toggle_state else "secondary",  # type: ignore[attr-defined]
            )
            command()

        btn.configure(command=on_click)
        return btn

    # -------------------------------------------------------------- public

    def set_active(self, key: str | None) -> None:
        if key is not None:
            self._active = key

    def set_recent_label(self, label: str | None) -> None:
        self._recent_label = label

    def recent_label(self) -> str | None:
        return self._recent_label

    def update_status(
        self,
        *,
        ocr_available: bool,
        ocr_status: str,
        inpaint_available: bool,
        inpaint_status: str,
    ) -> None:
        self._ocr_available = ocr_available
        self._ocr_status = ocr_status
        self._inpaint_available = inpaint_available
        self._inpaint_status = inpaint_status
