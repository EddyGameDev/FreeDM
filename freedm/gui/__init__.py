# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""The FreeDM graphical interface."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from freedm.store import JobStore
from freedm.gui.app import App
from freedm.gui.constants import APP_NAME, EXECUTABLE_EXTENSIONS


def run_gui() -> None:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    try:
        store = JobStore()
    except Exception:
        store = None
    App(root, store=store)
    root.mainloop()


__all__ = ["App", "run_gui", "APP_NAME", "EXECUTABLE_EXTENSIONS"]
