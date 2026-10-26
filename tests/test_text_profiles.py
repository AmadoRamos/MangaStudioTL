"""Lo que hace `text_profiles` cuando el archivo del usuario no colabora.

El camino bueno —guardar, volver a leer, nombres duplicados, sin nombre,
JSON inválido— ya lo cubre ``test_profiles_round_trip``, y las reglas de
nombres ``test_profile_names``. Aquí van las salidas que quedaban
sueltas, que son todas la misma idea: perder los perfiles no debe
impedir rotular un capítulo, así que un archivo que no se puede leer o
no tiene la forma esperada es «todavía no hay perfiles», nunca una
excepción que suba hasta la vista.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.utils import text_profiles
from src.utils.text_profiles import TextProfile


@pytest.fixture
def perfiles_en(monkeypatch):
    """Apunta el módulo a una ruta de las pruebas y la devuelve."""
    def apuntar(ruta: Path) -> Path:
        monkeypatch.setattr(text_profiles, "_PATH", ruta)
        return ruta
    return apuntar


def test_un_archivo_que_no_se_puede_leer_es_lista_vacia(
    perfiles_en, tmp_path: Path,
) -> None:
    """Una carpeta donde debería haber un JSON: `read_text` lanza OSError."""
    carpeta = tmp_path / "soy_una_carpeta"
    carpeta.mkdir()
    perfiles_en(carpeta)

    assert text_profiles.load() == ()


def test_un_json_que_no_es_una_lista_es_lista_vacia(
    perfiles_en, tmp_path: Path,
) -> None:
    """Editado a mano, el archivo puede ser cualquier cosa válida."""
    ruta = perfiles_en(tmp_path / "perfiles.json")

    for contenido in ('{"name": "Grito"}', '"Grito"', "42", "null"):
        ruta.write_text(contenido, encoding="utf-8")
        assert text_profiles.load() == (), contenido


def test_las_entradas_que_no_son_objetos_se_saltan(
    perfiles_en, tmp_path: Path,
) -> None:
    """Una lista con basura dentro deja los perfiles que sí valen."""
    ruta = perfiles_en(tmp_path / "perfiles.json")
    ruta.write_text(
        '["Grito", 7, null, {"name": "Diálogo", "max_pt": 28}]',
        encoding="utf-8",
    )

    assert text_profiles.load() == (
        TextProfile(name="Diálogo", max_pt=28),
    )


def test_guardar_contesta_que_no_si_el_disco_no_deja(
    perfiles_en, tmp_path: Path,
) -> None:
    """Un `False` que la vista puede contar; nunca una excepción."""
    perfiles_en(tmp_path / "no" / "existe" / "perfiles.json")

    assert text_profiles.save([TextProfile(name="Grito")]) is False
