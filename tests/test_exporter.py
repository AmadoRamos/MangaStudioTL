"""La exportación: qué imagen se usa de base y qué se escribe al lado."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from src.config import TRANSLATION_SIDECAR_SUFFIX, TRANSLATION_SUFFIX
from src.utils.exporter import export_translations
from src.utils.inpainter import clean_path
from src.utils.marks_store import Mark, MarksStore, TranslationEntry
from src.utils.text_renderer import RenderConfig


def _pagina(tmp_path: Path, nombre: str, color: str = "black") -> tuple[Path, Image.Image]:
    ruta = tmp_path / nombre
    img = Image.new("RGB", (200, 120), color)
    img.save(ruta, format="PNG")
    return ruta, img


def _store_con_texto(ruta: Path, texto: str = "HOLA") -> MarksStore:
    store = MarksStore(ruta)
    store.add(Mark(x=20, y=20, w=100, h=60, color="#ffcc00"))
    if texto:
        store.set_translation(
            0, TranslationEntry(text=texto, source_lang="en", target_lang="es"),
        )
    return store


def test_se_exporta_sobre_la_limpia_si_la_hay(tmp_path: Path) -> None:
    """Rotular sobre el original dejaría el texto viejo debajo del nuevo."""
    ruta, img = _pagina(tmp_path, "0001.png", color="black")
    Image.new("RGB", (200, 120), "white").save(clean_path(ruta), format="PNG")
    salida = tmp_path / "out"

    resultados = export_translations([(ruta, img)], [_store_con_texto(ruta)], salida)

    assert len(resultados) == 1
    assert resultados[0].used_clean is True
    assert resultados[0].translated_count == 1
    with Image.open(resultados[0].out_path) as png:
        # La base es la blanca, no la negra del original.
        assert png.convert("RGB").getpixel((0, 0)) == (255, 255, 255)


def test_sin_limpia_se_usa_el_original(tmp_path: Path) -> None:
    """Falta la limpia: se exporta igual y se deja constancia."""
    ruta, img = _pagina(tmp_path, "0001.png")
    salida = tmp_path / "out"

    resultados = export_translations([(ruta, img)], [_store_con_texto(ruta)], salida)

    assert resultados[0].used_clean is False
    assert resultados[0].out_path.name == f"0001{TRANSLATION_SUFFIX}"
    assert resultados[0].out_path.exists()


def test_una_marca_sin_texto_no_cuenta_como_traducida(tmp_path: Path) -> None:
    """Y no escribe sidecar: no hay nada que declarar de esa página."""
    ruta, img = _pagina(tmp_path, "0001.png")
    salida = tmp_path / "out"
    store = _store_con_texto(ruta, texto="")
    store.set_translation(
        0, TranslationEntry(text="   ", source_lang="en", target_lang="es"),
    )

    resultados = export_translations([(ruta, img)], [store], salida)

    assert resultados[0].translated_count == 0
    assert resultados[0].skipped_count == 1
    assert not (salida / f"0001{TRANSLATION_SIDECAR_SUFFIX}").exists()
    # Aun así la página sale, para que el capítulo esté completo.
    assert resultados[0].out_path.exists()


def test_el_sidecar_dice_lo_que_se_dibujo(tmp_path: Path) -> None:
    """No lo que se pidió: la variante que la familia no tenga se descarta.

    El sidecar es el registro de lo que hay en el PNG. Si guardase la
    petición, revisar una página exportada llevaría a conclusiones falsas.
    """
    ruta, img = _pagina(tmp_path, "0001.png")
    salida = tmp_path / "out"
    store = MarksStore(ruta)
    store.add(Mark(x=10, y=10, w=80, h=40, color="#ffcc00"))
    store.set_translation(
        0,
        TranslationEntry(
            text="HOLA", source_lang="en", target_lang="es",
            color=(9, 8, 7), max_pt=30,
        ),
    )

    export_translations([(ruta, img)], [store], salida, RenderConfig(max_pt=72))

    datos = json.loads(
        (salida / f"0001{TRANSLATION_SIDECAR_SUFFIX}").read_text(encoding="utf-8")
    )
    assert datos["translated_count"] == 1
    fila = datos["translations"][0]
    assert fila["text"] == "HOLA"
    # Lo que puso la sección gana al valor del capítulo.
    assert fila["color"] == [9, 8, 7]
    assert fila["max_pt"] == 30
    assert fila["bold"] is False


def test_el_progreso_avisa_por_pagina_y_al_final(tmp_path: Path) -> None:
    """La ventana necesita las dos cosas para no prometer un tiempo falso."""
    rutas = [_pagina(tmp_path, f"{i:04d}.png") for i in range(3)]
    stores = [_store_con_texto(r) for r, _ in rutas]
    vistos: list[tuple[int, int, str]] = []

    export_translations(
        rutas, stores, tmp_path / "out",
        on_progress=lambda i, t, p: vistos.append((i, t, p.name)),
    )

    assert [(i, t) for i, t, _ in vistos] == [(0, 3), (1, 3), (2, 3), (3, 3)]
    # El aviso final llega sin página: ya no queda ninguna en curso.
    assert vistos[-1][2] == ""


def test_listas_descuadradas_no_se_exportan(tmp_path: Path) -> None:
    """Emparejar mal página y marcas rotularía cada página con otra."""
    ruta, img = _pagina(tmp_path, "0001.png")
    with pytest.raises(ValueError):
        export_translations([(ruta, img)], [], tmp_path / "out")
    assert export_translations([], [], tmp_path / "out") == []
