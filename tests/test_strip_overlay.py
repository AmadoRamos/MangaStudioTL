"""Las marcas que la cinta dibuja, y las que no.

`StripCanvas.draw` rasteriza solo la banda visible y el overlay de
marcas recorría el capítulo entero, así que cada notch de rueda
destruía y recreaba las marcas de todas las páginas. Aquí se prueba lo
que *no* se dibuja.

Los métodos se llaman sin montar el widget, como en ``test_clean_cache``
con la vista: solo tocan los atributos que se le ponen al doble, y un
lienzo de Tk sobre una raíz oculta mide 1x1, con lo que la banda visible
no diría nada.
"""

from __future__ import annotations

import tkinter as tk
from types import MethodType, SimpleNamespace

from PIL import Image

from src.utils.marks_store import Mark
from src.views.strip_canvas import StripCanvas

ALTO_PAGINA = 100
PAGINAS = 10
MARCAS_POR_PAGINA = 3


class _CanvasFalso:
    """Un lienzo que solo apunta lo que le piden dibujar."""

    def __init__(self, *, alto: int, desplazamiento: float) -> None:
        self._alto = alto
        self._desplazamiento = desplazamiento
        self.creados: list[tuple] = []
        self.borrados: list[int] = []

    def winfo_width(self) -> int:
        return 80

    def winfo_height(self) -> int:
        return self._alto

    def canvasx(self, _v: float) -> float:
        return 0.0

    def canvasy(self, _v: float) -> float:
        return self._desplazamiento

    def create_rectangle(self, *coords, **kwargs) -> int:
        self.creados.append((coords, kwargs.get("tags", ())))
        return len(self.creados)

    def delete(self, item: int) -> None:
        self.borrados.append(item)


def _cinta(
    *, desplazamiento: float, seleccionada: tuple[int, int] | None = None,
    alto: int = 250,
) -> SimpleNamespace:
    stores = [
        [
            Mark(x=0, y=10 + 20 * m, w=20, h=10, color="#ffcc00")
            for m in range(MARCAS_POR_PAGINA)
        ]
        for _ in range(PAGINAS)
    ]
    vista = SimpleNamespace(
        _canvas=_CanvasFalso(alto=alto, desplazamiento=desplazamiento),
        _stores=stores,
        _layout=[
            (0.0, float(i * ALTO_PAGINA), 80, ALTO_PAGINA)
            for i in range(PAGINAS)
        ],
        _scale=1.0,
        _pages=PAGINAS,
        _mark_ids_by_page=[[] for _ in range(PAGINAS)],
        _marks_visible=True,
        _viewing_clean=False,
        _selected=seleccionada,
    )
    # Los tres métodos que `_render_marks` llama por su cuenta, atados al
    # doble: son justo lo que se quiere probar de verdad.
    for nombre in ("visible_band", "_overlay_pages", "image_to_strip"):
        setattr(vista, nombre, MethodType(getattr(StripCanvas, nombre), vista))
    return vista


def _paginas_dibujadas(vista: SimpleNamespace) -> set[int]:
    paginas = set()
    for _coords, tags in vista._canvas.creados:
        for tag in tags:
            if tag.startswith("img_"):
                paginas.add(int(tag[4:]))
    return paginas


def test_solo_se_dibujan_las_marcas_que_se_ven() -> None:
    """La regresión cara: 40 páginas de marcas por notch de rueda."""
    vista = _cinta(desplazamiento=0.0)

    StripCanvas._render_marks(vista)

    # La ventana abarca 250 px: las tres primeras páginas y ni una más.
    assert _paginas_dibujadas(vista) == {0, 1, 2}
    assert len(vista._canvas.creados) == 3 * MARCAS_POR_PAGINA


def test_la_banda_sigue_al_desplazamiento() -> None:
    """Lo que se dibuja es lo que se ve, no lo que se vio al abrir."""
    vista = _cinta(desplazamiento=500.0)

    StripCanvas._render_marks(vista)

    assert _paginas_dibujadas(vista) == {5, 6, 7}


def test_la_seleccionada_se_dibuja_aunque_no_se_vea() -> None:
    """Su recuadro de borrado se sale de la página, y es la única que lo tiene."""
    vista = _cinta(desplazamiento=0.0, seleccionada=(7, 1))

    StripCanvas._render_marks(vista)

    assert _paginas_dibujadas(vista) == {0, 1, 2, 7}
    # La marca elegida añade el recuadro del margen de borrado.
    tags_pagina_7 = [
        tags for _coords, tags in vista._canvas.creados if "img_7" in tags
    ]
    assert len(tags_pagina_7) == MARCAS_POR_PAGINA + 1
    assert any("pad" in tags for tags in tags_pagina_7)


def test_sin_marcas_visibles_no_se_dibuja_nada() -> None:
    """El interruptor de «ocultar marcas» sigue mandando sobre todo."""
    vista = _cinta(desplazamiento=0.0)
    vista._marks_visible = False

    StripCanvas._render_marks(vista)

    assert vista._canvas.creados == []


def _cinta_real(root: tk.Tk, *, marcas: dict[int, list[Mark]] | None = None):
    """Una cinta de verdad, con tres páginas de 80x100 y sin descodificar.

    `source` no se llega a llamar: estos tests son de la aritmética de
    coordenadas, que es lo que la cinta hace sin mirar los píxeles.
    """
    marcas = marcas or {}
    stores = [marcas.get(i, []) for i in range(3)]
    return StripCanvas(
        root,
        items_count=3,
        stores=stores,
        source=lambda i: (_ for _ in ()).throw(
            AssertionError("no debería descodificar nada"),
        ),
        size=lambda _i: (80, 100),
        scale=1.0,
        color="#ff0000",
    )


def test_las_paginas_se_apilan_en_un_solo_eje(root: tk.Tk) -> None:
    """Una debajo de otra, centradas sobre la más ancha."""
    cinta = _cinta_real(root)
    cinta.layout()

    assert cinta.total_height() == 300
    assert cinta._layout == [
        (0.0, 0.0, 80, 100), (0.0, 100.0, 80, 100), (0.0, 200.0, 80, 100),
    ]
    cinta.destroy()


def test_de_la_cinta_a_la_pagina_y_al_reves(root: tk.Tk) -> None:
    """La página que toca y el píxel dentro de ella."""
    cinta = _cinta_real(root)
    cinta.layout()

    assert cinta.page_at(-1) is None
    assert cinta.page_at(0) == 0
    assert cinta.page_at(150) == 1
    assert cinta.page_at(299) == 2
    assert cinta.page_at(300) is None

    assert cinta.strip_to_image(10, 150) == (1, 10, 50)
    assert cinta.image_to_strip(1, 10, 50) == (10.0, 150.0)
    # Con página dada, un punto que se fue a la vecina se queda dentro.
    assert cinta.strip_to_image(10, 250, 1) == (1, 10, 100)
    cinta.destroy()


def test_un_clic_encuentra_la_marca_de_su_pagina(root: tk.Tk) -> None:
    """La misma marca en dos páginas: la que contesta es la de debajo."""
    marca = Mark(x=10, y=20, w=30, h=40, color="#ffcc00")
    cinta = _cinta_real(root, marcas={0: [marca], 2: [marca]})
    cinta.layout()

    assert cinta.mark_at(20, 30) == (0, 0)
    assert cinta.mark_at(20, 230) == (2, 0)
    # Fuera del rectángulo no hay marca, aunque la página sí esté.
    assert cinta.mark_at(70, 95) is None
    cinta.destroy()


def test_la_vista_guardada_vuelve_con_su_escala(root: tk.Tk) -> None:
    """Lo que usa el interruptor «Limpia» para no perder el sitio."""
    cinta = _cinta_real(root)
    cinta.layout()
    cinta.set_viewport((2.0, 0.0, 120.0))

    assert cinta.scale() == 2.0
    assert cinta.zoom_percent() == 200
    # Y la escala es lo primero que devuelve, para volver a dársela.
    assert cinta.viewport()[0] == 2.0
    cinta.destroy()


def test_rasterizar_pide_solo_las_paginas_de_la_banda(root: tk.Tk) -> None:
    """El recorte y el escalado de verdad, con imágenes de verdad.

    El lienzo de una raíz oculta mide 1x1, así que la banda visible pilla
    la primera página y ninguna más: justo lo que se quiere comprobar,
    que a las otras no se les piden los píxeles.
    """
    pedidas: list[int] = []

    def source(idx: int) -> Image.Image:
        pedidas.append(idx)
        return Image.new("RGB", (80, 100), "white")

    cinta = StripCanvas(
        root,
        items_count=3,
        stores=[[], [], []],
        source=source,
        size=lambda _i: (80, 100),
        scale=1.0,
        color="#ff0000",
    )
    cinta.render()

    assert pedidas == [0], pedidas
    # Y la página que se dibujó tiene su item en el lienzo.
    assert list(cinta._photo_ids) == [0]
    cinta.destroy()
