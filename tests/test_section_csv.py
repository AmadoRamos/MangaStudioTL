"""El CSV del paso 3: sale, se edita fuera y vuelve por el id."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.utils.marks_store import Mark, MarksStore, OcrEntry, TranslationEntry
from src.utils.section_csv import HEADER, export_sections, import_sections


@pytest.fixture
def stores(tmp_path: Path) -> list[MarksStore]:
    """Dos páginas: la primera con dos secciones, la segunda con una."""
    made = []
    for page, count in ((1, 2), (2, 1)):
        store = MarksStore(tmp_path / f"page{page:03d}.jpg")
        for i in range(count):
            store.add(Mark(x=i * 200, y=0, w=100, h=50, color="#ffcc00"))
        made.append(store)
    made[0].set_ocr_result(0, OcrEntry(text="HELLO", confidence=90,
                                       language="eng"))
    made[0].set_translation(0, TranslationEntry(
        text="HOLA", source_lang="en", target_lang="es", max_pt=18,
    ))
    return made


def test_uid_unico_y_estable(stores: list[MarksStore], tmp_path: Path) -> None:
    uids = [m.uid for store in stores for m in store]
    assert len(set(uids)) == 3
    assert all(len(u) == 6 and u.isalnum() for u in uids)

    # Y el mismo capítulo reabierto conserva los ids: si no, el CSV
    # exportado ayer no encajaría hoy.
    reloaded = MarksStore(stores[0].image_path)
    reloaded.load()
    assert [m.uid for m in reloaded] == uids[:2]


def test_sidecar_viejo_estrena_id_y_lo_guarda(tmp_path: Path) -> None:
    path = tmp_path / "page001.jpg"
    sidecar = tmp_path / "page001.jpg.marks.json"
    sidecar.write_text(
        '{"version": 5, "marks": [{"x": 0, "y": 0, "w": 9, "h": 9}]}',
        encoding="utf-8",
    )
    store = MarksStore(path)
    store.load()
    uid = store.marks[0].uid
    assert len(uid) == 6
    assert uid in sidecar.read_text(encoding="utf-8")


def test_ida_y_vuelta(stores: list[MarksStore], tmp_path: Path) -> None:
    csv_path = tmp_path / "cap.csv"
    assert export_sections(stores, csv_path) == 3

    lines = csv_path.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == ",".join(HEADER)

    # Lo que haría el traductor fuera: rellenar una fila vacía y corregir
    # la que ya venía traducida.
    uid_a = stores[0].marks[1].uid
    uid_b = stores[0].marks[0].uid
    csv_path.write_text(
        ",".join(HEADER) + "\n"
        + f"{uid_a},BYE,ADIÓS\n"
        + f"{uid_b},HELLO,¡HOLA!\n"
        + "ZZZZZZ,otra,cosa\n",
        encoding="utf-8",
    )
    applied, unknown = import_sections(
        stores, csv_path, source_lang="en", target_lang="es",
    )
    assert (applied, unknown) == (2, 1)
    assert stores[0].get_ocr(1).text == "BYE"
    assert stores[0].get_translation(1).text == "ADIÓS"
    assert stores[0].get_translation(0).text == "¡HOLA!"
    # Y lo que la sección tuviera puesto en el paso 4 sigue ahí.
    assert stores[0].get_translation(0).max_pt == 18


def test_celda_vacia_no_borra(stores: list[MarksStore], tmp_path: Path) -> None:
    """Media hoja rellenada no puede tirar el OCR de la otra media."""
    csv_path = tmp_path / "medio.csv"
    csv_path.write_text(
        ",".join(HEADER) + "\n" + f"{stores[0].marks[0].uid},,\n",
        encoding="utf-8",
    )
    assert import_sections(stores, csv_path) == (0, 0)
    assert stores[0].get_ocr(0).text == "HELLO"
    assert stores[0].get_translation(0).text == "HOLA"


def test_punto_y_coma_del_excel_espanol(
    stores: list[MarksStore], tmp_path: Path,
) -> None:
    csv_path = tmp_path / "excel.csv"
    csv_path.write_text(
        ";".join(HEADER) + "\n" + f"{stores[1].marks[0].uid};ONE;UNO\n",
        encoding="utf-8-sig",
    )
    assert import_sections(stores, csv_path) == (1, 0)
    assert stores[1].get_translation(0).text == "UNO"
