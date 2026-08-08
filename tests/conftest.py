"""Fixtures compartidas por la suite.

Dos cosas que no puede hacer cada test por su cuenta:

* Una sola raíz de Tk para toda la sesión. Crear y destruir un
  ``tk.Tk()`` por test es lento y, sobre todo, deja widgets huérfanos
  cuando un test falla a medias.
* Los dos módulos que guardan estado del usuario —perfiles de texto y
  carpetas recientes— apuntan a un archivo en la raíz del proyecto
  resuelto al importar. Sin desviarlos, correr la suite le pisa al
  usuario sus perfiles y su historial.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from src.utils import recent_paths, text_profiles


@pytest.fixture(scope="session")
def root() -> tk.Tk:
    """La raíz oculta que comparten los tests de widgets."""
    win = tk.Tk()
    win.withdraw()
    yield win
    win.destroy()


@pytest.fixture
def tmp_file(tmp_path: Path) -> Path:
    """Un archivo que todavía no existe, dentro de un directorio temporal."""
    return tmp_path / "text_profiles.json"


@pytest.fixture(autouse=True)
def _isolate_user_state(tmp_path_factory) -> None:
    """Aparta los archivos del usuario mientras corre la suite."""
    sandbox = tmp_path_factory.mktemp("user_state")
    profiles_original = text_profiles._PATH
    recent_original = recent_paths._PATH_FILE
    text_profiles._PATH = sandbox / "text_profiles.json"
    recent_paths._PATH_FILE = sandbox / ".last_folder"
    yield
    text_profiles._PATH = profiles_original
    recent_paths._PATH_FILE = recent_original
