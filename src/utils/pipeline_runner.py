"""Pipeline runner: OCR over every pending mark of the chapter.

Single-thread worker. The recognition runs inline — the pipeline crops
and reads each pending mark itself and writes the text straight into the
store, so a result cannot be lost between two workers.

Cleaning is not part of this pass. It made the user wait between
«Marcar» and «Traducir» for something no step needs until the render, so
it lives in :mod:`src.utils.clean_queue`, which the App starts as soon as
this pass ends and keeps running in the background.

Progress reaches the Tk main thread through the queue that
:class:`BackgroundWorker` polls via ``after``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

from src.utils.background_worker import BackgroundWorker
from src.utils.crop_manager import CropManager
from src.utils.logger import get_logger
from src.utils.marks_store import MarksStore, OcrEntry
from src.utils.ocr_engine import OcrEngine, OcrResult

log = get_logger("pipeline_runner")

STEP_OCR = 1


@dataclass(frozen=True)
class OcrJobSpec:
    """A request to OCR one mark."""

    image_index: int
    mark_id: int
    image: Image.Image
    x: int
    y: int
    w: int
    h: int


StepStartCallback = Callable[[int, int, str], None]
StepProgressCallback = Callable[[int, int, int, str], None]
StepDoneCallback = Callable[[int, bool, str], None]
OverallDoneCallback = Callable[[bool, str], None]


class PipelineRunner(BackgroundWorker):
    """Reads every pending mark of the chapter on a single thread."""

    def __init__(
        self,
        ocr_engine: OcrEngine,
        crop_manager: CropManager,
    ) -> None:
        super().__init__()
        self._ocr_engine = ocr_engine
        self._crop_manager = crop_manager
        self._on_step_start: StepStartCallback | None = None
        self._on_step_progress: StepProgressCallback | None = None
        self._on_step_done: StepDoneCallback | None = None
        self._on_overall_done: OverallDoneCallback | None = None

    def attach(
        self,
        widget,
        on_step_start: StepStartCallback,
        on_step_progress: StepProgressCallback,
        on_step_done: StepDoneCallback,
        on_overall_done: OverallDoneCallback,
    ) -> None:
        super().attach(widget)
        self._on_step_start = on_step_start
        self._on_step_progress = on_step_progress
        self._on_step_done = on_step_done
        self._on_overall_done = on_overall_done

    def cancel(self) -> None:
        if not self.is_running():
            return
        log.info("Pipeline cancelado por el usuario")
        super().cancel()

    # ------------------------------------------------------------------
    # OCR of a single mark, on the calling thread
    # ------------------------------------------------------------------

    def resolve_lang(self, lang: str) -> str | None:
        """The language Tesseract will actually use, or ``None``.

        Falls back to English — or to whatever is installed — when the
        asked-for language has no traineddata. ``None`` means Tesseract
        has no usable language at all and OCR cannot run.
        """
        if self._ocr_engine.is_language_available(lang):
            return lang
        installed = self._ocr_engine.available_languages()
        fallback = "eng" if "eng" in installed else (
            next((x for x in installed if x != "osd"), "")
        )
        if not fallback:
            return None
        log.warning("Idioma '%s' no instalado, usando '%s'", lang, fallback)
        return fallback

    def recognize_spec(
        self, spec: OcrJobSpec, lang: str,
    ) -> tuple[OcrResult, str | None]:
        """Crop, recognise and clean up, on the calling thread."""
        crop_path: Path | None = None
        try:
            crop_path = self._crop_manager.crop(
                spec.image, spec.x, spec.y, spec.w, spec.h,
                image_index=spec.image_index, mark_id=spec.mark_id,
            )
            with Image.open(crop_path) as crop_img:
                crop_img.load()
                return self._ocr_engine.recognize(crop_img, lang=lang), None
        except Exception as exc:
            log.exception("Error procesando marca %d: %s", spec.mark_id, exc)
            return OcrResult(text="", confidence=0, language=lang), str(exc)
        finally:
            if crop_path is not None:
                try:
                    crop_path.unlink(missing_ok=True)
                except OSError as exc:
                    log.debug("No se pudo borrar crop %s: %s", crop_path, exc)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(
        self,
        items: list[tuple[Path, Image.Image]],
        stores: list[MarksStore],
        ocr_lang: str,
        force_ocr: bool = False,
    ) -> bool:
        """Read the chapter's pending marks.

        ``force_ocr`` re-reads marks that already have text — otherwise
        only the ones still empty are read, so a second pass costs the
        new marks and leaves reviewed text alone.
        """
        if self._busy_evt.is_set():
            self._emit("_on_overall_done", False, "Pipeline ya en curso")
            return False
        self._start_thread(
            "pipeline-runner", self._run_job,
            items, stores, ocr_lang, force_ocr,
        )
        return True

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _run_job(
        self,
        items: list[tuple[Path, Image.Image]],
        stores: list[MarksStore],
        ocr_lang: str,
        force_ocr: bool = False,
    ) -> None:
        try:
            ocr_ok = self._run_ocr(items, stores, ocr_lang, force_ocr)
            if self._cancel_evt.is_set():
                self._emit("_on_overall_done", False, "Cancelado por el usuario")
                return
            self._emit(
                "_on_overall_done", ocr_ok,
                "Texto extraído" if ocr_ok else "No se pudo extraer el texto",
            )
        except Exception as exc:
            log.exception("Error en pipeline: %s", exc)
            self._emit("_on_overall_done", False, f"Error: {exc}")
        finally:
            self._busy_evt.clear()

    @staticmethod
    def pending_ocr(stores: list[MarksStore], force: bool = False) -> int:
        """How many marks the next OCR pass would read."""
        if force:
            return sum(len(s) for s in stores)
        return sum(
            1 for s in stores for i in range(len(s))
            if s.get_ocr(i) is None or not s.get_ocr(i).text.strip()
        )

    def _run_ocr(
        self,
        items: list[tuple[Path, Image.Image]],
        stores: list[MarksStore],
        ocr_lang: str,
        force: bool = False,
    ) -> bool:
        """Read every pending mark and write the text into its store."""
        if not self._ocr_engine.is_available():
            self._emit("_on_step_start", STEP_OCR, 2, "OCR no disponible")
            self._emit("_on_step_done", STEP_OCR, False, "Tesseract no disponible")
            return False
        # Marks with no text yet — unless the user asked for all of them.
        specs: list[OcrJobSpec] = []
        for img_idx, store in enumerate(stores):
            for mark_id, mark in enumerate(store):
                entry = store.get_ocr(mark_id)
                if not force and entry is not None and entry.text.strip():
                    continue
                specs.append(OcrJobSpec(
                    image_index=img_idx,
                    mark_id=mark_id,
                    image=items[img_idx][1],
                    x=mark.x, y=mark.y, w=mark.w, h=mark.h,
                ))
        if not specs:
            self._emit("_on_step_start", STEP_OCR, 2, "OCR")
            self._emit("_on_step_progress", STEP_OCR, 0, 0, "Sin marcas pendientes")
            self._emit("_on_step_done", STEP_OCR, True, "Sin OCR pendiente")
            return True

        lang = self.resolve_lang(ocr_lang)
        if lang is None:
            self._emit("_on_step_start", STEP_OCR, 2, "OCR sin idiomas")
            self._emit(
                "_on_step_done", STEP_OCR, False,
                "Tesseract no tiene idiomas instalados",
            )
            return False

        total = len(specs)
        self._emit("_on_step_start", STEP_OCR, 2, f"OCR ({total} marca(s))")
        self._emit(
            "_on_step_progress", STEP_OCR, 0, total,
            f"Iniciando OCR sobre {total} marca(s)...",
        )
        with_text = 0
        for i, spec in enumerate(specs, start=1):
            if self._cancel_evt.is_set():
                break
            result, error = self.recognize_spec(spec, lang)
            store = stores[spec.image_index]
            store.set_ocr_result(spec.mark_id, OcrEntry(
                text=result.text.strip(),
                confidence=result.confidence,
                language=result.language or lang,
                engine="tesseract",
            ))
            if result.text.strip():
                with_text += 1
            label = f"{spec.image_index + 1:02d}·{spec.mark_id + 1:02d}"
            if error:
                message = f"OCR {i}/{total} — {label}: error"
            elif result.text.strip():
                preview = result.text.replace("\n", " ").strip()[:28]
                message = f"OCR {i}/{total} — {label}: «{preview}»"
            else:
                message = f"OCR {i}/{total} — {label}: sin texto"
            self._emit("_on_step_progress", STEP_OCR, i, total, message)
        if self._cancel_evt.is_set():
            self._emit("_on_step_done", STEP_OCR, False, "OCR cancelado")
            return False
        log.info(
            "OCR del pipeline: %d marca(s) leidas, %d con texto",
            total, with_text,
        )
        self._emit(
            "_on_step_done", STEP_OCR, True,
            f"OCR completado: {with_text}/{total} con texto",
        )
        return True
