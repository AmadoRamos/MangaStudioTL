"""Smoke checks for the two pieces of plumbing with no other coverage.

Run with: python test_smoke.py
"""

import tkinter as tk

from src.utils.background_worker import BackgroundWorker


def test_emit_dispatches_by_name(root: tk.Tk) -> None:
    """``_emit`` must call the attribute named at *dispatch* time."""
    seen: list[tuple] = []

    class Worker(BackgroundWorker):
        def __init__(self):
            super().__init__()
            self._on_done = None

    w = Worker()
    w.attach(root)
    w._emit("_on_done", 1, True, "listo")   # queued before the callback exists
    w._on_done = lambda *a: seen.append(a)
    w._poll()
    assert seen == [(1, True, "listo")], seen

    # A missing callback is dropped, not raised.
    w._emit("_on_nonexistent", 42)
    w._poll()
    assert seen == [(1, True, "listo")], seen

    # detach() drops what is still queued.
    w._emit("_on_done", 2, False, "tarde")
    w.detach()
    w._poll()
    assert seen == [(1, True, "listo")], seen


def test_drop_data_splitting(root: tk.Tk) -> None:
    """Tk's own list splitter replaces the hand-rolled brace parser."""
    data = "{D:/con espacio/0001.jpg} D:/simple.png {C:/a b/c d.jpeg}"
    assert [str(p) for p in root.tk.splitlist(data)] == [
        "D:/con espacio/0001.jpg",
        "D:/simple.png",
        "C:/a b/c d.jpeg",
    ]
    assert root.tk.splitlist("") == ()


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    try:
        test_emit_dispatches_by_name(root)
        test_drop_data_splitting(root)
    finally:
        root.destroy()
    print("OK")
