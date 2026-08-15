"""Qué se borra dentro del rectángulo: el rótulo, no el dibujo.

Nada de esto toca LaMa. Es la máscara que se le entrega, que es donde
está la mitad del resultado: lo que entra en la máscara se pierde y hay
que inventarlo, y lo que se queda fuera sobrevive tal cual.

Las escenas son sintéticas y feas a propósito —una barra por letra, una
línea recta por fondo— porque lo que se comprueba no es la calidad del
recorte sino las tres decisiones del módulo: la polaridad, las
componentes conexas y la guarda que devuelve el rectángulo.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from src.utils.text_mask import build_mask

# La caja que dibujaría quien rotula, y el área con margen de 10 px.
CAJA = (30, 30, 70, 70)
AREA = (20, 20, 80, 80)


def _escena(fondo: int, tinta: int) -> Image.Image:
    """Una letra dentro de la caja y una línea de fondo cruzándola.

    La línea entra por el margen y pasa por debajo de la caja sin tocar
    la letra: es la trama, el borde del globo o la línea cinética que
    hasta ahora se borraba por estar dentro del rectángulo.
    """
    img = Image.new("RGB", (100, 100), (fondo, fondo, fondo))
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 35, 50, 65), fill=(tinta, tinta, tinta))  # la letra
    draw.line((0, 78, 99, 78), fill=(tinta, tinta, tinta), width=2)
    return img


def _mascara(img: Image.Image, dilate: int = 2) -> np.ndarray:
    return np.asarray(build_mask(img, [(CAJA, AREA)], dilate))


def _cubierto(mask: np.ndarray, rect: tuple[int, int, int, int]) -> bool:
    return bool(mask[rect[1]:rect[3], rect[0]:rect[2]].all())


def _limpio(mask: np.ndarray, rect: tuple[int, int, int, int]) -> bool:
    return not mask[rect[1]:rect[3], rect[0]:rect[2]].any()


def test_la_mascara_coge_la_letra_y_deja_el_fondo() -> None:
    """Letra negra sobre globo blanco: se borra la letra, no la línea."""
    mask = _mascara(_escena(fondo=255, tinta=0))

    assert _cubierto(mask, (40, 35, 50, 65))
    # La línea del fondo pasa por dentro del área y sigue ahí.
    assert _limpio(mask, (20, 77, 38, 80))
    # Y con ella, la mayor parte del rectángulo que antes se borraba
    # entero: eso es exactamente lo que LaMa ya no tiene que inventar.
    area_px = (AREA[2] - AREA[0]) * (AREA[3] - AREA[1])
    assert np.count_nonzero(mask) < area_px * 0.5


def test_la_polaridad_la_decide_el_borde_no_una_constante() -> None:
    """La misma escena en negativo da la misma máscara.

    Es lo que separa el manga en blanco y negro del webtoon a color: en
    el mismo capítulo hay letra negra sobre globo blanco y letra blanca
    sobre fondo oscuro, y nadie va a etiquetar cuál es cuál.
    """
    normal = _mascara(_escena(fondo=255, tinta=0))
    negativo = _mascara(_escena(fondo=0, tinta=255))

    assert np.array_equal(normal, negativo)


def test_lo_pegado_a_la_letra_entra_entero_y_lo_suelto_no() -> None:
    """La componente conexa manda, no el rectángulo.

    El contorno y la sombra de un rótulo se salen de la caja que dibujó
    quien rotula: si se corta por la caja, queda el halo. Lo que no toca
    la letra, en cambio, es dibujo y se queda donde está.
    """
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 35, 50, 65), fill=(0, 0, 0))
    # Cola que sale de la letra y se derrama fuera de la caja.
    draw.rectangle((50, 50, 74, 53), fill=(0, 0, 0))
    # Mancha suelta dentro del área, sin tocar nada.
    draw.rectangle((22, 22, 27, 27), fill=(0, 0, 0))

    mask = np.asarray(build_mask(img, [(CAJA, AREA)], 0))

    assert _cubierto(mask, (50, 50, 74, 53))
    assert _limpio(mask, (22, 22, 28, 28))


def test_el_contorno_del_rotulo_se_va_con_la_letra() -> None:
    """Un rótulo con contorno se borra entero, contorno incluido.

    Salió de la página de ejemplo con el rótulo grande sobre la pared: el
    umbral coge el núcleo negro de la letra y deja el contorno blanco, y
    LaMa rellena el núcleo del color del contorno. El resultado es un
    fantasma blanco con forma de letra — peor que no haber tocado nada.
    """
    img = Image.new("RGB", (100, 100), (128, 128, 128))
    draw = ImageDraw.Draw(img)
    draw.rectangle((34, 29, 56, 71), fill=(255, 255, 255))  # el contorno
    draw.rectangle((40, 35, 50, 65), fill=(0, 0, 0))        # la letra

    mask = _mascara(img, dilate=0)

    assert _cubierto(mask, (40, 35, 50, 65))
    # El contorno es lo que antes se quedaba: las cuatro bandas de blanco
    # alrededor de la letra tienen que estar dentro de la máscara.
    assert _cubierto(mask, (34, 29, 56, 34))
    assert _cubierto(mask, (34, 66, 56, 71))
    # Y el fondo, que no es del color del contorno, sigue donde estaba.
    assert _limpio(mask, (20, 20, 33, 80))


def test_el_contorno_se_ve_aunque_la_caja_venga_ancha() -> None:
    """Agrandar la caja no puede hacer desaparecer el contorno.

    Esto se coló en una página de verdad: la misma marca daba contorno con
    la caja ajustada y dejaba de darlo al agrandarla un poco. La caja la
    dibuja una persona y suele sobrar sitio; todo lo oscuro del dibujo que
    caiga dentro entra en la máscara, y si el color pegado al trazo se
    promedia sobre todo junto, el fondo se lleva por delante el blanco del
    contorno. Por eso la pregunta se hace componente a componente.
    """
    img = Image.new("RGB", (100, 100), (128, 128, 128))
    draw = ImageDraw.Draw(img)
    draw.rectangle((34, 29, 56, 71), fill=(255, 255, 255))
    draw.rectangle((40, 35, 50, 65), fill=(0, 0, 0))
    # Lo que sobra dentro de la caja: tinta del dibujo, mucho borde y
    # ningún contorno. Es lo que antes diluía la medición.
    for x in (58, 61, 64):
        draw.rectangle((x, 32, x + 1, 68), fill=(40, 40, 40))

    mask = _mascara(img, dilate=0)

    assert _cubierto(mask, (34, 29, 56, 34))
    assert _cubierto(mask, (34, 66, 56, 71))


def test_el_contorno_solo_cuenta_si_no_es_el_fondo() -> None:
    """Sobre trama, el blanco pegado a la letra es el papel.

    En una trama de semitonos el fondo *es* blanco puro y negro puro a
    partes iguales. Si el blanco de al lado de la letra contase como
    contorno, se absorbería media trama y la marca acabaría borrándose
    como rectángulo, que es justo lo que se venía a evitar.
    """
    trama = np.full((100, 100), 255, np.uint8)
    trama[::3, ::3] = 160
    img = Image.fromarray(trama).convert("RGB")
    ImageDraw.Draw(img).rectangle((40, 35, 50, 65), fill=(0, 0, 0))

    mask = _mascara(img, dilate=1)

    assert _cubierto(mask, (40, 35, 50, 65))
    area_px = (AREA[2] - AREA[0]) * (AREA[3] - AREA[1])
    assert np.count_nonzero(mask) < area_px * 0.25


def test_sin_trazo_creible_se_borra_el_rectangulo() -> None:
    """La guarda: se limpia como siempre, nunca peor.

    Un área sin contraste no tiene letra que encontrar, y una casi toda
    tinta —un rótulo que se come el panel— no deja fondo que salvar. En
    los dos casos el rectángulo de siempre es la respuesta honesta.
    """
    liso = Image.new("RGB", (100, 100), (128, 128, 128))
    assert _cubierto(np.asarray(build_mask(liso, [(CAJA, AREA)], 2)), AREA)

    tapado = Image.new("RGB", (100, 100), (255, 255, 255))
    ImageDraw.Draw(tapado).rectangle((22, 22, 78, 78), fill=(0, 0, 0))
    assert _cubierto(np.asarray(build_mask(tapado, [(CAJA, AREA)], 2)), AREA)


def test_fuera_del_area_no_se_toca_un_pixel() -> None:
    """El punteado del paso 2 sigue siendo el techo.

    La letra se dilata para llevarse el antialiasing, y esa dilatación
    podría salirse del rectángulo que se le enseña a quien rotula. Se
    recorta: lo que promete el punteado es que fuera no pasa nada.
    """
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    ImageDraw.Draw(img).rectangle((22, 22, 78, 45), fill=(0, 0, 0))

    mask = np.asarray(build_mask(img, [(CAJA, AREA)], 8))

    assert _limpio(mask, (0, 0, 100, AREA[1]))
    assert _limpio(mask, (0, AREA[3], 100, 100))
    assert _limpio(mask, (0, 0, AREA[0], 100))
    assert _limpio(mask, (AREA[2], 0, 100, 100))
