"""Crop manager: extracts mark regions into a session-only temp folder.

The folder is created under the system temp directory and removed on
application shutdown. Stale folders from previous sessions are cleaned
on construction.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from pathlib import Path

from PIL import Image

from src.config import OCR_TEMP_PREFIX
from src.utils.logger import get_logger

log = get_logger("crop_manager")


class CropManager:
    """Manages the temp folder used to hold cropped mark images."""

    def __init__(self) -> None:
        self._root: Path = Path(
            tempfile.gettempdir()
        ) / f"{OCR_TEMP_PREFIX}{int(time.time())}_{uuid.uuid4().hex[:6]}"
        self._root.mkdir(parents=True, exist_ok=True)
        log.info("Carpeta temporal de crops: %s", self._root)
        self._cleanup_stale()

    @property
    def root(self) -> Path:
        return self._root

    def crop_path(self, image_index: int, mark_id: int) -> Path:
        """Return a path (not yet written) for a given crop."""
        return self._root / f"img{image_index:04d}_mark{mark_id:04d}.png"

    def crop(
        self,
        image: Image.Image,
        x: int,
        y: int,
        w: int,
        h: int,
        image_index: int = 0,
        mark_id: int = 0,
    ) -> Path:
        """Crop ``image`` and write the result to a temp file."""
        iw, ih = image.size
        x0 = max(0, min(x, iw))
        y0 = max(0, min(y, ih))
        x1 = max(0, min(x + w, iw))
        y1 = max(0, min(y + h, ih))
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"Crop vacio: ({x0},{y0})-({x1},{y1})")
        region = image.crop((x0, y0, x1, y1))
        out = self.crop_path(image_index, mark_id)
        region.save(out, format="PNG")
        return out

    def cleanup(self) -> None:
        """Remove the temp folder and all its contents."""
        if not self._root.exists():
            return
        try:
            shutil.rmtree(self._root, ignore_errors=True)
            log.info("Carpeta temporal eliminada: %s", self._root)
        except Exception as exc:
            log.warning("No se pudo eliminar %s: %s", self._root, exc)

    def _cleanup_stale(self) -> None:
        """Remove leftover OCR temp folders from previous sessions."""
        base = Path(tempfile.gettempdir())
        try:
            for entry in base.iterdir():
                if not entry.is_dir():
                    continue
                if entry.name.startswith(OCR_TEMP_PREFIX) and entry != self._root:
                    try:
                        shutil.rmtree(entry, ignore_errors=True)
                    except Exception:
                        pass
        except OSError as exc:
            log.warning("No se pudo limpiar temp: %s", exc)
