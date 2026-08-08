"""The «Finalizar y exportar» dialog, and the window that follows it.

States the destination, exactly what will be written and what will be
skipped, and only then offers the button that writes it — the order the
mockups use for every confirmation. :class:`ExportProgress` is what the
user then watches: la exportación bloquea la interfaz, y sin ella un
capítulo largo se lee como una aplicación colgada.
"""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from src.config import (
    COLOR_BG,
    COLOR_DIVIDER,
    COLOR_SURFACE,
    COLOR_TEXT,
    NEUTRAL_600,
)
from src.views import theme
from src.views.theme import DIALOG_WIDTH


class ExportDialog(tk.Toplevel):
    """Modal export confirmation. Blocks until closed.

    ``result`` is ``None`` when cancelled, otherwise
    ``(destination, open_when_done)``.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        initial_dir: Path,
        pages: int,
        sections: int,
        skipped: int,
        estimated_mb: float,
    ) -> None:
        super().__init__(master, bg=COLOR_BG)
        self.result: tuple[Path, bool] | None = None
        self.title("Finalizar y exportar")
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.configure(
            highlightthickness=2,
            highlightbackground=COLOR_TEXT, highlightcolor=COLOR_TEXT,
        )

        self._dir_var = tk.StringVar(value=str(initial_dir))
        self._open_var = tk.BooleanVar(value=True)

        self._build_header()
        self._build_body(pages, sections, skipped, estimated_mb)
        self._build_actions(pages)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.bind("<Return>", lambda _e: self._confirm())
        theme.center_on(self, master, DIALOG_WIDTH)
        self.grab_set()
        self.wait_window(self)

    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=COLOR_BG, padx=18, pady=16)
        header.pack(fill=tk.X)
        theme.heading(header, "Finalizar y exportar", size=15).pack(fill=tk.X)
        theme.rule(self, thickness=2, color=COLOR_TEXT).pack(fill=tk.X)

    def _build_body(
        self, pages: int, sections: int, skipped: int, estimated_mb: float,
    ) -> None:
        body = tk.Frame(self, bg=COLOR_BG, padx=18, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        theme.field_label(body, "Carpeta destino").pack(fill=tk.X, pady=(0, 5))
        row = tk.Frame(body, bg=COLOR_BG)
        row.pack(fill=tk.X, pady=(0, 14))
        field = theme.entry(row, self._dir_var)
        field.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)
        theme.button(
            row, "Examinar…", self._browse,
            variant="outline", size=9, padx=10, pady=7,
        ).pack(side=tk.LEFT, padx=(8, 0))

        theme.kicker(body, "Se escribirá").pack(fill=tk.X, pady=(0, 7))
        written = sections - skipped
        self._summary_row(body, f"{pages} PNG renderizados", f"~{estimated_mb:.0f} MB")
        self._summary_row(body, f"{pages} sidecars .translation.json", "schema v4")
        self._summary_row(
            body, f"{written} secciones con texto", "se dibujan",
        )
        if skipped:
            self._summary_row(
                body, f"{skipped} secciones sin traducción", "se omiten",
                muted=True,
            )

        theme.checkbox(
            body, "Abrir la carpeta al terminar", self._open_var,
        ).pack(fill=tk.X, pady=(14, 0))

    def _summary_row(
        self, parent: tk.Misc, left: str, right: str, *, muted: bool = False,
    ) -> None:
        fg = NEUTRAL_600 if muted else COLOR_TEXT
        row = tk.Frame(parent, bg=COLOR_SURFACE, padx=9, pady=7)
        row.pack(fill=tk.X, pady=(0, 1))
        theme.body(row, left, size=9, bg=COLOR_SURFACE, fg=fg).pack(side=tk.LEFT)
        theme.body(
            row, right, size=9, bg=COLOR_SURFACE, fg=fg, weight="bold",
        ).pack(side=tk.RIGHT)

    def _build_actions(self, pages: int) -> None:
        theme.rule(self, thickness=2, color=COLOR_DIVIDER).pack(fill=tk.X)
        actions = tk.Frame(self, bg=COLOR_BG, padx=18, pady=14)
        actions.pack(fill=tk.X)
        label = f"Exportar {pages} página" + ("s" if pages != 1 else "")
        theme.button(
            actions, label, self._confirm,
            variant="primary", padx=16, pady=10,
        ).pack(side=tk.LEFT)
        theme.button(
            actions, "Cancelar", self._cancel,
            variant="outline", padx=16, pady=10,
        ).pack(side=tk.LEFT, padx=(9, 0))

    # ------------------------------------------------------------------

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(
            title="Carpeta destino para la exportación",
            initialdir=self._dir_var.get() or None,
            parent=self,
        )
        if chosen:
            self._dir_var.set(chosen)

    def _confirm(self) -> None:
        destination = self._dir_var.get().strip()
        if not destination:
            return
        self.result = (Path(destination), bool(self._open_var.get()))
        self._close()

    def _cancel(self) -> None:
        self.result = None
        self._close()

    def _close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


class ExportProgress(tk.Toplevel):
    """En qué página va la exportación, cuánto lleva y cuánto le queda.

    ``step`` tiene la firma de ``on_progress`` del exportador, así que se
    le pasa tal cual. El exportador corre en el hilo de la interfaz, y por
    eso aquí se repinta con ``update_idletasks``: dibuja sin procesar
    clics, así que nadie puede lanzar una segunda exportación encima de
    la primera. — *saltado: exportar en un hilo con botón de cancelar;
    añadir si a alguien le hace falta parar un capítulo a medias.*
    """

    def __init__(self, master: tk.Misc, total: int) -> None:
        super().__init__(master, bg=COLOR_BG)
        self.title("Exportando")
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.configure(
            highlightthickness=2,
            highlightbackground=COLOR_TEXT, highlightcolor=COLOR_TEXT,
        )
        # La cruz no cancela nada: el exportador no sabe parar a mitad, y
        # una ventana que se va sin detenerlo mentiría.
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        header = tk.Frame(self, bg=COLOR_BG, padx=18, pady=16)
        header.pack(fill=tk.X)
        theme.heading(header, "Exportando", size=15).pack(fill=tk.X)
        theme.rule(self, thickness=2, color=COLOR_TEXT).pack(fill=tk.X)

        body = tk.Frame(self, bg=COLOR_BG, padx=18, pady=16)
        body.pack(fill=tk.BOTH, expand=True)
        self._page = theme.body(body, "", size=10, weight="bold")
        self._page.pack(fill=tk.X, pady=(0, 9))
        self._meter = theme.Meter(body, height=6)
        self._meter.pack(fill=tk.X, pady=(0, 9))
        foot = tk.Frame(body, bg=COLOR_BG)
        foot.pack(fill=tk.X)
        self._count = theme.body(foot, "", size=9, fg=NEUTRAL_600)
        self._count.pack(side=tk.LEFT)
        self._eta = theme.body(foot, "", size=9, fg=NEUTRAL_600)
        self._eta.pack(side=tk.RIGHT)

        self._started = time.monotonic()
        self.step(0, total, Path(""))
        theme.center_on(self, master, DIALOG_WIDTH)
        self.grab_set()

    def step(self, done: int, total: int, path: Path) -> None:
        """*done* páginas terminadas; *path* es la que empieza ahora."""
        self._page.configure(
            text=path.name or ("Preparando…" if done < total else "Terminando…"),
        )
        self._meter.set(done / total if total else 1.0)
        percent = int(done / total * 100) if total else 100
        self._count.configure(
            text=f"Página {min(done + 1, total)} de {total} · {percent} %",
        )
        self._eta.configure(text=self._eta_text(done, total))
        self.update_idletasks()

    def _eta_text(self, done: int, total: int) -> str:
        """Lo que falta, medido con lo que ya tardó.

        Una media simple: las páginas de un capítulo pesan parecido y se
        corrige sola en cada una. Con cero hechas no hay nada con qué
        medir, y decir un número inventado es peor que no decirlo.
        """
        if done <= 0:
            return "calculando…"
        if done >= total:
            return ""
        left = (time.monotonic() - self._started) / done * (total - done)
        if left < 60:
            return f"queda ~{max(1, int(left))} s"
        return f"queda ~{int(left // 60)} min {int(left % 60):02d} s"

    def close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
