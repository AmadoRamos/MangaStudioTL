"""El armazón que comparten los modales, ahora en `theme.ModalWindow`.

Estaba escrito cuatro veces —borde, transient, no redimensionable, la
cruz y el Escape de acuerdo, centrado, agarre, y un `_close` con el
`grab_release` tolerante— así que cambiarlo pedía acordarse de cuatro
sitios. Esto comprueba que es uno, y que las diferencias que sí son
reales siguen ahí.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from src.config import COLOR_TEXT
from src.utils.text_profiles import TextProfile
from src.views import theme
from src.views.export_dialog import ExportDialog, ExportProgress
from src.views.profile_dialog import DIALOG_WIDTH as PROFILE_WIDTH
from src.views.profile_dialog import ProfileDialog
from src.views.theme import ModalWindow, _MessageDialog


@pytest.fixture
def visible(root: tk.Tk) -> tk.Tk:
    """La raíz a la vista: `grab_set()` no funciona sobre una oculta."""
    theme.init(root)
    root.deiconify()
    yield root
    root.withdraw()


def _toplevels(root: tk.Tk) -> list[tk.Toplevel]:
    return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]


def _buttons(widget: tk.Misc) -> list[tk.Button]:
    found: list[tk.Button] = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Button):
            found.append(child)
        found.extend(_buttons(child))
    return found


def _press(dialog: tk.Toplevel, label: str) -> None:
    for btn in _buttons(dialog):
        if str(btn.cget("text")) == label:
            btn.invoke()
            return
    raise AssertionError(f"no hay botón «{label}»")


def test_los_cuatro_modales_salen_del_mismo_armazon() -> None:
    """Si alguien vuelve a escribirlo a mano, esto se entera."""
    for clase in (_MessageDialog, ExportDialog, ExportProgress, ProfileDialog):
        assert issubclass(clase, ModalWindow), clase.__name__
        assert clase._close is ModalWindow._close, (
            f"{clase.__name__} tiene su propio _close otra vez"
        )
        assert clase.show is ModalWindow.show, clase.__name__


def test_el_armazon_viste_la_ventana(visible: tk.Tk) -> None:
    """Borde ink de 2 px, atada, fija, con la cruz y el Escape puestos."""
    win = ModalWindow(visible, "Prueba")
    win.show(wait=False)

    assert win.title() == "Prueba"
    assert int(win.cget("highlightthickness")) == 2
    assert str(win.cget("highlightbackground")) == COLOR_TEXT
    assert win.resizable() == (False, False)
    assert str(win.transient()) == str(visible.winfo_toplevel())
    assert str(win.bind("<Escape>")), "Escape sin atar"
    assert str(win.protocol("WM_DELETE_WINDOW")), "la cruz sin manejador"
    assert win.grab_current() is win

    # El ancho lo comprueba `test_el_gestor_de_perfiles_sigue_siendo_el_ancho`
    # con un diálogo de verdad: una ventana vacía y sin mapear no tiene
    # todavía geometría que leer.

    win._close()
    assert not win.winfo_exists()
    # Cerrar dos veces no es un error que haya que contar.
    win._close()


def test_cerrar_dos_veces_no_revienta_sin_agarre(visible: tk.Tk) -> None:
    """El `grab_release` va en un try porque la ventana puede haberse ido."""
    win = ModalWindow(visible, "Prueba")
    win.show(wait=False)
    win.destroy()
    win._close()


def test_una_ventana_sin_salida_no_tiene_cruz_ni_escape(visible: tk.Tk) -> None:
    """`dismissable=False`: hay trabajo detrás que no sabe pararse."""
    win = ModalWindow(visible, "Trabajando", dismissable=False)
    win.show(wait=False)

    assert not str(win.bind("<Escape>"))
    # El manejador existe y no hace nada: la ventana sigue ahí.
    win.tk.call(win.protocol("WM_DELETE_WINDOW"))
    assert win.winfo_exists()
    win._close()


def test_el_gestor_de_perfiles_sigue_siendo_el_ancho(visible: tk.Tk) -> None:
    """640 y no 460: son dos paneles, no un párrafo.

    El ancho propio del gestor vivía en su llamada a `center_on`, y el
    armazón se lo habría comido de no pasarlo como parámetro.
    """
    assert PROFILE_WIDTH == 640

    anchos: list[int] = []

    def cuando_abra() -> None:
        dialog = _toplevels(visible)[-1]
        anchos.append(dialog.winfo_width())
        _press(dialog, "Cerrar")

    visible.after(50, cuando_abra)
    ProfileDialog(
        visible,
        profiles=(TextProfile(name="Diálogo"),),
        usage_of=lambda _n: 0,
        font_options=["Arial"],
        on_change=lambda _p: None,
        on_rename=lambda _a, _b: None,
    )

    assert anchos == [PROFILE_WIDTH], anchos


def test_la_exportacion_cancela_al_cerrar(
    visible: tk.Tk, tmp_path: Path,
) -> None:
    """Irse por la cruz es cancelar, nunca exportar."""
    def cuando_abra() -> None:
        dialog = _toplevels(visible)[-1]
        dialog.tk.call(dialog.protocol("WM_DELETE_WINDOW"))

    visible.after(50, cuando_abra)
    dialog = ExportDialog(
        visible, initial_dir=tmp_path,
        pages=2, sections=5, skipped=1, estimated_mb=3.0,
    )

    assert dialog.result is None
