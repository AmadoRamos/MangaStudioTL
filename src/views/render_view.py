"""Step 4 — render the translations and export the chapter.

The page gets the whole canvas; the per-section controls move into the
rail, as in the mockups: which section is selected, its box size and
the auto-fit result, then text, font, style, maximum size and colour. The
anchored action opens the export dialog, and once the write succeeds
the screen becomes the export report — same rail, same step, no modal
to dismiss before the user can read what happened.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import colorchooser

from PIL import Image

from src.config import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DIVIDER,
    COLOR_SURFACE,
    COLOR_TEXT,
    NEUTRAL_600,
    NEUTRAL_700,
    SIDEBAR_BG,
    TEXT_COLOR_PRESETS,
    TEXT_RENDER_DEFAULT_COLOR,
    TEXT_RENDER_FALLBACK_FAMILIES,
    TEXT_RENDER_USER_MAX_PT_MAX,
    TEXT_RENDER_USER_MAX_PT_MIN,
    TRANSLATION_DIR_NAME,
)
from src.utils.exporter import export_translations
from src.utils.inpainter import find_clean, has_clean
from src.utils.logger import get_logger
from src.utils import text_profiles
from src.utils.marks_store import MarksStore, TranslationEntry
from src.utils.text_profiles import TextProfile
from src.utils.text_renderer import (
    RenderConfig,
    box_rect,
    list_available_families,
    resolve_box,
    resolve_style,
)
from src.views import theme
from src.views.export_dialog import ExportDialog
from src.views.toolbar import StatusBar
from src.views.translator_canvas import TranslatorCanvas, _rgb_to_hex

log = get_logger("render_view")

# Rough per-page weight used for the export dialog's size estimate.
MB_PER_PAGE = 1.3
#: Quiet time before what was typed in the rail reaches the page.
TEXT_ECHO_MS = 220
#: The «no profile» row of the selector. Not a profile name: a section
#: with no profile falls straight through to the chapter defaults.
NO_PROFILE = "(ninguno)"


class RenderView(tk.Frame):
    """Step 4 view: clean image with the rendered translations."""

    def __init__(self, master: tk.Misc, workflow, sidebar) -> None:
        super().__init__(master, bg=COLOR_BG)
        self.workflow = workflow
        self._sidebar = sidebar
        self._items: list[tuple[Path, Image.Image]] = list(workflow.items)
        self._stores: list[MarksStore] = list(workflow.stores)
        self._index: int = 0
        self._viewing_clean: bool = True
        self._clean_cache: dict[int, Image.Image] = {}
        self._selected_mark: int | None = None

        self._config = RenderConfig(
            font_family=workflow.font_family,
            max_pt=workflow.max_pt,
            color=TEXT_RENDER_DEFAULT_COLOR,
            profiles=text_profiles.load(),
        )
        self._font_options: list[str] = self._build_font_options()

        # Rail widgets.
        self._inspector: tk.Frame | None = None
        self._text_widget: tk.Text | None = None
        self._font_var: tk.StringVar | None = None
        self._profile_var: tk.StringVar | None = None
        self._name_var: tk.StringVar | None = None
        #: Which section has the «guardar como perfil» field open, if
        #: any. Held as the mark id and not as a flag so that moving to
        #: another section closes it without anyone remembering to.
        self._naming_for: int | None = None
        self._size_var: tk.IntVar | None = None
        self._size_label: tk.Label | None = None
        self._bold_btn: tk.Button | None = None
        self._italic_btn: tk.Button | None = None
        self._style_note_holder: tk.Frame | None = None
        self._style_note: tk.Label | None = None
        self._swatch_row: tk.Frame | None = None
        self._text_after_id: str | None = None

        self._build_ui()
        self._build_sidebar_sections()
        self._load_current()
        self._canvas.set_render_config(self._config)

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._topbar = theme.TopBar(self)
        self._topbar.pack(side=tk.TOP, fill=tk.X)
        row = self._topbar.body

        self._nav_bar = theme.SegmentedBar(row, border_width=2)
        self._nav_bar.pack(side=tk.LEFT, pady=6)
        self._nav_bar.add("prev", "◀", self._on_prev, tooltip="Página anterior")
        self._nav_bar.add("count", "1 / 1", None, width=7)
        self._nav_bar.add("next", "▶", self._on_next, tooltip="Página siguiente")

        self._topbar.gap()

        zoom = theme.SegmentedBar(row, border_width=2)
        zoom.pack(side=tk.LEFT, padx=(0, 8), pady=6)
        zoom.add("out", "−", self._zoom_out, tooltip="Alejar (Ctrl + rueda)")
        zoom.add("reset", "100%", self._zoom_reset, width=6,
                 tooltip="Ajustar a la ventana")
        zoom.add("in", "+", self._zoom_in, tooltip="Acercar (Ctrl + rueda)")

        self._view_bar = theme.SegmentedBar(
            row, border_width=2, uniform_chars=theme.SEGMENT_CHARS,
        )
        self._view_bar.pack(side=tk.LEFT, pady=6)
        self._view_bar.add(
            "translated", "Traducida", lambda: self._set_clean_mode(True),
            tooltip="La página limpia con el texto traducido",
        )
        self._view_bar.add(
            "original", "Original", lambda: self._set_clean_mode(False),
            tooltip="La página original, sin tocar",
        )
        self._view_bar.set_active("translated")

        self._stage = tk.Frame(self, bg=COLOR_BG)
        self._stage.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._canvas = TranslatorCanvas(
            self._stage,
            on_change=self._on_canvas_change,
            on_select=self._on_canvas_select,
            on_text_edited=self._on_canvas_text_edited,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        self._status = StatusBar(self)
        self._status.pack(side=tk.BOTTOM, fill=tk.X)
        self._status.set_hint(
            "Clic en una sección para editarla · Ctrl+rueda zoom"
        )

    # ------------------------------------------------------------------
    # Rail — the section inspector
    # ------------------------------------------------------------------

    def _build_sidebar_sections(self) -> None:
        self._sidebar.clear_view_sections()
        self._inspector = self._sidebar.section("Sección")
        self._render_inspector()
        self._sidebar.set_footer(
            "Finalizar y exportar", self._on_finalize,
            hint=self._export_hint(),
            secondary_text="← Atrás", secondary_command=self._on_back,
        )

    def _export_hint(self) -> str:
        return (
            f"{len(self._items)} PNG + sidecars JSON · "
            f"{self.workflow.translated_marks()} sección(es) con texto"
        )

    def _render_inspector(self) -> None:
        """Rebuild the inspector for whichever section is selected."""
        if self._inspector is None:
            return
        # The field this timer would read is about to be destroyed, and
        # so are the toggles `restyle_button` mutates in place.
        self._cancel_text_timer()
        self._text_widget = None
        self._bold_btn = None
        self._italic_btn = None
        self._style_note_holder = None
        self._style_note = None
        for widget in list(self._inspector.winfo_children()):
            widget.destroy()

        store = self._stores[self._index] if self._stores else None
        sections = self._translated_sections()
        if store is None or not sections:
            theme.body(
                self._inspector,
                "Esta página no tiene secciones con traducción. "
                "Vuelve al paso 3 para escribirlas.",
                size=8, bg=SIDEBAR_BG, fg=NEUTRAL_600, wrap=210,
            ).pack(fill=tk.X)
            return

        if self._selected_mark not in sections:
            self._selected_mark = sections[0]
        mark_id = self._selected_mark
        position = sections.index(mark_id) + 1
        mark = store.marks[mark_id]
        entry = store.get_translation(mark_id)

        head = tk.Frame(self._inspector, bg=SIDEBAR_BG)
        head.pack(fill=tk.X)
        theme.body(
            head, f"{self._index + 1:02d}·{mark_id + 1:02d}", size=9,
            bg=SIDEBAR_BG, fg=COLOR_TEXT, weight="bold",
        ).pack(side=tk.LEFT)
        theme.tag(
            head, f"{position} / {len(sections)}", kind="accent",
        ).pack(side=tk.RIGHT)

        asked_max = self._config.asked(entry, "max_pt")
        max_pt = asked_max if asked_max is not None else self._config.max_pt
        bx, by, bw, bh = box_rect(mark, entry)
        theme.body(
            self._inspector,
            f"{bw} × {bh} px · auto-fit hasta {max_pt} pt",
            size=8, bg=SIDEBAR_BG, fg=NEUTRAL_600,
        ).pack(fill=tk.X, pady=(6, 10))

        # The box only earns a row of its own once it has left the mark;
        # while the two are the same there is nothing to say about it.
        if entry.box_offset:
            self._label_row("Cuadro de texto", "box_offset", pady=(0, 2))
            note = "Movido respecto a la marca."
            pad = mark.erase_padding
            if (
                bx < mark.x - pad or by < mark.y - pad
                or bx + bw > mark.x + mark.w + pad
                or by + bh > mark.y + mark.h + pad
            ):
                # Deliberate — a shout that overflows its globo is a real
                # thing to want — but the text out there lands on art
                # nobody erased, so the rail says so instead of the
                # export being the first to mention it.
                note += " Sobresale de lo que se limpió: ahí el texto cae sobre dibujo."
            theme.body(
                self._inspector, note,
                size=8, bg=SIDEBAR_BG, fg=NEUTRAL_600, wrap=210,
            ).pack(fill=tk.X, pady=(0, 10))

        # Text.
        theme.field_label(self._inspector, "Texto").pack(fill=tk.X, pady=(0, 5))
        self._text_widget = theme.text_area(self._inspector, height=3)
        self._text_widget.insert("1.0", entry.text)
        self._text_widget.pack(fill=tk.X, pady=(0, 10))
        self._text_widget.bind("<FocusOut>", lambda _e: self._commit_text())
        self._text_widget.bind("<Control-Return>", lambda _e: self._commit_text())
        self._text_widget.bind("<KeyRelease>", self._on_text_key)

        # Profile. It governs the four controls under it, so it sits
        # right on top of them.
        # No reset here: «(ninguno)» in the selector is that reset.
        self._label_row("Perfil")
        self._profile_var = tk.StringVar(value=entry.profile or NO_PROFILE)
        theme.option_menu(
            self._inspector, self._profile_var,
            [NO_PROFILE, *(p.name for p in self._config.profiles)],
            self._on_profile_change,
        ).pack(fill=tk.X, pady=(0, 4))
        actions = tk.Frame(self._inspector, bg=SIDEBAR_BG)
        actions.pack(fill=tk.X, pady=(0, 10))
        theme.button(
            actions, "Guardar como perfil…", self._begin_naming,
            variant="ghost", size=8, padx=6, pady=4,
            tooltip="Crear un perfil con lo que se ve en esta sección",
        ).pack(side=tk.LEFT)
        if entry.profile and len(sections) > 1:
            theme.button(
                actions, "A toda la página", self._apply_profile_to_page,
                variant="ghost", size=8, padx=6, pady=4,
                tooltip=(
                    f"Asignar «{entry.profile}» a las {len(sections)} "
                    "secciones de esta página"
                ),
            ).pack(side=tk.RIGHT)
        if self._naming_for == mark_id:
            self._build_name_row()

        # Font.
        self._label_row("Fuente", "font_family")
        self._font_var = tk.StringVar(
            value=self._config.asked(entry, "font_family")
            or self._config.font_family,
        )
        theme.option_menu(
            self._inspector, self._font_var, self._font_options,
            self._on_font_change,
        ).pack(fill=tk.X, pady=(0, 10))

        # Style. Two independent toggles rather than three exclusive
        # options: «normal» is both of them off, and negrita + cursiva
        # together is something rotulación actually uses.
        self._label_row("Estilo", "bold", "italic")
        style_row = tk.Frame(self._inspector, bg=SIDEBAR_BG)
        style_row.pack(fill=tk.X)
        self._bold_btn = theme.button(
            style_row, "Negrita", lambda: self._toggle_style("bold"),
            variant="ink" if self._config.asked(entry, "bold") else "outline",
            size=8, padx=10, pady=5,
            tooltip="Usar la variante negrita de esta fuente",
        )
        self._bold_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._italic_btn = theme.button(
            style_row, "Cursiva", lambda: self._toggle_style("italic"),
            variant="ink" if self._config.asked(entry, "italic") else "outline",
            size=8, padx=10, pady=5,
            tooltip="Usar la variante cursiva de esta fuente",
        )
        self._italic_btn.pack(side=tk.LEFT)
        # The warning lives in its own holder so that hiding it also
        # takes its spacing away instead of leaving an empty line.
        self._style_note_holder = tk.Frame(self._inspector, bg=SIDEBAR_BG)
        self._style_note_holder.pack(fill=tk.X, pady=(0, 10))
        self._style_note = theme.body(
            self._style_note_holder, "", size=8,
            bg=SIDEBAR_BG, fg=NEUTRAL_600, wrap=210,
        )
        self._sync_style_note(entry)

        # Maximum size.
        self._size_label = self._label_row(
            f"Tamaño máximo · {max_pt} pt", "max_pt", pady=(0, 2),
        )
        self._size_var = tk.IntVar(value=max_pt)
        theme.slider(
            self._inspector,
            from_=TEXT_RENDER_USER_MAX_PT_MIN,
            to=TEXT_RENDER_USER_MAX_PT_MAX,
            variable=self._size_var,
            command=self._on_size_change,
            bg=SIDEBAR_BG,
        ).pack(fill=tk.X)
        ends = tk.Frame(self._inspector, bg=SIDEBAR_BG)
        ends.pack(fill=tk.X, pady=(0, 10))
        theme.body(
            ends, str(TEXT_RENDER_USER_MAX_PT_MIN), size=8,
            bg=SIDEBAR_BG, fg=NEUTRAL_600,
        ).pack(side=tk.LEFT)
        theme.body(
            ends, str(TEXT_RENDER_USER_MAX_PT_MAX), size=8,
            bg=SIDEBAR_BG, fg=NEUTRAL_600,
        ).pack(side=tk.RIGHT)

        # Colour.
        self._label_row("Color", "color")
        self._swatch_row = tk.Frame(self._inspector, bg=SIDEBAR_BG)
        self._swatch_row.pack(fill=tk.X)
        current = self._config.asked(entry, "color") or self._config.color
        for color in TEXT_COLOR_PRESETS:
            theme.swatch(
                self._swatch_row, _rgb_to_hex(color),
                command=lambda c=color: self._set_color(c),
                selected=(tuple(color) == tuple(current)),
            ).pack(side=tk.LEFT, padx=(0, 3))
        theme.button(
            self._swatch_row, "Más…", self._pick_color,
            variant="ghost", size=8, padx=4, pady=2,
        ).pack(side=tk.LEFT, padx=(4, 0))

        # Sibling sections, so the rail can move between them.
        if len(sections) > 1:
            nav = tk.Frame(self._inspector, bg=SIDEBAR_BG)
            nav.pack(fill=tk.X, pady=(12, 0))
            theme.button(
                nav, "◀ Anterior",
                lambda: self._step_section(-1),
                variant="secondary", size=8, padx=8, pady=6,
            ).pack(side=tk.LEFT)
            theme.button(
                nav, "Siguiente ▶",
                lambda: self._step_section(1),
                variant="secondary", size=8, padx=8, pady=6,
            ).pack(side=tk.RIGHT)

    def _label_row(
        self, text: str, *fields: str, pady: tuple[int, int] = (0, 5),
    ) -> tk.Label:
        """Pack a field label, plus a «restablecer» if the section overrides it.

        The reset only appears when there is something to undo: one that
        is always there says nothing about whether this section differs
        from its profile, which is the single question it answers.
        Returns the label so the caller can keep reconfiguring it.
        """
        row = tk.Frame(self._inspector, bg=SIDEBAR_BG)
        row.pack(fill=tk.X, pady=pady)
        label = theme.field_label(row, text)
        label.pack(side=tk.LEFT)
        entry = self._current_entry()
        if entry is not None and any(
            getattr(entry, field) is not None for field in fields
        ):
            theme.button(
                row, "↺", lambda: self._reset_fields(*fields),
                variant="ghost", size=8, padx=4, pady=0,
                tooltip="Volver a lo que diga el perfil",
            ).pack(side=tk.RIGHT)
        return label

    def _build_name_row(self) -> None:
        """The inline «cómo se va a llamar» field, in the rail itself.

        A modal to ask for one word would be the only dialog in the step
        and would not look like the rest of the app.
        """
        row = tk.Frame(self._inspector, bg=SIDEBAR_BG)
        row.pack(fill=tk.X, pady=(0, 10))
        self._name_var = tk.StringVar()
        field = theme.entry(row, self._name_var)
        field.pack(side=tk.LEFT, fill=tk.X, expand=True)
        field.bind("<Return>", lambda _e: self._save_profile())
        field.bind("<Escape>", lambda _e: self._cancel_naming())
        field.focus_set()
        theme.button(
            row, "Guardar", self._save_profile,
            variant="primary", size=8, padx=8, pady=4,
        ).pack(side=tk.RIGHT, padx=(4, 0))

    def _translated_sections(self) -> list[int]:
        if not self._stores:
            return []
        store = self._stores[self._index]
        return [
            mark_id for mark_id in range(len(store))
            if (entry := store.get_translation(mark_id)) is not None
            and entry.text.strip()
        ]

    def _step_section(self, delta: int) -> None:
        sections = self._translated_sections()
        if not sections or self._selected_mark is None:
            return
        self._commit_text()
        position = sections.index(self._selected_mark)
        self._selected_mark = sections[(position + delta) % len(sections)]
        self._canvas.select(self._selected_mark)
        self._focus_selected()
        self._render_inspector()

    def _focus_selected(self) -> None:
        """Bring the selected section into view.

        Moving between sections from the rail is useless if the one you
        land on is off screen — which it is as soon as the page is
        zoomed in, and always on a webtoon strip.
        """
        if self._selected_mark is None:
            return
        try:
            self._canvas.ensure_mark_visible(self._selected_mark)
        except Exception as exc:  # a canvas that is not laid out yet
            log.debug("No se pudo desplazar a la sección: %s", exc)

    # ------------------------------------------------------------------
    # Section edits
    # ------------------------------------------------------------------

    def _current_entry(self) -> TranslationEntry | None:
        if self._selected_mark is None or not self._stores:
            return None
        return self._stores[self._index].get_translation(self._selected_mark)

    def _update_entry(self, **changes) -> None:
        entry = self._current_entry()
        if entry is None:
            return
        # ``replace`` rather than listing the fields: this used to rebuild
        # the entry one field at a time, which silently dropped every new
        # one — an override the user had set would vanish on the next edit
        # of any other control.
        self._stores[self._index].set_translation(
            self._selected_mark, replace(entry, edited=True, **changes),
        )
        # The entry changed, not the global config, so asking the canvas
        # to reconfigure itself would be a no-op: it only redraws when
        # one of its own defaults moves. Repaint explicitly.
        self._canvas.refresh()

    def _commit_text(self) -> None:
        if self._text_widget is None:
            return
        self._cancel_text_timer()
        text = self._text_widget.get("1.0", tk.END).strip()
        entry = self._current_entry()
        if entry is None or text == entry.text:
            return
        self._update_entry(text=text)
        self._sidebar.set_footer_hint(self._export_hint())

    def _on_text_key(self, _event: object = None) -> None:
        """Repaint shortly after the user stops typing.

        Committing on every keystroke would re-lay the box out and
        rewrite the sidecar per character; waiting for the focus to leave
        the field — which is what used to happen — reads as the edit
        having been ignored.
        """
        self._cancel_text_timer()
        self._text_after_id = self.after(TEXT_ECHO_MS, self._commit_text)

    def _cancel_text_timer(self) -> None:
        if self._text_after_id is None:
            return
        try:
            self.after_cancel(self._text_after_id)
        except Exception:
            pass
        self._text_after_id = None

    def _reset_fields(self, *fields: str) -> None:
        """Hand the fields back to the profile — or to the chapter default."""
        self._update_entry(**{field: None for field in fields})
        self._render_inspector()

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------

    def _on_profile_change(self, label: str) -> None:
        """Assign a profile, or take it away.

        Nothing else is touched: the fields this section had chosen for
        itself stay chosen. That is the difference between a shortcut
        and an atadura, and it only holds while the assignment writes
        the *name* and never copies the values.
        """
        self._update_entry(profile=None if label == NO_PROFILE else label)
        self._render_inspector()

    def _begin_naming(self) -> None:
        self._naming_for = self._selected_mark
        self._render_inspector()

    def _cancel_naming(self) -> None:
        self._naming_for = None
        self._render_inspector()

    def _save_profile(self) -> None:
        """Turn what this section looks like into a profile with a name.

        The values are the effective ones — what the rail is showing —
        and not just the overrides: a profile built from a section that
        had changed nothing would come out empty and look broken.
        """
        entry = self._current_entry()
        name = self._name_var.get().strip() if self._name_var else ""
        if not name or entry is None or self._selected_mark is None:
            self._cancel_naming()
            return
        mark = self._stores[self._index].marks[self._selected_mark]
        box = resolve_box(mark, entry, self._config)
        profile = TextProfile(
            name=name,
            font_family=box.font_family,
            max_pt=box.max_pt,
            color=box.color,
            # Lo pedido, no lo dibujado: un perfil guardado desde una
            # familia sin negrita instalada tiene que seguir diciendo
            # «negrita» cuando se aplique a otra que sí la tenga.
            bold=bool(self._config.asked(entry, "bold")),
            italic=bool(self._config.asked(entry, "italic")),
        )
        # Guardar con un nombre que ya existe es editar ese perfil, y
        # editarlo alcanza a todas las secciones que lo usan — en los
        # campos que esas secciones no hayan tocado.
        profiles = list(self._config.profiles)
        for i, existing in enumerate(profiles):
            if existing.name == name:
                profiles[i] = profile
                break
        else:
            profiles.append(profile)
        self._set_profiles(tuple(profiles))
        self._naming_for = None
        self._update_entry(profile=name)
        self._render_inspector()
        self._status.set(f"Perfil «{name}» guardado", "success")

    def _apply_profile_to_page(self) -> None:
        """Give every section on this page the selected one's profile.

        Only the profile. A section that had picked its own colour or
        size keeps it, because the profile is the weaker layer — which
        is what makes «todo esto es diálogo» safe to click.
        """
        entry = self._current_entry()
        if entry is None or not entry.profile:
            return
        store = self._stores[self._index]
        changed = 0
        for mark_id in self._translated_sections():
            other = store.get_translation(mark_id)
            if other is None or other.profile == entry.profile:
                continue
            store.set_translation(
                mark_id, replace(other, profile=entry.profile, edited=True),
            )
            changed += 1
        self._canvas.refresh()
        self._render_inspector()
        self._status.set(
            f"«{entry.profile}» aplicado a {changed} sección(es)", "success",
        )

    def _set_profiles(self, profiles: tuple[TextProfile, ...]) -> None:
        """Publish the new list: to the canvas, and to disk.

        The canvas repaints because its config changed, which is how
        editing a profile reaches the sections already using it.
        """
        self._config = replace(self._config, profiles=profiles)
        self._canvas.set_render_config(self._config)
        if not text_profiles.save(profiles):
            self._status.set(
                "El perfil no se pudo guardar en disco; vale para esta sesión",
                "warning",
            )

    def _on_font_change(self, _label: str) -> None:
        if self._font_var is None:
            return
        self._update_entry(font_family=self._font_var.get())
        # Another family, another set of variants on disk: the warning
        # about a missing negrita may have just appeared or gone away.
        self._sync_style_note(self._current_entry())

    def _toggle_style(self, field: str) -> None:
        """Flip «negrita» or «cursiva» for the selected section."""
        entry = self._current_entry()
        if entry is None:
            return
        # Se invierte lo que se está viendo, que puede venir del perfil:
        # apagar una negrita heredada es ponerle `False` a la sección,
        # no dejarla «sin tocar» y que el perfil la vuelva a encender.
        self._update_entry(
            **{field: not bool(self._config.asked(entry, field))},
        )
        self._sync_style_controls()

    def _sync_style_controls(self) -> None:
        """Repaint the two toggles in place, without rebuilding the rail.

        `restyle_button` mutates the widget, so the reference has to stay
        valid (DESIGN.md §7) — and rebuilding the section would take the
        text field's focus and caret with it.
        """
        entry = self._current_entry()
        if entry is None:
            return
        for btn, is_on in (
            (self._bold_btn, bool(self._config.asked(entry, "bold"))),
            (self._italic_btn, bool(self._config.asked(entry, "italic"))),
        ):
            if btn is not None:
                theme.restyle_button(btn, "ink" if is_on else "outline")
        self._sync_style_note(entry)

    def _sync_style_note(self, entry: TranslationEntry | None) -> None:
        """Say so when the chosen family has no such variant installed.

        PIL draws what is in the font file and synthesises nothing, so a
        family without a bold comes out regular. Without this line the
        toggle would look like it did nothing.
        """
        if self._style_note is None or entry is None:
            return
        family = (
            self._config.asked(entry, "font_family")
            or self._config.font_family
        )
        asked_bold = bool(self._config.asked(entry, "bold"))
        asked_italic = bool(self._config.asked(entry, "italic"))
        drawn_bold, drawn_italic = resolve_style(
            family, asked_bold, asked_italic,
        )
        missing: list[str] = []
        if asked_bold and not drawn_bold:
            missing.append("negrita")
        if asked_italic and not drawn_italic:
            missing.append("cursiva")
        if not missing:
            self._style_note.pack_forget()
            return
        plural = "s" if len(missing) > 1 else ""
        self._style_note.configure(
            text=(
                f"«{family}» no tiene {' ni '.join(missing)} "
                f"instalada{plural}; el texto se dibujará sin ella{plural}."
            ),
        )
        self._style_note.pack(fill=tk.X)

    def _on_size_change(self, value: str) -> None:
        try:
            size = int(float(value))
        except (TypeError, ValueError):
            return
        if self._size_label is not None:
            self._size_label.configure(text=f"Tamaño máximo · {size} pt")
        entry = self._current_entry()
        if entry is not None and entry.max_pt == size:
            # The slider fires while it is being dragged, and again when
            # it lands on a value it already had.
            return
        self._update_entry(max_pt=size)

    def _set_color(self, color: tuple[int, int, int]) -> None:
        self._update_entry(color=tuple(color))
        self._render_inspector()

    def _pick_color(self) -> None:
        entry = self._current_entry()
        asked = self._config.asked(entry, "color") if entry else None
        initial = _rgb_to_hex(asked or self._config.color)
        result = colorchooser.askcolor(
            color=initial, title="Color del texto", parent=self,
        )
        if not result or not result[0]:
            return
        self._set_color(tuple(int(round(c)) for c in result[0]))

    # ------------------------------------------------------------------
    # Canvas
    # ------------------------------------------------------------------

    def _on_canvas_change(self) -> None:
        self._render_inspector()

    def _on_canvas_select(self, mark_id: int) -> None:
        self._commit_text()
        self._selected_mark = mark_id
        self._render_inspector()

    def _on_canvas_text_edited(self, mark_id: int, text: str) -> None:
        self._selected_mark = mark_id
        self._update_entry(text=text.strip())
        self._render_inspector()
        self._sidebar.set_footer_hint(self._export_hint())

    def _on_prev(self) -> None:
        if self._index > 0:
            self._commit_text()
            self._index -= 1
            self._selected_mark = None
            self._load_current(focus_section=True)

    def _on_next(self) -> None:
        if self._index < len(self._items) - 1:
            self._commit_text()
            self._index += 1
            self._selected_mark = None
            self._load_current(focus_section=True)

    def _on_back(self) -> None:
        self.workflow.back_step()

    def destroy(self) -> None:
        # A pending echo would fire against a field that no longer exists.
        self._cancel_text_timer()
        super().destroy()

    def _zoom_in(self) -> None:
        self._canvas.zoom_in()

    def _zoom_out(self) -> None:
        self._canvas.zoom_out()

    def _zoom_reset(self) -> None:
        self._canvas.reset_zoom()

    def _set_clean_mode(self, viewing_clean: bool) -> None:
        if self._viewing_clean == viewing_clean:
            return
        # Same page, another bitmap of it: comparing the two is the point
        # of the toggle, so the reload must not drop the user back at the
        # top. Same treatment as «Limpia / Original» in step 2.
        keep = self._canvas.viewport()
        self._viewing_clean = viewing_clean
        self._view_bar.set_active("translated" if viewing_clean else "original")
        self._load_current()
        self._canvas.set_viewport(keep)

    def _load_current(self, *, focus_section: bool = False) -> None:
        if not self._items:
            return
        path, image = self._items[self._index]
        display = image
        if self._viewing_clean and has_clean(path):
            cached = self._clean_cache.get(self._index)
            if cached is None:
                cached = self._load_clean_image(path)
                if cached is not None:
                    self._clean_cache[self._index] = cached
            if cached is not None:
                display = cached
        self._canvas.set_image(display)
        self._canvas.set_store(self._stores[self._index])
        # Picks the first translated section when nothing is selected.
        self._render_inspector()
        if focus_section and self._selected_mark is not None:
            self._canvas.select(self._selected_mark)
            self._focus_selected()

        total = len(self._items)
        self._nav_bar.set_text("count", f"{self._index + 1} / {total}")
        self._nav_bar.set_enabled("prev", self._index > 0)
        self._nav_bar.set_enabled("next", self._index < total - 1)
        self._status.set(f"Página {self._index + 1}/{total} · {path.name}", "info")
        app = getattr(self.winfo_toplevel(), "_app", None)
        if app is not None and hasattr(app, "set_context"):
            app.set_context(f"{path.parent.name} · render")

    def on_clean_page_done(self, image_index: int, success: bool) -> None:
        """A page finished cleaning while the render step was open.

        Reaching step 4 no longer waits for LaMa, so pages arrive here
        still showing the original. Each one swaps itself in as it
        lands, without moving the view the user had set up.
        """
        if not success:
            return
        self._clean_cache.pop(image_index, None)
        if image_index != self._index or not self._viewing_clean:
            return
        keep = self._canvas.viewport()
        self._load_current()
        self._canvas.set_viewport(keep)
        self._status.set(
            f"Página {self._index + 1} limpia y lista", "success",
        )

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

    def _build_font_options(self) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for family in [
            self._config.font_family, *TEXT_RENDER_FALLBACK_FAMILIES,
            *list_available_families(),
        ]:
            name = (family or "").strip()
            key = name.lower()
            if not name or key in seen:
                continue
            seen.add(key)
            merged.append(name)
        return merged or [self._config.font_family or "Segoe UI"]

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def finalize(self) -> None:
        """Called by the workflow controller and by the footer action."""
        if not self._items:
            return
        self._commit_text()
        sections = self.workflow.total_marks()
        translated = self.workflow.translated_marks()
        dialog = ExportDialog(
            self,
            initial_dir=self._items[0][0].parent / TRANSLATION_DIR_NAME,
            pages=len(self._items),
            sections=sections,
            skipped=sections - translated,
            estimated_mb=len(self._items) * MB_PER_PAGE,
        )
        if dialog.result is None:
            return
        out_dir, open_when_done = dialog.result

        self._status.set("Exportando…", "working")
        self.update_idletasks()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            results = export_translations(
                items=self._items,
                stores=self._stores,
                out_dir=out_dir,
                config=self._config,
            )
        except Exception as exc:
            log.exception("Error exportando: %s", exc)
            # Un modal aquí repetía lo que la barra dice justo debajo. La
            # exportación es lo último del flujo: quien la lanzó está
            # mirando, y el detalle largo va al log.
            self._status.set(f"La exportación falló: {exc}", "error")
            return

        for store in self._stores:
            store.save()
        written = sum(1 for r in results if r.out_path and r.out_path.exists())
        drawn = sum(r.translated_count for r in results)
        skipped = sum(r.skipped_count for r in results)
        self._show_export_report(out_dir, written, drawn, skipped)
        if open_when_done:
            self._open_folder(out_dir)

    def _on_finalize(self) -> None:
        self.finalize()

    def _show_export_report(
        self, out_dir: Path, written: int, drawn: int, skipped: int,
    ) -> None:
        """Replace the canvas with the report, keeping the rail in step 4."""
        for widget in list(self._stage.winfo_children()):
            widget.destroy()
        self._topbar.pack_forget()
        pages = f"{written} página" + ("s" if written != 1 else "")
        self._status.set(f"{pages} escritas · {drawn} secciones dibujadas", "success")
        self._status.set_hint("")

        panel = tk.Frame(self._stage, bg=COLOR_BG, padx=40, pady=36)
        panel.pack(fill=tk.BOTH, expand=True)
        theme.kicker(panel, "Paso 4 de 4 · terminado").pack(fill=tk.X)
        theme.heading(
            panel, f"{written} páginas exportadas", size=26,
        ).pack(fill=tk.X, pady=(6, 8))
        theme.body(
            panel,
            "Los PNG renderizados y sus sidecars están en la carpeta de "
            "destino. El capítulo queda guardado por si quieres retocar "
            "una sección.",
            size=10, wrap=520,
        ).pack(fill=tk.X, pady=(0, 20))

        path_row = tk.Frame(
            panel, bg=COLOR_SURFACE, padx=16, pady=14,
            highlightthickness=2,
            highlightbackground=COLOR_TEXT, highlightcolor=COLOR_TEXT,
        )
        path_row.pack(fill=tk.X, pady=(0, 18))
        tk.Label(
            path_row, text=str(out_dir), font=theme.mono_font(9),
            bg=COLOR_SURFACE, fg=COLOR_TEXT, anchor=tk.W,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        theme.button(
            path_row, "Abrir carpeta", lambda: self._open_folder(out_dir),
            variant="primary", padx=14, pady=9,
        ).pack(side=tk.RIGHT, padx=(16, 0))

        theme.rule(panel, thickness=2, color=COLOR_DIVIDER).pack(fill=tk.X)
        stats = tk.Frame(panel, bg=COLOR_BG)
        stats.pack(fill=tk.X)
        self._stat(stats, "Escritas", str(written), 0)
        self._stat(stats, "Secciones", str(drawn), 1)
        self._stat(stats, "Omitidas", str(skipped), 2, accent=bool(skipped))
        theme.rule(panel, thickness=2, color=COLOR_DIVIDER).pack(fill=tk.X)

        pending = self._skipped_sections()
        if pending:
            theme.kicker(
                panel, "Sin traducción — se exportaron limpias",
            ).pack(fill=tk.X, pady=(16, 8))
            listing = tk.Frame(panel, bg=COLOR_BG)
            listing.pack(fill=tk.X)
            for label in pending[:6]:
                row = tk.Frame(listing, bg=COLOR_SURFACE, padx=10, pady=8)
                row.pack(fill=tk.X, pady=(0, 1))
                theme.body(
                    row, label, size=9, bg=COLOR_SURFACE, fg=NEUTRAL_700,
                ).pack(side=tk.LEFT)

        self._sidebar.clear_view_sections()
        summary = self._sidebar.section("Última exportación")
        theme.body(
            summary,
            f"{written} PNG · {drawn} secciones dibujadas\n"
            f"{skipped} sin traducción\n{out_dir}",
            size=8, bg=SIDEBAR_BG, fg=NEUTRAL_700, wrap=210,
        ).pack(fill=tk.X)
        self._sidebar.set_footer(
            "Volver al inicio", self._back_to_home,
            hint="El capítulo se conserva por si quieres retocarlo",
            variant="secondary",
        )

    def _stat(
        self, parent: tk.Misc, label: str, value: str, column: int,
        *, accent: bool = False,
    ) -> None:
        parent.grid_columnconfigure(column, weight=1, uniform="stat")
        cell = tk.Frame(parent, bg=COLOR_BG, pady=14)
        cell.grid(row=0, column=column, sticky="ew")
        theme.kicker(
            cell, label, fg=COLOR_ACCENT if accent else NEUTRAL_600,
        ).pack(fill=tk.X, pady=(0, 6))
        tk.Label(
            cell, text=value, font=theme.heading_font(20),
            bg=COLOR_BG, fg=COLOR_ACCENT if accent else COLOR_TEXT,
            anchor=tk.W,
        ).pack(fill=tk.X)

    def _skipped_sections(self) -> list[str]:
        labels: list[str] = []
        for page, store in enumerate(self._stores):
            for mark_id in range(len(store)):
                entry = store.get_translation(mark_id)
                if entry is not None and entry.text.strip():
                    continue
                ocr = store.get_ocr(mark_id)
                reason = (
                    f"OCR con confianza {ocr.confidence}"
                    if ocr is not None and ocr.text.strip()
                    else "sin texto reconocido"
                )
                labels.append(f"{page + 1:02d}·{mark_id + 1:02d} · {reason}")
        return labels

    def _back_to_home(self) -> None:
        self.workflow.reset()

    @staticmethod
    def _open_folder(path: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            log.warning("No se pudo abrir la carpeta %s: %s", path, exc)
