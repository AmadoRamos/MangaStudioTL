"""La geometría de la limpieza: qué se agrupa, qué se borra y qué caduca.

Nada de esto toca LaMa. Son las decisiones que se toman *antes* de
llamarlo, y son las que deciden si una página vuelve a pasar por el
modelo o no — o sea, minutos de espera por capítulo.
"""

from __future__ import annotations

from pathlib import Path

from src.config import INPAINT_PADDING_PX
from src.utils.inpainter import (
    Inpainter,
    bboxes_overlap,
    clean_is_stale,
    clean_path,
    cluster_marks,
    find_clean,
    marks_signature,
    union_bbox,
)
from src.utils.marks_store import Mark, MarksStore, sidecar_path


def _mark(x: int, y: int, w: int = 50, h: int = 20, **kw) -> Mark:
    return Mark(x=x, y=y, w=w, h=h, color="#ffcc00", **kw)


def test_la_firma_ignora_lo_que_no_llega_a_la_mascara() -> None:
    """El color de una caja no cambia un píxel de la limpia.

    Si entrase en la firma, recolorear una marca mandaría el capítulo
    entero de vuelta a LaMa para obtener el mismo PNG.
    """
    amarilla = [_mark(0, 0)]
    roja = [Mark(x=0, y=0, w=50, h=20, color="#ff0000")]
    assert marks_signature(amarilla) == marks_signature(roja)

    # Mover la caja sí.
    assert marks_signature(amarilla) != marks_signature([_mark(1, 0)])
    # Y el margen propio también, porque sí llega a la máscara.
    assert marks_signature(amarilla) != marks_signature([_mark(0, 0, padding=40)])
    # Pero un margen «sin tocar» no puede escribirse como si fuera el
    # valor por defecto: eso cambiaría todas las firmas ya guardadas.
    assert (
        marks_signature(amarilla)
        != marks_signature([_mark(0, 0, padding=INPAINT_PADDING_PX)])
    )
    # El orden de las marcas es parte de la firma, y basta con eso: dos
    # órdenes distintos producen la misma limpia, pero volver a limpiar
    # de más es barato comparado con no limpiar cuando hacía falta.
    assert len(marks_signature(amarilla)) == 16


def test_caducidad_de_la_limpia(tmp_path: Path) -> None:
    """Cuándo hay que volver a limpiar una página."""
    page = tmp_path / "p.jpg"
    page.write_bytes(b"no importa el contenido")
    marks = [_mark(0, 0)]

    # Sin marcas no hay nada que limpiar, aunque no exista la limpia.
    assert clean_is_stale(page, []) is False
    # Con marcas y sin limpia, hay trabajo.
    assert clean_is_stale(page, marks) is True

    clean_path(page).write_bytes(b"limpia")
    firma = marks_signature(marks)
    assert clean_is_stale(page, marks, firma) is False
    # La misma limpia con otras cajas detrás ya no vale.
    assert clean_is_stale(page, [_mark(9, 9)], firma) is True


def test_sin_firma_manda_la_fecha(tmp_path: Path) -> None:
    """Una limpia traída de fuera se cree, salvo que las marcas sean nuevas.

    Es la única prueba disponible cuando no hay firma guardada: un
    capítulo limpiado antes de que existieran las firmas, o a mano.
    """
    page = tmp_path / "p.jpg"
    page.write_bytes(b"x")
    clean_path(page).write_bytes(b"limpia")
    marks = [_mark(0, 0)]

    # Sidecar más viejo que la limpia: la limpia sigue valiendo.
    store = MarksStore(page)
    store.add(marks[0])
    side = sidecar_path(page)
    import os
    old = clean_path(page).stat().st_mtime - 100
    os.utime(side, (old, old))
    assert clean_is_stale(page, marks) is False

    # Sidecar tocado después: las cajas se movieron, hay que rehacerla.
    new = clean_path(page).stat().st_mtime + 100
    os.utime(side, (new, new))
    assert clean_is_stale(page, marks) is True


def test_find_clean_acepta_cualquier_extension(tmp_path: Path) -> None:
    """El paso 2 escribe PNG, pero una limpia de fuera puede ser jpg."""
    page = tmp_path / "p.jpg"
    assert find_clean(page) is None
    otra = tmp_path / "p.clean.jpg"
    otra.write_bytes(b"x")
    assert find_clean(page) == otra
    # La PNG que escribe la aplicación gana a la de fuera.
    propia = clean_path(page)
    propia.write_bytes(b"x")
    assert find_clean(page) == propia


def test_dos_marcas_lejos_no_comparten_recorte() -> None:
    """Agrupar de más es pedirle a LaMa un recorte enorme por nada."""
    juntas = [_mark(0, 0), _mark(60, 0)]      # 10 px de hueco
    assert len(cluster_marks(juntas, gap=32)) == 1
    lejos = [_mark(0, 0), _mark(500, 0)]
    assert len(cluster_marks(lejos, gap=32)) == 2
    assert cluster_marks([], gap=32) == []


def test_el_grupo_crece_en_cadena() -> None:
    """A—B—C entran juntas aunque A y C no se rocen entre sí.

    Sin la reabsorción, A y C acabarían en recortes distintos que se
    pisan en el pegado, y la costura se ve.
    """
    cadena = [_mark(0, 0), _mark(400, 0), _mark(70, 0)]
    grupos = cluster_marks(cadena, gap=32)
    assert len(grupos) == 2
    assert len(max(grupos, key=len)) == 2


def test_un_margen_grande_acerca_las_marcas() -> None:
    """Dos áreas borradas que se solapan tienen que ir en el mismo recorte.

    Solo cuenta lo que el usuario pidió *de más* sobre el margen base:
    si contase el margen entero, una marca sin ajustar cambiaría de
    grupo respecto a como agrupaba antes.
    """
    lejos = [_mark(0, 0), _mark(200, 0)]
    assert len(cluster_marks(lejos, gap=32)) == 2
    con_margen = [_mark(0, 0, padding=90), _mark(200, 0, padding=90)]
    assert len(cluster_marks(con_margen, gap=32)) == 1


def test_solapes_y_uniones() -> None:
    assert bboxes_overlap((0, 0, 10, 10), (5, 5, 20, 20)) is True
    assert bboxes_overlap((0, 0, 10, 10), (20, 0, 30, 10)) is False
    # Se tocan a través del hueco.
    assert bboxes_overlap((0, 0, 10, 10), (20, 0, 30, 10), gap=10) is True
    assert union_bbox([(0, 5, 10, 10), (3, 0, 20, 8)]) == (0, 0, 20, 10)
    assert union_bbox([]) == (0, 0, 0, 0)


def test_la_mascara_no_se_sale_de_la_imagen() -> None:
    """Una marca en el borde se recorta; si queda vacía, no se dibuja.

    ``getbbox`` devuelve un píxel más a la derecha y abajo porque
    ``ImageDraw.rectangle`` pinta ambos extremos: el área borrada es un
    píxel más ancha que la caja. Da igual para un relleno de LaMa, y se
    escribe aquí para que nadie lo «arregle» creyendo que es un desfase.
    """
    dentro = Inpainter.build_mask((100, 100), [_mark(10, 10, 20, 20, padding=0)])
    assert dentro.getbbox() == (10, 10, 31, 31)

    # Una marca entera fuera de la imagen no pinta nada.
    borde = Inpainter.build_mask((100, 100), [_mark(-50, -50, 20, 20, padding=0)])
    assert borde.getbbox() is None

    # Y una que se sale por la derecha se corta en el borde: pedirle a
    # PIL que pinte fuera del lienzo no ensancha la máscara, pero sí deja
    # el área borrada sin la franja de contexto que LaMa necesita.
    saliente = Inpainter.build_mask((100, 100), [_mark(80, 80, 60, 60, padding=0)])
    assert saliente.getbbox() == (80, 80, 100, 100)

    # Con margen el área crece, y se para en el borde de la imagen.
    con_margen = Inpainter.build_mask((100, 100), [_mark(0, 0, 20, 20, padding=10)])
    assert con_margen.getbbox() == (0, 0, 31, 31)

    # El ``padding`` explícito manda sobre el de cada marca: es lo que
    # pide quien quiere una máscara uniforme.
    forzada = Inpainter.build_mask(
        (100, 100), [_mark(10, 10, 20, 20, padding=40)], padding=0,
    )
    assert forzada.getbbox() == (10, 10, 31, 31)
