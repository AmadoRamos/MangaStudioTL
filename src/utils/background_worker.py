"""Base class for single-thread background workers with a Tk polling loop.

Concrete subclasses provide the job body via :meth:`_run_job` and report
progress with :meth:`_emit`, which queues a callback invocation. The
caller's Tk widget drains the queue on a timer, so every callback runs
on the main thread.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from typing import Callable

from src.utils.logger import get_logger

log = get_logger("background_worker")


class BackgroundWorker:
    """Single-thread worker that reports events back to the Tk main thread.

    Lifecycle:
        1. ``attach(widget)`` starts polling on a widget; subclasses set
           their callbacks in their own ``attach`` override.
        2. ``start(args)`` spawns a daemon thread that runs ``_run_job``.
        3. The thread calls ``_emit("_on_done", ...)``; the widget's
           ``after`` loop invokes the callback of that name.
        4. ``cancel()`` asks the thread to stop. ``detach()`` stops
           polling and drains any pending events.
    """

    _POLL_MS: int = 50

    def __init__(self) -> None:
        self._cancel_evt = threading.Event()
        self._busy_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._events: queue.Queue = queue.Queue()
        self._poll_widget: tk.Misc | None = None
        self._poll_after_id: str | None = None

    def attach(self, widget: tk.Misc) -> None:
        """Start polling ``widget`` for events on the main thread."""
        self.detach()
        self._poll_widget = widget
        self._schedule_poll()

    def detach(self) -> None:
        """Stop polling and drop any pending events."""
        if self._poll_after_id is not None and self._poll_widget is not None:
            try:
                self._poll_widget.after_cancel(self._poll_after_id)
            except Exception:
                pass
        self._poll_after_id = None
        self._poll_widget = None
        self._drain_queue()

    def is_running(self) -> bool:
        return self._busy_evt.is_set()

    def cancel(self) -> None:
        if not self._busy_evt.is_set():
            return
        self._cancel_evt.set()

    def _emit(self, callback_name: str, *args) -> None:
        """Queue ``self.<callback_name>(*args)`` for the main thread.

        The name is resolved when the event is dispatched, not when it is
        posted, so a callback replaced by a later ``attach`` wins.
        """
        self._events.put((callback_name, args))

    def _drain_queue(self) -> None:
        try:
            while True:
                self._events.get_nowait()
        except queue.Empty:
            pass

    def _start_thread(self, name: str, target: Callable, *args) -> None:
        self._cancel_evt.clear()
        self._busy_evt.set()
        self._thread = threading.Thread(
            target=target, args=args, daemon=True, name=name,
        )
        self._thread.start()

    def _schedule_poll(self) -> None:
        if self._poll_widget is None:
            return
        try:
            self._poll_after_id = self._poll_widget.after(
                self._POLL_MS, self._poll
            )
        except Exception:
            self._poll_after_id = None

    def _poll(self) -> None:
        if self._poll_widget is None:
            return
        try:
            while True:
                name, args = self._events.get_nowait()
                cb = getattr(self, name, None)
                if cb is None:
                    continue
                try:
                    cb(*args)
                except Exception as exc:
                    log.exception("Error en %s: %s", name, exc)
        except queue.Empty:
            pass
        self._schedule_poll()

    def _run_job(self) -> None:
        """Override in subclasses to run the worker body."""
        raise NotImplementedError
