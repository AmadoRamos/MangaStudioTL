"""El controlador de los cuatro pasos: por dónde se puede pasar y qué cuenta."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.utils.marks_store import Mark, OcrEntry, TranslationEntry
from src.workflow.controller import WorkflowController, WorkflowStep


class _AppFalsa:
    """Lo único que el controlador le pide a la App: repintar."""

    def __init__(self) -> None:
        self.repintados = 0
        self._current_view = None

    def _render_current_step(self) -> None:
        self.repintados += 1


@pytest.fixture
def app() -> _AppFalsa:
    return _AppFalsa()


def _items(tmp_path: Path, n: int) -> list[tuple[Path, Image.Image]]:
    salida = []
    for i in range(n):
        ruta = tmp_path / f"{i:04d}.png"
        img = Image.new("RGB", (20, 20), "white")
        img.save(ruta, format="PNG")
        salida.append((ruta, img))
    return salida


def test_sin_capitulo_no_se_pasa_de_la_portada(app: _AppFalsa) -> None:
    """Los pasos 2 a 4 no tienen nada sobre lo que trabajar."""
    ctrl = WorkflowController(app, [])
    ctrl.go_to(WorkflowStep.MARKS)
    assert ctrl.current_step == WorkflowStep.HOME
    assert app.repintados == 0


def test_el_paso_mas_lejos_no_se_pierde_al_volver(
    app: _AppFalsa, tmp_path: Path,
) -> None:
    """Es lo que dibuja los checks del riel: volver atrás no los borra."""
    ctrl = WorkflowController(app, _items(tmp_path, 1))
    ctrl.go_to(WorkflowStep.OCR_REVIEW)
    assert ctrl.highest_reached() == WorkflowStep.OCR_REVIEW

    ctrl.back_step()
    assert ctrl.current_step == WorkflowStep.MARKS
    assert ctrl.highest_reached() == WorkflowStep.OCR_REVIEW


def test_atras_se_para_en_la_portada(app: _AppFalsa, tmp_path: Path) -> None:
    ctrl = WorkflowController(app, _items(tmp_path, 1))
    ctrl.go_to(WorkflowStep.MARKS)
    ctrl.back_step()
    assert ctrl.current_step == WorkflowStep.HOME
    antes = app.repintados
    ctrl.back_step()
    assert ctrl.current_step == WorkflowStep.HOME
    # Y no repinta por nada.
    assert app.repintados == antes


def test_las_cuentas_del_riel(app: _AppFalsa, tmp_path: Path) -> None:
    """Marcas, traducidas y OCR pendientes, que es lo que el riel enseña."""
    items = _items(tmp_path, 2)
    ctrl = WorkflowController(app, items)

    for store in ctrl.stores:
        store.add(Mark(x=0, y=0, w=10, h=10, color="#ffcc00"))
    ctrl.stores[0].add(Mark(x=20, y=0, w=10, h=10, color="#ffcc00"))

    assert ctrl.total_marks() == 3
    assert ctrl.ocr_pending_marks() == 3

    ctrl.stores[0].set_ocr_result(0, OcrEntry(text="algo", confidence=90, language="eng"))
    # Un OCR que salió vacío sigue pendiente: no hay nada que traducir.
    ctrl.stores[0].set_ocr_result(1, OcrEntry(text="", confidence=0, language="eng"))
    assert ctrl.ocr_pending_marks() == 2

    ctrl.stores[0].set_translation(
        0, TranslationEntry(text="algo", source_lang="en", target_lang="es"),
    )
    # Una traducción en blanco no cuenta como traducida.
    ctrl.stores[1].set_translation(
        0, TranslationEntry(text="  ", source_lang="en", target_lang="es"),
    )
    assert ctrl.translated_marks() == 1


def test_paginas_sin_limpiar(app: _AppFalsa, tmp_path: Path) -> None:
    """Solo cuentan las que tienen marcas: una página en blanco no se limpia."""
    from src.utils.inpainter import clean_path, marks_signature

    items = _items(tmp_path, 2)
    ctrl = WorkflowController(app, items)
    assert ctrl.images_without_clean() == 0

    marca = Mark(x=0, y=0, w=10, h=10, color="#ffcc00")
    ctrl.stores[0].add(marca)
    assert ctrl.images_without_clean() == 1

    clean_path(items[0][0]).write_bytes(b"limpia")
    ctrl.stores[0].clean_signature = marks_signature([marca])
    assert ctrl.images_without_clean() == 0

    # Mover la caja deja la limpia atrasada.
    ctrl.stores[0].update_at(0, Mark(x=50, y=50, w=10, h=10, color="#ffcc00"))
    assert ctrl.images_without_clean() == 1


def test_reset_deja_la_aplicacion_como_recien_abierta(
    app: _AppFalsa, tmp_path: Path,
) -> None:
    """Tras exportar no puede quedar el capítulo anterior a medio camino."""
    ctrl = WorkflowController(app, _items(tmp_path, 2))
    ctrl.go_to(WorkflowStep.RENDER)
    ctrl.reset()

    assert ctrl.current_step == WorkflowStep.HOME
    assert ctrl.highest_reached() == WorkflowStep.HOME
    assert ctrl.has_items() is False
    assert ctrl.total_marks() == 0
