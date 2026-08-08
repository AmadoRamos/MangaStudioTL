"""The step-3 review table: every section of the chapter in one list.

Four columns, as in the mockups — ``Sección`` (``página·marca``), the
OCR text, the translation and the OCR confidence with a plain-language
band. Both text columns are edited in place: double-click a cell, type,
``Enter`` saves, ``Tab`` moves to the next cell, ``Esc`` cancels.

The table spans the whole chapter rather than one page, which is what
the ``Todas 46 / Pendientes 5 / Confianza baja 3`` filters count.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable

from src.config import (
    ACCENT_100,
    ACCENT_800,
    COLOR_BG,
    NEUTRAL_100,
    NEUTRAL_500,
)
from src.utils.logger import get_logger
from src.utils.marks_store import MarksStore
from src.views import theme

log = get_logger("translation_table")

PREVIEW_LEN = 120

FILTER_ALL = "all"
FILTER_PENDING = "pending"
FILTER_LOW = "low"

# Confidence bands. Tesseract's number means little on its own, so the
# table says what it implies instead.
CONFIDENCE_HIGH = 85
CONFIDENCE_LOW = 60

RowKey = tuple[int, int]


class TranslationTable(tk.Frame):
    """Chapter-wide OCR / translation review table."""

    def __init__(
        self,
        master: tk.Misc,
        on_translate_row: Callable[[int, int], None],
        on_translation_edited: Callable[[int, int, str], None],
        on_translation_deleted: Callable[[int, int], None],
        on_ocr_edited: Callable[[int, int, str], None] | None = None,
        on_select: Callable[[int, int], None] | None = None,
    ) -> None:
        super().__init__(master, bg=COLOR_BG)
        self._on_translate_row = on_translate_row
        self._on_translation_edited = on_translation_edited
        self._on_translation_deleted = on_translation_deleted
        self._on_ocr_edited = on_ocr_edited
        self._on_select = on_select

        self._stores: list[MarksStore] = []
        self._filter: str = FILTER_ALL
        self._running_keys: set[RowKey] = set()
        self._editor: tk.Entry | None = None
        self._editor_key: RowKey | None = None
        self._editor_column: str | None = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        holder = tk.Frame(self, bg=COLOR_BG)
        holder.pack(fill=tk.BOTH, expand=True)

        self._tree = ttk.Treeview(
            holder,
            columns=("section", "ocr", "trans", "conf"),
            show="headings",
            selectmode="browse",
            style="Modernist.Treeview",
        )
        self._tree.heading("section", text="SECCIÓN", anchor=tk.W)
        self._tree.heading("ocr", text="OCR", anchor=tk.W)
        self._tree.heading("trans", text="TRADUCCIÓN", anchor=tk.W)
        self._tree.heading("conf", text="CONFIANZA", anchor=tk.W)
        self._tree.column("section", width=84, anchor=tk.W, stretch=False)
        self._tree.column("ocr", width=320, anchor=tk.W, stretch=True)
        self._tree.column("trans", width=380, anchor=tk.W, stretch=True)
        self._tree.column("conf", width=120, anchor=tk.W, stretch=False)

        scrollbar = ttk.Scrollbar(
            holder, orient=tk.VERTICAL, command=self._tree.yview,
            style="Modernist.Vertical.TScrollbar",
        )
        self._tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._tree.tag_configure("low", background=ACCENT_100, foreground=ACCENT_800)
        self._tree.tag_configure("pending", foreground=NEUTRAL_500)
        self._tree.tag_configure("odd", background=NEUTRAL_100)

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Double-1>", self._on_double_click)
        self._tree.bind("<Return>", lambda _e: self._edit_selected("trans"))
        self._tree.bind("<Delete>", lambda _e: self._delete_selected())

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def set_stores(self, stores: Iterable[MarksStore]) -> None:
        self._cancel_editor()
        self._stores = list(stores)
        self.refresh()

    # Backwards-compatible single-store entry point.
    def set_store(self, store: MarksStore | None) -> None:
        self.set_stores([store] if store is not None else [])

    def set_filter(self, mode: str) -> None:
        self._filter = mode
        self.refresh()

    def counts(self) -> dict[str, int]:
        """Row counts behind the three filter chips."""
        total = pending = low = 0
        for _key, _page, _mark, ocr, trans in self._iter_rows():
            total += 1
            if trans is None or not trans.text.strip():
                pending += 1
            if ocr is not None and 0 < ocr.confidence < CONFIDENCE_LOW:
                low += 1
        return {FILTER_ALL: total, FILTER_PENDING: pending, FILTER_LOW: low}

    def _iter_rows(self):
        for page, store in enumerate(self._stores):
            for mark_id in range(len(store)):
                yield (
                    (page, mark_id), page, mark_id,
                    store.get_ocr(mark_id), store.get_translation(mark_id),
                )

    def refresh(self, highlight: RowKey | None = None) -> None:
        self._cancel_editor()
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        visible = 0
        for key, page, mark_id, ocr, trans in self._iter_rows():
            translated = bool(trans is not None and trans.text.strip())
            confidence = ocr.confidence if ocr is not None else 0
            is_low = 0 < confidence < CONFIDENCE_LOW
            if self._filter == FILTER_PENDING and translated:
                continue
            if self._filter == FILTER_LOW and not is_low:
                continue

            tags: list[str] = []
            if is_low:
                tags.append("low")
            elif not translated:
                tags.append("pending")
            elif visible % 2:
                tags.append("odd")

            if key in self._running_keys:
                trans_text = "⟳ traduciendo…"
            elif translated:
                trans_text = _truncate(trans.text)
                if trans.edited:
                    trans_text = f"{trans_text}   · editada"
            elif ocr is None or not ocr.text.strip():
                trans_text = "sin texto reconocido"
            elif is_low:
                trans_text = "revisa el OCR antes de traducir"
            else:
                trans_text = "—"

            self._tree.insert(
                "", tk.END, iid=_iid(key),
                values=(
                    f"{page + 1:02d}·{mark_id + 1:02d}",
                    _truncate(ocr.text if ocr else "") or "(sin OCR)",
                    trans_text,
                    _confidence_label(confidence),
                ),
                tags=tuple(tags),
            )
            visible += 1

        if highlight is not None:
            self.select(highlight)

    def set_running(self, page: int, mark_id: int, running: bool) -> None:
        key = (page, mark_id)
        if running:
            self._running_keys.add(key)
        else:
            self._running_keys.discard(key)
        iid = _iid(key)
        if not self._tree.exists(iid):
            return
        values = list(self._tree.item(iid, "values"))
        if len(values) == 4:
            values[2] = "⟳ traduciendo…" if running else values[2]
            self._tree.item(iid, values=values)

    def select(self, key: RowKey) -> None:
        iid = _iid(key)
        if not self._tree.exists(iid):
            return
        try:
            self._tree.selection_set(iid)
            self._tree.see(iid)
        except Exception:
            pass

    def selected_key(self) -> RowKey | None:
        selection = self._tree.selection()
        if not selection:
            return None
        return _key(selection[0])

    # ------------------------------------------------------------------
    # Inline editing
    # ------------------------------------------------------------------

    def _on_tree_select(self, _event: object) -> None:
        key = self.selected_key()
        if key is not None and self._on_select is not None:
            try:
                self._on_select(*key)
            except Exception as exc:
                log.exception("Error en on_select: %s", exc)

    def _on_double_click(self, event: tk.Event) -> None:
        region = self._tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        column = self._tree.identify_column(event.x)
        name = {"#2": "ocr", "#3": "trans"}.get(column)
        if name is None:
            return
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        self._open_editor(_key(iid), name)

    def _edit_selected(self, column: str) -> None:
        key = self.selected_key()
        if key is not None:
            self._open_editor(key, column)

    def _open_editor(self, key: RowKey, column: str) -> None:
        """Place an entry exactly over the cell being edited."""
        self._cancel_editor()
        iid = _iid(key)
        if not self._tree.exists(iid):
            return
        column_id = "#2" if column == "ocr" else "#3"
        bbox = self._tree.bbox(iid, column_id)
        if not bbox:
            self._tree.see(iid)
            bbox = self._tree.bbox(iid, column_id)
            if not bbox:
                return
        x, y, width, height = bbox
        page, mark_id = key
        store = self._stores[page]
        if column == "ocr":
            entry_obj = store.get_ocr(mark_id)
        else:
            entry_obj = store.get_translation(mark_id)
        current = entry_obj.text if entry_obj is not None else ""

        editor = theme.entry(self._tree, bg=COLOR_BG)
        editor.insert(0, current)
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        editor.select_range(0, tk.END)
        editor.bind("<Return>", lambda _e: self._commit_editor())
        editor.bind("<Escape>", lambda _e: self._cancel_editor())
        editor.bind("<Tab>", self._commit_and_advance)
        editor.bind("<FocusOut>", lambda _e: self._commit_editor())
        self._editor = editor
        self._editor_key = key
        self._editor_column = column

    def _commit_editor(self) -> str:
        if self._editor is None or self._editor_key is None:
            return ""
        text = self._editor.get().strip()
        key, column = self._editor_key, self._editor_column
        self._cancel_editor()
        page, mark_id = key
        try:
            if column == "ocr":
                if self._on_ocr_edited is not None:
                    self._on_ocr_edited(page, mark_id, text)
            else:
                self._on_translation_edited(page, mark_id, text)
        except Exception as exc:
            log.exception("Error guardando la celda: %s", exc)
        return "break"

    def _commit_and_advance(self, _event: object) -> str:
        key, column = self._editor_key, self._editor_column
        self._commit_editor()
        if key is None:
            return "break"
        if column == "ocr":
            self._open_editor(key, "trans")
            return "break"
        # Last cell of the row: jump to the OCR cell of the next one.
        iid = self._tree.next(_iid(key))
        if iid:
            self.select(_key(iid))
            self._open_editor(_key(iid), "ocr")
        return "break"

    def _cancel_editor(self) -> None:
        if self._editor is not None:
            try:
                self._editor.destroy()
            except Exception:
                pass
        self._editor = None
        self._editor_key = None
        self._editor_column = None

    # ------------------------------------------------------------------
    # Row actions
    # ------------------------------------------------------------------

    def retranslate_selected(self) -> None:
        key = self.selected_key()
        if key is None:
            return
        try:
            self._on_translate_row(*key)
        except Exception as exc:
            log.exception("Error en on_translate_row: %s", exc)

    def _delete_selected(self) -> None:
        key = self.selected_key()
        if key is None:
            return
        try:
            self._on_translation_deleted(*key)
        except Exception as exc:
            log.exception("Error en on_translation_deleted: %s", exc)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _iid(key: RowKey) -> str:
    return f"{key[0]}:{key[1]}"


def _key(iid: str) -> RowKey:
    page, mark = iid.split(":")
    return int(page), int(mark)


def _confidence_label(confidence: int) -> str:
    if confidence <= 0:
        return "—"
    if confidence >= CONFIDENCE_HIGH:
        band = "alta"
    elif confidence >= CONFIDENCE_LOW:
        band = "media"
    else:
        band = "baja"
    return f"{confidence}   {band}"


def _truncate(text: str) -> str:
    text = " ".join((text or "").split())
    if len(text) > PREVIEW_LEN:
        return text[: PREVIEW_LEN - 1] + "…"
    return text
