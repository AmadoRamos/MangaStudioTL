"""Los ocho agarres de la selección, que ahora son de ZoomedCanvas.

Los dos lienzos tenían su copia del andamio —dibujar, mover, hit-test,
«estoy dentro»— y la única diferencia real era de dónde sale el
rectángulo. Eso es `_selection_rect`, y esto comprueba las dos mitades:
que el andamio sigue siendo uno solo, y que cada subclase contesta con
lo suyo.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

from PIL import Image

from src.utils.marks_store import Mark, MarksStore, TranslationEntry
from src.views.marks_canvas import MarksCanvas
from src.views.translator_canvas import TranslatorCanvas
from src.views.zoomed_canvas import HANDLES, ZoomedCanvas

MARCA = Mark(x=100, y=200, w=60, h=40, color="#ffcc00")


def _sin_transformar(canvas: ZoomedCanvas) -> None:
    """Escala 1 y origen 0, para que un píxel de imagen sea uno de lienzo.

    La raíz de los tests está oculta y mide 1x1, así que el encaje
    automático daría una escala que no dice nada. Lo que se prueba aquí
    es la aritmética del andamio, no el encaje.
    """
    canvas._canvas_scale_x = 1.0
    canvas._canvas_scale_y = 1.0
    canvas._offset_x = 0.0
    canvas._offset_y = 0.0


def _marks_canvas(root: tk.Tk, tmp_path: Path) -> MarksCanvas:
    store = MarksStore(tmp_path / "p.png")
    store.add(MARCA)
    canvas = MarksCanvas(root, store)
    canvas.set_image(Image.new("RGB", (400, 600), "white"))
    _sin_transformar(canvas)
    canvas.select(0)
    return canvas


def test_el_andamio_no_esta_copiado() -> None:
    """Si alguien vuelve a pegarlo en una subclase, esto se entera."""
    for nombre in (
        "_handle_centers", "_clear_handles", "_draw_handles",
        "_move_handles", "_hit_test_handle", "_inside_selection",
    ):
        for subclase in (MarksCanvas, TranslatorCanvas):
            assert getattr(subclase, nombre) is getattr(ZoomedCanvas, nombre), (
                f"{subclase.__name__}.{nombre} ya no es el de la base"
            )
    # Y lo que sí es de cada una.
    for subclase in (MarksCanvas, TranslatorCanvas):
        assert subclase._selection_rect is not ZoomedCanvas._selection_rect


def test_la_base_sola_no_tiene_nada_que_agarrar(root: tk.Tk) -> None:
    """Sin selección no hay agarres: la base no tiene qué seleccionar."""
    canvas = ZoomedCanvas(root)
    canvas.set_image(Image.new("RGB", (40, 40), "white"))

    assert canvas._selection_rect() is None
    canvas._draw_handles()
    assert canvas._handle_ids == {}
    assert canvas._hit_test_handle(0, 0) is None
    assert canvas._inside_selection(0, 0) is False


def test_los_agarres_caen_en_las_esquinas(root: tk.Tk, tmp_path: Path) -> None:
    """Las ocho anclas, donde toca, y el hit-test que las encuentra."""
    canvas = _marks_canvas(root, tmp_path)

    assert canvas._selection_rect() == (100, 200, 60, 40)
    assert set(canvas._handle_ids) == {ancla for ancla, _ in HANDLES}

    # La esquina noroeste está en la esquina de la marca, y se agarra.
    assert canvas._handle_centers((100, 200, 60, 40))["nw"] == (100, 200)
    assert canvas._hit_test_handle(100, 200) == "nw"
    assert canvas._hit_test_handle(160, 240) == "se"
    # Lejos de todo agarre no hay ancla, pero el centro sí está dentro.
    assert canvas._hit_test_handle(130, 220) is None
    assert canvas._inside_selection(130, 220) is True
    assert canvas._inside_selection(10, 10) is False


def test_ocultar_las_marcas_apaga_los_agarres(root: tk.Tk, tmp_path: Path) -> None:
    """Una sola condición, en `_selection_rect`, y se apagan los tres."""
    canvas = _marks_canvas(root, tmp_path)
    canvas.set_marks_visible(False)

    assert canvas._selection_rect() is None
    assert canvas._handle_ids == {}
    assert canvas._hit_test_handle(100, 200) is None
    assert canvas._inside_selection(130, 220) is False


def test_el_traductor_agarra_el_cuadro_y_no_la_marca(
    root: tk.Tk, tmp_path: Path,
) -> None:
    """Arrastrado el texto fuera del globo, lo que se agarra es el cuadro."""
    store = MarksStore(tmp_path / "p.png")
    store.add(MARCA)
    store.set_translation(0, TranslationEntry(
        text="hola", source_lang="en", target_lang="es",
        box_offset=(10, -20, 5, 0),
    ))
    canvas = TranslatorCanvas(root)
    canvas.set_store(store)
    canvas.set_image(Image.new("RGB", (400, 600), "white"))
    _sin_transformar(canvas)
    canvas.select(0)

    assert canvas._selection_rect() == (110, 180, 65, 40)
    assert canvas._hit_test_handle(110, 180) == "nw"
