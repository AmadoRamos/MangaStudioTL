"""Background cleaning queue — LaMa running behind the workflow.

Cleaning is the slow half of the old pipeline and nothing needs its
output until step 4: step 3 works on text alone, and the render step
falls back to the original page when there is no clean version. So the
queue starts as soon as the OCR pass ends and keeps grinding while the
chapter is being translated, which is exactly the dead time it needs.

Two consequences shape this module:

* **The App owns the queue, not a view.** A :class:`BackgroundWorker`'s
  events are only drained by the widget that called ``attach()``, so a
  worker attached to a step's view stops being heard the moment the step
  changes — and the view's ``destroy`` cancels it outright. This one is
  polled on the root window and outlives every view swap.
* **Pages are checked for staleness, not just for existence.** Going
  back to step 2 and moving a box makes the ``.clean`` file on disk
  wrong; :func:`src.utils.inpainter.clean_is_stale` is what notices.

The App gets ``on_progress`` before each page, ``on_page_done`` with
the signature the store should record on success, and ``on_finished``
when the queue runs dry.
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image

from src.config import INPAINT_CLUSTER_GAP, INPAINT_DEFAULT_PADDING
from src.utils.background_worker import BackgroundWorker
from src.utils.inpainter import Inpainter, clean_path
from src.utils.logger import get_logger
from src.utils.marks_store import Mark

log = get_logger("clean_queue")


@dataclass(frozen=True)
class CleanJob:
    """One page waiting for LaMa."""

    image_index: int
    path: Path
    image: Image.Image
    marks: list[Mark] = field(default_factory=list)
    signature: str = ""
    padding: int = INPAINT_DEFAULT_PADDING
    cluster_gap: int = INPAINT_CLUSTER_GAP


ProgressCallback = Callable[[int, int, str], None]
PageDoneCallback = Callable[[int, Path, bool, str], None]
FinishedCallback = Callable[[int, int], None]


class CleanQueue(BackgroundWorker):
    """Cleans queued pages one at a time on a single background thread."""

    def __init__(self, inpainter: Inpainter) -> None:
        super().__init__()
        self._inpainter = inpainter
        self._lock = threading.Lock()
        self._queue: deque[CleanJob] = deque()
        self._current: Path | None = None
        self._done: int = 0
        self._failed: int = 0
        self._total: int = 0
        self._on_progress: ProgressCallback | None = None
        self._on_page_done: PageDoneCallback | None = None
        self._on_finished: FinishedCallback | None = None

    def attach(
        self,
        widget: tk.Misc,
        on_progress: ProgressCallback,
        on_page_done: PageDoneCallback,
        on_finished: FinishedCallback,
    ) -> None:
        super().attach(widget)
        self._on_progress = on_progress
        self._on_page_done = on_page_done
        self._on_finished = on_finished

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    def enqueue(self, jobs: list[CleanJob]) -> int:
        """Add pages to the queue, and start the thread if it is idle.

        Pages already queued or in flight are skipped, so calling this
        again after a second trip through step 2 costs only whatever
        actually changed. Returns how many were added.
        """
        if not jobs:
            return 0
        added = 0
        start = False
        with self._lock:
            known = {job.path for job in self._queue}
            if self._current is not None:
                known.add(self._current)
            for job in jobs:
                if job.path in known:
                    continue
                self._queue.append(job)
                known.add(job.path)
                self._total += 1
                added += 1
            # Claim the thread inside the lock: the worker clears the
            # busy flag under the same lock when it runs dry, so the two
            # cannot both conclude that nobody is working.
            if added and not self._busy_evt.is_set():
                self._busy_evt.set()
                start = True
        if start:
            self._start_thread("clean-queue", self._run_job)
        if added:
            log.info("Limpieza en segundo plano: %d pagina(s) en cola", added)
        return added

    def pending(self) -> int:
        """Pages still waiting, plus the one being cleaned right now."""
        with self._lock:
            return len(self._queue) + (1 if self._current is not None else 0)

    def progress(self) -> tuple[int, int]:
        with self._lock:
            return self._done, self._total

    def clear(self) -> None:
        """Drop everything still waiting. The page in flight finishes."""
        with self._lock:
            dropped = len(self._queue)
            self._queue.clear()
            self._total -= dropped
        if dropped:
            log.info("Limpieza en segundo plano: %d pagina(s) descartadas", dropped)

    def cancel(self) -> None:
        self.clear()
        super().cancel()

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _run_job(self) -> None:
        try:
            while not self._cancel_evt.is_set():
                with self._lock:
                    if not self._queue:
                        break
                    job = self._queue.popleft()
                    self._current = job.path
                    done, total = self._done, self._total
                self._emit("_on_progress", done, total, job.path.name)
                success = self._clean_one(job)
                with self._lock:
                    self._current = None
                    if success:
                        self._done += 1
                    else:
                        self._failed += 1
                    done, total = self._done, self._total
                self._emit(
                    "_on_page_done",
                    job.image_index, job.path, success, job.signature,
                )
                self._emit("_on_progress", done, total, job.path.name)
        except Exception as exc:
            log.exception("Error en la cola de limpieza: %s", exc)
        finally:
            with self._lock:
                self._current = None
                done, failed = self._done, self._failed
                # Nothing left to do, so the counters start from zero the
                # next time step 2 hands work over.
                if not self._queue:
                    self._done = self._failed = self._total = 0
                self._busy_evt.clear()
            self._emit("_on_finished", done, failed)

    def _clean_one(self, job: CleanJob) -> bool:
        if not self._inpainter.is_available():
            log.warning("LaMa no disponible, se omite %s", job.path.name)
            return False
        try:
            self._inpainter.cleanup_to_disk(
                job.image, job.marks, clean_path(job.path),
                padding=job.padding, cluster_gap=job.cluster_gap,
            )
            return True
        except Exception as exc:
            log.exception("No se pudo limpiar %s: %s", job.path.name, exc)
            return False

