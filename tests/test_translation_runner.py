"""El worker de traducción: qué emite, en qué orden y cuándo se niega.

El trabajo se llama aquí en el hilo del test —``_run_job`` no sabe en qué
hilo está— y los eventos se leen de la cola en vez de por el ``after`` de
Tk. Así se puede comprobar el orden exacto, que es lo que la vista
dibuja: la barra de progreso se mueve antes y después de cada marca, y
el texto llega marca a marca y no al final.
"""

from __future__ import annotations

import queue
from types import SimpleNamespace

import pytest

from src.utils.translation_runner import TranslationRunner


def _traductor(
    *, disponible: bool = True, par: bool = True,
    instala: bool = True, texto: str = "hola",
) -> SimpleNamespace:
    def translate(_t: str, _s: str, _g: str) -> str:
        return texto
    return SimpleNamespace(
        is_available=lambda: disponible,
        is_pair_available=lambda _s, _t: par,
        ensure_pair=lambda _s, _t: instala,
        translate=translate,
    )


def _eventos(runner: TranslationRunner) -> list[tuple]:
    """Lo que el worker dejó en la cola, en orden."""
    salida: list[tuple] = []
    try:
        while True:
            salida.append(runner._events.get_nowait())
    except queue.Empty:
        pass
    return salida


def test_sin_texto_no_arranca_y_lo_dice() -> None:
    """Un lote vacío no abre hilo: contesta y se queda."""
    runner = TranslationRunner(_traductor())

    assert runner.run_for_all([]) is False
    assert _eventos(runner) == [
        ("_on_done", (False, "No hay texto para traducir")),
    ]


def test_con_otra_traduccion_en_curso_se_niega() -> None:
    """Dos hilos traduciendo la misma marca se pisarían el sidecar."""
    runner = TranslationRunner(_traductor())
    runner._busy_evt.set()

    assert runner.run_for_all([(0, 0, "hello", "en", "es")]) is False
    assert _eventos(runner) == [("_on_done", (False, "Traduccion ya en curso"))]


def test_sin_argos_no_arranca() -> None:
    """Sin motor de traducción no hay nada que intentar."""
    runner = TranslationRunner(_traductor(disponible=False))

    assert runner.run_for_all([(0, 0, "hello", "en", "es")]) is False
    assert _eventos(runner) == [("_on_done", (False, "Argos no disponible"))]


def test_el_progreso_va_antes_y_despues_de_cada_marca() -> None:
    """Dos marcas: cinco avisos de progreso y un final."""
    runner = TranslationRunner(_traductor(texto="hola"))
    runner._run_job([(0, 0, "hello", "en", "es"), (0, 1, "bye", "en", "es")])

    assert _eventos(runner) == [
        ("_on_progress", (0, 2, 0, 0)),
        ("_on_mark_done", (0, 0, "hola", "en", "es", None)),
        ("_on_progress", (1, 2, 0, 0)),
        ("_on_progress", (1, 2, 0, 1)),
        ("_on_mark_done", (0, 1, "hola", "en", "es", None)),
        ("_on_progress", (2, 2, 0, 1)),
        ("_on_done", (True, "Traduccion completada: 2 marca(s)")),
    ]
    assert not runner.is_running()


def test_cancelar_para_antes_de_la_marca_siguiente() -> None:
    """La cancelación se mira entre marcas, que es donde se puede."""
    runner = TranslationRunner(_traductor())
    runner._cancel_evt.set()
    runner._run_job([(0, 0, "hello", "en", "es")])

    assert _eventos(runner) == [("_on_done", (False, "Cancelado por el usuario"))]
    assert not runner.is_running()


def test_un_par_que_no_se_puede_instalar_es_un_error_por_marca() -> None:
    """La marca vuelve vacía y con motivo; el lote sigue y acaba bien."""
    runner = TranslationRunner(_traductor(par=False, instala=False))
    runner._run_job([(0, 3, "hello", "en", "xx")])

    eventos = _eventos(runner)
    assert eventos[1] == (
        "_on_mark_done", (0, 3, "", "en", "xx", "Par en->xx no disponible"),
    )
    assert eventos[-1][1][0] is True


def test_si_el_traductor_revienta_la_marca_lleva_el_motivo() -> None:
    """Una marca rota no tumba el lote: va con su error y se sigue."""
    def revienta(_t: str, _s: str, _g: str) -> str:
        raise RuntimeError("modelo corrupto")

    traductor = _traductor()
    traductor.translate = revienta
    runner = TranslationRunner(traductor)
    runner._run_job([(0, 0, "hello", "en", "es")])

    eventos = _eventos(runner)
    assert eventos[1] == (
        "_on_mark_done", (0, 0, "", "en", "es", "modelo corrupto"),
    )
    # Y el lote no se cae por una marca.
    assert eventos[-1][1][0] is True


def test_el_hilo_se_lanza_y_suelta_el_ocupado(root) -> None:
    """La puerta de verdad: `run_for_all` con hilo, hasta el final."""
    runner = TranslationRunner(_traductor(texto="hola"))
    runner.attach(
        root,
        on_mark_done=lambda *a: None,
        on_progress=lambda *a: None,
        on_done=lambda *a: None,
    )
    try:
        assert runner.run_for_all([(0, 0, "hello", "en", "es")]) is True
        runner._thread.join(timeout=5)
        assert not runner.is_running()
        nombres = [nombre for nombre, _args in _eventos(runner)]
        assert nombres[-1] == "_on_done"
    finally:
        runner.detach()


def test_una_sola_marca_es_un_lote_de_una() -> None:
    """`run_for_mark` pasa por la misma puerta que el lote."""
    runner = TranslationRunner(_traductor())
    runner._busy_evt.set()  # para que no arranque ningún hilo

    assert runner.run_for_mark(2, 5, "hello", "en", "es") is False
    assert _eventos(runner) == [("_on_done", (False, "Traduccion ya en curso"))]


@pytest.mark.parametrize("ocupado", [False, True])
def test_cancelar_solo_marca_si_hay_algo_que_cancelar(ocupado: bool) -> None:
    """Igual que en la base: sin trabajo, la bandera no se queda puesta."""
    runner = TranslationRunner(_traductor())
    if ocupado:
        runner._busy_evt.set()
    runner.cancel()

    assert runner._cancel_evt.is_set() is ocupado
