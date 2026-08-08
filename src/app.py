"""Main application controller.

Owns the Tk root window, the persistent sidebar (with step indicator),
and the content area. The app drives a 4-step workflow via
:class:`WorkflowController`:

    1. Home        -> load images
    2. Marks       -> draw rectangles, OCR + clean
    3. OCR review  -> check / edit translations
    4. Render      -> per-section tweaks, export

Each step is rendered by a dedicated view; the sidebar shows the
section list and the Continue / Back / Finalize buttons provided by
the active view.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable

from PIL import Image

from src.config import (
    COLOR_BG,
    COLOR_TEXT,
    WINDOW_HEIGHT,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_TITLE,
    WINDOW_WIDTH,
)
from src.utils import recent_paths
from src.utils.clean_queue import CleanJob, CleanQueue
from src.utils.crop_manager import CropManager
from src.utils.dnd_handler import create_dnd_root
from src.utils.inpainter import (
    Inpainter,
    clean_is_stale,
    install_instructions as inpaint_instructions,
    marks_signature,
)
from src.utils.logger import get_logger, log_file_path
from src.utils.ocr_engine import OcrEngine, find_tesseract, install_instructions
from src.utils.pipeline_runner import PipelineRunner
from src.utils.translation_runner import TranslationRunner
from src.utils.translator import Translator, install_instructions as translator_instructions
from src.views.home_view import HomeView
from src.views.marks_view import MarksView
from src.views.ocr_review_view import OcrReviewView
from src.views.render_view import RenderView
from src.views import theme
from src.views.sidebar import Sidebar
from src.workflow.controller import WorkflowController, WorkflowStep

log = get_logger("app")

ImageItem = tuple[Path, Image.Image]


class App:
    """Top-level controller. Drives the linear workflow."""

    def __init__(self) -> None:
        log.info("Iniciando aplicacion")
        log.info("Archivo de log: %s", log_file_path())

        self._engine = OcrEngine()
        self._inpainter = Inpainter()
        self._translator = Translator()
        self._crop_manager = CropManager()

        try:
            root_cls = create_dnd_root()
            self.root: tk.Tk = root_cls()
        except Exception as exc:
            log.exception("No se pudo crear la ventana raiz: %s", exc)
            self._crop_manager.cleanup()
            raise

        self.root.title(WINDOW_TITLE)
        self.root.configure(bg=COLOR_BG)
        self.root.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self._center_window(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root._app = self
        theme.init(self.root)

        self._translation_runner = TranslationRunner(self._translator)
        self._pipeline_runner = PipelineRunner(self._engine, self._crop_manager)
        self._clean_queue = CleanQueue(self._inpainter)

        self._current_view: tk.Widget | None = None
        self.workflow: WorkflowController | None = None

        self._log_status()
        self._build_layout()
        # The cleaning queue is polled on the root window, not on a view.
        # It has to survive every step change: its whole point is to keep
        # grinding while the chapter is translated.
        self._clean_queue.attach(
            self.root,
            on_progress=self._on_clean_progress,
            on_page_done=self._on_clean_page_done,
            on_finished=self._on_clean_finished,
        )
        self._render_current_step()

    def _log_status(self) -> None:
        if not self._engine.is_available():
            binary = self._engine.binary_path() or find_tesseract() or "(no encontrado)"
            log.warning("OCR no disponible. Buscado en: %s", binary)
            log.warning("Para instalar: %s", install_instructions())
        else:
            log.info(
                "OCR Tesseract v%s en %s",
                self._engine.version() or "?",
                self._engine.binary_path(),
            )
            langs = self._engine.available_languages()
            log.info("Idiomas OCR disponibles: %s", ", ".join(langs) or "(ninguno)")
        if not self._inpainter.is_available():
            log.warning("LaMa no disponible: %s", inpaint_instructions())
        else:
            log.info("LaMa disponible para limpieza de imagenes")
        if not self._translator.is_available():
            log.warning("Argos no disponible: %s", translator_instructions())
        else:
            pairs = self._translator.installed_pairs()
            log.info(
                "Argos listo: %d par(es) instalado(s): %s",
                len(pairs), ", ".join(p.label for p in pairs) or "(ninguno)",
            )

    def _center_window(self, width: int, height: int) -> None:
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _build_layout(self) -> None:
        self._sidebar = Sidebar(
            self.root,
            ocr_status=self._ocr_status_text(),
            ocr_available=self._engine.is_available(),
            inpaint_available=self._inpainter.is_available(),
            inpaint_status=self._inpaint_status_text(),
            recent_label=recent_paths.display_name(),
        )
        self._sidebar.pack(side=tk.LEFT, fill=tk.Y)
        # The 2 px ink rule that separates the rail from the canvas.
        tk.Frame(self.root, bg=COLOR_TEXT, width=2).pack(side=tk.LEFT, fill=tk.Y)
        self._content = tk.Frame(self.root, bg=COLOR_BG)
        self._content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _ocr_status_text(self) -> str:
        if not self._engine.is_available():
            return "No disponible"
        version = self._engine.version() or "?"
        return f"v{version}"

    def _inpaint_status_text(self) -> str:
        return "Listo" if self._inpainter.is_available() else "No disponible"

    # ------------------------------------------------------------------
    # View factory
    # ------------------------------------------------------------------

    def _render_current_step(self) -> None:
        """Build / rebuild the view for the workflow's current step."""
        step = (
            self.workflow.current_step
            if self.workflow is not None
            else WorkflowStep.HOME
        )
        if step == WorkflowStep.HOME or self.workflow is None:
            self._build_home()
        elif step == WorkflowStep.MARKS:
            self._build_marks()
        elif step == WorkflowStep.OCR_REVIEW:
            self._build_ocr_review()
        elif step == WorkflowStep.RENDER:
            self._build_render()
        # Update step indicator.
        highest = (
            int(self.workflow.highest_reached())
            if self.workflow is not None
            else 1
        )
        self._sidebar.set_step_indicator(int(step), highest)

    def _swap_view(self, factory: Callable[[], tk.Widget]) -> None:
        # Stop child workers. The cleaning queue is not one of them: it
        # is polled on the root window so it survives every view swap.
        for runner in (self._translation_runner, self._pipeline_runner):
            try:
                runner.detach()
            except Exception:
                pass
        # Each step owns the rail below the step list, so hand it back
        # empty before the next view claims it.
        self._sidebar.clear_view_sections()
        self._sidebar.clear_footer()
        self._sidebar.show_engines(visible=False)
        if self._current_view is not None:
            try:
                self._current_view.destroy()
            except Exception as exc:
                log.warning("Error destruyendo vista previa: %s", exc)
            self._current_view = None
        try:
            view = factory()
            self._current_view = view
            view.pack(in_=self._content, fill=tk.BOTH, expand=True)
            try:
                view.focus_set()
            except Exception:
                pass
        except Exception as exc:
            log.exception("Error creando vista: %s", exc)
            messagebox_safe(str(exc), self.root)

    def set_context(self, text: str | None = None) -> None:
        """Mirror the mockups' title-bar context line into the OS title."""
        self.root.title(
            WINDOW_TITLE if not text else f"{WINDOW_TITLE}  —  {text}"
        )

    def chapter_name(self) -> str:
        if self.workflow is not None and self.workflow.items:
            return self.workflow.items[0][0].parent.name or "capítulo"
        return "capítulo"

    def _build_home(self) -> None:
        self.set_context(None)

        def factory() -> tk.Widget:
            return HomeView(
                self._content, workflow=self.workflow, sidebar=self._sidebar,
            )
        self._swap_view(factory)

    def _build_marks(self) -> None:
        if self.workflow is None or not self.workflow.items:
            self._render_current_step_to_home()
            return
        def factory() -> tk.Widget:
            return MarksView(
                self._content, self.workflow, self._sidebar,
                engine=self._engine,
                pipeline_runner=self._pipeline_runner,
            )
        self._swap_view(factory)

    def _build_ocr_review(self) -> None:
        if self.workflow is None or not self.workflow.items:
            self._render_current_step_to_home()
            return
        def factory() -> tk.Widget:
            return OcrReviewView(
                self._content, self.workflow, self._sidebar,
                translator=self._translator,
                translation_runner=self._translation_runner,
            )
        self._swap_view(factory)

    def _build_render(self) -> None:
        if self.workflow is None or not self.workflow.items:
            self._render_current_step_to_home()
            return
        def factory() -> tk.Widget:
            return RenderView(self._content, self.workflow, self._sidebar)
        self._swap_view(factory)

    # ------------------------------------------------------------------
    # Background cleaning
    # ------------------------------------------------------------------

    def start_background_clean(self) -> int:
        """Queue every marked page whose clean version is missing or stale.

        Called when step 2 hands over to step 3. Pages already queued are
        skipped, so coming back to «Marcar», touching one box and
        continuing again costs exactly that one page.
        """
        if self.workflow is None or not self.workflow.items:
            return 0
        if not self._inpainter.is_available():
            log.warning("LaMa no disponible: no se limpiara en segundo plano")
            return 0
        jobs: list[CleanJob] = []
        for index, (path, image) in enumerate(self.workflow.items):
            if index >= len(self.workflow.stores):
                break
            store = self.workflow.stores[index]
            marks = list(store)
            if not clean_is_stale(path, marks, store.clean_signature):
                continue
            jobs.append(CleanJob(
                image_index=index, path=path, image=image, marks=marks,
                signature=marks_signature(marks),
            ))
        added = self._clean_queue.enqueue(jobs)
        if added:
            done, total = self._clean_queue.progress()
            self._sidebar.set_clean_progress(done, total, "")
        return added

    def clean_pending(self) -> int:
        """Pages still waiting for LaMa, including the one in flight."""
        return self._clean_queue.pending()

    def _on_clean_progress(self, done: int, total: int, label: str) -> None:
        self._sidebar.set_clean_progress(done, total, label)

    def _on_clean_page_done(
        self, image_index: int, path: Path, success: bool, signature: str,
    ) -> None:
        store = None
        if self.workflow is not None and 0 <= image_index < len(self.workflow.stores):
            store = self.workflow.stores[image_index]
        if store is None or store.image_path != path:
            # The chapter changed while this page was in flight, so the
            # index no longer points at the page that was cleaned.
            log.info("Limpieza de %s descartada: el capitulo cambio", path.name)
            return
        if success:
            # Recorded only now: a signature written before the file
            # exists would make a crashed run look finished.
            store.clean_signature = signature
        self._notify_view("on_clean_page_done", image_index, success)

    def _on_clean_finished(self, done: int, failed: int) -> None:
        self._sidebar.set_clean_progress(0, 0, "")
        if failed:
            log.warning("Limpieza terminada: %d hecha(s), %d fallida(s)", done, failed)
        elif done:
            log.info("Limpieza terminada: %d pagina(s)", done)
        self._notify_view("on_clean_finished", done, failed)

    def _notify_view(self, hook_name: str, *args) -> None:
        """Tell the on-screen view about the queue, if it cares."""
        hook = getattr(self._current_view, hook_name, None)
        if hook is None:
            return
        try:
            hook(*args)
        except Exception as exc:
            log.exception("Error en %s: %s", hook_name, exc)

    def _render_current_step_to_home(self) -> None:
        if self.workflow is not None:
            self.workflow.go_to(WorkflowStep.HOME)
        else:
            self._render_current_step()

    # ------------------------------------------------------------------
    # Loading helpers
    # ------------------------------------------------------------------

    def _ensure_workflow(self, items: list[ImageItem]) -> None:
        if self.workflow is None:
            self.workflow = WorkflowController(self, items)
        else:
            self.workflow.items = list(items)
            self.workflow.reload_stores()

    def _open_files_drop(self, paths: list[str]) -> None:
        try:
            from src.utils import image_loader
            path_objs = [Path(p) for p in paths]
            expanded = image_loader.expand_paths(path_objs)
            items, failed = image_loader.load_images_with_paths(expanded)
            if failed:
                theme.alert(
                    self.root,
                    "Algunas imágenes no pudieron cargarse",
                    f"No se pudieron abrir {len(failed)} archivo(s).",
                    level="error",
                )
            if not items:
                theme.alert(
                    self.root,
                    "Sin imágenes",
                    "No se encontraron imágenes válidas en lo que se abrió.",
                )
                return
            # Every way in lands here, so this is the one place that has
            # to remember the chapter for the «Recientes» rail.
            recent_paths.save(items[0][0].parent)
            self._refresh_recent_label()
            # Whatever was still queued belongs to the chapter being
            # replaced; the page in flight is allowed to finish and is
            # dropped on arrival.
            self._clean_queue.clear()
            self._sidebar.set_clean_progress(0, 0, "")
            self._ensure_workflow(items)
            self.workflow.go_to(WorkflowStep.MARKS)
        except Exception as exc:
            log.exception("Error en drop: %s", exc)
            messagebox_safe(str(exc), self.root)

    def _prompt_open_files(self) -> None:
        """Ask for the chapter's folder, and only that.

        This used to open the file picker first and, if you cancelled it,
        show a folder picker straight after. Cancelling is how you say
        "not now", so answering it with a second dialog read as the app
        refusing to take no for an answer. Loose images still come in by
        dropping them on the zone, which is a deliberate gesture rather
        than a dialog you dismissed.
        """
        try:
            from tkinter import filedialog
            initial = recent_paths.load()
            folder = filedialog.askdirectory(
                title="Selecciona la carpeta del capitulo",
                initialdir=str(initial) if initial else None,
                mustexist=True,
            )
            if folder:
                self._open_files_drop([folder])
        except Exception as exc:
            log.exception("Error abriendo dialogo: %s", exc)
            messagebox_safe(f"No se pudo abrir el dialogo:\n{exc}", self.root)

    def _prompt_open_recent(self, folder: Path | None = None) -> None:
        target = folder if folder is not None else recent_paths.load()
        if target is None:
            messagebox_safe("No hay una carpeta reciente valida.", self.root)
            return
        if not target.is_dir():
            # It was there when we wrote it down; say so and stop
            # offering it instead of failing silently every click.
            recent_paths.forget(target)
            self._refresh_recent_label()
            messagebox_safe(f"La carpeta ya no existe:\n{target}", self.root)
            return
        self._open_files_drop([str(target)])

    def _refresh_recent_label(self) -> None:
        if self._sidebar is not None:
            self._sidebar.set_recent_label(recent_paths.display_name())

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        log.info("Cerrando aplicacion")
        for runner in (self._translation_runner, self._pipeline_runner,
                       self._clean_queue):
            try:
                if runner.is_running():
                    runner.cancel()
            except Exception:
                pass
            try:
                runner.detach()
            except Exception:
                pass
        self._crop_manager.cleanup()
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self) -> None:
        try:
            self.root.mainloop()
        except Exception as exc:
            log.exception("Error en mainloop: %s", exc)
            raise
        finally:
            for runner in (self._translation_runner, self._pipeline_runner,
                           self._clean_queue):
                try:
                    runner.detach()
                except Exception:
                    pass
            self._crop_manager.cleanup()
            log.info("Aplicacion finalizada")


def messagebox_safe(message: str, master: tk.Misc | None = None) -> None:
    """Show an error without crashing if nothing can be painted yet.

    Every caller is an exception handler, and some of them can fire
    before ``theme.init(root)`` has run or before there is a window to
    put a dialog on. So the app's own dialog is attempted first and the
    native box stays underneath as the floor: it must never be the error
    report that dies reporting the error.
    """
    if master is not None:
        try:
            theme.alert(master, "Error", message, level="error")
            return
        except Exception:
            log.exception("El dialogo propio fallo, se usa el nativo")
    try:
        from tkinter import messagebox
        messagebox.showerror("Error", message)
    except Exception:
        log.error("No se pudo mostrar messagebox: %s", message)
