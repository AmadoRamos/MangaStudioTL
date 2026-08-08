"""El historial de carpetas: orden, tope y filas muertas.

``_PATH_FILE`` lo desvía ``conftest`` a un temporal para toda la suite,
así que estos tests no le tocan al usuario su ``.last_folder``.
"""

from __future__ import annotations

from pathlib import Path

from src.utils import recent_paths
from src.utils.recent_paths import MAX_HISTORY, display_name, forget, history, load, save


def _carpetas(tmp_path: Path, n: int) -> list[Path]:
    out = []
    for i in range(n):
        d = tmp_path / f"cap{i:02d}"
        d.mkdir()
        out.append(d)
    return out


def test_la_ultima_abierta_va_primero(tmp_path: Path) -> None:
    a, b = _carpetas(tmp_path, 2)
    save(a)
    save(b)
    assert history() == [b, a]
    assert load() == b
    assert display_name() == b.name


def test_reabrir_una_carpeta_la_sube_sin_duplicarla(tmp_path: Path) -> None:
    """Volver a una carpeta la pone arriba, no añade una fila igual.

    La copia repetida hay que quitarla al escribir, no solo al leer: si
    se queda en el archivo, ocupa sitio contra el tope de diez y expulsa
    carpetas de verdad.
    """
    a, b, c = _carpetas(tmp_path, 3)
    save(a)
    save(b)
    save(c)
    save(a)
    assert history() == [a, c, b]
    assert len(recent_paths._PATH_FILE.read_text(encoding="utf-8").splitlines()) == 3


def test_una_carpeta_borrada_no_ocupa_sitio(tmp_path: Path) -> None:
    """La fila se salta al leer: el riel no ofrece lo que ya no está."""
    a, b = _carpetas(tmp_path, 2)
    save(a)
    save(b)
    b.rmdir()
    assert history() == [a]
    assert load() == a


def test_sin_historial_no_hay_nada_que_ofrecer() -> None:
    assert history() == []
    assert load() is None
    assert display_name() is None


def test_el_historial_tiene_tope(tmp_path: Path) -> None:
    """Se recuerdan diez; la undécima empuja a la más vieja fuera."""
    carpetas = _carpetas(tmp_path, MAX_HISTORY + 2)
    for c in carpetas:
        save(c)
    recordadas = history(limit=99)
    assert len(recordadas) == MAX_HISTORY
    assert recordadas[0] == carpetas[-1]
    assert carpetas[0] not in recordadas


def test_olvidar_quita_solo_esa(tmp_path: Path) -> None:
    a, b = _carpetas(tmp_path, 2)
    save(a)
    save(b)
    forget(a)
    assert history() == [b]


def test_el_archivo_de_una_sola_linea_sigue_valiendo(tmp_path: Path) -> None:
    """Lo que escribían las versiones viejas se lee como un historial de una."""
    a = _carpetas(tmp_path, 1)[0]
    recent_paths._PATH_FILE.write_text(str(a), encoding="utf-8")
    assert history() == [a]
