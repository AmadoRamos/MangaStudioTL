"""Step 1 — open a chapter.

The mockups' first screen: a kicker, a large heading, one line about
what happens to the files, and a dashed drop zone that carries the two
ways in (drop or browse) plus the resume callout when a chapter was
left half-finished. The rail alongside carries the recent chapters and
the engine status.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

from src.config import (
    ACCENT_700,
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_SURFACE,
    COLOR_TEXT,
    NEUTRAL_600,
    SIDEBAR_BG,
    TRANSLATION_DEFAULT_SRC,
    TRANSLATION_DEFAULT_TGT,
)
from src.utils import image_loader, recent_paths
from src.utils.dnd_handler import DND_AVAILABLE, register_drop_target
from src.utils.logger import get_logger
from src.views import theme
from src.views.toolbar import Tooltip

log = get_logger("home_view")

#: How many remembered folders the rail lists. More than this and the
#: engine block gets pushed off the bottom on a short window.
RECENT_IN_RAIL = 5

STEP_NAMES: dict[int, str] = {
    1: "Inicio",
    2: "Marcar secciones",
    3: "Revisión OCR",
    4: "Render y export",
}


class HomeView(tk.Frame):
    """Step 1: load images, show recent folder, offer to resume."""

    def __init__(self, master: tk.Misc, workflow=None, sidebar=None) -> None:
        super().__init__(master, bg=COLOR_BG)
        self.workflow = workflow
        self._sidebar = sidebar
        self._build_ui()
        if sidebar is not None:
            self._build_sidebar_sections()
        register_drop_target(self, self._handle_drop)

    def set_workflow(self, workflow) -> None:
        self.workflow = workflow
        self._refresh_resume_callout()

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = tk.Frame(self, bg=COLOR_BG)
        outer.pack(fill=tk.BOTH, expand=True, padx=40, pady=36)

        theme.kicker(outer, "Paso 1 de 4").pack(fill=tk.X)
        theme.heading(outer, "Abre un capítulo", size=26).pack(
            fill=tk.X, pady=(6, 6),
        )
        theme.body(
            outer,
            "Arrastra una carpeta de imágenes aquí o selecciónala. "
            "Todo el proceso ocurre en tu equipo: sin subir nada.",
            size=10, wrap=520,
        ).pack(fill=tk.X, pady=(0, 22))

        zone = theme.DashedZone(outer, bg=COLOR_SURFACE)
        zone.pack(fill=tk.BOTH, expand=True)
        body = zone.body

        theme.kicker(body, "Arrastra y suelta", bg=COLOR_SURFACE).pack(
            fill=tk.X, pady=(24, 16),
        )
        theme.heading(
            body,
            "Suelta aquí una carpeta o imágenes sueltas (.jpg, .png)",
            size=16, bg=COLOR_SURFACE, wrap=420,
        ).pack(fill=tk.X)
        theme.button(
            body, "Abrir carpeta", self._on_open_files,
            variant="primary", padx=16, pady=10,
            tooltip="Elegir la carpeta con las páginas del capítulo",
        ).pack(anchor=tk.W, pady=(16, 0))

        if not DND_AVAILABLE:
            theme.body(
                body,
                "Instala «tkinterdnd2» (pip install tkinterdnd2) para "
                "habilitar arrastrar y soltar.",
                size=9, bg=COLOR_SURFACE, fg=ACCENT_700, wrap=420,
            ).pack(anchor=tk.W, pady=(12, 0))

        self._callout_host = tk.Frame(body, bg=COLOR_SURFACE)
        self._callout_host.pack(fill=tk.X, pady=(16, 24))
        self._refresh_resume_callout()

    def _refresh_resume_callout(self) -> None:
        """The «you left something half-done» box, with one way back in."""
        for widget in list(self._callout_host.winfo_children()):
            widget.destroy()
        if self.workflow is None or not self.workflow.has_items():
            return

        pages = len(self.workflow.items)
        marks = self.workflow.total_marks()
        step = int(self.workflow.current_step)
        name = self._chapter_name()

        callout = theme.card(
            self._callout_host, bg=COLOR_BG,
            border=COLOR_ACCENT, border_width=2, padx=16, pady=14,
        )
        callout.pack(fill=tk.X)
        text = tk.Frame(callout, bg=COLOR_BG)
        text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        theme.heading(
            text, f"Tienes un trabajo a medias — {name}", size=10, bg=COLOR_BG,
        ).pack(fill=tk.X)
        theme.body(
            text,
            f"{pages} imágenes · {marks} secciones marcadas · "
            f"se quedó en el paso {step} ({STEP_NAMES.get(step, step)})",
            size=8, bg=COLOR_BG, fg=NEUTRAL_600,
        ).pack(fill=tk.X, pady=(4, 0))
        theme.button(
            callout, "Continuar →", self._on_continue,
            variant="primary", padx=14, pady=9,
        ).pack(side=tk.RIGHT, padx=(16, 0))

    def _chapter_name(self) -> str:
        if self.workflow is not None and self.workflow.items:
            return self.workflow.items[0][0].parent.name or "Capítulo"
        return "Capítulo"

    # ------------------------------------------------------------------
    # Rail
    # ------------------------------------------------------------------

    def _build_sidebar_sections(self) -> None:
        self._sidebar.clear_view_sections()
        folders = recent_paths.history(RECENT_IN_RAIL)
        if folders:
            title = "Reciente" if len(folders) == 1 else "Recientes"
            body = self._sidebar.section(title)
            for folder in folders:
                self._recent_card(body, folder)

        app = self._app()
        translator = getattr(app, "_translator", None) if app else None
        pair = f"{TRANSLATION_DEFAULT_SRC}→{TRANSLATION_DEFAULT_TGT}"
        ready = False
        if translator is not None:
            try:
                ready = translator.is_pair_available(
                    TRANSLATION_DEFAULT_SRC, TRANSLATION_DEFAULT_TGT,
                )
            except Exception:
                ready = translator.is_available()
        self._sidebar.show_engines(
            translator_pair=pair,
            translator_ready=ready,
            on_download_pair=self._on_download_pair,
        )
        self._sidebar.clear_footer()

    def _recent_card(self, parent: tk.Misc, folder: Path) -> None:
        count = self._count_images(folder)
        card = theme.card(parent, bg=SIDEBAR_BG)
        card.pack(fill=tk.X, pady=(0, 8))
        theme.body(
            card, folder.name or str(folder), size=9, bg=SIDEBAR_BG,
            fg=COLOR_TEXT, weight="bold",
        ).pack(fill=tk.X)
        # Only the tail of the path: a deep folder wraps to five lines in
        # a 260 px rail and pushes the engine block off the bottom. The
        # whole path is one hover away.
        detail = self._short_parent(folder)
        if count is not None:
            detail = f"{detail} · {count} imágenes"
        theme.body(
            card, detail, size=8, bg=SIDEBAR_BG, fg=NEUTRAL_600, wrap=210,
        ).pack(fill=tk.X, pady=(2, 0))
        Tooltip(card, str(folder))
        for widget in (card, *card.winfo_children()):
            widget.configure(cursor="hand2")
            widget.bind(
                "<Button-1>", lambda _e, f=folder: self._on_open_recent(f),
            )

    @staticmethod
    def _short_parent(folder: Path) -> str:
        parent = folder.parent
        if parent == parent.parent:  # a drive root, nothing to trim
            return str(parent)
        tail = parent.name or str(parent)
        return tail if parent.parent == parent.parent.parent else f"…\\{tail}"

    @staticmethod
    def _count_images(folder: Path) -> int | None:
        try:
            return len(image_loader.expand_folder(folder))
        except Exception:
            return None

    def _on_download_pair(self) -> None:
        app = self._app()
        translator = getattr(app, "_translator", None) if app else None
        if translator is None:
            return
        from tkinter import messagebox
        pair = f"{TRANSLATION_DEFAULT_SRC}→{TRANSLATION_DEFAULT_TGT}"
        if translator.is_pair_available(
            TRANSLATION_DEFAULT_SRC, TRANSLATION_DEFAULT_TGT,
        ):
            # Nothing to download — the rail was stale, so refresh it
            # instead of claiming an install that never happened.
            self._build_sidebar_sections()
            messagebox.showinfo(
                "Par ya instalado",
                f"El par {pair} ya estaba instalado. Motores actualizado.",
                parent=self,
            )
            return

        # The download blocks the UI thread for a few hundred MB; say so
        # before the window stops repainting.
        if not messagebox.askokcancel(
            "Descargar par de idiomas",
            f"Se descargará el modelo {pair} (~300 MB).\n"
            "La ventana quedará sin responder hasta que termine.",
            parent=self,
        ):
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            ok = translator.ensure_pair(
                TRANSLATION_DEFAULT_SRC, TRANSLATION_DEFAULT_TGT,
            )
        finally:
            self.config(cursor="")
        if ok:
            messagebox.showinfo(
                "Par listo",
                f"Par {pair} instalado.",
                parent=self,
            )
            self._build_sidebar_sections()
        else:
            messagebox.showwarning(
                "No se pudo descargar",
                "No se pudo instalar el par. Revisa logs/app.log.",
                parent=self,
            )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_continue(self) -> None:
        app = self._app()
        if app is None:
            return
        render = getattr(app, "_render_current_step", None)
        if render is not None:
            render()

    def _on_open_files(self) -> None:
        app = self._app()
        if app is not None and hasattr(app, "_prompt_open_files"):
            app._prompt_open_files()

    def _on_open_recent(self, folder: Path | None = None) -> None:
        app = self._app()
        if app is not None and hasattr(app, "_prompt_open_recent"):
            app._prompt_open_recent(folder)
            # The folder may have vanished since it was recorded, which
            # drops it from the history — repaint so the rail agrees.
            if self.winfo_exists() and self._sidebar is not None:
                self._build_sidebar_sections()

    def _app(self):
        toplevel = self.winfo_toplevel()
        return getattr(toplevel, "_app", None)

    def _handle_drop(self, paths: list[str]) -> None:
        if not paths:
            return
        try:
            first = Path(paths[0])
            if any(p.lower().endswith((".jpg", ".jpeg", ".png")) for p in paths):
                recent_paths.save(first.parent)
            else:
                recent_paths.save(first)
        except Exception:
            pass
        app = self._app()
        if app is None:
            return
        if hasattr(app, "_open_files_drop"):
            app._open_files_drop(paths)
        else:
            self._on_open_files()
