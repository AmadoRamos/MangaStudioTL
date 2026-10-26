"""El envoltorio de Argos Translate, con Argos sustituido por un doble.

Aquí no se traduce nada de verdad: lo que se prueba es lo que el módulo
decide por su cuenta, que es donde ha habido fallos —leer los códigos de
un par instalado con dos formas distintas de la API, no dar por
instalado un par que Argos solo alcanzaría pivotando, y degradar sin
reventar cuando el módulo no está—. Un par de verdad pesa 300 MB y la
descarga es red: nada de eso cabe en la suite.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.utils import translator as mod
from src.utils.translator import LanguagePair, Translator, _translation_codes


class _Traduccion:  # pylint: disable=too-few-public-methods
    """Una traducción instalada, con la forma nueva de la API.

    Las instaladas exponen ``from_lang``/``to_lang`` —objetos con
    ``.code``— y solo los *paquetes* llevan ``from_code``/``to_code``.
    """

    def __init__(self, src: str, tgt: str, texto: str = "hola") -> None:
        self.from_lang = SimpleNamespace(code=src)
        self.to_lang = SimpleNamespace(code=tgt)
        self._texto = texto

    def translate(self, _text: str) -> str:
        return self._texto


def _traduccion_vieja(src: str, tgt: str) -> SimpleNamespace:
    """La forma plana, que es la que traía la API anterior."""
    return SimpleNamespace(from_code=src, to_code=tgt)


def _idioma(code: str, salidas: list) -> SimpleNamespace:
    """Un idioma instalado: su código y las traducciones que salen de él."""
    return SimpleNamespace(code=code, translations_from=salidas)


def _argos(monkeypatch, idiomas: list, **paquete) -> SimpleNamespace:
    """Pone un Argos de pega en los globales del módulo."""
    traducciones = {}
    for idioma in idiomas:
        try:
            salidas = list(idioma.translations_from)
        except Exception:
            continue  # un idioma roto es uno de los casos de prueba
        for t in salidas:
            src, tgt = _translation_codes(t)
            traducciones[(src, tgt)] = t
    fake_translate = SimpleNamespace(
        get_installed_languages=lambda: list(idiomas),
        get_translation_from_codes=lambda s, t: traducciones.get((s, t)),
    )
    fake_package = SimpleNamespace(**paquete)
    monkeypatch.setattr(mod, "_ARGOS_AVAILABLE", True)
    monkeypatch.setattr(mod, "argos_translate", fake_translate)
    monkeypatch.setattr(mod, "argos_package", fake_package)
    return fake_translate


def test_los_codigos_se_leen_en_las_dos_formas_de_la_api() -> None:
    """La regresión que dejaba la lista de pares vacía para siempre.

    Pedirle a una traducción instalada los nombres planos del paquete
    lanza, y el módulo acababa diciendo que un modelo descargado no
    estaba.
    """
    assert _translation_codes(_Traduccion("en", "es")) == ("en", "es")
    assert _translation_codes(_traduccion_vieja("en", "es")) == ("en", "es")
    assert _translation_codes(SimpleNamespace()) == (None, None)


def test_los_pares_instalados_dejan_fuera_la_identidad(monkeypatch) -> None:
    """Argos sintetiza en->en por cada idioma, y eso no lo bajó nadie."""
    _argos(monkeypatch, [
        _idioma("en", [_Traduccion("en", "en"), _Traduccion("en", "es")]),
        _idioma("es", [_Traduccion("es", "es")]),
    ])

    assert Translator().installed_pairs() == [LanguagePair("en", "es")]


def test_un_idioma_que_no_se_deja_leer_no_tumba_la_lista(monkeypatch) -> None:
    """Un catálogo a medias deja los idiomas que sí se leen."""
    class _Roto:  # pylint: disable=too-few-public-methods
        code = "xx"

        @property
        def translations_from(self):
            raise RuntimeError("catálogo corrupto")

    _argos(monkeypatch, [_Roto(), _idioma("en", [_Traduccion("en", "es")])])

    assert Translator().installed_pairs() == [LanguagePair("en", "es")]


def test_un_par_solo_alcanzable_pivotando_no_esta_instalado(monkeypatch) -> None:
    """`get_translation_from_codes` contesta por pares que nadie bajó.

    Con en->es y es->fr instalados, Argos sabe dar en->fr pivotando. Si
    el módulo se fiara de esa respuesta, la interfaz diría que el modelo
    está listo sin que se haya descargado nada.
    """
    fake = _argos(monkeypatch, [
        _idioma("en", [_Traduccion("en", "es")]),
        _idioma("es", [_Traduccion("es", "fr")]),
    ])
    # El doble solo contesta por lo instalado; lo que se prueba es que el
    # módulo no se lo pregunta.
    fake.get_translation_from_codes = lambda s, t: object()
    tr = Translator()

    assert tr.is_pair_available("en", "es") is True
    assert tr.is_pair_available("en", "fr") is False
    # Traducir al mismo idioma no necesita modelo.
    assert tr.is_pair_available("en", "en") is True


def test_ensure_pair_no_toca_la_red_si_ya_esta(monkeypatch) -> None:
    """Pedir un par instalado no mira el índice de paquetes."""
    def no_llamar() -> None:
        raise AssertionError("no debería mirar el índice")

    _argos(
        monkeypatch,
        [_idioma("en", [_Traduccion("en", "es")])],
        update_package_index=no_llamar,
    )

    assert Translator().ensure_pair("en", "es") is True


def test_ensure_pair_instala_el_paquete_que_coincide(monkeypatch) -> None:
    """De la lista del índice se baja el par pedido, no otro."""
    instalados: list[str] = []
    paquetes = [
        SimpleNamespace(from_code="en", to_code="fr", download=lambda: "fr.argos"),
        SimpleNamespace(from_code="en", to_code="es", download=lambda: "es.argos"),
    ]
    _argos(
        monkeypatch, [],
        update_package_index=lambda: None,
        get_available_packages=lambda: paquetes,
        install_from_path=instalados.append,
    )

    assert Translator().ensure_pair("en", "es") is True
    assert instalados == ["es.argos"]


def test_ensure_pair_contesta_que_no_sin_paquete_y_sin_red(monkeypatch) -> None:
    """Ni par inexistente ni red caída son una excepción: son False."""
    _argos(
        monkeypatch, [],
        update_package_index=lambda: None,
        get_available_packages=lambda: [],
        install_from_path=lambda _p: None,
    )
    assert Translator().ensure_pair("en", "xx") is False

    def sin_red() -> None:
        raise OSError("sin conexión")

    _argos(monkeypatch, [], update_package_index=sin_red)
    assert Translator().ensure_pair("en", "es") is False


@pytest.mark.parametrize("texto", ["", "   "])
def test_un_texto_vacio_vuelve_tal_cual(texto: str, monkeypatch) -> None:
    """Ni se le pregunta a Argos por una cadena en blanco."""
    _argos(monkeypatch, [_idioma("en", [_Traduccion("en", "es")])])
    assert Translator().translate(texto, "en", "es") == texto


def test_traducir_sin_el_par_devuelve_el_original(monkeypatch) -> None:
    """Nunca una cadena vacía: el OCR es lo único que hay si falla."""
    _argos(monkeypatch, [_idioma("en", [_Traduccion("en", "es")])])
    assert Translator().translate("hello", "en", "fr") == "hello"


def test_traducir_devuelve_lo_que_dice_argos(monkeypatch) -> None:
    """El camino bueno, con el modelo contestando."""
    _argos(monkeypatch, [
        _idioma("en", [_Traduccion("en", "es", texto="hola")]),
    ])
    assert Translator().translate("hello", "en", "es") == "hola"


def test_si_argos_revienta_al_traducir_se_queda_el_original(monkeypatch) -> None:
    """Un modelo corrupto deja el OCR, que es lo único que hay si falla."""
    def revienta(_text: str) -> str:
        raise RuntimeError("modelo corrupto")

    rota = _Traduccion("en", "es")
    rota.translate = revienta
    _argos(monkeypatch, [_idioma("en", [rota])])

    assert Translator().translate("hello", "en", "es") == "hello"


def test_una_traduccion_vacia_se_descarta(monkeypatch) -> None:
    """Un modelo que contesta con nada deja el original, no un hueco."""
    _argos(monkeypatch, [_idioma("en", [_Traduccion("en", "es", texto="")])])
    assert Translator().translate("hello", "en", "es") == "hello"


def test_sin_el_modulo_todo_degrada_sin_reventar(monkeypatch) -> None:
    """Sin argostranslate instalado la aplicación sigue abriéndose."""
    monkeypatch.setattr(mod, "_ARGOS_AVAILABLE", False)
    monkeypatch.setattr(mod, "argos_translate", None)
    monkeypatch.setattr(mod, "argos_package", None)
    tr = Translator()

    assert tr.is_available() is False
    assert tr.installed_pairs() == []
    assert tr.is_pair_available("en", "es") is False
    assert tr.ensure_pair("en", "es") is False
    assert tr.translate("hello", "en", "es") == "hello"
    assert Translator.is_module_available() is False


def test_is_available_se_cae_con_el_catalogo(monkeypatch) -> None:
    """Sin idiomas instalados no hay nada que traducir, y se dice."""
    _argos(monkeypatch, [])
    assert Translator().is_available() is False

    def revienta() -> None:
        raise RuntimeError("no se pudo abrir el catálogo")

    monkeypatch.setattr(
        mod, "argos_translate",
        SimpleNamespace(get_installed_languages=revienta),
    )
    tr = Translator()
    assert tr.is_available() is False
    assert "catálogo" in (tr.load_error() or "")


def test_la_etiqueta_de_un_par_es_la_que_se_ensena() -> None:
    """Lo que el riel escribe en la tarjeta de motores."""
    assert LanguagePair("en", "es").label == "en -> es"
