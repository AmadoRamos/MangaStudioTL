"""El sidecar: lo que se guarda, lo que se lee y lo que se reordena."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import INPAINT_PADDING_PX
from src.utils.marks_store import (
    Mark,
    MarksStore,
    OcrEntry,
    TranslationEntry,
    sidecar_path,
    to_single_line,
)


@pytest.fixture
def store(tmp_path: Path) -> MarksStore:
    """Un almacén sobre una imagen que no hace falta que exista.

    El sidecar se escribe al lado de la ruta, no dentro de la imagen, así
    que el archivo de la página nunca llega a abrirse.
    """
    return MarksStore(tmp_path / "page001.jpg")


def _mark(x: int = 10, y: int = 20, **kw) -> Mark:
    return Mark(x=x, y=y, w=100, h=50, color="#ffcc00", **kw)


def test_single_line_joins_what_tesseract_partio() -> None:
    """El OCR devuelve renglones; Argos traduce por renglones. Mal par.

    Un globo estrecho parte «SOMETHING» en dos con guión, y esa frase
    tiene que volver a ser una antes de que la traduzca nadie.
    """
    assert to_single_line("I DON'T\nKNOW") == "I DON'T KNOW"
    # El guión de final de renglón se va con el salto: en un globo es
    # maquetado, no un compuesto de verdad.
    assert to_single_line("SOME-\nTHING") == "SOMETHING"
    # Pero un guión con texto detrás en el mismo renglón sí es del autor.
    assert to_single_line("well-known name") == "well-known name"
    assert to_single_line("a\r\nb\r\nc") == "a b c"
    assert to_single_line("  varios   espacios \n ") == "varios espacios"
    assert to_single_line("") == ""


def test_padding_resuelve_una_sola_vez() -> None:
    """``None`` es «el del capítulo», y un negativo no encoge la máscara."""
    assert _mark().erase_padding == INPAINT_PADDING_PX
    assert _mark(padding=0).erase_padding == 0
    assert _mark(padding=40).erase_padding == 40
    assert Mark(0, 0, 1, 1, "#fff", padding=-5).erase_padding == 0

    # Sin tocar no se escribe: un capítulo que nadie ajustó conserva el
    # sidecar que ya tenía.
    assert "padding" not in _mark().to_dict()
    assert _mark(padding=0).to_dict()["padding"] == 0


def test_mark_from_dict_aguanta_basura() -> None:
    """Un sidecar editado a mano no puede tumbar la carga entera."""
    assert Mark.from_dict({"x": 1, "y": 2, "w": 3, "h": 4}).color == "#ffcc00"
    assert Mark.from_dict(
        {"x": 1, "y": 2, "w": 3, "h": 4, "padding": "no es un número"}
    ).padding is None
    with pytest.raises(KeyError):
        Mark.from_dict({"x": 1})


def test_borrar_una_marca_arrastra_su_texto(store: MarksStore) -> None:
    """Al quitar un hueco, todo lo de detrás baja un puesto.

    Es la regresión que importa: descartar solo las claves fuera de
    rango dejaría el OCR de cada marca pegado al de su vecina.
    """
    for i in range(3):
        store.add(_mark(x=i * 200))
    for i in range(3):
        store.set_ocr_result(i, OcrEntry(text=f"ocr{i}", confidence=90, language="eng"))
        store.set_translation(
            i, TranslationEntry(text=f"tr{i}", source_lang="en", target_lang="es"),
        )

    assert store.remove_at(0) is not None

    assert len(store) == 2
    # Lo que era la marca 1 es ahora la 0, con su texto y no con el de otra.
    assert store.get_ocr(0).text == "ocr1"
    assert store.get_ocr(1).text == "ocr2"
    assert store.get_translation(0).text == "tr1"
    assert store.get_translation(1).text == "tr2"
    assert store.get_ocr(2) is None


def test_indices_fuera_de_rango_no_hacen_nada(store: MarksStore) -> None:
    """Escribir en una marca que no existe se ignora, no revienta."""
    store.add(_mark())
    store.set_ocr_result(7, OcrEntry(text="x", confidence=1, language="eng"))
    store.set_translation(-1, TranslationEntry(text="x", source_lang="en", target_lang="es"))
    assert store.ocr_results == {}
    assert store.translations == {}
    assert store.remove_at(7) is None
    assert store.update_at(7, _mark()) is False


def test_ida_y_vuelta_por_el_disco(store: MarksStore) -> None:
    """Lo que se guarda se vuelve a leer igual, incluido el OCR de un renglón."""
    store.add(_mark(padding=30))
    store.add(_mark(x=400))
    # El salto entra por la puerta de escritura y sale ya unido: el que
    # llama no tiene que acordarse de la regla.
    store.set_ocr_result(0, OcrEntry(text="dos\nrenglones", confidence=80, language="spa"))
    store.set_translation(
        0,
        TranslationEntry(
            text="hola", source_lang="en", target_lang="es",
            color=(1, 2, 3), bold=False, profile="Grito",
        ),
    )
    store.clean_signature = "abc123"

    fresh = MarksStore(store.image_path)
    fresh.load()

    assert fresh.marks == store.marks
    assert fresh.clean_signature == "abc123"
    assert fresh.get_ocr(0).text == "dos renglones"
    entry = fresh.get_translation(0)
    assert entry.color == (1, 2, 3)
    # ``False`` no es «sin tocar»: es «esta sección va en redonda pase lo
    # que pase», y tiene que sobrevivir al viaje.
    assert entry.bold is False
    assert entry.profile == "Grito"
    # Y el sello de tiempo lo pone el almacén, no quien llama.
    assert entry.ran_at


def test_un_sidecar_roto_es_una_pagina_sin_marcas(store: MarksStore) -> None:
    """Perder las marcas de una página no puede impedir abrir el capítulo."""
    sidecar_path(store.image_path).write_text("{ esto no es json", encoding="utf-8")
    assert store.load() == []

    # Una marca inválida se cae sola; las buenas de al lado se cargan.
    sidecar_path(store.image_path).write_text(
        json.dumps({
            "version": 5,
            "marks": [{"x": 1, "y": 2, "w": 3, "h": 4}, {"falta": "todo"}],
        }),
        encoding="utf-8",
    )
    assert len(store.load()) == 1


def test_un_ocr_corrupto_no_tumba_la_carga(store: MarksStore) -> None:
    """Y el aviso tiene que hablar de la entrada mala, no de otra cosa.

    El registro del error usaba la variable del bucle de las marcas: con
    una página sin marcas, avisar de un OCR ilegible reventaba dentro del
    propio ``except`` y se llevaba por delante la carga entera.
    """
    sidecar_path(store.image_path).write_text(
        json.dumps({
            "version": 5,
            "marks": [],
            "ocr_results": {"0": "esto tenía que ser un objeto"},
            "translations": {"0": 12345},
        }),
        encoding="utf-8",
    )
    assert store.load() == []
    assert store.ocr_results == {}
    assert store.translations == {}


def test_guardar_solo_cuando_hay_algo_que_guardar(store: MarksStore) -> None:
    """Sin cambios no se toca el disco: el sidecar es de quien lo escribió."""
    path = sidecar_path(store.image_path)
    assert store.save() is True
    assert not path.exists()

    store.add(_mark())
    assert path.exists()

    # Reponer la misma marca no es un cambio.
    assert store.update_at(0, store.marks[0]) is False
