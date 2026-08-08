"""Smoke checks for the pieces of plumbing with no other coverage.

Run with: python test_smoke.py
"""

import tempfile
import tkinter as tk
from pathlib import Path

from src.utils.background_worker import BackgroundWorker
from src.utils.marks_store import Mark, TranslationEntry
from src.utils.text_profiles import TextProfile
from src.utils.text_renderer import RenderConfig, resolve_box


def test_emit_dispatches_by_name(root: tk.Tk) -> None:
    """``_emit`` must call the attribute named at *dispatch* time."""
    seen: list[tuple] = []

    class Worker(BackgroundWorker):
        def __init__(self):
            super().__init__()
            self._on_done = None

    w = Worker()
    w.attach(root)
    w._emit("_on_done", 1, True, "listo")   # queued before the callback exists
    w._on_done = lambda *a: seen.append(a)
    w._poll()
    assert seen == [(1, True, "listo")], seen

    # A missing callback is dropped, not raised.
    w._emit("_on_nonexistent", 42)
    w._poll()
    assert seen == [(1, True, "listo")], seen

    # detach() drops what is still queued.
    w._emit("_on_done", 2, False, "tarde")
    w.detach()
    w._poll()
    assert seen == [(1, True, "listo")], seen


def test_drop_data_splitting(root: tk.Tk) -> None:
    """Tk's own list splitter replaces the hand-rolled brace parser."""
    data = "{D:/con espacio/0001.jpg} D:/simple.png {C:/a b/c d.jpeg}"
    assert [str(p) for p in root.tk.splitlist(data)] == [
        "D:/con espacio/0001.jpg",
        "D:/simple.png",
        "C:/a b/c d.jpeg",
    ]
    assert root.tk.splitlist("") == ()


def test_dialog_answers(root: tk.Tk) -> None:
    """Sólo el botón que confirma dice «sí»; cerrar dice «no».

    Es la única parte del diálogo con lógica: un modal que devolviera
    ``True`` al cerrarse convertiría «¿borrar las marcas?» en una trampa.
    """
    from src.views import theme

    theme.init(root)
    root.deiconify()          # grab_set() no funciona sobre una raíz oculta

    def buttons(widget: tk.Misc) -> list[tk.Button]:
        found: list[tk.Button] = []
        for child in widget.winfo_children():
            if isinstance(child, tk.Button):
                found.append(child)
            found.extend(buttons(child))
        return found

    def when_open(action) -> None:
        def go() -> None:
            dialog = [
                w for w in root.winfo_children() if isinstance(w, tk.Toplevel)
            ][-1]
            action(dialog)
        root.after(50, go)

    def press(label: str):
        def do(dialog: tk.Toplevel) -> None:
            for btn in buttons(dialog):
                if str(btn.cget("text")) == label:
                    btn.invoke()
                    return
            raise AssertionError(f"no hay botón «{label}»")
        return do

    when_open(press("Borrar las marcas"))
    assert theme.confirm(
        root, "Limpiar", "Se borran.", confirm_label="Borrar las marcas",
    ) is True

    when_open(press("Cancelar"))
    assert theme.confirm(
        root, "Limpiar", "Se borran.", confirm_label="Borrar las marcas",
    ) is False

    # Cerrar la ventana tiene que coincidir con «Cancelar». Se invoca el
    # manejador del gestor de ventanas en vez de simular la tecla:
    # `event_generate` depende del foco, que en una prueba no está dado.
    def close_window(dialog: tk.Toplevel) -> None:
        assert str(dialog.bind("<Escape>")), "Escape sin atar"
        dialog.tk.call(dialog.protocol("WM_DELETE_WINDOW"))

    when_open(close_window)
    assert theme.confirm(
        root, "Limpiar", "Se borran.", confirm_label="Borrar las marcas",
    ) is False

    # Un aviso es el mismo diálogo sin el botón de cancelar.
    labels: list[str] = []

    def record(dialog: tk.Toplevel) -> None:
        labels.extend(str(b.cget("text")) for b in buttons(dialog))
        press("Entendido")(dialog)

    when_open(record)
    theme.alert(root, "Aviso", "Ya está.")
    assert labels == ["Entendido"], labels

    root.withdraw()


def test_box_precedence() -> None:
    """The section beats the chapter, and ``None`` means «sin tocar»."""
    mark = Mark(x=10, y=20, w=200, h=80, color="#ec3013")
    config = RenderConfig(
        font_family="Arial", max_pt=36, color=(0x20, 0x1E, 0x1D),
    )

    untouched = TranslationEntry(text="hola", source_lang="en", target_lang="es")
    box = resolve_box(mark, untouched, config)
    assert (box.x, box.y, box.w, box.h) == (10, 20, 200, 80), box
    assert box.font_family == "Arial", box.font_family
    assert box.max_pt == 36, box.max_pt
    assert box.color == (0x20, 0x1E, 0x1D), box.color

    # Every field set on the section wins, including a max_pt smaller
    # than the chapter's and a colour the chapter never mentions.
    from dataclasses import replace
    touched = replace(
        untouched, font_family="Georgia", max_pt=18, color=(255, 0, 0),
    )
    box = resolve_box(mark, touched, config)
    assert box.font_family == "Georgia", box.font_family
    assert box.max_pt == 18, box.max_pt
    assert box.color == (255, 0, 0), box.color

    # «Sin tocar» y «esta va en redonda pase lo que pase» se dibujan
    # igual, y ninguna de las dos mira el disco. Que una negrita pedida
    # llegue a dibujarse depende de qué fuentes tenga la máquina, así
    # que eso es cosa de `resolve_style`, no de este test.
    for asked in (None, False):
        plain = replace(untouched, bold=asked, italic=asked)
        box = resolve_box(mark, plain, config)
        assert (box.bold, box.italic) == (False, False), (asked, box)


def test_profile_layer() -> None:
    """El perfil se mete entre la sección y el capítulo, sin pisar nada."""
    from dataclasses import replace

    mark = Mark(x=0, y=0, w=200, h=80, color="#ec3013")
    grito = TextProfile(
        name="Grito", font_family="Georgia", max_pt=60, color=(255, 0, 0),
    )
    config = RenderConfig(
        font_family="Arial", max_pt=36, color=(0x20, 0x1E, 0x1D),
        profiles=(grito,),
    )
    entry = TranslationEntry(
        text="¡AH!", source_lang="en", target_lang="es", profile="Grito",
    )

    # Sin nada puesto a mano, manda el perfil y no el capítulo.
    box = resolve_box(mark, entry, config)
    assert (box.font_family, box.max_pt, box.color) == (
        "Georgia", 60, (255, 0, 0),
    ), box

    # Lo que la sección puso a mano gana al perfil; lo que no tocó, no.
    own = replace(entry, color=(0, 0, 255))
    box = resolve_box(mark, own, config)
    assert box.color == (0, 0, 255), box.color
    assert box.max_pt == 60, box.max_pt

    # Editar el perfil alcanza a la sección — en los campos que ella no
    # eligió. Es la razón de guardar el nombre y no una copia.
    edited = replace(config, profiles=(replace(grito, max_pt=24),))
    box = resolve_box(mark, own, edited)
    assert box.max_pt == 24, box.max_pt
    assert box.color == (0, 0, 255), box.color

    # Un perfil renombrado o borrado se lee como «ninguno», no como error.
    orphan = replace(entry, profile="Ya no existe")
    assert resolve_box(mark, orphan, config).max_pt == 36


def test_rect_geometry() -> None:
    """Mover y redimensionar un rectángulo: recorte, volteo y mínimo.

    Las usan los dos lienzos —las marcas del paso 2 y el cuadro de texto
    del paso 4—, así que una regresión aquí rompe los dos.
    """
    from src.views.zoomed_canvas import move_rect, resize_rect

    bounds = (1000, 800)

    # Mover se detiene en el borde sin encoger la caja.
    assert move_rect((10, 10, 100, 50), -50, -50, bounds) == (0, 0, 100, 50)
    assert move_rect((900, 700, 100, 50), 500, 500, bounds) == (900, 750, 100, 50)

    # Cada tirador mueve solo sus lados.
    rect = (100, 100, 200, 100)
    assert resize_rect(rect, "se", 50, 20, bounds, 5) == (100, 100, 250, 120)
    assert resize_rect(rect, "nw", 50, 20, bounds, 5) == (150, 120, 150, 80)
    assert resize_rect(rect, "n", 0, 20, bounds, 5) == (100, 120, 200, 80)

    # Arrastrar un lado más allá del opuesto voltea la caja, no la rompe:
    # w y h siguen siendo positivos.
    assert resize_rect(rect, "e", -300, 0, bounds, 5) == (0, 100, 100, 100)

    # Y nunca queda más pequeña que el mínimo.
    assert resize_rect(rect, "se", -199, 0, bounds, 5) == (100, 100, 5, 100)


def test_box_offset() -> None:
    """El cuadro de texto se guarda como diferencia contra la marca."""
    import json
    from dataclasses import replace

    from src.utils.text_renderer import box_rect

    mark = Mark(x=100, y=100, w=200, h=80, color="#ec3013")
    entry = TranslationEntry(text="hola", source_lang="en", target_lang="es")

    # Sin desplazamiento el cuadro *es* la marca — y una sección sin
    # traducción todavía también.
    assert box_rect(mark, entry) == (100, 100, 200, 80)
    assert box_rect(mark, None) == (100, 100, 200, 80)

    moved = replace(entry, box_offset=(20, -40, 60, 0))
    assert box_rect(mark, moved) == (120, 60, 260, 80)

    # Es la razón de guardar la diferencia: mover la marca en el paso 2
    # se lleva el cuadro con ella en vez de descolocar el texto.
    assert box_rect(replace(mark, x=500), moved) == (520, 60, 260, 80)

    # Y sobrevive al viaje por el sidecar, donde la tupla es una lista.
    data = json.loads(json.dumps(moved.to_dict()))
    assert TranslationEntry.from_dict(data) == moved


def test_profiles_round_trip(tmp_file) -> None:
    """Lo que se escribe se vuelve a leer; lo ilegible es «no hay perfiles»."""
    from src.utils import text_profiles

    original = text_profiles._PATH
    text_profiles._PATH = tmp_file
    try:
        assert text_profiles.load() == ()          # todavía no existe

        saved = (
            TextProfile(name="Diálogo", font_family="Segoe UI", max_pt=28),
            # Un perfil que solo dice una cosa es legítimo: los demás
            # campos siguen cayendo al capítulo.
            TextProfile(name="Grito", bold=True, color=(255, 0, 0)),
        )
        assert text_profiles.save(saved)
        assert text_profiles.load() == saved

        # Sin nombre no es un perfil, y un duplicado haría que la sección
        # dependiese del orden del archivo.
        tmp_file.write_text(
            '[{"name": "A"}, {"max_pt": 12}, {"name": "A", "max_pt": 99}]',
            encoding="utf-8",
        )
        assert text_profiles.load() == (TextProfile(name="A"),)

        tmp_file.write_text("{ esto no es json", encoding="utf-8")
        assert text_profiles.load() == ()
    finally:
        text_profiles._PATH = original


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    try:
        test_emit_dispatches_by_name(root)
        test_drop_data_splitting(root)
        test_dialog_answers(root)
        test_box_precedence()
        test_profile_layer()
        test_rect_geometry()
        test_box_offset()
        with tempfile.TemporaryDirectory() as tmp:
            test_profiles_round_trip(Path(tmp) / "text_profiles.json")
    finally:
        root.destroy()
    print("OK")
