"""Partir el texto y elegir el cuerpo: lo que decide si un globo se lee.

Las medidas exactas dependen de la fuente que haya instalada, así que
aquí no se afirma ningún ancho en píxeles: se afirma la regla —que
ninguna línea se salga, que el texto quepa de alto, que una caja más
grande nunca dé un cuerpo más pequeño—, que es lo que puede romperse.
"""

from __future__ import annotations

from PIL import Image

from src.utils.text_renderer import (
    STYLE_BOLD,
    STYLE_BOLD_ITALIC,
    STYLE_ITALIC,
    STYLE_REGULAR,
    TextBox,
    _load_font,
    _text_width,
    _wrap,
    fit_text,
    render_text,
    resolve_style,
    style_name,
)

FONT = _load_font(20)


def _cabe(lineas: list[str], ancho: int) -> bool:
    return all(_text_width(l, FONT) <= ancho for l in lineas)


def test_el_texto_se_parte_por_palabras() -> None:
    """Una frase larga en una caja estrecha sale en varias líneas."""
    lineas = _wrap("uno dos tres cuatro cinco seis siete ocho", FONT, 80)
    assert len(lineas) > 1
    assert _cabe(lineas, 80)
    # Y no se pierde ni se inventa ninguna palabra.
    assert " ".join(lineas).split() == "uno dos tres cuatro cinco seis siete ocho".split()


def test_una_palabra_mas_ancha_que_la_caja_se_parte_por_letras() -> None:
    """Sin esto, la palabra se sale del globo y no hay cuerpo que lo arregle."""
    lineas = _wrap("supercalifragilisticoespialidoso", FONT, 40)
    assert len(lineas) > 1
    assert _cabe(lineas, 40)
    assert "".join(lineas) == "supercalifragilisticoespialidoso"


def test_los_saltos_del_usuario_se_respetan() -> None:
    """Un salto escrito a mano es una decisión de rotulado, no sobra."""
    assert _wrap("uno\ndos", FONT, 10_000) == ["uno", "dos"]
    assert _wrap("uno\r\ndos", FONT, 10_000) == ["uno", "dos"]
    # Un renglón en blanco separa párrafos y también se guarda.
    assert _wrap("uno\n\ndos", FONT, 10_000) == ["uno", "", "dos"]


def test_el_vacio_es_una_linea_vacia() -> None:
    """Nunca una lista vacía: quien dibuja cuenta líneas para centrar."""
    assert _wrap("", FONT, 100) == [""]
    assert _wrap("   ", FONT, 100) == [""]


def test_una_caja_mayor_nunca_da_letra_menor() -> None:
    """La búsqueda binaria tiene que ser monótona.

    Es la propiedad que hace que ampliar un globo en el paso 4 se vea
    como ampliar el texto, y no como un salto arbitrario.
    """
    texto = "el gato duerme sobre el tejado caliente"
    pequena = fit_text(TextBox(0, 0, 100, 60, texto))
    mediana = fit_text(TextBox(0, 0, 200, 120, texto))
    grande = fit_text(TextBox(0, 0, 400, 240, texto))
    assert pequena.font_size <= mediana.font_size <= grande.font_size


def test_el_texto_elegido_cabe_de_verdad() -> None:
    """Lo que devuelve ``fit_text`` es lo que se dibuja: tiene que caber."""
    caja = TextBox(0, 0, 160, 90, "una frase de varias palabras para repartir")
    fit = fit_text(caja)
    font = _load_font(fit.font_size)
    assert all(_text_width(l, font) <= caja.w for l in fit.lines)
    ascent, descent = font.getmetrics()
    assert int((ascent + descent) * 1.15) * len(fit.lines) <= caja.h


def test_una_caja_sin_area_no_busca_nada() -> None:
    """Una caja de ancho cero devuelve el mínimo sin recorrer la búsqueda."""
    fit = fit_text(TextBox(0, 0, 0, 50, "algo", min_pt=9))
    assert fit.font_size == 9
    assert fit.lines == [""]


def test_el_cuerpo_nunca_baja_del_minimo() -> None:
    """Aunque no quepa, se dibuja algo: un globo vacío es peor."""
    fit = fit_text(TextBox(0, 0, 12, 12, "una frase larguísima que no cabe", min_pt=8))
    assert fit.font_size >= 8


def test_los_dos_interruptores_suman_un_estilo() -> None:
    assert style_name(False, False) == STYLE_REGULAR
    assert style_name(True, False) == STYLE_BOLD
    assert style_name(False, True) == STYLE_ITALIC
    assert style_name(True, True) == STYLE_BOLD_ITALIC


def test_una_variante_que_no_existe_no_se_promete(monkeypatch) -> None:
    """Una familia sin negrita en disco vuelve en redonda, no sintetizada.

    PIL dibuja lo que hay en el archivo y no inventa el trazo grueso, así
    que «negrita» solo es cierto si existe el archivo. Que el riel pueda
    avisarlo antes de exportar depende de que esta respuesta sea la real.

    Se simula el disco porque qué fuentes hay instaladas cambia con la
    máquina, y la regla que se prueba es la escalera, no el catálogo.
    """
    from src.utils import text_renderer

    # Una familia con archivo solo para la redonda.
    monkeypatch.setattr(
        text_renderer,
        "_resolve_font_path",
        lambda fam, style=STYLE_REGULAR: (
            "C:/falsa.ttf" if style == STYLE_REGULAR else None
        ),
    )
    assert resolve_style("Solo Redonda", True, False) == (False, False)
    assert resolve_style("Solo Redonda", True, True) == (False, False)

    # Y una que sí las tiene todas responde que sí.
    monkeypatch.setattr(
        text_renderer, "_resolve_font_path", lambda fam, style=STYLE_REGULAR: "C:/x.ttf"
    )
    assert resolve_style("Completa", True, True) == (True, True)
    assert resolve_style("Completa", True, False) == (True, False)


def test_sin_pedir_variante_no_se_mira_el_disco(monkeypatch) -> None:
    """La respuesta de la redonda es inmediata: se pide en cada preview."""
    from src.utils import text_renderer

    def _explota(*_args, **_kw):
        raise AssertionError("no debería mirar el disco")

    monkeypatch.setattr(text_renderer, "_resolve_font_path", _explota)
    assert resolve_style("Lo Que Sea", False, False) == (False, False)


def test_dibujar_no_toca_el_original() -> None:
    """El render devuelve una copia: la página original se reusa después."""
    base = Image.new("RGB", (60, 40), "white")
    salida = render_text(base, [TextBox(5, 5, 50, 30, "hola", color=(0, 0, 0))])
    assert salida is not base
    assert base.getbbox() is None or base.getpixel((0, 0)) == (255, 255, 255)
    # Y algo ha pintado.
    assert salida.getcolors(maxcolors=16) != [(60 * 40, (255, 255, 255))]
