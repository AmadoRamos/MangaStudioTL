"""Step 3 — review the OCR and its translation.

The chapter's sections in one table (see :mod:`translation_table`),
filtered by the three chips in the control strip. The rail carries the
language pair, how the pair was installed, and how much of the chapter
is translated; the anchored action moves on to the render step.

When Tesseract never ran, the step does not throw a modal: the problem,
its cause and the way out are stated inside the screen — a banner with
the path that was searched, and a body that offers to type the text by
hand instead.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog

from PIL import Image

from src.config import (
    ACCENT_100,
    ACCENT_700,
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DIVIDER,
    COLOR_TEXT,
    NEUTRAL_600,
    NEUTRAL_700,
    SIDEBAR_BG,
    TRANSLATION_DEFAULT_SRC,
    TRANSLATION_DEFAULT_TGT,
    TRANSLATION_LANGS,
)
from src.utils.logger import get_logger
from src.utils.marks_store import MarksStore, OcrEntry, TranslationEntry
from src.utils.translation_runner import TranslationRunner
from src.utils.translator import Translator
from src.views import theme
from src.views.toolbar import StatusBar
from src.views.translation_table import (
    FILTER_ALL,
    FILTER_LOW,
    FILTER_PENDING,
    TranslationTable,
)

log = get_logger("ocr_review_view")


class OcrReviewView(tk.Frame):
    """Step 3 view: OCR + translation review across the whole chapter."""

    def __init__(
        self,
        master: tk.Misc,
        workflow,
        sidebar,
        translator: Translator,
        translation_runner: TranslationRunner,
    ) -> None:
        super().__init__(master, bg=COLOR_BG)
        self.workflow = workflow
        self._sidebar = sidebar
        self._translator = translator
        self._translation_runner = translation_runner
        self._items: list[tuple[Path, Image.Image]] = list(workflow.items)
        self._stores: list[MarksStore] = list(workflow.stores)

        self._source_lang: str = TRANSLATION_DEFAULT_SRC
        self._target_lang: str = TRANSLATION_DEFAULT_TGT
        self._src_var: tk.StringVar | None = None
        self._tgt_var: tk.StringVar | None = None
        self._pair_card: tk.Frame | None = None
        self._progress_label: tk.Label | None = None
        self._progress_meter: theme.Meter | None = None
        self._filter_bar: theme.SegmentedBar | None = None

        self._build_ui()
        self._build_sidebar_sections()
        self._translation_runner.attach(
            self,
            on_mark_done=self._on_translation_done,
            on_progress=self._on_translation_progress,
            on_done=self._on_translation_done_overall,
        )
        self._table.set_stores(self._stores)
        self._refresh_counts()
        self._set_context()
        self.after(200, self._auto_translate_if_pending)

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._topbar = theme.TopBar(self)
        self._topbar.pack(side=tk.TOP, fill=tk.X)
        row = self._topbar.body

        self._filter_bar = theme.SegmentedBar(
            row, border_width=2, uniform_chars=theme.SEGMENT_CHARS,
        )
        self._filter_bar.pack(side=tk.LEFT, pady=6)
        self._filter_bar.add(
            FILTER_ALL, "Todas", lambda: self._set_filter(FILTER_ALL),
        )
        self._filter_bar.add(
            FILTER_PENDING, "Pendientes",
            lambda: self._set_filter(FILTER_PENDING),
            tooltip="Secciones que aún no tienen traducción",
        )
        self._filter_bar.add(
            FILTER_LOW, "Confianza baja",
            lambda: self._set_filter(FILTER_LOW),
            tooltip="El OCR no está seguro: conviene revisarlas",
        )
        self._filter_bar.set_active(FILTER_ALL)

        self._topbar.gap()

        # Same ink border and weight as the filter strip beside them:
        # with the faint «secondary» outline these three read as labels
        # rather than as something you can press.
        for text, command, hint, last in (
            ("⌕ Extraer texto", self._extract_ocr,
             "Vuelve al paso 2 y lee con Tesseract las secciones que aún "
             "no tienen texto", False),
            ("↻ Re-traducir todo", self._translate_all,
             "Vuelve a traducir todas las secciones con OCR", False),
            ("⬇ Descargar par", self._ensure_pair_clicked,
             "Instala el par origen → destino de Argos", True),
        ):
            theme.button(
                row, text, command,
                variant="outline", border_width=2,
                size=8, padx=12, pady=4, tooltip=hint,
            ).pack(side=tk.LEFT, padx=(0, 0 if last else 8), pady=6)

        # The banner only appears when OCR never produced anything.
        self._banner = tk.Frame(self, bg=ACCENT_100)
        self._body = tk.Frame(self, bg=COLOR_BG)
        self._body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._table = TranslationTable(
            self._body,
            on_translate_row=self._on_table_translate_row,
            on_translation_edited=self._on_table_translation_edited,
            on_translation_deleted=self._on_table_translation_deleted,
            on_ocr_edited=self._on_table_ocr_edited,
        )
        self._table.pack(fill=tk.BOTH, expand=True)

        self._status = StatusBar(self)
        self._status.pack(side=tk.BOTTOM, fill=tk.X)
        self._status.set("Doble clic para editar una celda", "info")
        self._status.set_hint(
            "Enter = guardar · Tab = siguiente celda · Supr = borrar traducción"
        )
        self._refresh_empty_state()

    def _refresh_empty_state(self) -> None:
        """Swap the table for the no-OCR explanation when it is empty."""
        has_ocr = any(
            store.get_ocr(mid) is not None
            and store.get_ocr(mid).text.strip()
            for store in self._stores
            for mid in range(len(store))
        )
        if has_ocr:
            self._banner.pack_forget()
            for widget in list(self._body.winfo_children()):
                if widget is not self._table:
                    widget.destroy()
            if not self._table.winfo_manager():
                self._table.pack(fill=tk.BOTH, expand=True)
            return

        self._table.pack_forget()
        self._build_banner()
        self._build_no_ocr_body()

    def _build_banner(self) -> None:
        for widget in list(self._banner.winfo_children()):
            widget.destroy()
        self._banner.pack(side=tk.TOP, fill=tk.X, after=self._topbar)
        inner = tk.Frame(self._banner, bg=ACCENT_100, padx=14, pady=12)
        inner.pack(fill=tk.X)
        text = tk.Frame(inner, bg=ACCENT_100)
        text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        theme.heading(
            text, "No hay texto reconocido en este capítulo",
            size=10, bg=ACCENT_100,
        ).pack(fill=tk.X)
        theme.body(
            text, f"Ruta buscada: {self._tesseract_path()}",
            size=8, bg=ACCENT_100, fg=NEUTRAL_700,
        ).pack(fill=tk.X, pady=(3, 0))
        theme.button(
            inner, "Extraer texto", self._extract_ocr,
            variant="primary", size=8, padx=10, pady=7,
        ).pack(side=tk.RIGHT, padx=(8, 0))
        theme.button(
            inner, "Elegir ruta…", self._choose_tesseract,
            variant="outline", border_width=2, size=8, padx=10, pady=7,
        ).pack(side=tk.RIGHT)
        theme.rule(self._banner, thickness=2, color=COLOR_TEXT).pack(
            side=tk.BOTTOM, fill=tk.X,
        )

    def _build_no_ocr_body(self) -> None:
        for widget in list(self._body.winfo_children()):
            if widget is not self._table:
                widget.destroy()
        panel = tk.Frame(self._body, bg=COLOR_BG, padx=40)
        panel.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(panel, bg=COLOR_BG)
        inner.place(relx=0.0, rely=0.5, anchor=tk.W)
        theme.kicker(inner, "Tabla vacía").pack(fill=tk.X, pady=(0, 14))
        marks = self.workflow.total_marks()
        theme.heading(
            inner,
            f"Las {marks} marcas del capítulo están limpias, pero sin OCR",
            size=16, wrap=460,
        ).pack(fill=tk.X)
        theme.body(
            inner,
            "Puedes escribir la traducción a mano en cada sección y seguir "
            "al paso 4, o instalar Tesseract y reintentar.",
            size=9, wrap=460,
        ).pack(fill=tk.X, pady=(12, 0))
        theme.button(
            inner, "Escribir el texto a mano", self._write_by_hand,
            variant="outline", border_width=2, padx=14, pady=9,
        ).pack(anchor=tk.W, pady=(14, 0))

    def _tesseract_path(self) -> str:
        app = getattr(self.winfo_toplevel(), "_app", None)
        engine = getattr(app, "_engine", None) if app else None
        if engine is not None:
            try:
                return engine.binary_path() or "(no encontrado en el PATH)"
            except Exception:
                pass
        return "(no encontrado en el PATH)"

    def _choose_tesseract(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Selecciona tesseract.exe",
            filetypes=[("Ejecutable", "*.exe"), ("Todos", "*.*")],
            parent=self,
        )
        if not chosen:
            return
        app = getattr(self.winfo_toplevel(), "_app", None)
        engine = getattr(app, "_engine", None) if app else None
        if engine is None:
            return
        try:
            engine.set_binary_path(Path(chosen))
        except Exception as exc:
            log.exception("No se pudo fijar la ruta de Tesseract: %s", exc)
            self._status.set(f"Ruta no válida: {exc}", "error")
            return
        self._refresh_empty_state()

    def _extract_ocr(self) -> None:
        """Go back to step 2 and start the extraction there.

        Tesseract, the progress meters and the mark list all live in step
        2; running the OCR from here would mean a second copy of all
        three. Since this view is destroyed by the step change, every
        reference it needs is taken before the move.
        """
        app = getattr(self.winfo_toplevel(), "_app", None)
        workflow = self.workflow
        if app is None or workflow is None:
            return
        workflow.back_step()
        view = getattr(app, "_current_view", None)
        run = getattr(view, "run_pipeline", None)
        if callable(run):
            # After the view has drawn itself, so the progress rail is
            # already on screen when the first mark comes back.
            view.after(80, run)

    def _write_by_hand(self) -> None:
        """Seed empty translations so every mark gets an editable row."""
        for store in self._stores:
            for mark_id in range(len(store)):
                if store.get_translation(mark_id) is None:
                    store.set_translation(mark_id, TranslationEntry(
                        text="", source_lang=self._source_lang,
                        target_lang=self._target_lang, engine="manual",
                        edited=True, ran_at="",
                    ))
        self._banner.pack_forget()
        for widget in list(self._body.winfo_children()):
            if widget is not self._table:
                widget.destroy()
        self._table.pack(fill=tk.BOTH, expand=True)
        self._table.refresh()
        self._status.set(
            "Doble clic en la columna Traducción para escribir el texto", "info",
        )

    # ------------------------------------------------------------------
    # Rail
    # ------------------------------------------------------------------

    def _build_sidebar_sections(self) -> None:
        self._sidebar.clear_view_sections()

        langs = self._sidebar.section("Idiomas")
        row = tk.Frame(langs, bg=SIDEBAR_BG)
        row.pack(fill=tk.X)
        self._src_var = self._lang_selector(
            row, "Origen", self._source_lang, self._on_source_change,
        )
        theme.body(row, "→", size=10, bg=SIDEBAR_BG, fg=COLOR_TEXT).pack(
            side=tk.LEFT, padx=6, pady=(14, 0),
        )
        self._tgt_var = self._lang_selector(
            row, "Destino", self._target_lang, self._on_target_change,
        )
        self._pair_card = tk.Frame(langs, bg=SIDEBAR_BG)
        self._pair_card.pack(fill=tk.X, pady=(10, 0))
        self._refresh_pair_card()

        self._sidebar.section_divider()

        progress = self._sidebar.section("Progreso")
        self._progress_label = theme.body(
            progress, "", size=8, bg=SIDEBAR_BG, fg=NEUTRAL_700,
        )
        self._progress_label.pack(fill=tk.X, pady=(0, 6))
        self._progress_meter = theme.Meter(progress, height=6)
        self._progress_meter.pack(fill=tk.X)

        self._sidebar.set_footer(
            "Continuar proceso →", self._on_continue,
            hint="Pasa al render con las traducciones actuales",
            secondary_text="← Atrás", secondary_command=self._on_back,
        )
        self._refresh_progress()

    def _lang_selector(
        self, parent: tk.Misc, label: str, code: str, command,
    ) -> tk.StringVar:
        column = tk.Frame(parent, bg=SIDEBAR_BG)
        column.pack(side=tk.LEFT, fill=tk.X, expand=True)
        theme.field_label(column, label).pack(fill=tk.X, pady=(0, 5))
        var = tk.StringVar(value=self._label_for_code(code))
        theme.option_menu(
            column, var, TRANSLATION_LANGS.keys(), command,
        ).pack(fill=tk.X)
        return var

    def _refresh_pair_card(self) -> None:
        if self._pair_card is None:
            return
        for widget in list(self._pair_card.winfo_children()):
            widget.destroy()
        installed = self._translator.is_pair_available(
            self._source_lang, self._target_lang,
        )
        pair = f"{self._source_lang}→{self._target_lang}"
        card = theme.card(
            self._pair_card, bg=SIDEBAR_BG,
            border=COLOR_DIVIDER if installed else COLOR_ACCENT,
            border_width=1 if installed else 2,
        )
        card.pack(fill=tk.X)
        dot = tk.Frame(
            card, bg=COLOR_ACCENT if installed else NEUTRAL_600,
            width=8, height=8,
        )
        dot.pack(side=tk.LEFT, padx=(0, 9), pady=(4, 0), anchor=tk.N)
        text = tk.Frame(card, bg=SIDEBAR_BG)
        text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        theme.body(
            text,
            f"Par {pair} {'instalado' if installed else 'sin instalar'}",
            size=8, bg=SIDEBAR_BG, fg=COLOR_TEXT, weight="bold", wrap=180,
        ).pack(fill=tk.X)
        theme.body(
            text,
            "Argos · offline" if installed
            else "Pulsa «Descargar par» para bajarlo",
            size=8, bg=SIDEBAR_BG,
            fg=NEUTRAL_600 if installed else ACCENT_700, wrap=180,
        ).pack(fill=tk.X)

    def _refresh_progress(self) -> None:
        total = self.workflow.total_marks()
        translated = self.workflow.translated_marks()
        edited = sum(
            1 for store in self._stores
            for entry in store.translations.values()
            if entry.edited and entry.text.strip()
        )
        if self._progress_label is not None:
            detail = f"{translated} de {total} traducidas"
            if edited:
                detail += f" · {edited} editada(s)"
            self._progress_label.configure(text=detail)
        if self._progress_meter is not None:
            self._progress_meter.set(translated / total if total else 0.0)
        self._sidebar.set_footer_state(translated > 0)
        if translated == 0:
            self._sidebar.set_footer_hint(
                "Traduce al menos una sección para continuar",
            )
        else:
            self._sidebar.set_footer_hint(
                f"Pasa al render con {translated} sección(es)",
            )

    def _refresh_counts(self) -> None:
        if self._filter_bar is None:
            return
        counts = self._table.counts()
        self._filter_bar.set_text(FILTER_ALL, f"Todas {counts[FILTER_ALL]}")
        self._filter_bar.set_text(
            FILTER_PENDING, f"Pendientes {counts[FILTER_PENDING]}",
        )
        self._filter_bar.set_text(
            FILTER_LOW, f"Confianza baja {counts[FILTER_LOW]}",
        )

    def _set_filter(self, mode: str) -> None:
        if self._filter_bar is not None:
            self._filter_bar.set_active(mode)
        self._table.set_filter(mode)

    def _set_context(self) -> None:
        app = getattr(self.winfo_toplevel(), "_app", None)
        if app is not None and hasattr(app, "set_context"):
            app.set_context(f"{app.chapter_name()} · revisión")

    # ------------------------------------------------------------------
    # Languages
    # ------------------------------------------------------------------

    def _label_for_code(self, code: str) -> str:
        for label, value in TRANSLATION_LANGS.items():
            if value == code:
                return label
        return code

    def _code_for_label(self, label: str) -> str:
        return TRANSLATION_LANGS.get(label, label)

    def _on_source_change(self, _label: str) -> None:
        if self._src_var is None:
            return
        self._source_lang = self._code_for_label(self._src_var.get())
        self._refresh_pair_card()

    def _on_target_change(self, _label: str) -> None:
        if self._tgt_var is None:
            return
        self._target_lang = self._code_for_label(self._tgt_var.get())
        self._refresh_pair_card()

    def _ensure_pair_clicked(self) -> None:
        pair = f"{self._source_lang}→{self._target_lang}"
        if self._translator.is_pair_available(
            self._source_lang, self._target_lang,
        ):
            # Pulsar «Descargar» y que no se descargue nada es lo único
            # que hay que contestar con un modal aun habiendo barra: la
            # barra cuenta lo que ocurre, no responde a un clic que no
            # hizo nada. La tarjeta se rehace por si estaba desfasada.
            self._refresh_pair_card()
            theme.alert(
                self,
                "Par ya instalado",
                f"El par {pair} ya estaba instalado. No hay nada que "
                "descargar.",
            )
            return

        self._status.set(f"Descargando el par {pair}…", "working")
        self.update_idletasks()
        ok = self._translator.ensure_pair(self._source_lang, self._target_lang)
        self._refresh_pair_card()
        if ok:
            self._status.set("Par instalado y listo para traducir", "success")
        else:
            self._status.set(
                "No se pudo instalar el par. Revisa logs/app.log", "error",
            )

    # ------------------------------------------------------------------
    # Table callbacks
    # ------------------------------------------------------------------

    def _on_table_ocr_edited(self, page: int, mark_id: int, text: str) -> None:
        store = self._stores[page]
        if not 0 <= mark_id < len(store):
            return
        existing = store.get_ocr(mark_id)
        store.set_ocr_result(mark_id, OcrEntry(
            text=text.strip(),
            confidence=existing.confidence if existing else 0,
            language=existing.language if existing else "eng",
            engine=existing.engine if existing else "manual",
            ran_at=existing.ran_at if existing else "",
        ))
        self._table.refresh()
        self._refresh_counts()

    def _on_table_translation_edited(
        self, page: int, mark_id: int, text: str,
    ) -> None:
        store = self._stores[page]
        if not 0 <= mark_id < len(store):
            return
        existing = store.get_translation(mark_id)
        # ``replace`` en vez de copiar campo a campo: así los ajustes de
        # la sección (color, fuente, tamaño, estilo) sobreviven a que
        # alguien retoque el texto aquí, y añadir uno nuevo no obliga a
        # acordarse de este sitio.
        if existing is not None:
            updated = replace(existing, text=text.strip(), edited=True)
        else:
            updated = TranslationEntry(
                text=text.strip(),
                source_lang=self._source_lang,
                target_lang=self._target_lang,
                engine="argos",
                edited=True,
                ran_at="",
            )
        store.set_translation(mark_id, updated)
        self._table.refresh()
        self._refresh_counts()
        self._refresh_progress()

    def _on_table_translation_deleted(self, page: int, mark_id: int) -> None:
        store = self._stores[page]
        if not 0 <= mark_id < len(store):
            return
        store._translations.pop(mark_id, None)
        store._dirty = True
        store.save()
        self._table.refresh()
        self._refresh_counts()
        self._refresh_progress()

    def _on_table_translate_row(self, page: int, mark_id: int) -> None:
        store = self._stores[page]
        if not 0 <= mark_id < len(store):
            return
        ocr = store.get_ocr(mark_id)
        if ocr is None or not ocr.text.strip():
            self._status.set("Esa sección no tiene texto OCR", "info")
            return
        if self._translation_runner.is_running():
            return
        self._translation_runner.run_for_mark(
            image_index=page, mark_id=mark_id,
            text=ocr.text, source_lang=self._source_lang,
            target_lang=self._target_lang,
        )
        self._table.set_running(page, mark_id, True)
        self._status.set(f"Traduciendo {page + 1:02d}·{mark_id + 1:02d}…", "working")

    # ------------------------------------------------------------------
    # Batch translation
    # ------------------------------------------------------------------

    def _pending_items(self, only_missing: bool) -> list:
        items = []
        for page, store in enumerate(self._stores):
            for mark_id, entry in store.ocr_results.items():
                if not entry.text.strip():
                    continue
                if only_missing:
                    translated = store.get_translation(mark_id)
                    if translated is not None and translated.text.strip():
                        continue
                items.append((
                    page, mark_id, entry.text,
                    self._source_lang, self._target_lang,
                ))
        return items

    def _auto_translate_if_pending(self) -> None:
        if not self._translator.is_available():
            return
        pending = self._pending_items(only_missing=True)
        if not pending:
            return
        log.info("Auto-traduciendo %d marcas pendientes", len(pending))
        self._translation_runner.run_for_all(pending)
        self._status.set(
            f"Auto-traduciendo {len(pending)} sección(es)…", "working",
        )

    def _translate_all(self) -> None:
        if self._translation_runner.is_running():
            return
        items = self._pending_items(only_missing=False)
        if not items:
            self._status.set("No hay secciones con texto OCR", "info")
            return
        self._translation_runner.run_for_all(items)
        self._status.set(f"Traduciendo {len(items)} sección(es)…", "working")

    def _on_translation_done(
        self, image_index, mark_id, text, source_lang, target_lang, error,
    ) -> None:
        self._table.set_running(image_index, mark_id, False)
        if not 0 <= image_index < len(self._stores):
            return
        store = self._stores[image_index]
        if not 0 <= mark_id < len(store):
            return
        if error:
            log.warning(
                "Traduccion pag %d marca %d: ERROR %s",
                image_index + 1, mark_id + 1, error,
            )
            return
        existing = store.get_translation(mark_id)
        # Vuelve a traducir el texto, pero conserva todo lo que la
        # sección tuviera puesto a mano.
        fresh = TranslationEntry(
            text=text,
            source_lang=source_lang,
            target_lang=target_lang,
            engine="argos",
            edited=False,
            ran_at="",
        )
        if existing is not None:
            fresh = replace(
                existing,
                text=text,
                source_lang=source_lang,
                target_lang=target_lang,
                engine="argos",
                edited=False,
                ran_at="",
            )
        store.set_translation(mark_id, fresh)

    def _on_translation_progress(
        self, current, total, image_index, mark_id,
    ) -> None:
        self._status.set(f"Traduciendo {current + 1} de {total}…", "working")

    def _on_translation_done_overall(self, success: bool, message: str) -> None:
        self._table.refresh()
        self._refresh_counts()
        self._refresh_progress()
        self._status.set(message, "success" if success else "error")

    # ------------------------------------------------------------------
    # Nav
    # ------------------------------------------------------------------

    def _on_back(self) -> None:
        self.workflow.back_step()

    def _on_continue(self) -> None:
        if self.workflow.translated_marks() == 0:
            self._status.set(
                "Traduce o escribe al menos una sección antes de continuar.",
                "info",
            )
            return
        # The render falls back to the original page while a clean
        # version is still being made, and swaps it in as each one
        # lands — but arriving to unclean pages with nothing having said
        # why reads as a bug, so say it here instead of blocking.
        pending = self._clean_pending()
        if pending and not theme.confirm(
            self,
            "Limpieza en curso",
            f"Quedan {pending} página(s) por limpiar.\n\n"
            "Puedes continuar: el render usa la original mientras tanto "
            "y cambia a la limpia en cuanto esté lista.",
            confirm_label="Continuar igualmente",
        ):
            return
        for store in self._stores:
            store.save()
        self.workflow.continue_step()

    def _clean_pending(self) -> int:
        app = getattr(self.workflow, "app", None)
        if app is None or not hasattr(app, "clean_pending"):
            return 0
        try:
            return int(app.clean_pending())
        except Exception:
            return 0

    def destroy(self) -> None:  # type: ignore[override]
        try:
            self._translation_runner.detach()
        except Exception:
            pass
        try:
            self._translation_runner.cancel()
        except Exception:
            pass
        super().destroy()
