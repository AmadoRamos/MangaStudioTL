"""El paso de OCR del capítulo: a qué marcas llega y qué cuenta.

Como en ``test_translation_runner``, el trabajo se llama en el hilo del
test y los eventos se leen de la cola. El motor y el recortador son
dobles: lo que se prueba es a cuántas marcas se llama, qué se escribe en
el sidecar y qué se le dice a la barra, no si Tesseract sabe leer.
"""

from __future__ import annotations

import queue
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.utils.marks_store import Mark, MarksStore, OcrEntry
from src.utils.ocr_engine import OcrResult
from src.utils.pipeline_runner import OcrJobSpec, PipelineRunner


def _motor(
    *, disponible: bool = True, idiomas: tuple[str, ...] = ("eng", "spa"),
    texto: str = "HELLO", acepta_idioma: bool = True,
) -> SimpleNamespace:
    leidas: list[str] = []

    def recognize(_img, lang: str = "eng") -> OcrResult:
        leidas.append(lang)
        return OcrResult(text=texto, confidence=88, language=lang, engine="doble")

    return SimpleNamespace(
        is_available=lambda: disponible,
        is_language_available=lambda _l: acepta_idioma,
        available_languages=lambda: idiomas,
        recognize=recognize,
        leidas=leidas,
    )


def _recortador(tmp_path: Path) -> SimpleNamespace:
    """Escribe un PNG de verdad: el pipeline lo abre con PIL."""
    hechos: list[Path] = []

    def crop(_img, _x, _y, _w, _h, image_index=0, mark_id=0, context=0) -> Path:
        destino = tmp_path / f"crop{image_index}_{mark_id}.png"
        Image.new("RGB", (10, 10), "white").save(destino)
        hechos.append(destino)
        return destino

    return SimpleNamespace(crop=crop, hechos=hechos)


def _capitulo(tmp_path: Path, marcas_por_pagina: list[int]):
    items = []
    stores = []
    for idx, cuantas in enumerate(marcas_por_pagina):
        ruta = tmp_path / f"{idx:04d}.png"
        Image.new("RGB", (100, 100), "white").save(ruta)
        items.append((ruta, Image.new("RGB", (100, 100), "white")))
        store = MarksStore(ruta)
        for m in range(cuantas):
            store.add(Mark(x=5 * m, y=5, w=20, h=10, color="#ffcc00"))
        stores.append(store)
    return items, stores


def _eventos(runner: PipelineRunner) -> list[tuple]:
    salida: list[tuple] = []
    try:
        while True:
            salida.append(runner._events.get_nowait())
    except queue.Empty:
        pass
    return salida


def test_las_pendientes_son_las_que_no_tienen_texto(tmp_path: Path) -> None:
    """Un segundo paso cuesta las marcas nuevas, no el capítulo entero."""
    _items, stores = _capitulo(tmp_path, [2, 1])
    stores[0].set_ocr_result(0, OcrEntry(
        text="ya leída", confidence=90, language="eng", engine="doble",
    ))

    assert PipelineRunner.pending_ocr(stores) == 2
    assert PipelineRunner.pending_ocr(stores, force=True) == 3

    # Texto en blanco no cuenta como leída.
    stores[0].set_ocr_result(1, OcrEntry(
        text="   ", confidence=0, language="eng", engine="doble",
    ))
    assert PipelineRunner.pending_ocr(stores) == 2


def test_el_idioma_que_se_usa_de_verdad(tmp_path: Path) -> None:
    recortador = _recortador(tmp_path)

    # Con el idioma pedido instalado, se usa tal cual.
    runner = PipelineRunner(_motor(), recortador)
    assert runner.resolve_lang("spa+eng") == "spa+eng"

    # Sin él, manda lo que haya: inglés primero.
    runner = PipelineRunner(
        _motor(acepta_idioma=False, idiomas=("eng", "deu")), recortador,
    )
    assert runner.resolve_lang("jpn") == "eng"

    # Sin inglés, el primero que no sea «osd», que no es un idioma.
    runner = PipelineRunner(
        _motor(acepta_idioma=False, idiomas=("osd", "deu")), recortador,
    )
    assert runner.resolve_lang("jpn") == "deu"

    # Sin nada utilizable, el paso no puede correr.
    runner = PipelineRunner(
        _motor(acepta_idioma=False, idiomas=("osd",)), recortador,
    )
    assert runner.resolve_lang("jpn") is None


def test_el_texto_leido_va_al_sidecar_de_su_marca(tmp_path: Path) -> None:
    """Cada marca recibe lo suyo: texto, confianza y quién lo leyó."""
    items, stores = _capitulo(tmp_path, [2])
    motor = _motor(texto="HELLO")
    runner = PipelineRunner(motor, _recortador(tmp_path))

    assert runner._run_ocr(items, stores, "eng") is True

    assert motor.leidas == ["eng", "eng"]
    for mark_id in (0, 1):
        entrada = stores[0].get_ocr(mark_id)
        assert entrada is not None
        assert entrada.text == "HELLO"
        assert entrada.engine == "doble"
        assert entrada.confidence == 88

    nombres = [nombre for nombre, _args in _eventos(runner)]
    assert nombres[0] == "_on_step_start"
    assert nombres[-1] == "_on_step_done"
    # Un aviso de inicio y uno por marca.
    assert nombres.count("_on_step_progress") == 3


def test_sin_marcas_pendientes_no_se_llama_al_motor(tmp_path: Path) -> None:
    """Volver al paso 2 y seguir no vuelve a leer lo ya leído."""
    items, stores = _capitulo(tmp_path, [1])
    stores[0].set_ocr_result(0, OcrEntry(
        text="ya está", confidence=90, language="eng", engine="doble",
    ))
    motor = _motor()
    runner = PipelineRunner(motor, _recortador(tmp_path))

    assert runner._run_ocr(items, stores, "eng") is True
    assert motor.leidas == []
    assert _eventos(runner)[-1] == (
        "_on_step_done", (1, True, "Sin OCR pendiente"),
    )


def test_forzar_relee_las_que_ya_tenian_texto(tmp_path: Path) -> None:
    """«Rehacer el OCR» pisa el texto viejo, que es lo que se le pide."""
    items, stores = _capitulo(tmp_path, [1])
    stores[0].set_ocr_result(0, OcrEntry(
        text="vieja", confidence=10, language="eng", engine="doble",
    ))
    motor = _motor(texto="NUEVA")
    runner = PipelineRunner(motor, _recortador(tmp_path))

    assert runner._run_ocr(items, stores, "eng", force=True) is True
    assert stores[0].get_ocr(0).text == "NUEVA"


def test_sin_motor_el_paso_no_corre(tmp_path: Path) -> None:
    """Sin OCR disponible el paso lo dice en vez de leer nada."""
    items, stores = _capitulo(tmp_path, [1])
    runner = PipelineRunner(_motor(disponible=False), _recortador(tmp_path))

    assert runner._run_ocr(items, stores, "eng") is False
    assert _eventos(runner)[-1] == (
        "_on_step_done", (1, False, "Ningún motor de OCR disponible"),
    )


def test_cancelar_para_el_paso_y_lo_dice(tmp_path: Path) -> None:
    """Cancelado antes de la primera marca: ni una lectura."""
    items, stores = _capitulo(tmp_path, [2])
    motor = _motor()
    runner = PipelineRunner(motor, _recortador(tmp_path))
    runner._cancel_evt.set()

    assert runner._run_ocr(items, stores, "eng") is False
    assert motor.leidas == []
    assert _eventos(runner)[-1] == ("_on_step_done", (1, False, "OCR cancelado"))


def test_el_recorte_se_borra_aunque_el_motor_reviente(tmp_path: Path) -> None:
    """El recorte es temporal: si se queda, el disco crece sin motivo."""
    def revienta(_img, lang: str = "eng") -> OcrResult:
        raise RuntimeError("motor roto")

    motor = _motor()
    motor.recognize = revienta
    recortador = _recortador(tmp_path)
    runner = PipelineRunner(motor, recortador)
    imagen = Image.new("RGB", (100, 100), "white")

    resultado, error = runner.recognize_spec(
        OcrJobSpec(image_index=0, mark_id=0, image=imagen, x=0, y=0, w=20, h=10),
        "eng",
    )

    assert resultado.text == "" and error == "motor roto"
    assert recortador.hechos and not recortador.hechos[0].exists()


def test_el_recorte_se_borra_tambien_cuando_todo_va_bien(tmp_path: Path) -> None:
    """El camino bueno tampoco deja basura en el temporal."""
    recortador = _recortador(tmp_path)
    runner = PipelineRunner(_motor(texto="LEIDO"), recortador)
    imagen = Image.new("RGB", (100, 100), "white")

    resultado, error = runner.recognize_spec(
        OcrJobSpec(image_index=0, mark_id=0, image=imagen, x=0, y=0, w=20, h=10),
        "eng",
    )

    assert (resultado.text, error) == ("LEIDO", None)
    assert not recortador.hechos[0].exists()


def test_con_otro_paso_en_curso_se_niega(tmp_path: Path) -> None:
    """Dos pases de OCR a la vez escribirían el mismo sidecar."""
    items, stores = _capitulo(tmp_path, [1])
    runner = PipelineRunner(_motor(), _recortador(tmp_path))
    runner._busy_evt.set()

    assert runner.run(items, stores, "eng") is False
    assert _eventos(runner) == [
        ("_on_overall_done", (False, "Pipeline ya en curso")),
    ]
