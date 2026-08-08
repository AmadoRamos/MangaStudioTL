"""Background translation runner.

A single worker thread translates one snippet at a time, reporting
progress to the Tk main loop through the queue that
:class:`BackgroundWorker` polls via ``after``.
"""

from __future__ import annotations

from typing import Callable

from src.utils.background_worker import BackgroundWorker
from src.utils.logger import get_logger
from src.utils.translator import Translator

log = get_logger("translation_runner")

#: One job: ``(image_index, mark_id, text, source_lang, target_lang)``.
TranslationJob = tuple[int, int, str, str, str]

MarkDoneCallback = Callable[[int, int, str, str, str, str | None], None]
ProgressCallback = Callable[[int, int, int, int], None]
DoneCallback = Callable[[bool, str], None]


class TranslationRunner(BackgroundWorker):
    """Single-thread translation worker.

    The view calls :meth:`attach` once with a Tk widget and the three
    callbacks. :meth:`cancel` interrupts the current run.
    """

    def __init__(self, translator: Translator) -> None:
        super().__init__()
        self._translator = translator
        self._on_mark_done: MarkDoneCallback | None = None
        self._on_progress: ProgressCallback | None = None
        self._on_done: DoneCallback | None = None

    def attach(
        self,
        widget,
        on_mark_done: MarkDoneCallback,
        on_progress: ProgressCallback,
        on_done: DoneCallback,
    ) -> None:
        super().attach(widget)
        self._on_mark_done = on_mark_done
        self._on_progress = on_progress
        self._on_done = on_done

    def cancel(self) -> None:
        if not self.is_running():
            return
        log.info("Traduccion cancelada por el usuario")
        super().cancel()

    def run_for_mark(
        self,
        image_index: int,
        mark_id: int,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> bool:
        """Queue a single-mark translation."""
        return self.run_for_all(
            [(image_index, mark_id, text, source_lang, target_lang)]
        )

    def run_for_all(self, items: list[TranslationJob]) -> bool:
        """Queue many translations at once."""
        if not items:
            self._emit("_on_done", False, "No hay texto para traducir")
            return False
        if self._busy_evt.is_set():
            log.warning("Traduccion ya en curso, ignorando nueva solicitud")
            self._emit("_on_done", False, "Traduccion ya en curso")
            return False
        if not self._translator.is_available():
            self._emit("_on_done", False, "Argos no disponible")
            return False
        self._start_thread("translation-runner", self._run_job, list(items))
        return True

    def _run_job(self, jobs: list[TranslationJob]) -> None:
        total = len(jobs)
        try:
            for i, (img_idx, mark_id, text, src, tgt) in enumerate(jobs):
                if self._cancel_evt.is_set():
                    self._emit("_on_done", False, "Cancelado por el usuario")
                    return
                self._emit("_on_progress", i, total, img_idx, mark_id)
                translated, error = self._translate_one(text, src, tgt, mark_id)
                self._emit(
                    "_on_mark_done", img_idx, mark_id, translated, src, tgt, error,
                )
                self._emit("_on_progress", i + 1, total, img_idx, mark_id)
            self._emit("_on_done", True, f"Traduccion completada: {total} marca(s)")
        except Exception as exc:
            log.exception("Error en worker de traduccion: %s", exc)
            self._emit("_on_done", False, f"Error: {exc}")
        finally:
            self._busy_evt.clear()

    def _translate_one(
        self, text: str, src: str, tgt: str, mark_id: int,
    ) -> tuple[str, str | None]:
        if not self._translator.is_pair_available(src, tgt):
            if not self._translator.ensure_pair(src, tgt):
                return "", f"Par {src}->{tgt} no disponible"
        try:
            return self._translator.translate(text, src, tgt), None
        except Exception as exc:
            log.exception("Error traduciendo marca %d: %s", mark_id, exc)
            return "", str(exc)
