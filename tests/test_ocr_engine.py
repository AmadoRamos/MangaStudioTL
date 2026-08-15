"""El reparto entre los dos motores de OCR.

Lo que se comprueba aquí es la regla que los ordena, no si leen bien:
eso se midió aparte sobre las páginas de ``example/`` y está resumido en
:mod:`src.utils.ocr_engine`. Los motores van sustituidos por dobles,
porque cargar RapidOCR de verdad tarda un segundo y necesita sus modelos.
"""

from __future__ import annotations

import pytest
from PIL import Image

from src.utils.ocr_engine import OcrEngine, OcrResult, reading_order


@pytest.fixture
def img() -> Image.Image:
    return Image.new("RGB", (120, 40), "white")


def _engine(monkeypatch, *, rapid: str | None, tess: str | None) -> OcrEngine:
    """Un motor con los dos caminos sustituidos.

    ``None`` significa «este motor no está»; una cadena, lo que devuelve.
    """
    eng = OcrEngine()
    monkeypatch.setattr(eng, "rapid_available", lambda: rapid is not None)
    monkeypatch.setattr(
        eng, "_recognize_rapid",
        lambda im, lang: OcrResult(rapid or "", 90, lang, "rapidocr"),
    )
    monkeypatch.setattr(
        eng, "_recognize_tesseract",
        lambda im, lang: OcrResult(tess or "", 80, lang, "tesseract" if tess else ""),
    )
    return eng


def test_manda_rapidocr_cuando_lee(monkeypatch, img: Image.Image) -> None:
    """Si RapidOCR devuelve texto, ese texto gana y Tesseract no corre."""
    eng = _engine(monkeypatch, rapid="HEHE, SHE'S SO CUTE.", tess="HEHE, SHES S30 CUTE")
    result = eng.recognize(img, lang="eng")
    assert result.text == "HEHE, SHE'S SO CUTE."
    assert result.engine == "rapidocr"


def test_tesseract_recoge_lo_que_rapidocr_no_ve(monkeypatch, img: Image.Image) -> None:
    """El vacío de RapidOCR es la señal que enciende el respaldo.

    Es el caso «HEEHEE ~» del banco: RapidOCR no detecta nada y se calla,
    y ahí Tesseract acierta. Un vacío es detectable; un texto malo no.
    """
    eng = _engine(monkeypatch, rapid="", tess="HEEHEE ~")
    result = eng.recognize(img, lang="eng")
    assert result.text == "HEEHEE ~"
    assert result.engine == "tesseract"


def test_solo_espacios_cuenta_como_vacio(monkeypatch, img: Image.Image) -> None:
    """Un resultado en blanco no es un resultado."""
    eng = _engine(monkeypatch, rapid="   \n ", tess="ALGO")
    assert eng.recognize(img, lang="eng").text == "ALGO"


def test_sin_rapidocr_lee_tesseract_directamente(monkeypatch, img: Image.Image) -> None:
    """Sin RapidOCR instalado el motor sigue siendo el de antes."""
    eng = _engine(monkeypatch, rapid=None, tess="TEXTO")
    result = eng.recognize(img, lang="eng")
    assert result.text == "TEXTO"
    assert result.engine == "tesseract"


def test_un_fallo_de_rapidocr_no_pierde_la_marca(monkeypatch, img: Image.Image) -> None:
    """Si RapidOCR revienta, lee Tesseract en vez de perderse el texto."""
    eng = OcrEngine()
    monkeypatch.setattr(eng, "rapid_available", lambda: True)

    def explota(im, lang):
        raise RuntimeError("onnxruntime se cayó")

    monkeypatch.setattr(eng, "_recognize_rapid", explota)
    monkeypatch.setattr(
        eng, "_recognize_tesseract",
        lambda im, lang: OcrResult("RESCATADO", 80, lang, "tesseract"),
    )
    assert eng.recognize(img, lang="eng").text == "RESCATADO"


def test_con_rapidocr_ningun_idioma_bloquea(monkeypatch) -> None:
    """RapidOCR lee alfabeto latino, así que no hay traineddata que falte.

    Antes, un Tesseract sin ``spa`` atascaba el capítulo en el paso 2.
    """
    eng = OcrEngine()
    monkeypatch.setattr(eng, "rapid_available", lambda: True)
    monkeypatch.setattr(eng, "available_languages", lambda: ())
    assert eng.is_language_available("spa+eng")
    assert eng.is_available()


def test_sin_rapidocr_mandan_los_traineddata(monkeypatch) -> None:
    """Sin él vuelve la regla vieja: lo que Tesseract tenga instalado."""
    eng = OcrEngine()
    monkeypatch.setattr(eng, "rapid_available", lambda: False)
    monkeypatch.setattr(eng, "available_languages", lambda: ("eng", "osd"))
    assert eng.is_language_available("eng")
    assert not eng.is_language_available("spa+eng")


# ----------------------------------------------------------------------
# Orden de lectura
# ----------------------------------------------------------------------

def _box(x0: int, y0: int, x1: int, y1: int) -> list:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def test_las_lineas_se_ordenan_de_arriba_abajo() -> None:
    """RapidOCR devuelve las cajas como salen de la red, no en orden."""
    got = reading_order([
        (_box(10, 60, 200, 100), "SEGUNDA"),
        (_box(10, 10, 200, 50), "PRIMERA"),
    ])
    assert got == "PRIMERA SEGUNDA"


def test_lo_que_comparte_renglon_se_ordena_por_x() -> None:
    """Dos cajas a la misma altura son un renglón, izquierda primero."""
    got = reading_order([
        (_box(120, 10, 200, 50), "DERECHA"),
        (_box(10, 12, 100, 52), "IZQUIERDA"),
    ])
    assert got == "IZQUIERDA DERECHA"


def test_sin_detecciones_no_hay_texto() -> None:
    assert reading_order([]) == ""
