"""La máscara de borrado, ceñida al trazo del rótulo.

Hasta aquí la máscara era el rectángulo de la marca engordado por su
margen: un bloque sólido que se borraba entero y que LaMa tenía que
inventar entero. Debajo de ese bloque hay trama, líneas cinéticas y
bordes de globo que sí existen, y una red pequeña los reinventa peor de
lo que estaban.

Este módulo se queda solo con los píxeles que son rótulo. El truco no es
el umbral —eso lo hace Otsu—, son las dos decisiones de alrededor:

  - la polaridad la decide el anillo del borde, no una constante, porque
    el mismo capítulo trae letra negra sobre globo blanco y letra blanca
    sobre fondo oscuro;
  - se quedan las componentes conexas que tocan la caja que dibujó el
    usuario, y solo esas. Eso se lleva el contorno y la sombra aunque se
    derramen fuera de la caja, y deja en paz la trama que pasa por
    debajo.

Cuando el umbral no encuentra nada creíble se devuelve el rectángulo de
siempre: se limpia como antes, nunca peor.

Nada de esto toca LaMa ni torch, así que se puede probar sin modelo.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from src.utils.logger import get_logger

log = get_logger("text_mask")

#: (x0, y0, x1, y1) en coordenadas del recorte, extremo derecho excluido.
Rect = tuple[int, int, int, int]

#: Por encima de esto lo detectado ya no es «el trazo»: o el umbral se ha
#: partido por donde no era, o el rótulo se come el panel de verdad. En
#: los dos casos el rectángulo es la respuesta honesta.
_MAX_COVERAGE = 0.65
#: Y por debajo de esto no ha encontrado letra ninguna.
_MIN_COVERAGE = 0.005

#: Cuánto tiene que salirse del fondo el color pegado al trazo para que
#: cuente como contorno del rótulo. Se compara contra los percentiles del
#: anillo y no contra su media, porque en una trama de semitonos la media
#: no es ningún color que exista: el fondo es blanco puro y negro puro a
#: partes iguales, y el blanco del hueco que se le abre al rótulo es el
#: mismo blanco del papel. Medido sobre las 22 marcas de las páginas de
#: ejemplo, el margen sobre p95: 5 en la trama —que no es contorno— y 16
#: en el rótulo con contorno blanco sobre pared gris, que sí lo es.
_HALO_DELTA = 10
#: Y cuánto se puede parecer un píxel al contorno para ser contorno.
_HALO_TOL = 24
#: Hasta dónde se busca. Un contorno de rótulo grande ronda los 15 px; el
#: límite existe para que un fondo del mismo color que el contorno no se
#: absorba entero.
_HALO_REACH_PX = 16
#: Tamaño mínimo de una componente para preguntarle por su contorno. Una
#: mota de trama o de JPEG no tiene contorno, y en una página tramada son
#: miles.
_HALO_MIN_AREA_PX = 64
_HALO_MIN_AREA_FRAC = 0.001


def build_mask(
    crop: Image.Image,
    regions: list[tuple[Rect, Rect]],
    dilate: int,
) -> Image.Image:
    """Máscara del recorte (255 = se borra) para varias marcas.

    Cada región es ``(caja, área)``: la caja que dibujó quien rotula y esa
    misma caja engordada por su margen. El área es el techo —fuera de ella
    no se toca un píxel, que es lo que promete el rectángulo punteado del
    paso 2— y la caja es lo que decide qué componentes son rótulo.
    """
    width, height = crop.size
    mask = np.zeros((height, width), np.uint8)
    if not regions:
        return Image.fromarray(mask, mode="L")
    gray = cv2.cvtColor(np.asarray(crop.convert("RGB")), cv2.COLOR_RGB2GRAY)
    for box, area in regions:
        ax0, ay0, ax1, ay1 = area
        if ax1 <= ax0 or ay1 <= ay0:
            continue
        roi = gray[ay0:ay1, ax0:ax1]
        inner = _clip(
            (box[0] - ax0, box[1] - ay0, box[2] - ax0, box[3] - ay0),
            ax1 - ax0, ay1 - ay0,
        )
        strokes = _strokes(roi, inner, dilate)
        if strokes is None:
            mask[ay0:ay1, ax0:ax1] = 255
        else:
            mask[ay0:ay1, ax0:ax1] |= strokes
    return Image.fromarray(mask, mode="L")


def _clip(rect: Rect, width: int, height: int) -> Rect:
    return (
        max(0, min(int(rect[0]), width)),
        max(0, min(int(rect[1]), height)),
        max(0, min(int(rect[2]), width)),
        max(0, min(int(rect[3]), height)),
    )


def _strokes(roi: np.ndarray, box: Rect, dilate: int) -> np.ndarray | None:
    """Los píxeles de rótulo dentro de ``roi``, o None si no son creíbles."""
    if roi.size == 0 or box[2] <= box[0] or box[3] <= box[1]:
        return None
    ring = _ring(roi)
    thr, bright = cv2.threshold(
        roi, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU,
    )
    # El borde del área es margen: lo que haya ahí es fondo por
    # construcción. Si el fondo cae en la clase clara, el rótulo es la
    # oscura, y al revés.
    #
    # La comparación es estricta porque Otsu devuelve el umbral *dentro*
    # de la clase oscura: en una imagen de dos valores puros —tinta plana
    # sobre globo blanco, o sea la mitad del manga— devuelve 0, y con un
    # ``>=`` el fondo negro se leería como clase clara y se borraría el
    # fondo en vez del rótulo.
    text = cv2.bitwise_not(bright) if np.median(ring) > thr else bright
    text = _fill_holes(text)
    text = _touching(text, box)
    text = _absorb_halo(roi, text, ring)
    if dilate > 0:
        text = cv2.dilate(text, _kernel(dilate))
    coverage = float(np.count_nonzero(text)) / float(text.size)
    if not _MIN_COVERAGE <= coverage <= _MAX_COVERAGE:
        log.debug(
            "trazo descartado (%.1f%% del area): se borra el rectangulo",
            coverage * 100,
        )
        return None
    return text


def _kernel(radius: int) -> np.ndarray:
    return np.ones((2 * radius + 1, 2 * radius + 1), np.uint8)


def _absorb_halo(
    roi: np.ndarray,
    text: np.ndarray,
    ring: np.ndarray,
) -> np.ndarray:
    """Se lleva también el contorno del rótulo, si lo tiene.

    Un rótulo grande casi nunca es tinta plana: lleva un contorno blanco,
    o el hueco que se le abre a la trama para que se lea. Ese contorno no
    es del color de la letra, así que el umbral no lo coge — y borrar la
    letra sin él deja un fantasma con su forma, que es peor que no haber
    tocado nada.

    Se detecta preguntando si el color pegado al trazo es un color que el
    fondo ya tiene: si cae dentro del rango del anillo del área, la letra
    está posada directamente sobre el fondo y aquí no hay nada que hacer.
    Si se sale, ese color es contorno y entra, hasta donde llegue
    ``_HALO_REACH_PX``.

    La pregunta se hace **por componente y no por máscara entera**, y esa
    es la parte que costó una página mal limpiada: la caja la dibuja una
    persona, y suele sobrar sitio. Todo lo oscuro del dibujo que caiga
    dentro entra en la máscara, y si se promedia el color pegado a todo
    junto, el gris de la pared se lleva por delante el blanco del
    contorno — la misma marca daba contorno con la caja ajustada y no lo
    daba al agrandarla. Letra a letra no hay nada que promediar.

    Cuando el contorno es grueso, absorberlo dispara la guarda de
    cobertura y la marca acaba borrándose como rectángulo. Es lo correcto
    y no un efecto secundario: un rótulo con un contorno así no deja
    fondo que salvar, y lo que hay que evitar a toda costa es rellenar la
    letra dejando el contorno puesto, que deja un fantasma con su forma.
    """
    if not text.any():
        return text
    low, high = np.percentile(ring, (5, 95))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(text, 8)
    # Una mota no tiene contorno que valga la pena mirar, y mirarlas todas
    # en una trama de semitonos son miles de recortes para nada.
    floor = max(_HALO_MIN_AREA_PX, int(text.size * _HALO_MIN_AREA_FRAC))
    out = text.copy()
    for index in range(1, count):
        if stats[index, cv2.CC_STAT_AREA] < floor:
            continue
        window = _window(stats[index], text.shape)
        piece = (labels[window] == index).astype(np.uint8) * 255
        patch = roi[window]
        band = cv2.bitwise_and(
            cv2.dilate(piece, _kernel(3)), cv2.bitwise_not(piece),
        )
        values = patch[band > 0]
        if values.size == 0:
            continue
        halo = float(np.median(values))
        if low - _HALO_DELTA <= halo <= high + _HALO_DELTA:
            continue
        near = np.abs(patch.astype(np.int16) - halo) <= _HALO_TOL
        reach = cv2.dilate(piece, _kernel(_HALO_REACH_PX)) > 0
        out[window] |= np.where(near & reach, 255, 0).astype(np.uint8)
    return out


def _window(stat: np.ndarray, shape: tuple[int, int]) -> tuple[slice, slice]:
    """La caja de una componente con sitio para su contorno alrededor."""
    margin = _HALO_REACH_PX + 3
    x, y = stat[cv2.CC_STAT_LEFT], stat[cv2.CC_STAT_TOP]
    w, h = stat[cv2.CC_STAT_WIDTH], stat[cv2.CC_STAT_HEIGHT]
    return (
        slice(max(0, y - margin), min(shape[0], y + h + margin)),
        slice(max(0, x - margin), min(shape[1], x + w + margin)),
    )


def _ring(roi: np.ndarray) -> np.ndarray:
    """El anillo de 1 px que rodea al área: el fondo, por construcción."""
    return np.concatenate((roi[0], roi[-1], roi[:, 0], roi[:, -1]))


def _fill_holes(binary: np.ndarray) -> np.ndarray:
    """Rellena lo que quede encerrado dentro del trazo.

    Sirve para dos cosas a la vez: el interior de la ``O``, y el núcleo
    negro de un rótulo blanco sobre fondo oscuro, del que el umbral solo
    ha cogido el contorno.

    Se inunda desde una orla añadida alrededor porque el borde real de la
    región puede ser trazo, y entonces no habría por dónde entrar.
    """
    height, width = binary.shape
    padded = cv2.copyMakeBorder(
        binary, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0,
    )
    scratch = np.zeros((height + 4, width + 4), np.uint8)
    cv2.floodFill(padded, scratch, (0, 0), 255)
    outside = padded[1:-1, 1:-1]
    return cv2.bitwise_or(binary, cv2.bitwise_not(outside))


def _touching(binary: np.ndarray, box: Rect) -> np.ndarray:
    """Solo las componentes conexas que pisan ``box``.

    Es el filtro que separa el rótulo del dibujo: la letra y todo lo que
    va pegado a ella entran enteros aunque se salgan de la caja, y la
    trama o el borde del globo que pasan por el margen se quedan.
    """
    count, labels = cv2.connectedComponents(binary, connectivity=8)
    if count <= 1:
        return binary
    keep = np.unique(labels[box[1]:box[3], box[0]:box[2]])
    keep = keep[keep != 0]
    if keep.size == 0:
        return np.zeros_like(binary)
    return np.where(np.isin(labels, keep), 255, 0).astype(np.uint8)
