"""Image inpainting via LaMa (simple-lama-inpainting wrapper).

Strategy: cluster nearby marks, then for each cluster crop a region
(padding around the cluster's union bbox), run LaMa on the small
crop, and paste the result back. This is much faster than processing
the full image and gives LaMa enough context to fill in correctly.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFilter

from src.config import (
    CLEAN_SUFFIX,
    SUPPORTED_EXTENSIONS,
    INPAINT_CLUSTER_GAP,
    INPAINT_DEFAULT_PADDING,
    INPAINT_MASK_DILATE_PX,
    INPAINT_MODEL,
    INPAINT_MODELS,
    INPAINT_PADDING_PX,
    MODELS_DIR,
)
from src.utils import text_mask
from src.utils.logger import get_logger
from src.utils.marks_store import Mark

log = get_logger("inpainter")

try:
    from simple_lama_inpainting import SimpleLama

    _LAMA_AVAILABLE: bool = True
    _IMPORT_ERROR: str | None = None
except Exception as exc:
    SimpleLama = None  # type: ignore[assignment]
    _LAMA_AVAILABLE = False
    _IMPORT_ERROR = str(exc)
    log.warning("simple-lama-inpainting no disponible: %s", exc)


def resolve_model(name: str = INPAINT_MODEL) -> Path | None:
    """Archivo TorchScript del modelo ``name``, o None para el de siempre.

    Un nombre desconocido, o uno cuyo archivo todavia no se ha generado
    con ``tools/trace_manga_lama.py``, cae al big-lama por defecto con un
    aviso en el log. Preferimos limpiar peor que no limpiar: quien pone
    la variable esta probando algo, y quedarse sin paso 2 por un archivo
    que falta es mas caro que perder la mejora.
    """
    if not name:
        return None
    filename = INPAINT_MODELS.get(name)
    if filename is None:
        log.warning(
            "INPAINT_MODEL=%r no existe; se usara big-lama. Opciones: %s",
            name, ", ".join(sorted(INPAINT_MODELS)) or "(ninguna)",
        )
        return None
    path = MODELS_DIR / filename
    if not path.exists():
        log.warning(
            "Modelo %r no encontrado en %s; se usara big-lama. "
            "Generalo con: python tools/trace_manga_lama.py",
            name, path,
        )
        return None
    return path


def clean_path(image_path: Path) -> Path:
    """Where the clean version of ``image_path`` is *written* (always PNG)."""
    return image_path.with_name(image_path.stem + CLEAN_SUFFIX)


def find_clean(image_path: Path) -> Path | None:
    """The clean version of ``image_path`` on disk, whatever its format.

    The cleaning step writes PNG, but the ``<nombre>.clean.<ext>``
    convention also covers pages someone cleaned elsewhere and dropped
    into the folder, so read paths accept any supported extension.
    """
    preferred = clean_path(image_path)
    if preferred.exists():
        return preferred
    for ext in SUPPORTED_EXTENSIONS:
        candidate = image_path.with_name(f"{image_path.stem}.clean{ext}")
        if candidate.exists():
            return candidate
    return None


def has_clean(image_path: Path) -> bool:
    return find_clean(image_path) is not None


def marks_signature(
    marks: Iterable[Mark],
    padding: int = INPAINT_DEFAULT_PADDING,
    cluster_gap: int = INPAINT_CLUSTER_GAP,
) -> str:
    """Fingerprint of everything that shapes a clean version.

    The colour of a box does not reach the mask, so it is left out: a
    page whose marks only changed colour must not be cleaned again.

    A per-mark padding only joins the fingerprint when it was actually
    set. Folding the resolved default in instead would change every
    signature ever written and send whole chapters back through LaMa for
    a value that did not move. El modelo de la sección entra con la
    misma regla y por el mismo motivo.

    El ``m3`` y la dilatación son la excepción, y a propósito: ahí lo que
    cambia no es un valor que nadie movió, es qué tapa la máscara. Un
    ``.clean`` escrito con la máscara rectangular ya no es el que sale
    hoy de las mismas cajas, así que tiene que caducar. Se paga una
    pasada de LaMa por capítulo, una sola vez. El número es la versión
    del algoritmo de ``text_mask``: si vuelve a cambiar, se sube.
    """
    boxes = ";".join(
        f"{m.x},{m.y},{m.w},{m.h}"
        + ("" if m.padding is None else f",p{m.padding}")
        + ("" if not m.model else f",m{m.model}")
        for m in marks
    )
    raw = f"{padding}|{cluster_gap}|m3d{INPAINT_MASK_DILATE_PX}|{boxes}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def clean_is_stale(
    image_path: Path,
    marks: list[Mark],
    recorded: str = "",
    padding: int = INPAINT_DEFAULT_PADDING,
    cluster_gap: int = INPAINT_CLUSTER_GAP,
) -> bool:
    """Whether ``image_path`` still needs a cleaning pass.

    True when the page has marks and either has no clean version, or the
    one on disk came from a different set of boxes. Without a recorded
    signature — a chapter cleaned before signatures existed, or cleaned
    by hand elsewhere — the file is trusted unless the marks were saved
    after it was written, which is the only evidence available there.
    """
    if not marks:
        return False
    current = find_clean(image_path)
    if current is None:
        return True
    if recorded:
        return recorded != marks_signature(marks, padding, cluster_gap)
    from src.utils.marks_store import sidecar_path
    try:
        return sidecar_path(image_path).stat().st_mtime > current.stat().st_mtime
    except OSError:
        return False


def mark_bbox(m: Mark) -> tuple[int, int, int, int]:
    return (m.x, m.y, m.x + m.w, m.y + m.h)


def _cluster_bbox(m: Mark) -> tuple[int, int, int, int]:
    """Box grown by whatever the user asked for *beyond* the baseline.

    Clustering decides which marks share a crop, and two marks whose
    erased areas overlap have to. ``cluster_gap`` was tuned against the
    baseline ``INPAINT_PADDING_PX`` that every mask already carried, so
    only the excess over it is added here: a mark with no padding of its
    own grows by nothing and clusters exactly as it did before.
    """
    extra = max(0, m.erase_padding - INPAINT_PADDING_PX)
    if not extra:
        return mark_bbox(m)
    return (m.x - extra, m.y - extra, m.x + m.w + extra, m.y + m.h + extra)


def bboxes_overlap(
    a: tuple[int, int, int, int],
    b: tuple[int, int, int, int],
    gap: int = 0,
) -> bool:
    """Return True if bboxes (x0, y0, x1, y1) overlap or are within ``gap``."""
    return not (
        a[2] + gap < b[0]
        or a[0] > b[2] + gap
        or a[3] + gap < b[1]
        or a[1] > b[3] + gap
    )


def union_bbox(
    rects: Iterable[tuple[int, int, int, int]],
) -> tuple[int, int, int, int]:
    """Union of several (x0, y0, x1, y1) rects."""
    it = iter(rects)
    try:
        first = next(it)
    except StopIteration:
        return (0, 0, 0, 0)
    x0, y0, x1, y1 = first
    for r in it:
        x0 = min(x0, r[0])
        y0 = min(y0, r[1])
        x1 = max(x1, r[2])
        y1 = max(y1, r[3])
    return (x0, y0, x1, y1)


def cluster_marks(
    marks: list[Mark],
    gap: int = INPAINT_CLUSTER_GAP,
) -> list[list[Mark]]:
    """Group marks into clusters separated by less than ``gap`` pixels.

    Two marks join the same cluster if their bboxes overlap or are
    within ``gap`` pixels. Algorithm: pick an unassigned mark, start
    a cluster, repeatedly absorb any unassigned mark within gap of
    the cluster's current expanded bbox.
    """
    if not marks:
        return []
    n = len(marks)
    rects = [_cluster_bbox(m) for m in marks]
    assigned = [False] * n
    clusters: list[list[Mark]] = []

    for i in range(n):
        if assigned[i]:
            continue
        cluster = [marks[i]]
        assigned[i] = True
        changed = True
        while changed:
            changed = False
            current_bbox = union_bbox(_cluster_bbox(m) for m in cluster)
            expanded = (
                current_bbox[0] - gap,
                current_bbox[1] - gap,
                current_bbox[2] + gap,
                current_bbox[3] + gap,
            )
            for j in range(n):
                if assigned[j]:
                    continue
                if bboxes_overlap(expanded, rects[j]):
                    cluster.append(marks[j])
                    assigned[j] = True
                    changed = True
        clusters.append(cluster)
    return clusters


def group_by_model(marks: list[Mark]) -> list[tuple[str, list[Mark]]]:
    """Las marcas repartidas por el modelo que las rellena.

    Dos secciones vecinas con modelos distintos no pueden compartir
    cluster: un cluster es una llamada a una red. Ordenado para que el
    modelo por defecto —cadena vacía— vaya siempre primero, y para que
    la misma página dé el mismo resultado dos veces seguidas.
    """
    groups: dict[str, list[Mark]] = {}
    for m in marks:
        groups.setdefault(m.model, []).append(m)
    return sorted(groups.items())


class Inpainter:
    """Lazy-loading LaMa wrapper for image cleanup."""

    def __init__(self) -> None:
        # Un modelo cargado por nombre resuelto: una página puede mezclar
        # secciones con modelos distintos y no queremos recargar 200 MB en
        # cada cluster.
        # ponytail: sin desalojo. Son dos modelos como mucho —los que hay
        # en INPAINT_MODELS— y el que no se use nunca no se carga.
        self._models: dict[str, object] = {}
        self._lock = threading.Lock()
        self._available: bool | None = None
        self._load_error: str | None = None

    @staticmethod
    def is_module_available() -> bool:
        return _LAMA_AVAILABLE

    @staticmethod
    def module_import_error() -> str | None:
        return _IMPORT_ERROR

    def is_available(self) -> bool:
        if not _LAMA_AVAILABLE:
            self._available = False
            return False
        if self._available is not None:
            return self._available
        try:
            self._ensure_model()
            self._available = True
        except Exception as exc:
            self._load_error = str(exc)
            self._available = False
            log.warning("LaMa no disponible: %s", exc)
        return self._available

    def load_error(self) -> str | None:
        return self._load_error

    def _ensure_model(self, name: str = INPAINT_MODEL):
        """El modelo de ``name``, cargándolo la primera vez que se pide.

        La clave del cache es la ruta ya resuelta y no el nombre pedido:
        así un nombre que no existe y el modelo por defecto comparten la
        misma instancia en vez de cargar dos veces lo mismo.
        """
        alt = resolve_model(name)
        key = str(alt or "")
        model = self._models.get(key)
        if model is not None:
            return model
        with self._lock:
            if key in self._models:
                return self._models[key]
            log.info("Cargando modelo LaMa (puede tardar la primera vez)...")
            if SimpleLama is None:
                raise RuntimeError("simple-lama-inpainting no instalado")
            # SimpleLama ya mira LAMA_MODEL y hace torch.jit.load de esa
            # ruta en vez de descargar el big-lama. Aprovechar ese gancho
            # nos ahorra tener que traernos la arquitectura al programa:
            # un TorchScript trae el grafo dentro.
            if alt is not None:
                os.environ["LAMA_MODEL"] = str(alt)
                log.info("Modelo de inpainting alternativo: %s", alt.name)
            else:
                os.environ.pop("LAMA_MODEL", None)
            self._models[key] = SimpleLama()
            log.info("Modelo LaMa cargado")
            return self._models[key]

    @staticmethod
    def build_mask(
        image_size: tuple[int, int],
        marks: Iterable[Mark],
        padding: int | None = None,
    ) -> Image.Image:
        """Build a binary mask (white = area to inpaint).

        Each mark brings its own margin; ``padding`` overrides it for
        every mark, which is what a caller that wants a uniform mask
        regardless of the boxes' settings asks for.
        """
        iw, ih = image_size
        mask = Image.new("L", (iw, ih), 0)
        if iw <= 0 or ih <= 0:
            return mask
        draw = ImageDraw.Draw(mask)
        for m in marks:
            p = m.erase_padding if padding is None else padding
            x0 = max(0, m.x - p)
            y0 = max(0, m.y - p)
            x1 = min(iw, m.x + m.w + p)
            y1 = min(ih, m.y + m.h + p)
            if x1 > x0 and y1 > y0:
                draw.rectangle((x0, y0, x1, y1), fill=255)
        return mask

    def inpaint_marks(
        self,
        image: Image.Image,
        marks: list[Mark],
        padding: int = INPAINT_DEFAULT_PADDING,
        cluster_gap: int = INPAINT_CLUSTER_GAP,
    ) -> Image.Image:
        """Cluster marks and inpaint each cluster region.

        For each cluster: compute the union bbox, expand it by
        ``padding`` (clipped to the image), crop the image, build a
        mask for that region, run LaMa, then paste the cleaned crop
        back. Areas outside any cluster are preserved untouched.
        """
        if not self.is_available():
            raise RuntimeError("LaMa no esta disponible")
        if image.mode != "RGB":
            image = image.convert("RGB")
        if not marks:
            return image.copy()

        iw, ih = image.size
        result = image.copy()
        # Una pasada por modelo. Cada una recorta de ``result`` y no del
        # original, porque dos secciones vecinas con modelos distintos
        # caen en pasadas distintas y la segunda tiene que ver lo que
        # dejó la primera dentro de su recorte.
        for name, group in group_by_model(marks):
            model = self._ensure_model(name)
            clusters = cluster_marks(group, gap=cluster_gap)
            log.info(
                "Inpainting clusterizado: %d cluster(s) con padding=%d, modelo=%s",
                len(clusters), padding, name or "(por defecto)",
            )
            self._inpaint_clusters(
                result, clusters, model, padding, (iw, ih),
            )
        return result

    def _inpaint_clusters(
        self,
        result: Image.Image,
        clusters: list[list[Mark]],
        model,
        padding: int,
        image_size: tuple[int, int],
    ) -> None:
        """Rellena ``clusters`` sobre ``result``, en el sitio."""
        iw, ih = image_size
        for c_idx, cluster in enumerate(clusters):
            bbox = union_bbox(mark_bbox(m) for m in cluster)
            # ``padding`` is context for LaMa, measured from the boxes.
            # A mark whose margin reaches past it would have its mask
            # clipped at the crop edge — erased area lost, and no
            # untouched pixels left for LaMa to blend into. So the crop
            # grows to keep the widest margin inside it with room to
            # spare, and stays exactly as it was for ordinary marks.
            widest = max(m.erase_padding for m in cluster)
            crop_pad = max(padding, widest + INPAINT_PADDING_PX)
            x0 = max(0, bbox[0] - crop_pad)
            y0 = max(0, bbox[1] - crop_pad)
            x1 = min(iw, bbox[2] + crop_pad)
            y1 = min(ih, bbox[3] + crop_pad)
            if x1 <= x0 or y1 <= y0:
                continue
            crop_box = (x0, y0, x1, y1)
            crop_w, crop_h = x1 - x0, y1 - y0
            log.debug(
                "  cluster %d/%d: %d marca(s) en crop %dx%d @ (%d,%d)",
                c_idx + 1, len(clusters), len(cluster),
                crop_w, crop_h, x0, y0,
            )

            crop = result.crop(crop_box)
            mask = self._build_mask_in_crop(
                crop, crop_box, cluster, crop_w, crop_h
            )

            if _mask_has_pixels(mask):
                clean_crop = model(crop, mask)
                clean_crop = _crop_to(clean_crop, crop_w, crop_h)
                result.paste(clean_crop, crop_box, _paste_alpha(mask))
            else:
                log.debug("  cluster %d: mask vacia, saltando", c_idx + 1)

    def inpaint(
        self,
        image: Image.Image,
        mask: Image.Image,
    ) -> Image.Image:
        """Run LaMa inpainting on ``image`` using the binary ``mask``.

        Kept for backward compatibility with callers that pass a full
        image mask. The cluster-based path is :meth:`inpaint_marks`,
        used by the inpainting runner.
        """
        if not self.is_available():
            raise RuntimeError("LaMa no esta disponible")
        if image.size != mask.size:
            mask = mask.resize(image.size, Image.Resampling.LANCZOS)
        if image.mode != "RGB":
            image = image.convert("RGB")
        return self._ensure_model()(image, mask)

    @staticmethod
    def _build_mask_in_crop(
        crop: Image.Image,
        crop_box: tuple[int, int, int, int],
        cluster: list[Mark],
        crop_w: int,
        crop_h: int,
    ) -> Image.Image:
        """Build a mask for a cropped region from a list of marks.

        Dentro de la caja de cada marca engordada por su margen, lo que
        se borra es el trazo del rótulo y no el rectángulo entero: ver
        :mod:`src.utils.text_mask`. El rectángulo sigue siendo el techo
        —fuera de él no se toca nada, que es lo que dibuja el punteado
        del paso 2— y sigue siendo la respuesta cuando el trazo no se
        detecta. El padding del recorte, alrededor de todo esto, se
        conserva como contexto para LaMa.
        """
        x0, y0 = int(crop_box[0]), int(crop_box[1])
        regions: list[tuple[text_mask.Rect, text_mask.Rect]] = []
        for m in cluster:
            box = (
                int(m.x) - x0, int(m.y) - y0,
                int(m.x + m.w) - x0, int(m.y + m.h) - y0,
            )
            pad = m.erase_padding
            area = (
                max(0, box[0] - pad),
                max(0, box[1] - pad),
                min(int(crop_w), box[2] + pad),
                min(int(crop_h), box[3] + pad),
            )
            if area[2] > area[0] and area[3] > area[1]:
                regions.append((box, area))
        return text_mask.build_mask(crop, regions, INPAINT_MASK_DILATE_PX)

    def cleanup_to_disk(
        self,
        image: Image.Image,
        marks: list[Mark],
        out_path: Path,
        padding: int = INPAINT_DEFAULT_PADDING,
        cluster_gap: int = INPAINT_CLUSTER_GAP,
    ) -> None:
        """Cluster, inpaint each cluster, save to ``out_path``."""
        if not self.is_available():
            raise RuntimeError("LaMa no esta disponible")
        if not marks:
            log.info("Sin areas para limpiar, copiando original")
            _save_atomic(image, out_path)
            return
        log.info(
            "Inpainting %s (%d marca(s), padding=%d)",
            out_path.name, len(marks), padding,
        )
        result = self.inpaint_marks(image, marks, padding=padding, cluster_gap=cluster_gap)
        _save_atomic(result, out_path)
        log.info("Guardada version limpia: %s", out_path.name)


def _save_atomic(image: Image.Image, out_path: Path) -> None:
    """Write the PNG through a temporary, then move it into place.

    Cleaning now runs in the background, so the app can be closed
    half-way through a save. Landing the file in one move keeps a
    truncated PNG from being read back as the page's clean version.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".part")
    image.save(tmp, format="PNG")
    tmp.replace(out_path)


def _crop_to(img: Image.Image, width: int, height: int) -> Image.Image:
    """Crop ``img`` to (width, height) if LaMa padded the output."""
    if img.size == (width, height):
        return img
    if img.size[0] >= width and img.size[1] >= height:
        return img.crop((0, 0, width, height))
    log.warning(
        "LaMa devolvio %s, se esperaba (%d, %d) - usando tal cual",
        img.size, width, height,
    )
    return img


def _mask_has_pixels(mask: Image.Image) -> bool:
    return mask.getbbox() is not None


def _paste_alpha(mask: Image.Image) -> Image.Image:
    """Por dónde se pega lo que devuelve el modelo.

    LaMa devuelve el recorte entero reconstruido, no solo el agujero:
    pegarlo tal cual sustituye también los píxeles que estaban bien —el
    contexto y todo el fondo que la máscara al trazo acaba de salvar— por
    la regeneración de la red. Pegando por la máscara, lo de fuera queda
    idéntico al byte.

    Se ensancha antes de desenfocar a propósito. Un desenfoque a secas
    baja el alfa dentro del borde de la máscara y deja transparentarse el
    rótulo que se estaba borrando; ensanchando primero, la rampa cae
    fuera, que es donde sirve para algo: mata la costura.
    """
    return mask.filter(ImageFilter.MaxFilter(5)).filter(
        ImageFilter.GaussianBlur(1.5)
    )


def install_instructions() -> str:
    return (
        "Instala las dependencias con:\n"
        "  pip install -r requirements.txt\n"
        "Esto instala torch (~500MB) y simple-lama-inpainting.\n"
        "La primera ejecucion descargara el modelo LaMa (~150MB)."
    )
