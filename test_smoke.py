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
        test_box_precedence()
        test_profile_layer()
        with tempfile.TemporaryDirectory() as tmp:
            test_profiles_round_trip(Path(tmp) / "text_profiles.json")
    finally:
        root.destroy()
    print("OK")
