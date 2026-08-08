"""Las limpias que el paso 2 guarda en memoria, y las que no.

Una página de webcomic pasa de los 30 MB descodificada y el capítulo
original ya está cargado aparte, así que aquí lo que se prueba es lo que
*no* se carga. Los métodos se llaman sin construir la vista entera: solo
tocan los cuatro atributos que se le ponen al doble, y montar un
``MarksView`` de verdad exige media aplicación.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.config import CLEAN_CACHE_PAGES
from src.views.marks_view import MarksView
from src.views.render_view import RenderView


def _vista(tmp_path: Path, paginas: int, *, viendo_limpia: bool) -> SimpleNamespace:
    items = []
    for i in range(paginas):
        ruta = tmp_path / f"{i:04d}.png"
        # El original es pequeño; la limpia, más alta. Así se nota si la
        # medida que devuelve es la de la limpia o la del original.
        Image.new("RGB", (10, 20), "white").save(ruta, format="PNG")
        Image.new("RGB", (10, 60), "white").save(
            tmp_path / f"{i:04d}.clean.png", format="PNG",
        )
        items.append((ruta, Image.new("RGB", (10, 20), "white")))
    return SimpleNamespace(
        _items=items,
        _index=0,
        _viewing_clean=viendo_limpia,
        _clean_available={i: True for i in range(paginas)},
        _clean_cache={},
        _clean_sizes={},
        # El lector de cabeceras es el de verdad: es justo lo que se
        # quiere comprobar que se usa en lugar de abrir la imagen.
        _read_clean_size=MarksView._read_clean_size,
    )


def test_medir_una_pagina_no_la_descodifica(tmp_path: Path) -> None:
    """La cinta necesita el alto de todas las páginas, no sus píxeles.

    Es la regresión cara: colocar la cinta con «ver limpia» encendido
    pedía la imagen entera de cada página, o sea el capítulo duplicado
    en memoria antes de dibujar nada.
    """
    vista = _vista(tmp_path, 30, viendo_limpia=True)

    medidas = [MarksView._strip_size(vista, i) for i in range(30)]

    # Da el tamaño de la limpia, que es la que se está mirando.
    assert medidas == [(10, 60)] * 30
    # Y no ha guardado ni una sola imagen descodificada.
    assert vista._clean_cache == {}
    assert len(vista._clean_sizes) == 30


def test_sin_ver_la_limpia_se_mide_el_original(tmp_path: Path) -> None:
    """Y sin tocar el disco: el original ya está cargado en memoria."""
    vista = _vista(tmp_path, 3, viendo_limpia=False)
    assert [MarksView._strip_size(vista, i) for i in range(3)] == [(10, 20)] * 3
    assert vista._clean_sizes == {}


def test_una_limpia_ilegible_cae_al_tamano_del_original(tmp_path: Path) -> None:
    """Sin medida no se puede colocar la cinta, y un hueco la descuadra."""
    vista = _vista(tmp_path, 1, viendo_limpia=True)
    (tmp_path / "0000.clean.png").write_bytes(b"esto no es un PNG")
    assert MarksView._strip_size(vista, 0) == (10, 20)


def test_solo_se_guardan_unas_pocas_paginas(tmp_path: Path) -> None:
    """Recorrer el capítulo no puede ir dejando cada limpia en memoria."""
    vista = _vista(tmp_path, 20, viendo_limpia=True)

    for i in range(20):
        vista._index = i
        MarksView._remember_clean(vista, i, Image.new("RGB", (10, 60), "white"))
        assert len(vista._clean_cache) <= CLEAN_CACHE_PAGES

    # Y lo que queda es lo que rodea a la página mirada, no lo primero
    # que entró: al desplazarse, lo de al lado es lo que vuelve a hacer
    # falta enseguida.
    assert max(vista._clean_cache) == 19
    assert min(vista._clean_cache) >= 20 - CLEAN_CACHE_PAGES


def test_se_suelta_la_pagina_mas_lejana(tmp_path: Path) -> None:
    """Con el foco en una página, la que se va es la del otro extremo."""
    vista = _vista(tmp_path, 30, viendo_limpia=True)
    vista._index = 10
    for i in (9, 10, 11, 12, 29):
        MarksView._remember_clean(vista, i, Image.new("RGB", (10, 60), "white"))

    assert 29 not in vista._clean_cache
    assert set(vista._clean_cache) == {9, 10, 11, 12}


def test_el_paso_4_guarda_con_el_mismo_tope(tmp_path: Path) -> None:
    """La vista de rotulado acumulaba una limpia por página visitada.

    No tiene cinta, así que solo carga la página en pantalla, pero
    recorrer el capítulo entero las iba dejando todas en memoria.
    """
    vista = _vista(tmp_path, 20, viendo_limpia=True)

    for i in range(20):
        vista._index = i
        RenderView._remember_clean(vista, i, Image.new("RGB", (10, 60), "white"))
        assert len(vista._clean_cache) <= CLEAN_CACHE_PAGES

    assert max(vista._clean_cache) == 19
