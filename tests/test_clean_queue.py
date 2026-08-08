"""La cola de limpieza: qué entra, qué se descarta y qué se cuenta.

LaMa no aparece por ninguna parte. Lo que se prueba es la contabilidad
alrededor: una página encolada dos veces se limpiaría dos veces, y cada
pasada son decenas de segundos de GPU por página.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PIL import Image

from src.utils.clean_queue import CleanJob, CleanQueue
from src.utils.marks_store import Mark

TIMEOUT = 5.0


class _FakeInpainter:
    """Un LaMa que no piensa, y que se puede parar a mitad."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.cleaned: list[Path] = []
        self.gate.set()

    def is_available(self) -> bool:
        return self.available

    def cleanup_to_disk(self, image, marks, out_path, padding=0, cluster_gap=0):
        self.entered.set()
        assert self.gate.wait(TIMEOUT), "la prueba dejó la puerta cerrada"
        self.cleaned.append(out_path)


def _job(tmp_path: Path, idx: int) -> CleanJob:
    return CleanJob(
        image_index=idx,
        path=tmp_path / f"{idx:04d}.png",
        image=Image.new("RGB", (8, 8), "white"),
        marks=[Mark(x=0, y=0, w=4, h=4, color="#ffcc00")],
        signature=f"firma{idx}",
    )


def _esperar_parada(queue: CleanQueue) -> None:
    if queue._thread is not None:
        queue._thread.join(TIMEOUT)
    assert not queue.is_running(), "el hilo de limpieza no terminó"


@pytest.fixture
def parada() -> _FakeInpainter:
    """Un inpainter que se queda quieto en la primera página."""
    fake = _FakeInpainter()
    fake.gate.clear()
    return fake


def test_una_pagina_ya_encolada_no_entra_dos_veces(
    tmp_path: Path, parada: _FakeInpainter,
) -> None:
    """Volver al paso 2 solo cuesta lo que de verdad haya cambiado."""
    queue = CleanQueue(parada)
    assert queue.enqueue([_job(tmp_path, 0), _job(tmp_path, 1)]) == 2
    assert parada.entered.wait(TIMEOUT)

    # La 0 está en vuelo y la 1 sigue en cola: ninguna de las dos repite.
    assert queue.enqueue([_job(tmp_path, 0), _job(tmp_path, 1)]) == 0
    # Una nueva sí entra, sin arrancar un segundo hilo.
    assert queue.enqueue([_job(tmp_path, 2)]) == 1

    parada.gate.set()
    _esperar_parada(queue)
    assert len(parada.cleaned) == 3


def test_encolar_nada_no_arranca_nada(tmp_path: Path) -> None:
    queue = CleanQueue(_FakeInpainter())
    assert queue.enqueue([]) == 0
    assert queue.is_running() is False
    assert queue.pending() == 0


def test_descartar_la_cola_deja_acabar_la_de_encima(
    tmp_path: Path, parada: _FakeInpainter,
) -> None:
    """Interrumpir a LaMa a medias dejaría un PNG a medio escribir."""
    queue = CleanQueue(parada)
    queue.enqueue([_job(tmp_path, i) for i in range(4)])
    assert parada.entered.wait(TIMEOUT)

    queue.clear()
    # Solo queda la que ya estaba en la mesa.
    assert queue.pending() == 1

    parada.gate.set()
    _esperar_parada(queue)
    assert len(parada.cleaned) == 1


def test_al_vaciarse_los_contadores_vuelven_a_cero(tmp_path: Path) -> None:
    """El paso 2 puede volver a entregar trabajo, y empieza de nuevo."""
    fake = _FakeInpainter()
    queue = CleanQueue(fake)
    queue.enqueue([_job(tmp_path, 0), _job(tmp_path, 1)])
    _esperar_parada(queue)

    assert queue.progress() == (0, 0)
    assert queue.pending() == 0
    assert len(fake.cleaned) == 2

    # Y la misma página vuelve a entrar: la cola ya no la conoce.
    assert queue.enqueue([_job(tmp_path, 0)]) == 1
    _esperar_parada(queue)
    assert len(fake.cleaned) == 3


def test_sin_lama_la_pagina_se_da_por_fallada(tmp_path: Path) -> None:
    """No se rompe la cola: el paso 4 cae al original y se puede seguir."""
    fake = _FakeInpainter(available=False)
    queue = CleanQueue(fake)
    queue.enqueue([_job(tmp_path, 0)])
    _esperar_parada(queue)

    assert fake.cleaned == []
    assert queue.pending() == 0


def test_lo_que_se_le_cuenta_a_la_aplicacion(tmp_path: Path) -> None:
    """La App se entera por la cola de eventos, no por el hilo.

    Cada aviso lleva el nombre del método que hay que llamar en el hilo
    de Tk; resolverlo al despacharlo es lo que permite reengancharse
    entre pasos sin perder avisos.
    """
    queue = CleanQueue(_FakeInpainter())
    queue.enqueue([_job(tmp_path, 0)])
    _esperar_parada(queue)

    avisos = []
    while not queue._events.empty():
        avisos.append(queue._events.get_nowait())
    nombres = [n for n, _ in avisos]

    assert nombres.count("_on_page_done") == 1
    assert nombres[-1] == "_on_finished"
    # Y el «hecha» viaja con la firma, que es lo que el sidecar apunta.
    hecha = next(args for n, args in avisos if n == "_on_page_done")
    assert hecha[0] == 0                    # índice de la página
    assert hecha[2] is True                 # salió bien
    assert hecha[3] == "firma0"
