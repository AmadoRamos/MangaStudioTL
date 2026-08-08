"""Linear workflow controller for the translator app.

Owns the cross-step state (items, stores, render config, current step)
and the transitions between the four steps:

    1. Home       -> load images
    2. Marks      -> draw rectangles, OCR
    3. OCR review -> check / edit translations
    4. Render     -> tweak per-section, export

Cleaning is not a step. It starts when step 2 hands over and runs in the
background while the chapter is translated, because nothing before the
render needs it — see :mod:`src.utils.clean_queue`.

The App constructs a :class:`WorkflowController` and asks it to build
the right view for each step.
"""

from __future__ import annotations

from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from src.utils.logger import get_logger
from src.utils.marks_store import MarksStore

if TYPE_CHECKING:
    from src.app import App

log = get_logger("workflow")


class WorkflowStep(IntEnum):
    HOME = 1
    MARKS = 2
    OCR_REVIEW = 3
    RENDER = 4


class WorkflowController:
    """Linear controller. One step at a time, forward + back."""

    def __init__(self, app: "App", items: list[tuple[Path, Image.Image]]):
        self._app = app
        self.items: list[tuple[Path, Image.Image]] = list(items)
        self.stores: list[MarksStore] = [MarksStore(p) for p, _ in items]
        for s in self.stores:
            s.load()
        self.current_step: WorkflowStep = WorkflowStep.HOME
        self.font_family: str = "Segoe UI"
        self.max_pt: int = 36
        # Highest step the user has reached; used to show check marks.
        self._highest_reached: WorkflowStep = WorkflowStep.HOME

    # ------------------------------------------------------------------
    # Step navigation
    # ------------------------------------------------------------------

    def go_to(self, step: WorkflowStep) -> None:
        if not self.items and step != WorkflowStep.HOME:
            log.warning("No hay imagenes cargadas, no se puede ir al paso %s", step)
            return
        self.current_step = WorkflowStep(step)
        if self.current_step.value > self._highest_reached.value:
            self._highest_reached = self.current_step
        log.info("Workflow -> paso %s", self.current_step.name)
        self._app._render_current_step()

    def continue_step(self) -> None:
        """Advance to the next step (or finalize if on the last one)."""
        if self.current_step == WorkflowStep.HOME:
            if self.items:
                self.go_to(WorkflowStep.MARKS)
            return
        if self.current_step == WorkflowStep.MARKS:
            view = self._app._current_view
            if view is not None and hasattr(view, "run_pipeline"):
                try:
                    # The OCR gates the advance; the view moves on itself
                    # once the text is in and hands the cleaning to the
                    # background queue on the way out.
                    view.run_pipeline(advance=True)
                except Exception as exc:
                    log.exception("Error lanzando pipeline: %s", exc)
                return
            self.go_to(WorkflowStep.OCR_REVIEW)
            return
        if self.current_step == WorkflowStep.OCR_REVIEW:
            self.go_to(WorkflowStep.RENDER)
            return
        if self.current_step == WorkflowStep.RENDER:
            view = self._app._current_view
            if view is not None and hasattr(view, "finalize"):
                try:
                    view.finalize()
                except Exception as exc:
                    log.exception("Error finalizando: %s", exc)
            return

    def back_step(self) -> None:
        """Move one step backwards (capped at HOME)."""
        if self.current_step == WorkflowStep.HOME:
            return
        self.current_step = WorkflowStep(self.current_step.value - 1)
        log.info("Workflow <- paso %s", self.current_step.name)
        self._app._render_current_step()

    def reset(self) -> None:
        """Reset to HOME (called after export)."""
        self.items = []
        self.stores = []
        self.current_step = WorkflowStep.HOME
        self._highest_reached = WorkflowStep.HOME
        self._app._render_current_step()

    @property
    def app(self) -> "App":
        """The App, which owns everything that outlives a single step."""
        return self._app

    def has_items(self) -> bool:
        return bool(self.items)

    def highest_reached(self) -> WorkflowStep:
        return self._highest_reached

    def reload_stores(self) -> None:
        """Re-create stores from current items (used after adding images)."""
        self.stores = [MarksStore(p) for p, _ in self.items]
        for s in self.stores:
            s.load()

    # ------------------------------------------------------------------
    # State helpers used by views
    # ------------------------------------------------------------------

    def total_marks(self) -> int:
        return sum(len(s) for s in self.stores)

    def translated_marks(self) -> int:
        return sum(
            1 for s in self.stores
            for v in s.translations.values() if v.text.strip()
        )

    def ocr_pending_marks(self) -> int:
        return sum(
            1 for s in self.stores
            for i in range(len(s))
            if s.get_ocr(i) is None or not (s.get_ocr(i).text.strip())
        )

    def images_without_clean(self) -> int:
        """Marked pages whose clean version is missing or out of date."""
        from src.utils.inpainter import clean_is_stale
        return sum(
            1 for index, (path, _) in enumerate(self.items)
            if index < len(self.stores)
            and clean_is_stale(
                path, list(self.stores[index]), self.stores[index].clean_signature,
            )
        )
