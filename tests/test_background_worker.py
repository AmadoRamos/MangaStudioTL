"""La base de los tres workers: un hilo y una cola hacia el hilo de Tk.

Lo que se prueba es el reparto, no el trabajo: que un callback se busque
cuando el evento se despacha y no cuando se encola —de eso depende que
una vista que se va no reciba lo que pidió la anterior—, que uno que
revienta no se lleve a los demás, y que soltar el widget tire lo que
quedaba pendiente.

No se prueba que el repintado caiga en el hilo de la interfaz: eso lo
decide el ``after`` de Tk, no este módulo.
"""

from __future__ import annotations

import threading
import tkinter as tk

import pytest

from src.utils.background_worker import BackgroundWorker


class _Worker(BackgroundWorker):
    """Un worker con un trabajo de mentira y un contador de llamadas."""

    def __init__(self) -> None:
        super().__init__()
        self.recibido: list[tuple] = []
        self.terminado = threading.Event()

    def _on_algo(self, *args) -> None:
        self.recibido.append(args)

    def _run_job(self, valor: int) -> None:  # type: ignore[override]
        try:
            self._emit("_on_algo", valor)
        finally:
            self._busy_evt.clear()
            self.terminado.set()


@pytest.fixture
def worker():
    """Un worker suelto, siempre desatado al acabar."""
    w = _Worker()
    yield w
    w.detach()


def test_un_callback_que_revienta_no_se_lleva_a_los_demas(
    worker: _Worker, root: tk.Tk,
) -> None:
    """En Tk, una excepción que escapa de un manejador tumba la ventana."""
    def revienta(*_args) -> None:
        raise RuntimeError("callback roto")

    worker.attach(root)
    worker._on_roto = revienta  # type: ignore[attr-defined]
    worker._emit("_on_roto")
    worker._emit("_on_algo", "después")
    worker._poll()

    assert worker.recibido == [("después",)]


def test_cancelar_sin_trabajo_no_marca_nada(worker: _Worker) -> None:
    """`cancel` sobre un worker parado no deja la bandera puesta.

    Si la dejara, el siguiente trabajo nacería cancelado.
    """
    worker.cancel()
    assert not worker._cancel_evt.is_set()

    worker._busy_evt.set()
    worker.cancel()
    assert worker._cancel_evt.is_set()


def test_el_hilo_corre_el_trabajo_y_la_cola_lo_trae(
    worker: _Worker, root: tk.Tk,
) -> None:
    """De punta a punta: hilo de verdad, cola de verdad, un `_poll`."""
    worker.attach(root)
    worker._start_thread("prueba", worker._run_job, 42)
    assert worker.terminado.wait(timeout=5), "el hilo no terminó"
    worker._thread.join(timeout=5)

    assert not worker.is_running()
    worker._poll()
    assert worker.recibido == [(42,)]


def test_empezar_limpia_la_cancelacion_anterior(
    worker: _Worker, root: tk.Tk,
) -> None:
    """Un trabajo nuevo no nace cancelado por el anterior."""
    worker.attach(root)
    worker._cancel_evt.set()
    worker._start_thread("prueba", worker._run_job, 1)
    assert worker.terminado.wait(timeout=5)
    worker._thread.join(timeout=5)

    assert not worker._cancel_evt.is_set()


def test_emit_dispatches_by_name(root: tk.Tk) -> None:
    """``_emit`` must call the attribute named at *dispatch* time.

    Venía de ``test_smoke``, que era la casa de lo que no tenía otra;
    `BackgroundWorker` ya la tiene. Se queda con su doble propio.
    """
    seen: list[tuple] = []

    class Worker(BackgroundWorker):
        def __init__(self):
            super().__init__()
            self._on_done = None

    w = Worker()
    w.attach(root)
    w._emit("_on_done", 1, True, "listo")   # queued before the callback exists
    w._on_done = lambda *a: seen.append(a)
    w._poll()
    assert seen == [(1, True, "listo")], seen

    # A missing callback is dropped, not raised.
    w._emit("_on_nonexistent", 42)
    w._poll()
    assert seen == [(1, True, "listo")], seen

    # detach() drops what is still queued.
    w._emit("_on_done", 2, False, "tarde")
    w.detach()
    w._poll()
    assert seen == [(1, True, "listo")], seen
