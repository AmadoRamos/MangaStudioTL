"""Image loading utilities.

Provides functions to:
- Filter supported file paths by extension.
- Expand a folder into the list of image files it contains.
- Load a sorted, validated list of ``PIL.Image.Image`` objects.

A ``<name>.clean.<ext>`` file is the text-free version of ``<name>``,
written by the cleaning step (or brought in by hand). It is a derived
artefact of a page, not a page of its own, so it never joins the
chapter's own list — see :func:`is_clean_variant`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, UnidentifiedImageError

from src.config import SUPPORTED_EXTENSIONS
from src.utils.logger import get_logger

log = get_logger("image_loader")

#: Infix that marks a file as the clean version of another one.
CLEAN_MARKER = ".clean"


def is_supported(path: Path) -> bool:
    """Return True if ``path`` has a supported image extension."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def clean_base_name(path: Path) -> str | None:
    """The page ``path`` is the clean version of, or ``None``.

    ``0001.clean.png`` -> ``0001``. The base carries no extension
    because the cleaner always writes PNG whatever the source was.
    """
    stem = path.stem
    if stem.lower().endswith(CLEAN_MARKER):
        return stem[: -len(CLEAN_MARKER)]
    return None


def is_clean_variant(path: Path) -> bool:
    return clean_base_name(path) is not None


def expand_folder(folder: Path) -> list[Path]:
    """Return the chapter's pages inside ``folder`` (non-recursive)."""
    if not folder.is_dir():
        log.warning("No es una carpeta valida: %s", folder)
        return []
    return _drop_clean_variants(
        [p for p in folder.iterdir() if p.is_file() and is_supported(p)]
    )


def _drop_clean_variants(paths: list[Path]) -> list[Path]:
    """Remove every ``x.clean.ext`` whose page ``x`` is in the list.

    A clean file whose page is missing is kept and treated as an
    ordinary image: dropping it would leave the user staring at «no se
    encontraron imágenes» over a folder that visibly has some.
    """
    originals = {
        p.stem.lower() for p in paths if not is_clean_variant(p)
    }
    kept: list[Path] = []
    dropped = 0
    for p in paths:
        base = clean_base_name(p)
        if base is not None and base.lower() in originals:
            dropped += 1
            continue
        kept.append(p)
    if dropped:
        log.info("%d version(es) limpia(s) omitida(s) de la lista", dropped)
    return kept


def expand_paths(paths: Iterable[Path]) -> list[Path]:
    """Expand a mix of file and folder paths into a flat list of image files.

    Folders are scanned (non-recursive). Files that are not supported images
    are dropped, as are the clean versions of pages already in the list.
    The result is sorted alphabetically.
    """
    resolved: list[Path] = []
    for raw in paths:
        if raw.is_dir():
            resolved.extend(expand_folder(raw))
        elif raw.is_file() and is_supported(raw):
            resolved.append(raw)
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in resolved:
        try:
            key = p.resolve()
        except OSError:
            key = p
        if key not in seen:
            seen.add(key)
            unique.append(p)
    # Run again over the merged list: a folder and a loose file dropped
    # together can pair a page with a clean version from the other side.
    unique = _drop_clean_variants(unique)
    unique.sort(key=lambda p: p.name.lower())
    log.info("expand_paths: %d archivo(s) unico(s)", len(unique))
    return unique


def load_images_with_paths(
    paths: Iterable[Path],
) -> tuple[list[tuple[Path, Image.Image]], list[Path]]:
    """Load a list of image files preserving their paths.

    Returns a tuple ``(items, failed)`` where each item is a
    ``(Path, PIL.Image.Image)`` pair. ``failed`` is the list of paths
    that could not be opened.
    """
    items: list[tuple[Path, Image.Image]] = []
    failed: list[Path] = []
    for path in paths:
        try:
            with Image.open(path) as img:
                img.load()
                items.append((path, img.copy()))
            log.debug(
                "Imagen cargada: %s (%dx%d)",
                path.name,
                items[-1][1].size[0],
                items[-1][1].size[1],
            )
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            log.warning("No se pudo cargar '%s': %s", path, exc)
            failed.append(path)
    log.info("Carga completada: %d OK, %d con error", len(items), len(failed))
    return items, failed
