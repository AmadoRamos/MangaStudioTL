"""Los recortes que se le pasan al OCR: recorte, nombre y limpieza."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PIL import Image

from src.config import OCR_TEMP_PREFIX
from src.utils.crop_manager import CropManager


@pytest.fixture
def manager(monkeypatch, tmp_path: Path) -> CropManager:
    """Un gestor cuya carpeta temporal vive dentro del ``tmp_path``.

    Sin desviar ``gettempdir``, el barrido de carpetas viejas borraría
    las de una sesión real que estuviera abierta en la misma máquina.
    """
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    mgr = CropManager()
    yield mgr
    mgr.cleanup()


def test_el_recorte_se_queda_dentro_de_la_imagen(manager: CropManager) -> None:
    """Una marca que se sale por el borde se recorta a lo que hay."""
    img = Image.new("RGB", (100, 80), "white")
    salida = manager.crop(img, x=90, y=70, w=50, h=50)
    with Image.open(salida) as recorte:
        assert recorte.size == (10, 10)


def test_un_recorte_vacio_es_un_error(manager: CropManager) -> None:
    """Sin píxeles no hay nada que reconocer, y el OCR no debe recibirlo."""
    img = Image.new("RGB", (100, 80), "white")
    with pytest.raises(ValueError):
        manager.crop(img, x=200, y=200, w=10, h=10)
    with pytest.raises(ValueError):
        manager.crop(img, x=10, y=10, w=0, h=10)


def test_cada_marca_tiene_su_archivo(manager: CropManager) -> None:
    """Página y marca van en el nombre: dos marcas no se pisan el archivo."""
    a = manager.crop_path(1, 2)
    assert a != manager.crop_path(1, 3)
    assert a != manager.crop_path(2, 2)
    # Con relleno de ceros, para que ordenen igual que se numeran.
    assert a.name == "img0001_mark0002.png"


def test_al_cerrar_no_queda_nada(manager: CropManager) -> None:
    img = Image.new("RGB", (50, 50), "white")
    manager.crop(img, 0, 0, 10, 10)
    assert manager.root.exists()
    manager.cleanup()
    assert not manager.root.exists()
    # Y volver a limpiar no es un error.
    manager.cleanup()


def test_se_barren_las_carpetas_de_sesiones_muertas(
    monkeypatch, tmp_path: Path,
) -> None:
    """Un cierre en seco deja su carpeta; la abre la siguiente sesión.

    Son recortes PNG de páginas enteras: sin el barrido, el temporal
    crece un capítulo por cada cierre inesperado.
    """
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    vieja = tmp_path / f"{OCR_TEMP_PREFIX}999_abcdef"
    vieja.mkdir()
    (vieja / "basura.png").write_bytes(b"x")
    ajena = tmp_path / "otra_cosa"
    ajena.mkdir()

    mgr = CropManager()
    try:
        assert not vieja.exists()
        # Lo que no es suyo no se toca.
        assert ajena.exists()
        assert mgr.root.exists()
    finally:
        mgr.cleanup()


def test_el_contexto_ensancha_el_recorte(manager: CropManager) -> None:
    """``context`` añade margen por los cuatro lados.

    Es lo que necesita el detector de RapidOCR para ver dónde acaba el
    texto; sin él deja bocadillos enteros sin leer.
    """
    img = Image.new("RGB", (200, 160), "white")
    out = manager.crop(img, 50, 40, 60, 30, context=16)
    with Image.open(out) as crop:
        assert crop.size == (60 + 32, 30 + 32)


def test_el_contexto_no_se_sale_de_la_imagen(manager: CropManager) -> None:
    """Pegado a una esquina, el margen se recorta a lo que hay.

    Sin esto, una marca en el borde pediría coordenadas negativas y el
    recorte saldría desplazado.
    """
    img = Image.new("RGB", (100, 80), "white")
    out = manager.crop(img, 0, 0, 40, 30, context=16)
    with Image.open(out) as crop:
        # Por arriba y por la izquierda no hay nada que añadir; por abajo
        # y por la derecha sí caben los 16 px.
        assert crop.size == (40 + 16, 30 + 16)
