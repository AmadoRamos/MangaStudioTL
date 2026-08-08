"""Export translated images to a destination folder.

For every source image, the clean version (``<name>.clean.png``) is
opened, the translated text is rendered at each mark's rectangle, and
the result is saved as ``<basename>.translated.png`` in the chosen
output folder. A ``<basename>.translation.json`` sidecar is also
written with the final list of translations per image.

If no clean version exists, the original image is used and a warning
is logged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

from src.config import (
    TEXT_RENDER_MAX_PT,
    TRANSLATION_SIDECAR_SUFFIX,
    TRANSLATION_SUFFIX,
)
from src.utils.inpainter import find_clean
from src.utils.logger import get_logger
from src.utils.marks_store import MarksStore
from src.utils.text_renderer import TextBox, render_text, resolve_style

log = get_logger("exporter")


@dataclass(frozen=True)
class ExportResult:
    out_path: Path
    used_clean: bool
    translated_count: int
    skipped_count: int


ProgressCallback = Callable[[int, int, Path], None]


def export_translations(
    items: list[tuple[Path, Image.Image]],
    stores: list[MarksStore],
    out_dir: Path,
    text_color: tuple[int, int, int] = (0, 0, 0),
    font_family: str | None = None,
    max_pt: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[ExportResult]:
    """Render and write the translated images.

    ``items`` is a list of ``(path, original_image)`` pairs; ``stores``
    is the parallel list of :class:`MarksStore` with translations set.

    Returns one :class:`ExportResult` per image, in order.
    """
    if len(items) != len(stores):
        raise ValueError("items y stores deben tener la misma longitud")
    if not items:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[ExportResult] = []
    total = len(items)
    for idx, ((path, _), store) in enumerate(zip(items, stores)):
        if on_progress is not None:
            try:
                on_progress(idx, total, path)
            except Exception as exc:
                log.warning("Error en on_progress: %s", exc)

        used_clean = True
        cp = find_clean(path)
        if cp is not None:
            try:
                base = Image.open(cp)
                base.load()
            except Exception as exc:
                log.warning(
                    "No se pudo abrir la limpia %s (%s), usando original",
                    cp, exc,
                )
                base = _load_original(path)
                used_clean = False
        else:
            base = _load_original(path)
            used_clean = False
        if base is None:
            log.error("No se pudo cargar imagen base para %s", path)
            results.append(ExportResult(
                out_path=Path(), used_clean=False,
                translated_count=0, skipped_count=0,
            ))
            continue

        base = base.convert("RGBA")
        boxes: list[TextBox] = []
        translated = 0
        skipped = 0
        sidecar_payload: list[dict] = []
        for mark_id, mark in enumerate(store):
            entry = store.get_translation(mark_id)
            if entry is None or not entry.text.strip():
                skipped += 1
                continue
            # Per-section overrides win over the global config.
            section_color = entry.color or text_color
            section_family = entry.font_family or font_family
            section_max_pt = (
                entry.max_pt
                if entry.max_pt is not None
                else (max_pt if max_pt is not None else TEXT_RENDER_MAX_PT)
            )
            # No hay capa global de estilo: «sin tocar» es redonda.
            section_bold = bool(entry.bold)
            section_italic = bool(entry.italic)
            drawn_bold, drawn_italic = resolve_style(
                section_family, section_bold, section_italic,
            )
            boxes.append(TextBox(
                x=mark.x,
                y=mark.y,
                w=mark.w,
                h=mark.h,
                text=entry.text,
                color=section_color,
                align="center",
                font_family=section_family,
                max_pt=section_max_pt,
                bold=section_bold,
                italic=section_italic,
            ))
            translated += 1
            sidecar_payload.append({
                "mark_id": mark_id,
                "x": mark.x,
                "y": mark.y,
                "w": mark.w,
                "h": mark.h,
                "text": entry.text,
                "source_lang": entry.source_lang,
                "target_lang": entry.target_lang,
                "engine": entry.engine,
                "edited": entry.edited,
                "ran_at": entry.ran_at,
                "color": list(section_color),
                "font_family": section_family,
                "max_pt": section_max_pt,
                # Lo que se dibujó, no lo que se pidió: si la familia no
                # tiene la variante instalada, el PNG salió en redonda y
                # el sidecar debe decir eso.
                "bold": drawn_bold,
                "italic": drawn_italic,
            })

        rendered = render_text(base, boxes) if boxes else base

        out_path = out_dir / f"{path.stem}{TRANSLATION_SUFFIX}"
        try:
            rendered.save(out_path, format="PNG")
            log.info(
                "Exportada %s (%d traducida(s), %d sin traduccion)",
                out_path.name, translated, skipped,
            )
        except Exception as exc:
            log.exception("No se pudo guardar %s: %s", out_path, exc)
            results.append(ExportResult(
                out_path=out_path, used_clean=used_clean,
                translated_count=0, skipped_count=0,
            ))
            continue

        if sidecar_payload:
            sidecar = out_dir / f"{path.stem}{TRANSLATION_SIDECAR_SUFFIX}"
            try:
                sidecar.write_text(
                    json.dumps(
                        {
                            "image": path.name,
                            "translated_count": len(sidecar_payload),
                            "translations": sidecar_payload,
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except Exception as exc:
                log.warning("No se pudo escribir sidecar %s: %s", sidecar, exc)

        results.append(ExportResult(
            out_path=out_path, used_clean=used_clean,
            translated_count=translated, skipped_count=skipped,
        ))

    if on_progress is not None:
        try:
            on_progress(total, total, Path(""))
        except Exception:
            pass
    return results


def _load_original(path: Path) -> Image.Image | None:
    try:
        img = Image.open(path)
        img.load()
        return img.copy()
    except Exception as exc:
        log.exception("No se pudo abrir original %s: %s", path, exc)
        return None
