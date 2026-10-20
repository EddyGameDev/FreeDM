# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Part of the App class: The browser handoff: the control server, the extension and the native messaging host."""
from __future__ import annotations

import os
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk

from freedm.settings import save as save_settings

from freedm.control_server import (ControlServer, export_extension,
                                  token_path)
from freedm.engine import Download
from freedm.gui.constants import APP_NAME
from freedm import native_host


class BrowserMixin:
    """The browser handoff: the control server, the extension and the native messaging host."""

    def _start_control(self) -> bool:
        try:
            ctrl = ControlServer(on_add=self._incoming.put)
            if ctrl.start():
                self.control = ctrl
                return True
            self._notify_status(f"Browser handoff unavailable: {ctrl.last_error}")
        except Exception as exc:       # noqa: BLE001
            self._notify_status(f"Browser handoff unavailable: {exc}")
        self.control = None
        return False

    def _toggle_control(self) -> None:
        if self.browser_enabled_var.get():
            self._start_control()
        elif self.control is not None:
            self.control.stop()
            self.control = None
        if self.store is not None:
            save_settings(
                self.store,
                control_enabled=self.browser_enabled_var.get())

    def _copy_token(self) -> None:
        if self.control is None:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.control.token)
        messagebox.showinfo(APP_NAME, "Token copied to the clipboard.")

    def _export_extension(self, browser: str = "chrome") -> None:
        try:
            dest = export_extension(browser=browser)
        except Exception as exc:       # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Could not export the extension: {exc}")
            return
        if browser == "firefox":
            how = ("about:debugging#/runtime/this-firefox > Load Temporary "
                   "Add-on... and pick that folder")
        else:
            how = ("chrome://extensions > Developer mode > Load unpacked "
                   "and pick that folder")
        messagebox.showinfo(
            APP_NAME,
            "Extension exported to:\n" + dest
            + f"\n\nTo install it in {browser.capitalize()}: {how}")
        self._open(dest)

    def _install_native_host(self) -> None:
        """Register the native messaging host so the extension can start us."""
        origins = native_host.extension_origins(self.extension_id)
        try:
            ok, message = native_host.install_host(origins)
        except Exception as exc:       # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Could not install: {exc}")
            return
        if ok:
            messagebox.showinfo(
                APP_NAME,
                "Native host installed.\n\n" + message +
                "\n\nNow the extension can start FreeDM by itself when a "
                "download is handed over while the app is closed.")
        else:
            messagebox.showwarning(APP_NAME, message)

    def _uninstall_native_host(self) -> None:
        try:
            ok, message = native_host.uninstall_host()
        except Exception as exc:       # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Could not remove: {exc}")
            return
        messagebox.showinfo(
            APP_NAME, message if ok else
            "Nothing to remove.\n\n" + message)

    def _add_from_browser(self, payload: dict) -> None:
        """Create a download from a validated extension payload (main thread)."""
        url = payload.get("url") or ""
        extension_id = payload.get("extension_id") or ""
        if extension_id and extension_id != self.extension_id:
            # N11: the extension tells us its id, so the native host can be
            # registered for that extension only.
            self.extension_id = extension_id
            save_settings(self.store, extension_id=extension_id)
        headers = dict(payload.get("headers") or {})
        if payload.get("referer"):
            headers.setdefault("Referer", payload["referer"])
        if payload.get("user_agent"):
            headers.setdefault("User-Agent", payload["user_agent"])
        dest = payload.get("dest_dir") or self.dir_var.get().strip() or os.getcwd()
        dl = Download(
            url, dest_dir=dest, filename=payload.get("filename"),
            num_threads=payload.get("threads") or self.threads_var.get(),
            headers=headers, cookies=payload.get("cookies"),
            speed_limit=self.default_limit, checksum=self.default_checksum,
            dest_resolver=self._dest_resolver(),
            allow_private_segments=self.allow_private_segments, store=self.store)
        self._enqueue(dl)
        self.status_var.set(f"Browser: {url}")
