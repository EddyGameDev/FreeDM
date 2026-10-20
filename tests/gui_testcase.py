# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Shared base class for the FreeDM GUI tests.

A GUI test must never write into the user's real Downloads folder and must
never start a real download. :class:`GuiTestCase` enforces both:

- the app is pointed at a temporary folder, and
- the scheduler's ``pump`` is disabled, so jobs stay queued.

Use it like this::

    from gui_testcase import GuiTestCase

    class MyTests(GuiTestCase):
        def test_something(self):
            self.app.url_var.set("https://example.com/f.bin")
            self.app.add_download()
"""
from __future__ import annotations

import gc
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)
for _path in (_PROJECT, _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)


class GuiTestCase(unittest.TestCase):
    """A hidden Tk window wired to a temporary queue and download folder."""

    prefix = "freedm_gui_"

    def setUp(self) -> None:
        from freedm.store import JobStore
        from freedm import gui

        try:
            import tkinter as tk
        except ImportError as exc:
            # Python built without Tk (some CI images): skip, do not fail.
            self.skipTest(f"Tk is not available: {exc}")
        self.tk = tk
        self.tmp = tempfile.mkdtemp(prefix=self.prefix)
        self.store = JobStore(os.path.join(self.tmp, "q.db"))
        # No control server in tests: it would bind a real port.
        self.store.set_setting("control_enabled", "0")
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as exc:
            # No usable display (a headless CI box): skip, do not fail.
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.skipTest(f"no usable Tk display: {exc}")
        self.app = gui.App(self.root, store=self.store)
        # Safety: a test must never touch the user's Downloads folder and
        # must never start a real download.
        self.app.dir_var.set(self.tmp)
        self.app.scheduler.pump = lambda: None
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        for step in (self._stop_scheduler, self._destroy_root,
                     self._close_store, self._remove_temp):
            try:
                step()
            except Exception:       # noqa: BLE001 - cleanup must not fail
                pass

    def _stop_scheduler(self) -> None:
        # Stop the refresh timer first, so Tk does not fire a pending
        # callback while the window is being destroyed.
        handle = getattr(self.app, "_poll_handle", None)
        if handle:
            try:
                self.root.after_cancel(handle)
            except Exception:       # noqa: BLE001
                pass
        self.app.scheduler.shutdown()

    def _destroy_root(self) -> None:
        self.root.destroy()
        # Release the app (and its Tk variables) here, on the main thread.
        # A Tk Variable's finaliser calls into Tcl, which is not allowed
        # from a worker thread - and the objects would otherwise be freed
        # later, by whichever thread happened to collect them.
        self.app = None
        gc.collect()

    def _close_store(self) -> None:
        self.store.close()

    def _remove_temp(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_gui_tests_never_use_the_real_downloads_folder(self):
        """Guard: a GUI test must never write into the user's Downloads.

        The app is pointed at a temporary folder and the scheduler cannot
        start anything, so no ``.part`` file can appear next to the user's
        real downloads."""
        self.assertTrue(self.app.dir_var.get().startswith(self.tmp),
                        self.app.dir_var.get())
        self.assertNotEqual(self.app.dir_var.get(),
                            os.path.join(os.path.expanduser("~"), "Downloads"))
