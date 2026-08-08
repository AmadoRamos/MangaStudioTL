"""Drag & drop helpers built on top of ``tkinterdnd2``.

``tkinterdnd2`` provides a drop-enabled ``Tk`` root via
``TkinterDnD.DnDWrapper``. This module exposes a single helper
``create_dnd_root`` that returns the proper root class and a registry
``register_drop_target`` to bind a callback to a widget.

Falling back gracefully: if ``tkinterdnd2`` is not installed, the
factory returns the standard ``tk.Tk`` class and registration becomes
a no-op so the app still runs (without drag & drop support).
"""

from __future__ import annotations

from typing import Callable

import tkinter as tk

from src.utils.logger import get_logger

log = get_logger("dnd_handler")

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE: bool = True
    log.info("tkinterdnd2 disponible: drag & drop activado")
except Exception as exc:
    DND_AVAILABLE = False
    DND_FILES = None
    TkinterDnD = None
    log.warning("tkinterdnd2 no disponible (%s): drag & drop deshabilitado", exc)


DnDCallback = Callable[[list[str]], None]


def create_dnd_root() -> type[tk.Tk]:
    """Return a ``Tk`` subclass with DnD support if available."""
    if DND_AVAILABLE and TkinterDnD is not None:
        return TkinterDnD.Tk
    return tk.Tk


def register_drop_target(widget: tk.Misc, on_drop: DnDCallback) -> None:
    """Bind ``widget`` to receive file drops, calling ``on_drop(paths)``.

    On platforms or environments where ``tkinterdnd2`` is not available,
    this is a silent no-op.
    """
    if not DND_AVAILABLE:
        return

    def _handle(event: object) -> None:
        try:
            data = getattr(event, "data", "")
        except Exception as exc:
            log.exception("Error leyendo evento drop: %s", exc)
            return
        if not data:
            return
        # tkinterdnd2 hands back a Tcl list: paths with spaces come
        # wrapped in braces. Tk already knows how to split that.
        try:
            paths = [str(p) for p in widget.tk.splitlist(str(data))]
        except tk.TclError as exc:
            log.warning("No se pudo interpretar el drop %r: %s", data, exc)
            return
        log.info("Drop recibido: %d ruta(s)", len(paths))
        if paths:
            try:
                on_drop(paths)
            except Exception as exc:
                log.exception("Error en callback de drop: %s", exc)

    try:
        widget.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
        widget.dnd_bind("<<Drop>>", _handle)  # type: ignore[attr-defined]
        log.debug("Drop target registrado en %s", widget)
    except Exception as exc:
        log.exception("No se pudo registrar drop target: %s", exc)
