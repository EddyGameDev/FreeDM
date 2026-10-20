# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Part of the App class: The automatic parts: the daily window, the shut-down when the queue drains, the categories and the network settings."""
from __future__ import annotations

import os
import subprocess
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from freedm.engine import (DOWNLOADING, PAUSED, PROBING, QUEUED,
                         SCHEDULED, global_speed_limit,
                         set_global_speed_limit)
from freedm.settings import save as save_settings

from freedm.automation import (describe_schedule, format_time,
                           in_window, parse_time, shutdown_command,
                           SHUTDOWN, SLEEP)
from freedm.categories import (default_rules, destination_for,
                             format_rules, load_rules, parse_rules)
from freedm.engine import Download, human_speed
from freedm.gui.constants import APP_NAME
from freedm.network import PROXY, install_address_preference
from freedm import logsetup, update
from freedm.version import version_info


class AutomationMixin:
    """The automatic parts: the daily window, the shut-down when the queue drains, the categories and the network settings."""

    def _apply_window(self) -> None:
        """Set the daily window in which downloads may start."""
        start = parse_time(self.window_start_var.get())
        end = parse_time(self.window_end_var.get())
        raw_start = self.window_start_var.get().strip()
        raw_end = self.window_end_var.get().strip()
        if raw_start and start is None:
            messagebox.showerror(APP_NAME, f"Bad start time: {raw_start!r}")
            return
        if raw_end and end is None:
            messagebox.showerror(APP_NAME, f"Bad end time: {raw_end!r}")
            return
        self.window_start = start
        self.window_end = end
        self.scheduler.set_window(start, end)
        save_settings(self.store, window_start=raw_start, window_end=raw_end)
        self.status_var.set("Download window: " + self.scheduler.window_status())

    def _toggle_shutdown(self) -> None:
        self.shutdown_when_done = self.shutdown_var.get()
        save_settings(self.store, shutdown_when_done=self.shutdown_when_done)
        self._shutdown_armed = False
        self.status_var.set(
            "Shut down when done: "
            + ("on" if self.shutdown_when_done else "off"))

    def _queue_is_empty(self) -> bool:
        """True when nothing is running, queued, scheduled or waiting."""
        for dl in self.downloads:
            if dl.status in (DOWNLOADING, PROBING, QUEUED, SCHEDULED, PAUSED):
                return False
        return True

    def _check_shutdown_when_done(self) -> None:
        """Ask the user, then power off - only when the queue is really empty."""
        if not self.shutdown_when_done or self._shutdown_armed:
            return
        if not self._queue_is_empty():
            return
        self._shutdown_armed = True
        verb = "shut down" if self.shutdown_mode != SLEEP else "sleep"
        if not messagebox.askyesno(
                APP_NAME,
                f"All downloads are finished.\n\nShut the computer {verb} now?",
                icon="question"):
            self.shutdown_when_done = False
            self.shutdown_var.set(False)
            save_settings(self.store, shutdown_when_done=False)
            return
        command = shutdown_command(self.shutdown_mode)
        if not command:
            messagebox.showerror(
                APP_NAME, "This platform has no supported power command.")
            return
        try:
            subprocess.Popen(command)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not {verb}: {exc}")

    def _apply_network_settings(self) -> None:
        """Push the proxy / address settings into the shared configuration."""
        PROXY.configure(self.proxy_url, self.proxy_user, self.proxy_pass,
                        self.proxy_bypass)
        install_address_preference(self.prefer_ipv4)

    def _check_connection(self) -> str:
        """Make a small request through the current settings and report."""
        import requests
        url = "https://api.github.com/" if self.proxy_url else \
            "https://www.gstatic.com/generate_204"
        try:
            response = requests.get(url, timeout=15, proxies=PROXY.proxies(),
                                    headers={"User-Agent": "FreeDM/1.0"})
        except Exception as exc:      # noqa: BLE001
            return f"Connection failed: {exc}"
        if response.status_code < 400:
            return f"Connection OK (HTTP {response.status_code}) via {PROXY.summary()}"
        return f"Connection failed: HTTP {response.status_code}"

    def _toggle_auto_sort(self) -> None:
        save_settings(self.store, auto_sort=self.auto_sort_var.get())
        self.status_var.set(
            "Sort into category folders: "
            + ("on" if self.auto_sort_var.get() else "off"))

    def _target_dir(self, filename: str) -> str:
        """Where a new download should go (category subfolder when enabled)."""
        base = self.dir_var.get().strip() or os.getcwd()
        if not self.auto_sort_var.get():
            return base
        return destination_for(filename or "", base, self.category_rules)

    def _dest_resolver(self):
        """A resolver that picks the category folder once the name is known."""
        if not self.auto_sort_var.get():
            return None
        base = self.dir_var.get().strip() or os.getcwd()
        rules = self.category_rules

        def resolve(filename: str) -> str:
            return destination_for(filename, base, rules)

        return resolve

    def _toggle_log(self) -> None:
        enabled = self.log_var.get()
        path = logsetup.enable(enabled)
        save_settings(self.store, log_enabled=enabled)
        self.status_var.set(
            f"Log file {'enabled' if enabled else 'disabled'}: {path}")

    def _kb_to_bytes(self, kb: float) -> float:
        return max(0.0, float(kb)) * 1024.0

    def limit_selected(self) -> None:
        """Set a live speed cap (KB/s) on the selection and as the new default."""
        current_kb = self.default_limit / 1024.0 if self.default_limit else 0
        answer = simpledialog.askstring(
            "Speed limit",
            "Limit each selected download to (KB/s).\n"
            "0 or empty = unlimited.\n\n"
            "The value is remembered as the default for new downloads.",
            initialvalue=f"{current_kb:g}", parent=self.root)
        if answer is None:
            return
        answer = answer.strip().replace(",", ".")
        try:
            kb = float(answer) if answer else 0.0
        except ValueError:
            messagebox.showerror(APP_NAME, f"Not a number: {answer!r}")
            return
        bps = self._kb_to_bytes(kb)
        self.default_limit = bps
        save_settings(self.store, speed_limit=bps)
        selected = self._selected()
        for dl in selected:
            try:
                dl.set_speed_limit(bps)
            except Exception:       # noqa: BLE001
                pass
        scope = f"{len(selected)} job(s)" if selected else "new downloads"
        if bps:
            self.status_var.set(f"Limit set to {kb:g} KB/s for {scope}")
        else:
            self.status_var.set(f"Speed limit removed for {scope}")

    def global_limit_dialog(self) -> None:
        """Cap the *combined* throughput of every download (N4)."""
        current_kb = self.global_limit / 1024.0 if self.global_limit else 0
        answer = simpledialog.askstring(
            "Global speed limit",
            "Cap the combined speed of ALL downloads (KB/s).\n"
            "0 or empty = unlimited.\n\n"
            "Every running and future download shares this budget.",
            initialvalue=f"{current_kb:g}", parent=self.root)
        if answer is None:
            return
        answer = answer.strip().replace(",", ".")
        try:
            kb = float(answer) if answer else 0.0
        except ValueError:
            messagebox.showerror(APP_NAME, f"Not a number: {answer!r}")
            return
        bps = self._kb_to_bytes(kb)
        self.global_limit = bps
        set_global_speed_limit(bps)
        save_settings(self.store, global_speed_limit=bps)
        if bps:
            self.status_var.set(
                f"Global limit: {kb:g} KB/s for all downloads")
        else:
            self.status_var.set("Global speed limit removed")
