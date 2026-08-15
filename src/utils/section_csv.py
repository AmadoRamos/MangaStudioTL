"""Las secciones del capítulo como CSV, para traducir fuera y volver.

Tres columnas —``id``, ``texto original``, ``texto traducido``— y el id
alfanumérico de la marca como única referencia: el número de página y el
de sección se corren en cuanto alguien borra una marca anterior, el
``uid`` no (ver :mod:`src.utils.marks_store`).

Al cargar, una celda vacía no borra lo que había: una hoja rellenada a
medias es lo normal —se traducen veinte secciones hoy y el resto
mañana—, y tratarla como «déjalo en blanco» tiraría el OCR de todo lo
que aún no se ha tocado. Para vaciar una sección está la tabla del paso
3, donde se ve lo que se está borrando.
"""

from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Sequence

from src.utils.logger import get_logger
from src.utils.marks_store import MarksStore, OcrEntry, TranslationEntry

log = get_logger("section_csv")

HEADER = ["id", "texto original", "texto traducido"]


def export_sections(stores: Iterable[MarksStore], path: Path) -> int:
    """Escribe una fila por sección del capítulo. Devuelve cuántas.

    ``utf-8-sig`` porque el destino habitual es Excel, que sin BOM abre
    el archivo en la codificación del sistema y enseña los acentos
    rotos.
    """
    rows = 0
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        for store in stores:
            for mark_id, mark in enumerate(store):
                ocr = store.get_ocr(mark_id)
                trans = store.get_translation(mark_id)
                writer.writerow([
                    mark.uid,
                    ocr.text if ocr is not None else "",
                    trans.text if trans is not None else "",
                ])
                rows += 1
    log.info("Exportadas %d seccion(es) a %s", rows, path.name)
    return rows


def import_sections(
    stores: Sequence[MarksStore],
    path: Path,
    *,
    source_lang: str = "",
    target_lang: str = "",
) -> tuple[int, int]:
    """Vuelca el CSV sobre las secciones. Devuelve ``(aplicadas, ajenas)``.

    «Ajenas» son las filas cuyo id no está en el capítulo abierto: un
    archivo de otro capítulo, o una sección que se borró después de
    exportar. Se cuentan y se siguen, que es más útil que abortarlo todo
    por una fila.
    """
    index = {
        mark.uid: (store, mark_id)
        for store in stores
        for mark_id, mark in enumerate(store)
        if mark.uid
    }
    applied = unknown = 0
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        first = fh.readline()
        fh.seek(0)
        # El Excel en español guarda con punto y coma. Contar cuál manda
        # en la cabecera cuesta menos que un Sniffer que puede fallar.
        delimiter = ";" if first.count(";") > first.count(",") else ","
        for row in csv.reader(fh, delimiter=delimiter):
            if not row:
                continue
            uid = row[0].strip()
            if not uid or uid.lower() == HEADER[0]:
                continue
            target = index.get(uid)
            if target is None:
                unknown += 1
                continue
            store, mark_id = target
            original = row[1].strip() if len(row) > 1 else ""
            translated = row[2].strip() if len(row) > 2 else ""
            if _apply(store, mark_id, original, translated,
                      source_lang, target_lang):
                applied += 1
    log.info(
        "Importadas %d seccion(es) de %s (%d id(s) fuera del capítulo)",
        applied, path.name, unknown,
    )
    return applied, unknown


def _apply(
    store: MarksStore,
    mark_id: int,
    original: str,
    translated: str,
    source_lang: str,
    target_lang: str,
) -> bool:
    """Deja el texto de una fila en su sección. ``True`` si cambió algo."""
    changed = False
    ocr = store.get_ocr(mark_id)
    if original and (ocr is None or ocr.text != original):
        # La confianza y el idioma son de quien leyó el recorte; el texto
        # que llega del CSV lo escribió una persona, y eso es lo que dice
        # el motor.
        store.set_ocr_result(mark_id, replace(ocr, text=original, engine="csv")
                             if ocr is not None
                             else OcrEntry(text=original, confidence=0,
                                           language="", engine="csv"))
        changed = True

    trans = store.get_translation(mark_id)
    if translated and (trans is None or trans.text != translated):
        # ``replace`` para no llevarse por delante el color, la fuente o
        # el perfil que la sección tuviera puestos en el paso 4.
        store.set_translation(mark_id, replace(
            trans, text=translated, edited=True, engine="csv",
        ) if trans is not None else TranslationEntry(
            text=translated,
            source_lang=source_lang,
            target_lang=target_lang,
            engine="csv",
            edited=True,
        ))
        changed = True
    return changed
