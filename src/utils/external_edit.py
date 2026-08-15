"""Editar una sección en el programa de imagen que tenga el usuario.

Recorta el rectángulo de una marca a un PNG temporal y, cuando el usuario
guarda desde su editor, lo pega de vuelta en la versión limpia de la
página. Es la salida para lo que LaMa no resuelve —trama compleja, rótulo
sobre dibujo, onomatopeya grande— sin obligar a limpiar la página entera
a mano, que hasta ahora era la única alternativa.

Dos decisiones que no son de estilo:

* **El pegado es duro**, sin máscara. El difuminado de bordes de
  :func:`~src.utils.inpainter._paste_alpha` existe para disimular la
  costura de una regeneración automática; aquí el borde lo ha decidido
  una persona y suavizarlo sería contradecirla.
* **Se escribe siempre en** :func:`~src.utils.inpainter.clean_path`, sea
  cual sea la base. El original no se toca nunca: es la única copia de la
  página que hay, y el paso 4 ya lee por ``find_clean``.

Quien llame a :func:`apply_region` tiene que grabar después
``store.clean_signature = marks_signature(marks)``, o la siguiente pasada
de limpieza reescribe el ``.clean.png`` entero y se lleva el retoque por
delante sin decir nada.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

from src.config import EDIT_TEMP_DIR
from src.utils.inpainter import _save_atomic, clean_path
from src.utils.logger import get_logger
from src.utils.marks_store import Mark

log = get_logger("external_edit")

Box = tuple[int, int, int, int]

#: Cuánto se guardan los recortes ya editados. Cada edición deja un
#: archivo nuevo, así que sin barrer la carpeta crece sin fin a varios MB
#: por sección. Un día de margen deja fuera lo que se está editando ahora
#: por mucho que se alargue la sesión.
EDIT_KEEP_SECONDS = 24 * 3600


def edit_dir() -> Path:
    """Carpeta de los recortes en edición, creada al vuelo."""
    root = Path(tempfile.gettempdir()) / EDIT_TEMP_DIR
    root.mkdir(parents=True, exist_ok=True)
    _prune(root)
    return root


def _prune(root: Path, keep: float = EDIT_KEEP_SECONDS) -> int:
    """Tira los recortes de sesiones viejas. Devuelve cuántos.

    Un archivo que el usuario siga teniendo abierto en el editor da un
    error de archivo en uso al borrarlo; se ignora y se sigue con el
    resto, que es justo lo que se quiere: se irá en la barrida siguiente.
    """
    limit = time.time() - keep
    gone = 0
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        log.warning("No se pudo barrer %s: %s", root, exc)
        return 0
    for entry in entries:
        try:
            if entry.is_file() and entry.stat().st_mtime < limit:
                entry.unlink()
                gone += 1
        except OSError:
            continue
    if gone:
        log.info("Recortes viejos borrados: %d", gone)
    return gone


def region_box(mark: Mark, size: tuple[int, int]) -> Box:
    """El recuadro punteado de ``mark``, recortado a la página.

    La marca crecida por su ``erase_padding``, que es exactamente lo que
    el usuario ve dibujado y lo que el paso 2 le promete que se borrará.
    Recortar solo la caja dejaría fuera el halo del rótulo, que es medio
    trabajo del retoque.
    """
    pad = mark.erase_padding
    width, height = size
    x0 = max(0, min(mark.x - pad, width))
    y0 = max(0, min(mark.y - pad, height))
    x1 = max(0, min(mark.x + mark.w + pad, width))
    y1 = max(0, min(mark.y + mark.h + pad, height))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"Recorte vacio: ({x0},{y0})-({x1},{y1})")
    return (x0, y0, x1, y1)


def region_file(page_path: Path, uid: str) -> Path:
    """Un archivo nuevo para el recorte de una marca. Lo crea vacío.

    Lleva el ``uid`` y no el índice: borrar una marca anterior desplaza
    los índices (``MarksStore._shift_down``) y el archivo abierto en el
    editor pasaría a pegarse en el sitio de otra.

    Y lleva la hora, porque **cada intento estrena archivo**. Reeditar la
    misma sección sobre el mismo nombre pisa lo que el editor pueda tener
    todavía abierto: unos guardan sobre el archivo que abrieron sin
    releerlo —y devuelven la versión vieja encima del retoque nuevo— y
    Windows además puede tenerlo bloqueado mientras esté abierto. El
    ``mkstemp`` cierra el resto del hueco: dos ediciones en el mismo
    segundo tampoco chocan.
    """
    fd, name = tempfile.mkstemp(
        prefix=f"{page_path.stem}_{uid}_{time.strftime('%Y%m%d-%H%M%S')}_",
        suffix=".png", dir=edit_dir(),
    )
    os.close(fd)
    return Path(name)


def export_region(image: Image.Image, box: Box, dest: Path) -> Path:
    """Escribe el recorte ``box`` de ``image`` en ``dest`` como PNG."""
    image.crop(box).save(dest, format="PNG")
    log.info("Recorte para editar fuera: %s %s", dest.name, box)
    return dest


def apply_region(
    page_path: Path, base: Image.Image, box: Box, edited: Path,
) -> None:
    """Pega ``edited`` sobre ``base`` en ``box`` y guarda la limpia.

    ``base`` es la limpia si ya existía, si no el original; en el segundo
    caso esta es la llamada que crea el ``.clean.png``. La imagen que
    entra no se modifica: puede ser la página del capítulo que la vista
    tiene cargada en memoria.
    """
    x0, y0, x1, y1 = box
    want = (x1 - x0, y1 - y0)
    mode = base.mode if base.mode in ("RGB", "RGBA", "L") else "RGB"
    with Image.open(edited) as raw:
        patch = raw.convert(mode)
    if patch.size != want:
        # Los editores aplanan, recortan y reencuadran. Se pega lo que
        # quepa desde la esquina: escalar movería de sitio un retoque
        # hecho a mano, y rellenar el hueco lo pintaría de negro.
        log.warning(
            "El editor devolvio %s, se esperaba %s: se pega lo que cabe",
            patch.size, want,
        )
        patch = patch.crop(
            (0, 0, min(patch.width, want[0]), min(patch.height, want[1])),
        )
    result = base.convert(mode)  # copia: la base puede ser la del capítulo
    result.paste(patch, (x0, y0))
    _save_atomic(result, clean_path(page_path))
    log.info("Retoque aplicado en %s %s", clean_path(page_path).name, box)


def open_in_editor(path: Path) -> None:
    """Abre ``path`` en el programa que elija el usuario.

    En Windows sale el diálogo «Abrir con» del sistema, que lista
    Photoshop, GIMP, Krita o lo que haya instalado. Sale más barato que
    una pantalla de ajustes con la ruta a un ejecutable, y no hay una
    ruta que se quede obsoleta cuando actualicen el editor.

    Por ``rundll32`` y no por el verbo ``openas`` de ``startfile``: ese
    verbo pasa por los verbos registrados del tipo de archivo y devuelve
    ``WinError 1155`` cuando el ``.png`` está asociado a una aplicación
    UWP —Fotos, la de fábrica—, que es el caso corriente. ``OpenAs_RunDLL``
    es lo que abre el propio Explorador y no depende de la asociación.
    """
    if sys.platform.startswith("win"):
        try:
            subprocess.Popen(  # pylint: disable=consider-using-with
                ["rundll32.exe", "shell32.dll,OpenAs_RunDLL", str(path)],
            )
            return
        except OSError as exc:
            log.warning("«Abrir con» no disponible (%s), abriendo normal", exc)
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
    # ponytail: fuera de Windows no hay selector, va el programa asociado.
    # Con un «Abrir con» nativo equivalente, cambiarlo aquí.
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(path)])  # pylint: disable=consider-using-with
