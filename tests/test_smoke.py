"""Smoke checks for the pieces of plumbing with no other coverage.

Run with: python -m pytest
"""

import time
import tkinter as tk
from pathlib import Path

from src.utils.background_worker import BackgroundWorker
from src.utils.marks_store import Mark, TranslationEntry
from src.utils.text_profiles import STYLE_FIELDS, TextProfile
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


def test_button_variants() -> None:
    """Nadie pide una variante que no existe.

    `theme.button` cae en la de por defecto ante un nombre desconocido,
    así que una errata —o un «secondary» que sobrevivió al borrado— se
    dibuja bien y nadie se entera. Aquí sí se entera.
    """
    import re

    from src.views.theme import _VARIANTS

    assert set(_VARIANTS) == {"primary", "ink", "outline", "ghost"}, _VARIANTS
    for path in Path("src").rglob("*.py"):
        for name in re.findall(r'variant="(\w+)"', path.read_text("utf-8")):
            assert name in _VARIANTS, f"{path}: variante «{name}»"


def test_tool_icons(root: tk.Tk) -> None:
    """Los iconos del dock del paso 2: cargan, se tiñen y se cachean.

    El tinte no es adorno: un PNG negro no obedece al `fg` del botón, así
    que sin repintar, un conmutador encendido —fondo tinta— se queda sin
    icono, y uno desactivado se ve igual que uno activo.
    """
    from src.views import theme

    theme.init(root)
    names = (
        "draw-polygon-solid", "eye-solid", "eye-slash-solid",
        "clock-rotate-left-solid", "trash-solid",
        "list-ul-solid", "list-check-solid",
    )
    for name in names:
        image = theme.icon(name)
        assert image.width() == theme.ICON_SIZE, (name, image.width())

    # La caché reparte por color: el mismo nombre en dos tintes son dos
    # imágenes, y repetido es la misma.
    claro = theme.icon("trash-solid", color="#ffffff")
    assert claro is not theme.icon("trash-solid")
    assert claro is theme.icon("trash-solid", color="#ffffff")

    # Y un botón icono-solo cambia de dibujo al desactivarse, que es la
    # regresión fácil: sigue funcionando igual, solo se ve mal.
    btn = theme.button(
        root, "", icon_name="trash-solid", tooltip="Limpiar todo",
    )
    encendido = str(btn.cget("image"))
    fondo = str(btn.cget("bg"))
    theme.set_enabled(btn, False)
    assert str(btn.cget("image")) != encendido, "el icono no se apagó"
    theme.set_enabled(btn, True)
    assert str(btn.cget("image")) == encendido

    # Un conmutador se enciende tiñendo el icono de acento, sin tocar el
    # fondo. Y desactivado gana al acento: un icono rojo apagado sería una
    # promesa falsa.
    from src.config import COLOR_ACCENT

    theme.set_icon_color(btn, COLOR_ACCENT)
    acento = str(btn.cget("image"))
    assert acento != encendido, "el acento no llegó al icono"
    assert str(btn.cget("bg")) == fondo, "el fondo no debía cambiar"
    theme.set_enabled(btn, False)
    assert str(btn.cget("image")) not in (acento, encendido)
    theme.set_enabled(btn, True)
    assert str(btn.cget("image")) == acento
    theme.set_icon_color(btn, None)
    assert str(btn.cget("image")) == encendido

    # Y el ojo se cambia por el ojo tachado sin tocar nada más.
    theme.set_icon(btn, "eye-solid")
    assert btn._icon == "eye-solid"
    btn.destroy()


def test_marks_wheel() -> None:
    """La rueda del paso 2: lo que la bloquea es el arrastre, no el modo.

    Sin construir la vista —solo hacen falta los cuatro atributos que el
    manejador toca— porque montar `MarksView` pide imágenes, OCR y riel.
    """
    from src.views.marks_view import MODE_ALL, MODE_ONE, MarksView

    class Event:
        def __init__(self, delta: int) -> None:
            self.delta = delta

    class Strip:
        def __init__(self) -> None:
            self.scrolled: list[int] = []

        def yview_scroll(self, amount: int, _what: str) -> None:
            self.scrolled.append(amount)

    class Page:
        def __init__(self, pannable: bool) -> None:
            self.pannable = pannable
            self.panned: list[float] = []

        def can_pan_y(self) -> bool:
            return self.pannable

        def pan_by(self, _dx: float, dy: float) -> None:
            self.panned.append(dy)

    view = MarksView.__new__(MarksView)
    view._drag = None
    view._items = [object(), object(), object()]
    view._index = 1
    view._selected = None
    view._load_current = lambda: None  # type: ignore[method-assign]

    # «Todas»: la rueda recorre la tira…
    view._mode = MODE_ALL
    view._marks_canvas = None
    strip = view._canvas = Strip()
    view._mousewheel(Event(120))
    assert strip.scrolled == [-1], strip.scrolled

    # …salvo en medio de un arrastre, que es lo único que la para.
    view._drag = {"preview_id": 1}
    view._mousewheel(Event(120))
    assert strip.scrolled == [-1], "el arrastre no bloqueó la rueda"
    view._drag = None

    # «Una» con la página ampliada: desplaza y no cambia de página.
    view._mode = MODE_ONE
    view._canvas = None
    page = view._marks_canvas = Page(pannable=True)
    view._mousewheel(Event(-120))
    assert page.panned and view._index == 1, (page.panned, view._index)

    # «Una» con la página entera a la vista: pasa de página y para en el
    # extremo, que es de lo que ya se guardan _on_prev / _on_next.
    view._marks_canvas = Page(pannable=False)
    view._mousewheel(Event(-120))
    assert view._index == 2, view._index
    view._mousewheel(Event(-120))
    assert view._index == 2, "se salió por el final"
    for _ in range(3):
        view._mousewheel(Event(120))
    assert view._index == 0, "se salió por el principio"


def test_wheel_dispatch() -> None:
    """El riel reparte la rueda: si no es suya, es de la vista."""
    from src.views.sidebar import Sidebar

    class Event:
        delta = 120

    class Scroll:
        def __init__(self) -> None:
            self.scrolled: list[int] = []

        def yview_scroll(self, amount: int, _what: str) -> None:
            self.scrolled.append(amount)

    class View:
        def __init__(self) -> None:
            self.got = 0

        def wheel(self, _event: object) -> None:
            self.got += 1

    rail = Sidebar.__new__(Sidebar)
    rail._scroll = Scroll()
    rail._overflows = lambda: True  # type: ignore[method-assign]
    rail._pointer_over_rail = lambda _e: over[0]  # type: ignore[method-assign]
    over = [False]

    view = View()
    rail.set_wheel_client(view.wheel)

    # Fuera del riel manda la vista.
    rail._on_wheel(Event())
    assert (view.got, rail._scroll.scrolled) == (1, []), view.got

    # Sobre el riel manda el riel, y la vista no se entera.
    over[0] = True
    rail._on_wheel(Event())
    assert (view.got, rail._scroll.scrolled) == (1, [-1])

    # Sobre el riel sin nada que desplazar no pasa nada: la rueda no cae
    # al lienzo de detrás solo porque el riel no tenga scroll.
    rail._overflows = lambda: False  # type: ignore[method-assign]
    rail._on_wheel(Event())
    assert (view.got, rail._scroll.scrolled) == (1, [-1])

    # Y el borrado borra de verdad, que con «is» no lo haría: cada
    # acceso a un método ligado devuelve un objeto nuevo.
    rail.clear_wheel_client(view.wheel)
    assert rail._wheel_client is None
    # Pero una vista que muere tarde no desbanca a la que ya ocupó su
    # sitio.
    later = View()
    rail.set_wheel_client(later.wheel)
    rail.clear_wheel_client(view.wheel)
    assert rail._wheel_client is not None


def test_detail_panel(root: tk.Tk) -> None:
    """El panel del paso 3 guarda contra la fila que tenía cargada."""
    from src.views import theme
    from src.views.translation_table import PREVIEW_LEN, TranslationTable

    theme.init(root)
    largo = "palabra " * 40
    assert len(largo) > PREVIEW_LEN

    class Ocr:
        def __init__(self, text: str) -> None:
            self.text = text
            self.confidence = 90

    class Trans:
        def __init__(self, text: str) -> None:
            self.text = text
            self.edited = False

    class Store:
        def __init__(self, rows: list) -> None:
            self.rows = rows

        def __len__(self) -> int:
            return len(self.rows)

        def get_ocr(self, i: int):
            return self.rows[i][0]

        def get_translation(self, i: int):
            return self.rows[i][1]

    escrituras: list[tuple] = []
    table = TranslationTable(
        root,
        on_translate_row=lambda *a: None,
        on_translation_edited=lambda *a: (
            escrituras.append(a), table.refresh(),
        ),
        on_translation_deleted=lambda *a: None,
    )
    table.set_stores([Store([
        (Ocr("uno"), Trans(largo)),
        (Ocr("dos"), Trans("corto")),
    ])])

    # La fila es una vista previa recortada; el texto entero está abajo.
    fila = table._tree.item("0:0", "values")
    assert len(fila[2]) < len(largo) and fila[2].endswith("…"), fila[2]
    table._load_detail((0, 0))
    assert table._area_text(table._detail_trans) == largo

    # Se teclea y se cambia de fila: lo escrito va a la fila que estaba
    # cargada, no a la recién seleccionada. Y el aviso repinta la tabla,
    # que vuelve a pasar por aquí — una sola escritura, no dos.
    table._detail_trans.insert(tk.END, " añadido")
    table._load_detail((0, 1))
    assert len(escrituras) == 1, escrituras
    assert escrituras[0][:2] == (0, 0), escrituras[0]
    assert escrituras[0][2].endswith("añadido")

    # Sin cambios no se guarda nada.
    table._commit_detail()
    assert len(escrituras) == 1, escrituras

    # Sin selección el panel se apaga.
    table._load_detail(None)
    assert str(table._detail_trans.cget("state")) == "disabled"
    assert "SIN SELECCIÓN" in str(table._detail_kicker.cget("text"))

    table.destroy()


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

    # El contorno: cero es una respuesta, no un hueco. Sin esto, quitarle
    # el borde a una viñeta suelta obligaría a quitarle el perfil entero.
    borde = replace(config, profiles=(replace(grito, stroke_width=6),))
    assert resolve_box(mark, entry, borde).stroke_width == 6
    assert resolve_box(mark, replace(entry, stroke_width=0), borde).stroke_width == 0
    # Y con nadie opinando, manda el suelo del capítulo.
    assert resolve_box(mark, entry, config).stroke_width == config.stroke_width

    # El riel pregunta por estos campos en la sección para saber si se
    # aparta del perfil, y se los quita de golpe al restablecer. Uno que
    # el perfil dicte y la sección no tenga reventaría las dos cosas.
    assert all(hasattr(own, field) for field in STYLE_FIELDS), STYLE_FIELDS


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

        # Dos entradas que solo se diferencian en la caja de las letras
        # son un nombre que el selector no sabe separar.
        tmp_file.write_text(
            '[{"name": "Grito"}, {"name": "grito", "max_pt": 99}]',
            encoding="utf-8",
        )
        assert text_profiles.load() == (TextProfile(name="Grito"),)

        tmp_file.write_text("{ esto no es json", encoding="utf-8")
        assert text_profiles.load() == ()
    finally:
        text_profiles._PATH = original


def test_profile_names() -> None:
    """Qué nombre vale para un perfil, que es lo único ramificado del gestor.

    El nombre es la clave con la que el sidecar encuentra el perfil, así
    que un duplicado —o «(ninguno)», que es la fila de desasignar— deja
    secciones apuntando a algo que no se puede elegir.
    """
    from src.utils.text_profiles import NO_PROFILE, validate_name

    existing = (TextProfile(name="Grito"), TextProfile(name="Diálogo"))

    assert validate_name("Narración", existing) is None
    assert validate_name("   ", existing) is not None
    assert validate_name(NO_PROFILE, existing) is not None
    assert validate_name("(NINGUNO)", existing) is not None
    assert validate_name("grito", existing) is not None

    # Renombrar un perfil cambiándole solo la caja no es duplicarlo.
    assert validate_name("GRITO", existing, current="Grito") is None
    # Pero seguir chocando con otro sí lo es.
    assert validate_name("diálogo", existing, current="Grito") is not None


def test_export_progress(root: tk.Tk) -> None:
    """La ventana de la exportación: qué página, cuánto y cuánto falta.

    El exportador cuenta las páginas *terminadas* y avisa una vez más al
    acabar, sin nombre; la ventana tiene que leer las dos cosas sin
    pasarse del total ni prometer un tiempo que no puede saber.
    """
    from src.views import theme
    from src.views.export_dialog import ExportProgress

    theme.init(root)
    root.deiconify()          # grab_set() no funciona sobre una raíz oculta
    win = ExportProgress(root, total=4)

    assert win._count.cget("text") == "Página 1 de 4 · 0 %"
    # Sin ninguna hecha no hay con qué medir, y un número inventado sería
    # peor que no dar ninguno.
    assert win._eta.cget("text") == "calculando…"

    # Dos páginas en dos segundos: quedan dos, o sea unos dos segundos.
    win._started = time.monotonic() - 2.0
    win.step(2, 4, Path("pagina_03.png"))
    assert win._page.cget("text") == "pagina_03.png"
    assert win._count.cget("text") == "Página 3 de 4 · 50 %"
    assert win._eta.cget("text") == "queda ~2 s", win._eta.cget("text")
    assert abs(win._meter._fraction - 0.5) < 1e-9, win._meter._fraction

    # El aviso final llega sin página y no puede contar una de más.
    win.step(4, 4, Path(""))
    assert win._count.cget("text") == "Página 4 de 4 · 100 %"
    assert win._eta.cget("text") == ""
    assert win._page.cget("text") == "Terminando…"
    win.close()
