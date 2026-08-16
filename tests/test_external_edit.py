"""El viaje de ida y vuelta de un recorte editado en otro programa.

Lo que se prueba aquí es lo que puede perder trabajo del usuario: que el
retoque acabe donde tiene que acabar, que no se lleve por delante el
resto de la página, y que un editor que devuelve otro tamaño no rompa el
pegado ni pinte bandas negras.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.config import EDIT_TEMP_DIR
from src.utils.external_edit import (
    _open_commands,
    _prune,
    apply_region,
    export_region,
    region_box,
    region_file,
)
from src.utils.inpainter import clean_path
from src.utils.marks_store import Mark
from src.views.marks_view import MarksView


def _mark(x: int = 40, y: int = 30, w: int = 50, h: int = 20, **kw) -> Mark:
    return Mark(x=x, y=y, w=w, h=h, color="#ffcc00", **kw)


def _page(tmp_path: Path, size=(200, 150)) -> tuple[Path, Image.Image]:
    ruta = tmp_path / "pagina.png"
    imagen = Image.new("RGB", size, "white")
    imagen.save(ruta)
    return ruta, imagen


def test_ida_y_vuelta(tmp_path: Path) -> None:
    """Lo pintado fuera entra en la limpia, y solo dentro de la caja."""
    ruta, pagina = _page(tmp_path)
    marca = _mark(padding=10)
    caja = region_box(marca, pagina.size)
    recorte = export_region(pagina, caja, tmp_path / "recorte.png")

    x0, y0, x1, y1 = caja
    assert Image.open(recorte).size == (x1 - x0, y1 - y0)

    Image.new("RGB", (x1 - x0, y1 - y0), "red").save(recorte)
    apply_region(ruta, pagina, caja, recorte)

    limpia = Image.open(clean_path(ruta))
    assert limpia.size == pagina.size
    assert limpia.getpixel((x0, y0)) == (255, 0, 0)
    assert limpia.getpixel((x1 - 1, y1 - 1)) == (255, 0, 0)
    # Un píxel fuera de la caja sigue siendo el de la página.
    assert limpia.getpixel((x1, y1)) == (255, 255, 255)
    # Y la imagen que entró no se ha tocado: puede ser la del capítulo.
    assert pagina.getpixel((x0, y0)) == (255, 255, 255)


def test_el_editor_devolvio_otro_tamano(tmp_path: Path) -> None:
    """Aplanar o reencuadrar fuera no puede reventar el pegado.

    Se pega lo que quepa desde la esquina: ni se escala —movería de sitio
    un retoque hecho a mano— ni se rellena el hueco, que saldría negro.
    """
    ruta, pagina = _page(tmp_path)
    caja = region_box(_mark(padding=10), pagina.size)
    x0, y0, x1, y1 = caja

    grande = tmp_path / "grande.png"
    Image.new("RGB", (x1 - x0 + 30, y1 - y0 + 30), "red").save(grande)
    apply_region(ruta, pagina, caja, grande)
    limpia = Image.open(clean_path(ruta))
    assert limpia.size == pagina.size
    assert limpia.getpixel((x1 - 1, y1 - 1)) == (255, 0, 0)
    assert limpia.getpixel((x1, y1)) == (255, 255, 255)

    pequeno = tmp_path / "pequeno.png"
    Image.new("RGB", (10, 10), "blue").save(pequeno)
    apply_region(ruta, pagina, caja, pequeno)
    limpia = Image.open(clean_path(ruta))
    assert limpia.size == pagina.size
    assert limpia.getpixel((x0, y0)) == (0, 0, 255)
    # Lo que el editor no devolvió se queda como estaba, no en negro.
    assert limpia.getpixel((x1 - 1, y1 - 1)) == (255, 255, 255)


def test_la_caja_no_se_sale_de_la_pagina() -> None:
    """Una marca pegada al borde con margen grande sigue siendo válida."""
    caja = region_box(_mark(x=0, y=0, padding=200), (200, 150))
    assert caja == (0, 0, 200, 150)

    x0, y0, x1, y1 = region_box(_mark(x=180, y=140, padding=200), (200, 150))
    assert (x0, y0) == (0, 0)
    assert (x1, y1) == (200, 150)


def test_sin_limpia_previa_se_crea(tmp_path: Path) -> None:
    """La primera edición de una página sin limpiar crea el .clean."""
    ruta, pagina = _page(tmp_path)
    assert not clean_path(ruta).exists()

    caja = region_box(_mark(), pagina.size)
    recorte = tmp_path / "recorte.png"
    Image.new("RGB", (caja[2] - caja[0], caja[3] - caja[1]), "red").save(recorte)
    apply_region(ruta, pagina, caja, recorte)

    assert clean_path(ruta).exists()
    assert Image.open(clean_path(ruta)).getpixel(caja[:2]) == (255, 0, 0)


def test_cada_sistema_usa_su_abrir_con() -> None:
    """Los tres sistemas, sin ejecutar nada.

    Es lo único de este reparto que se puede comprobar desde Windows: que
    macOS y Linux hagan lo que dicen hay que verlo en un Mac y en un Linux.
    """
    ruta = Path("/tmp/pagina_ABC123.png")

    (windows,) = _open_commands(ruta, "win32")
    assert windows[:2] == ["rundll32.exe", "shell32.dll,OpenAs_RunDLL"]

    mac, mac_reserva = _open_commands(ruta, "darwin")
    assert mac[0] == "osascript"
    assert any("choose application" in trozo for trozo in mac)
    # La ruta va suelta al final, no incrustada en el texto del script:
    # incrustarla obliga a escapar comillas a mano y una carpeta con un
    # apóstrofo en el nombre rompería el AppleScript.
    assert mac[-1] == str(ruta)
    assert not any(str(ruta) in trozo for trozo in mac[:-1])
    assert mac_reserva == ["open", str(ruta)]

    linux = _open_commands(ruta, "linux")
    assert linux[0] == ["xdg-open", str(ruta)]
    # Ninguno de Linux pregunta: son cobertura de escritorio, no calidad.
    assert all(cmd[-1] == str(ruta) for cmd in linux)


def _vigilante(recorte: Path) -> SimpleNamespace:
    """El vigilante del recorte, sin construir la vista entera.

    Como en ``test_clean_cache``: solo se le ponen los atributos que el
    método toca, porque un ``MarksView`` de verdad exige media aplicación.
    """
    vista = SimpleNamespace(
        _edit_after=None,
        _edit_session={
            "file": recorte,
            "stamp": MarksView._file_stamp(recorte),
            "settling": False,
        },
        winfo_exists=lambda: True,
        _file_stamp=MarksView._file_stamp,
        _status=SimpleNamespace(set=lambda *a, **k: None),
        _schedule_edit_poll=lambda: None,
        aplicados=[],
    )
    vista._apply_external_edit = vista.aplicados.append

    def _terminar(**_kw):
        vista._edit_session = None

    vista._end_external_edit = _terminar
    return vista


def _guardar(recorte: Path, tam: int) -> None:
    """Un «guardado» del editor: cambia el tamaño, no solo el mtime."""
    recorte.write_bytes(b"x" * tam)


def test_el_retoque_se_aplica_una_vez_por_guardado(tmp_path: Path) -> None:
    """Nada de pegar a mitad de escritura, y nada de pegar dos veces.

    Los editores escriben en dos pasadas, así que hace falta ver el mismo
    ``stat`` dos veces seguidas antes de tocar la limpia: pegar el PNG a
    medio escribir da una imagen truncada donde había trabajo bueno.
    """
    recorte = tmp_path / "recorte.png"
    _guardar(recorte, 10)
    vista = _vigilante(recorte)

    # Sin tocar nada, no pasa nada por mucho que se mire.
    MarksView._poll_external_edit(vista)
    MarksView._poll_external_edit(vista)
    assert vista.aplicados == []

    # El editor empieza a escribir: se ve el cambio, pero todavía no se pega.
    _guardar(recorte, 20)
    MarksView._poll_external_edit(vista)
    assert vista.aplicados == []

    # Ya está quieto: se pega, y una sola vez.
    MarksView._poll_external_edit(vista)
    assert len(vista.aplicados) == 1
    MarksView._poll_external_edit(vista)
    assert len(vista.aplicados) == 1

    # Y un segundo guardado vuelve a entrar: la sesión sigue viva.
    _guardar(recorte, 30)
    MarksView._poll_external_edit(vista)
    MarksView._poll_external_edit(vista)
    assert len(vista.aplicados) == 2


def test_si_el_recorte_desaparece_se_deja_de_vigilar(tmp_path: Path) -> None:
    """Sin esto, un editor que renombra al guardar llena el log a un aviso
    por segundo hasta que alguien cierre el paso 2."""
    recorte = tmp_path / "recorte.png"
    _guardar(recorte, 10)
    vista = _vigilante(recorte)
    recorte.unlink()

    MarksView._poll_external_edit(vista)

    assert vista._edit_session is None
    assert vista.aplicados == []


def _temp_aparte(monkeypatch, tmp_path: Path) -> Path:
    """Manda la carpeta de recortes al tmp del test, no al del sistema."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path / EDIT_TEMP_DIR


def test_el_recorte_se_nombra_por_uid(monkeypatch, tmp_path: Path) -> None:
    """Borrar una marca anterior desplaza los índices; el uid no.

    Si el archivo fuese ``mark0003.png``, el recorte abierto en el editor
    se pegaría en el sitio de otra marca en cuanto se borre una de arriba.
    """
    _temp_aparte(monkeypatch, tmp_path)
    ruta = tmp_path / "pagina.png"
    a, b = _mark(), _mark(x=10)
    assert a.uid != b.uid
    assert region_file(ruta, a.uid) != region_file(ruta, b.uid)
    assert a.uid in region_file(ruta, a.uid).name


def test_cada_intento_estrena_archivo(monkeypatch, tmp_path: Path) -> None:
    """Reeditar la misma sección no pisa el archivo del intento anterior.

    Hay editores que guardan sobre el archivo que abrieron sin releerlo:
    con el nombre fijo, el que quedó abierto de antes devolvía la versión
    vieja encima del retoque nuevo. Y en Windows ni siquiera se puede
    sobrescribir mientras el editor lo tenga bloqueado.
    """
    _temp_aparte(monkeypatch, tmp_path)
    ruta = tmp_path / "pagina.png"
    marca = _mark()

    nombres = {region_file(ruta, marca.uid) for _ in range(5)}

    assert len(nombres) == 5
    # Y quedan creados, para que el nombre no se lo pueda llevar otro.
    assert all(p.exists() for p in nombres)


def test_se_barren_los_recortes_viejos(monkeypatch, tmp_path: Path) -> None:
    """Si no, la carpeta crece sin fin: cada edición deja varios MB."""
    carpeta = _temp_aparte(monkeypatch, tmp_path)
    viejo = region_file(tmp_path / "pagina.png", "AAAAAA")
    nuevo = region_file(tmp_path / "pagina.png", "BBBBBB")
    os.utime(viejo, (0, 0))

    assert _prune(carpeta) == 1

    assert not viejo.exists()
    assert nuevo.exists()
