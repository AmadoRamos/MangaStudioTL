"""Qué archivos son páginas del capítulo y cuáles son versiones limpias."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.utils.image_loader import (
    clean_base_name,
    expand_folder,
    expand_paths,
    is_clean_variant,
    is_supported,
    load_images_with_paths,
)


def _png(path: Path, size: tuple[int, int] = (4, 4)) -> Path:
    Image.new("RGB", size, "white").save(path, format="PNG")
    return path


def test_que_cuenta_como_pagina(tmp_path: Path) -> None:
    assert is_supported(tmp_path / "a.PNG") is True
    assert is_supported(tmp_path / "a.jpeg") is True
    assert is_supported(tmp_path / "a.webp") is False
    assert is_supported(tmp_path / "a.marks.json") is False


def test_la_limpia_lleva_el_nombre_de_su_pagina(tmp_path: Path) -> None:
    """``0001.clean.png`` es de ``0001``, sin extensión: siempre sale PNG."""
    assert clean_base_name(tmp_path / "0001.clean.png") == "0001"
    assert clean_base_name(tmp_path / "0001.CLEAN.png") == "0001"
    assert clean_base_name(tmp_path / "0001.png") is None
    assert is_clean_variant(tmp_path / "0001.clean.jpg") is True


def test_la_limpia_no_es_una_pagina_mas(tmp_path: Path) -> None:
    """Con su página delante, la limpia no entra en la lista del capítulo.

    Si entrase, el capítulo tendría el doble de páginas y la mitad
    saldría sin rotular.
    """
    _png(tmp_path / "0001.png")
    _png(tmp_path / "0001.clean.png")
    _png(tmp_path / "0002.png")

    assert [p.name for p in expand_folder(tmp_path)] == ["0001.png", "0002.png"]


def test_una_limpia_huerfana_si_es_una_pagina(tmp_path: Path) -> None:
    """Sin su original, se trata como una imagen normal.

    Descartarla dejaría al usuario mirando «no se encontraron imágenes»
    sobre una carpeta que a la vista tiene alguna.
    """
    _png(tmp_path / "0009.clean.png")
    assert [p.name for p in expand_folder(tmp_path)] == ["0009.clean.png"]


def test_expand_paths_ordena_y_no_repite(tmp_path: Path) -> None:
    """Carpetas y archivos sueltos mezclados salen en un orden estable.

    El capítulo se lee en el orden de esta lista, así que tiene que salir
    ordenado aunque las páginas lleguen de dos sitios y en desorden —y
    sin distinguir mayúsculas, o ``Z.png`` se colaría antes que ``a.png``.
    """
    _png(tmp_path / "z.png")
    _png(tmp_path / "M.png")
    otra = tmp_path / "sub"
    otra.mkdir()
    _png(otra / "a.png")

    salida = expand_paths([tmp_path, otra, tmp_path / "z.png"])
    assert [p.name for p in salida] == ["a.png", "M.png", "z.png"]


def test_la_pareja_puede_venir_de_dos_sitios(tmp_path: Path) -> None:
    """Una carpeta y un archivo suelto pueden emparejar página y limpia.

    Por eso el descarte se repite sobre la lista ya fusionada: en la
    primera pasada cada lado estaba solo y ninguno tenía a su pareja.
    """
    carpeta = tmp_path / "cap"
    carpeta.mkdir()
    _png(carpeta / "0001.clean.png")
    suelta = _png(tmp_path / "0001.png")

    salida = expand_paths([carpeta, suelta])
    assert [p.name for p in salida] == ["0001.png"]


def test_una_imagen_rota_no_tumba_la_carga(tmp_path: Path) -> None:
    """La que no abre se apunta como fallida y las demás siguen cargando."""
    buena = _png(tmp_path / "ok.png", size=(3, 7))
    mala = tmp_path / "rota.png"
    mala.write_bytes(b"esto no es un PNG")

    items, failed = load_images_with_paths([buena, mala])

    assert [p for p, _ in items] == [buena]
    assert items[0][1].size == (3, 7)
    assert failed == [mala]


def test_las_imagenes_sobreviven_al_cierre_del_archivo(tmp_path: Path) -> None:
    """Lo que se devuelve son píxeles en memoria, no un archivo abierto.

    El capítulo se queda cargado mientras dura la sesión, y el archivo se
    cierra al salir del ``with``. Si la imagen fuera perezosa, el primer
    acceso volvería a un descriptor cerrado — o peor, a una página que
    entretanto se movió de sitio.
    """
    ruta = _png(tmp_path / "p.png", size=(5, 5))
    items, _ = load_images_with_paths([ruta])
    ruta.unlink()
    assert items[0][1].getpixel((0, 0)) == (255, 255, 255)
    # Y se puede seguir trabajando con ella, no solo leerla.
    assert items[0][1].crop((0, 0, 2, 2)).size == (2, 2)
