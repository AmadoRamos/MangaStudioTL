"""Las marcas que la cinta dibuja, y las que no.

`_draw_strip` rasteriza solo la banda visible y el overlay de marcas
recorría el capítulo entero, así que cada notch de rueda destruía y
recreaba las marcas de todas las páginas. Aquí se prueba lo que *no* se
dibuja.

Los métodos se llaman sin construir la vista entera, como en
``test_clean_cache``: solo tocan los atributos que se le ponen al doble,
y montar un ``MarksView`` de verdad exige media aplicación.
"""

from __future__ import annotations

from types import MethodType, SimpleNamespace

from src.utils.marks_store import Mark
from src.views.marks_view import MarksView

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


def _vista(
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
        _items=[None] * PAGINAS,
        _stores=stores,
        _strip_layout=[
            (0.0, float(i * ALTO_PAGINA), 80, ALTO_PAGINA)
            for i in range(PAGINAS)
        ],
        _strip_scale=1.0,
        _mark_ids_by_image=[[] for _ in range(PAGINAS)],
        _marks_visible=True,
        _viewing_clean=False,
        _selected=seleccionada,
    )
    # Los tres métodos que `_render_all_marks` llama por su cuenta, atados
    # al doble: son justo lo que se quiere probar de verdad.
    for nombre in ("_visible_band", "_overlay_pages", "_image_to_strip"):
        setattr(vista, nombre, MethodType(getattr(MarksView, nombre), vista))
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
    vista = _vista(desplazamiento=0.0)

    MarksView._render_all_marks(vista)

    # La ventana abarca 250 px: las tres primeras páginas y ni una más.
    assert _paginas_dibujadas(vista) == {0, 1, 2}
    assert len(vista._canvas.creados) == 3 * MARCAS_POR_PAGINA


def test_la_banda_sigue_al_desplazamiento() -> None:
    """Lo que se dibuja es lo que se ve, no lo que se vio al abrir."""
    vista = _vista(desplazamiento=500.0)

    MarksView._render_all_marks(vista)

    assert _paginas_dibujadas(vista) == {5, 6, 7}


def test_la_seleccionada_se_dibuja_aunque_no_se_vea() -> None:
    """Su recuadro de borrado se sale de la página, y es la única que lo tiene."""
    vista = _vista(desplazamiento=0.0, seleccionada=(7, 1))

    MarksView._render_all_marks(vista)

    assert _paginas_dibujadas(vista) == {0, 1, 2, 7}
    # La marca elegida añade el recuadro del margen de borrado.
    tags_pagina_7 = [
        tags for _coords, tags in vista._canvas.creados if "img_7" in tags
    ]
    assert len(tags_pagina_7) == MARCAS_POR_PAGINA + 1
    assert any("pad" in tags for tags in tags_pagina_7)


def test_sin_marcas_visibles_no_se_dibuja_nada() -> None:
    """El interruptor de «ocultar marcas» sigue mandando sobre todo."""
    vista = _vista(desplazamiento=0.0)
    vista._marks_visible = False

    MarksView._render_all_marks(vista)

    assert vista._canvas.creados == []
