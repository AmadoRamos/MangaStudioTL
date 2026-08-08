"""Persists the folders the user has opened, most recent first.

Stored one path per line in a small text file at the project root; the
first line is the folder opened last. Folders that no longer exist on
disk are skipped when read, so a chapter that was moved or deleted
cannot keep a dead row in the rail.

The single-line files written by earlier versions read back as a
one-entry history, so nothing is lost on upgrade.
"""

from __future__ import annotations

import os
from pathlib import Path

from src.config import PROJECT_ROOT, RECENT_PATHS_FILE
from src.utils.logger import get_logger

log = get_logger("recent_paths")

_PATH_FILE: Path = PROJECT_ROOT / RECENT_PATHS_FILE

#: How many folders to remember. The rail shows a handful; the rest are
#: kept so a chapter you come back to next week is still one click away.
MAX_HISTORY: int = 10


def _read_lines() -> list[str]:
    if not _PATH_FILE.exists():
        return []
    try:
        text = _PATH_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("No se pudo leer %s: %s", _PATH_FILE, exc)
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def _write_lines(lines: list[str]) -> None:
    try:
        _PATH_FILE.write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        log.warning("No se pudo escribir %s: %s", _PATH_FILE, exc)


def _key(raw: str) -> str:
    """Comparison key: Windows paths differ only in spelling, not identity."""
    return os.path.normcase(os.path.normpath(raw))


def _resolved(folder: Path) -> str:
    try:
        return str(folder.resolve())
    except OSError:
        return str(folder)


def save(folder: Path) -> None:
    """Record ``folder`` as the most recently opened one."""
    entry = _resolved(folder)
    target = _key(entry)
    lines = [entry]
    for raw in _read_lines():
        if _key(raw) != target:
            lines.append(raw)
    _write_lines(lines[:MAX_HISTORY])


def forget(folder: Path) -> None:
    """Drop ``folder`` from the history (used when it no longer opens)."""
    target = _key(_resolved(folder))
    _write_lines([raw for raw in _read_lines() if _key(raw) != target])


def history(limit: int = MAX_HISTORY) -> list[Path]:
    """The remembered folders that still exist, most recent first."""
    out: list[Path] = []
    seen: set[str] = set()
    for raw in _read_lines():
        key = _key(raw)
        if key in seen:
            continue
        seen.add(key)
        p = Path(raw)
        if not p.is_dir():
            continue
        out.append(p)
        if len(out) >= limit:
            break
    return out


def load() -> Path | None:
    """Return the last folder if it still exists on disk, else ``None``."""
    entries = history(1)
    return entries[0] if entries else None


def display_name() -> str | None:
    """Short, user-facing name of the recent folder (for the sidebar)."""
    p = load()
    if p is None:
        return None
    return p.name or str(p)
