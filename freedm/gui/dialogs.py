# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Part of the App class: The dialogs: the ones that act on a job and the ones that change the settings."""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from freedm.categories import (default_rules, export_queue,
                             format_rules, import_queue, load_rules,
                             parse_rules)
from freedm.control_server import export_extension, token_path
from freedm.engine import (Download, human_size, human_speed,
                         human_time, global_speed_limit, QUEUED)
from freedm.gui.constants import APP_NAME, EXECUTABLE_EXTENSIONS
from freedm.network import PROXY
from freedm.settings import save as save_settings
from freedm.verify import (ALGORITHMS, cleanup_orphans,
                         find_orphans, parse_checksum)
from freedm import logsetup, native_host, update


class DialogsMixin:
    """The dialogs: the ones that act on a job and the ones that change the settings."""

    def categories_dialog(self) -> None:
        """Edit the category rules (one category per line)."""
        win = tk.Toplevel(self.root)
        win.title("Categories")
        win.geometry("560x400")
        win.transient(self.root)

        ttk.Label(
            win,
            text=("One category per line:  Name: .ext, .ext\n"
                  "Files are saved into a subfolder named after the category\n"
                  "when 'Sort into category folders' is ticked.\n"
                  "Anything that matches no rule goes to 'Other'."),
            justify="left",
        ).pack(anchor="w", padx=12, pady=(8, 4))

        text = tk.Text(win, height=14, wrap="none")
        text.pack(fill="both", expand=True, padx=12)
        text.insert("1.0", format_rules(self.category_rules))

        status = ttk.Label(win, text="", foreground="#a00")
        status.pack(anchor="w", padx=12, pady=(4, 0))

        btns = ttk.Frame(win, padding=(12, 4, 12, 12))
        btns.pack(fill="x")

        def apply() -> None:
            rules, errors = parse_rules(text.get("1.0", "end"))
            if errors:
                status.configure(text="; ".join(errors[:3]))
                return
            self.category_rules = rules
            save_settings(self.store, category_rules=format_rules(rules))
            status.configure(text="Saved.")
            self._notify_status(f"{len(rules)} categories saved")

        ttk.Button(btns, text="Save", command=apply).pack(side="right", padx=(4, 0))
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Restore defaults", command=lambda: (
            text.delete("1.0", "end"),
            text.insert("1.0", format_rules(default_rules())))).pack(side="left")

    def export_queue_dialog(self) -> None:
        """Write the current queue to a file."""
        path = filedialog.asksaveasfilename(
            title="Export the queue",
            defaultextension=".json",
            initialfile="freedm-queue.json",
            filetypes=[("FreeDM queue", "*.json"), ("All files", "*.*")],
            parent=self.root)
        if not path:
            return
        jobs = []
        for dl in self.downloads:
            jobs.append({
                "url": dl.url,
                "filename": dl.filename,
                "dest_dir": dl.dest_dir,
                "threads": dl.num_threads,
                "checksum": dl.checksum,
            })
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(export_queue(jobs))
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not write the file:\n{exc}")
            return
        self.status_var.set(f"Exported {len(jobs)} job(s) to {path}")

    def import_queue_dialog(self) -> None:
        """Read jobs from a file (exported queue or a list of URLs)."""
        path = filedialog.askopenfilename(
            title="Import a queue",
            filetypes=[("FreeDM queue", "*.json"), ("Text files", "*.txt"),
                       ("All files", "*.*")],
            parent=self.root)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not read the file:\n{exc}")
            return
        jobs, errors = import_queue(text)
        if errors:
            messagebox.showwarning(
                APP_NAME,
                "Some entries were skipped:\n" + "\n".join(errors[:5]))
        if not jobs:
            return
        added = 0
        for job in jobs:
            url = job.get("url")
            if not url:
                continue
            try:
                self._new_download(
                    url,
                    filename=job.get("filename"),
                    dest_dir=job.get("dest_dir") or self.dir_var.get().strip(),
                    num_threads=job.get("threads"),
                    checksum=job.get("checksum") or "",
                )
                added += 1
            except Exception:       # noqa: BLE001
                continue
        self.status_var.set(f"Imported {added} job(s) from {os.path.basename(path)}")

    def show_in_folder(self) -> None:
        """Open the containing folder and select the file (Windows)."""
        sel = self._selected()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a download first.")
            return
        for dl in sel:
            path = dl.path
            if not path or not os.path.exists(path):
                path = os.path.join(dl.dest_dir, dl.filename or "")
            if not path:
                continue
            folder = os.path.dirname(path)
            if sys.platform.startswith("win") and os.path.exists(path):
                try:
                    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
                    return
                except OSError:
                    pass
            if folder and os.path.isdir(folder):
                self._open(folder)
                return

    def schedule_dialog(self) -> None:
        """Set the start time of the selected job(s)."""
        selection = self._selected()
        if not selection:
            messagebox.showinfo(APP_NAME, "Select a download first.")
            return
        win = tk.Toplevel(self.root)
        win.title("Schedule download")
        win.geometry("480x260")
        win.transient(self.root)
        pad = {"padx": 12, "pady": 6}

        ttk.Label(
            win,
            text=("Choose when the selected job(s) should start.\n"
                  "A time in the future keeps them waiting; the schedule is\n"
                  "saved, so it survives a restart."),
            justify="left",
        ).pack(anchor="w", **pad)

        row = ttk.Frame(win)
        row.pack(fill="x", padx=12)
        ttk.Label(row, text="Date:").pack(side="left")
        now = datetime.datetime.now()
        date_var = tk.StringVar(value=now.strftime("%Y-%m-%d"))
        ttk.Entry(row, textvariable=date_var, width=14).pack(
            side="left", padx=(4, 12))
        ttk.Label(row, text="Time:").pack(side="left")
        time_var = tk.StringVar(value=now.strftime("%H:%M"))
        ttk.Entry(row, textvariable=time_var, width=8).pack(side="left", padx=(4, 0))

        info = ttk.Label(win, text="", foreground="#a00")
        info.pack(anchor="w", padx=12)

        btns = ttk.Frame(win, padding=(12, 6, 12, 12))
        btns.pack(fill="x")

        def apply(when: float | None) -> None:
            for dl in selection:
                dl.set_start_at(when)
                if when is None:
                    dl.status = QUEUED
                self.scheduler.submit(dl)
            win.destroy()
            if when is None:
                self.status_var.set(
                    f"Schedule cleared for {len(selection)} job(s)")
            else:
                self.status_var.set(
                    f"{len(selection)} job(s) scheduled for "
                    + datetime.datetime.fromtimestamp(when).strftime("%d %b %H:%M"))

        def apply_typed() -> None:
            try:
                date = datetime.datetime.strptime(
                    date_var.get().strip(), "%Y-%m-%d")
            except ValueError:
                info.configure(text="The date must look like 2026-10-19.")
                return
            try:
                clock = datetime.datetime.strptime(
                    time_var.get().strip(), "%H:%M")
            except ValueError:
                info.configure(text="The time must look like 02:30.")
                return
            when = date.replace(hour=clock.hour, minute=clock.minute,
                                second=0, microsecond=0)
            stamp = when.timestamp()
            if stamp <= time.time():
                info.configure(text="That moment is in the past.")
                return
            apply(stamp)

        ttk.Button(btns, text="Schedule", command=apply_typed).pack(
            side="right", padx=(4, 0))
        ttk.Button(btns, text="Start now", command=lambda: apply(None)).pack(
            side="right")
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")

    def about_dialog(self) -> None:
        """Version, licence and the optional update check / log file."""
        from freedm.version import version_info, version_text
        info = version_info()
        win = tk.Toplevel(self.root)
        win.title("About FreeDM")
        win.geometry("520x340")
        win.transient(self.root)
        pad = {"padx": 12, "pady": 6}

        ttk.Label(win, text=info["app"], font=("", 13, "bold")).pack(
            anchor="w", **pad)
        ttk.Label(win, text=f"Version {info['version']}").pack(anchor="w", **pad)
        ttk.Label(
            win,
            text=("A free, source-available download manager.\n"
                  f"Licensed under the {info['license']}:\n"
                  "noncommercial use, modification and redistribution."),
            justify="left",
        ).pack(anchor="w", **pad)
        ttk.Label(win, text=f"Settings and queue: {info['settings']}",
                  foreground="#555").pack(anchor="w", **pad)

        ttk.Checkbutton(
            win, text="Write a log file (for bug reports)",
            variable=self.log_var, command=self._toggle_log).pack(
                anchor="w", padx=12, pady=(8, 0))
        ttk.Label(win, text=f"Log file: {logsetup.log_path()}",
                  foreground="#555").pack(anchor="w", padx=32)

        status = ttk.Label(win, text="", foreground="#555")
        status.pack(anchor="w", padx=12, pady=(6, 0))

        btns = ttk.Frame(win, padding=(12, 6, 12, 12))
        btns.pack(fill="x")

        def check() -> None:
            status.configure(text="Checking...")
            win.update_idletasks()
            newer, message = update.check_for_update(info["version"])
            status.configure(text=message)
            if newer:
                self._notify_status("A newer FreeDM is available")

        ttk.Button(btns, text="Check for updates", command=check).pack(
            side="left")
        ttk.Button(btns, text="Open the log folder",
                   command=lambda: self._open(os.path.dirname(
                       logsetup.log_path()))).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")

    def network_dialog(self) -> None:
        """Proxy settings, address-family preference and a connection check."""
        win = tk.Toplevel(self.root)
        win.title("Network options")
        win.geometry("560x420")
        win.transient(self.root)
        pad = {"padx": 12, "pady": 6}

        ttk.Label(
            win,
            text=("Route every download through a proxy (HTTP or SOCKS).\n"
                  "Leave the address empty to connect directly."),
            justify="left",
        ).pack(anchor="w", **pad)

        grid = ttk.Frame(win)
        grid.pack(fill="x", padx=12)

        url_var = tk.StringVar(value=self.proxy_url)
        user_var = tk.StringVar(value=self.proxy_user)
        pass_var = tk.StringVar(value=self.proxy_pass)
        bypass_var = tk.StringVar(value=self.proxy_bypass)
        ipv4_var = tk.BooleanVar(value=self.prefer_ipv4)
        private_var = tk.BooleanVar(value=self.allow_private_segments)

        rows = (
            ("Proxy:", url_var),
            ("User:", user_var),
            ("Password:", pass_var),
            ("Bypass:", bypass_var),
        )
        for index, (label, var) in enumerate(rows):
            ttk.Label(grid, text=label).grid(row=index, column=0, sticky="w",
                                             pady=3)
            entry = ttk.Entry(grid, textvariable=var, width=42)
            if label == "Password:":
                entry.configure(show="*")
            entry.grid(row=index, column=1, sticky="ew", pady=3)
        grid.columnconfigure(1, weight=1)

        ttk.Label(
            win,
            text=("Bypass: comma separated hosts that must be reached "
                  "directly (e.g. localhost, 127.0.0.1, *.internal)"),
        ).pack(anchor="w", padx=12)
        ttk.Checkbutton(
            win, text="Prefer IPv4 when a host has both (a broken IPv6 route "
                      "is a common cause of hangs)",
            variable=ipv4_var).pack(anchor="w", padx=12, pady=(6, 0))
        ttk.Checkbutton(
            win, text="Allow segments from private addresses "
                      "(a stream on your own network)",
            variable=private_var).pack(anchor="w", padx=12)

        status = ttk.Label(win, text="", foreground="#a00")
        status.pack(anchor="w", padx=12, pady=(4, 0))

        btns = ttk.Frame(win, padding=(12, 6, 12, 12))
        btns.pack(fill="x")

        def save() -> None:
            self.proxy_url = url_var.get().strip()
            self.proxy_user = user_var.get().strip()
            self.proxy_pass = pass_var.get()
            self.proxy_bypass = bypass_var.get().strip()
            self.prefer_ipv4 = ipv4_var.get()
            self.allow_private_segments = private_var.get()
            self._apply_network_settings()
            save_settings(self.store, proxy_url=self.proxy_url,
                          proxy_user=self.proxy_user, proxy_pass=self.proxy_pass,
                          proxy_bypass=self.proxy_bypass,
                          prefer_ipv4=self.prefer_ipv4,
                          allow_private_segments=self.allow_private_segments)
            status.configure(text="Saved. " + PROXY.summary(), foreground="#080")
            self._notify_status("Network settings saved")

        def test() -> None:
            self.proxy_url = url_var.get().strip()
            self.proxy_user = user_var.get().strip()
            self.proxy_pass = pass_var.get()
            self.proxy_bypass = bypass_var.get().strip()
            self._apply_network_settings()
            result = self._check_connection()
            status.configure(text=result, foreground="#a00" if "failed" in result
                             else "#080")

        ttk.Button(btns, text="Save", command=save).pack(side="right", padx=(4, 0))
        ttk.Button(btns, text="Test connection", command=test).pack(side="right")
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")

    def mirrors_dialog(self) -> None:
        """Set alternative sources (mirror base URLs) for the selected job."""
        selection = self._selected()
        if not selection:
            messagebox.showinfo(APP_NAME, "Select a download first.")
            return
        win = tk.Toplevel(self.root)
        win.title("Mirrors")
        win.geometry("560x360")
        win.transient(self.root)

        ttk.Label(
            win,
            text=("Alternative sources for the same file, one per line.\n"
                  "A mirror is a base URL; the path of the original file is\n"
                  "appended to it, so https://mirror.example/files/x.zip\n"
                  "is fetched from https://mirror.example/files/x.zip.\n"
                  "The mirror must serve the identical file."),
            justify="left",
        ).pack(anchor="w", padx=12, pady=(8, 4))

        text = tk.Text(win, height=8, wrap="none")
        text.pack(fill="both", expand=True, padx=12)
        existing = list(selection[0].mirrors or [])
        if existing:
            text.insert("1.0", "\n".join(existing))

        btns = ttk.Frame(win, padding=(12, 6, 12, 12))
        btns.pack(fill="x")

        def apply() -> None:
            lines = [line.strip() for line in text.get("1.0", "end").splitlines()
                     if line.strip()]
            for dl in selection:
                dl.set_mirrors(lines)
            win.destroy()
            self.status_var.set(
                f"{len(lines)} mirror(s) set for {len(selection)} job(s)")

        ttk.Button(btns, text="Save", command=apply).pack(side="right", padx=(4, 0))
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")

    def checksum_dialog(self) -> None:
        """Set the expected checksum for the selection (and for new downloads)."""
        win = tk.Toplevel(self.root)
        win.title("Checksum verification")
        win.geometry("560x260")
        win.transient(self.root)
        pad = {"padx": 12, "pady": 6}

        ttk.Label(
            win,
            text=("Paste the digest published by the site.\n"
                  "Format: <algorithm>:<hex>   (e.g. sha256:1a2b...)\n"
                  "A bare 64-character hex digest is treated as sha256.\n\n"
                  "The file is hashed when the download finishes; a mismatch\n"
                  "marks the job as failed and shows both digests."),
            justify="left",
        ).pack(anchor="w", **pad)

        row = ttk.Frame(win)
        row.pack(fill="x", padx=12)
        ttk.Label(row, text="Algorithm:").pack(side="left")
        algo_var = tk.StringVar(value="sha256")
        ttk.Combobox(row, textvariable=algo_var, state="readonly", width=10,
                     values=sorted(ALGORITHMS)).pack(side="left", padx=(4, 12))
        ttk.Label(row, text="Digest:").pack(side="left")
        digest_var = tk.StringVar()
        ttk.Entry(row, textvariable=digest_var).pack(
            side="left", fill="x", expand=True, padx=(4, 0))

        btns = ttk.Frame(win, padding=(12, 6, 12, 12))
        btns.pack(fill="x")

        def apply() -> None:
            algo = algo_var.get().strip().lower()
            digest = digest_var.get().strip()
            spec = f"{algo}:{digest}" if digest else ""
            try:
                parse_checksum(spec)
            except ValueError as exc:
                messagebox.showerror(APP_NAME, str(exc), parent=win)
                return
            self.default_checksum = spec
            save_settings(self.store, default_checksum=spec)
            applied = 0
            for dl in self._selected():
                ok, message = dl.set_checksum(spec)
                if not ok:
                    messagebox.showerror(APP_NAME, message, parent=win)
                    return
                applied += 1
            win.destroy()
            self.status_var.set(
                f"Checksum set ({spec or 'cleared'}) for {applied} job(s) "
                "and new downloads")

        ttk.Button(btns, text="Apply", command=apply).pack(side="right", padx=(4, 0))
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Clear",
                   command=lambda: digest_var.set("")).pack(side="left")

    def cleanup_dialog(self) -> None:
        """Find and delete abandoned .part / resume files (N3)."""
        win = tk.Toplevel(self.root)
        win.title("Clean up leftovers")
        win.geometry("640x460")
        win.transient(self.root)
        pad = {"padx": 12, "pady": 6}

        ttk.Label(
            win,
            text=("Finds abandoned .part and .part.state.json files left behind\n"
                  "by downloads you gave up on, and deletes them.\n"
                  "Only files older than the given age are listed, so running\n"
                  "downloads are never touched."),
            justify="left",
        ).pack(anchor="w", **pad)

        row = ttk.Frame(win)
        row.pack(fill="x", padx=12)
        ttk.Label(row, text="Folder:").pack(side="left")
        folder_var = tk.StringVar(value=self.dir_var.get().strip() or os.getcwd())
        ttk.Entry(row, textvariable=folder_var).pack(
            side="left", fill="x", expand=True, padx=(4, 8))
        ttk.Label(row, text="Older than (days):").pack(side="left")
        days_var = tk.IntVar(value=self.cleanup_days or 30)
        ttk.Spinbox(row, from_=0, to=3650, width=6,
                    textvariable=days_var).pack(side="left", padx=(4, 0))

        listing = tk.Listbox(win, height=14, selectmode="extended")
        listing.pack(fill="both", expand=True, padx=12, pady=(8, 0))

        btns = ttk.Frame(win, padding=(12, 6, 12, 12))
        btns.pack(fill="x")
        found: list[str] = []

        def scan() -> None:
            listing.delete(0, "end")
            found.clear()
            try:
                days = int(days_var.get())
            except (tk.TclError, ValueError):
                days = 30
            if days <= 0:
                messagebox.showinfo(
                    APP_NAME, "Set an age greater than 0 to scan.", parent=win)
                return
            found.extend(find_orphans(folder_var.get().strip(), days))
            for path in found:
                listing.insert("end", path)
            self.status_var.set(f"Cleanup scan: {len(found)} leftover file(s)")

        def delete() -> None:
            chosen = [listing.get(i) for i in listing.curselection()]
            if not chosen:
                messagebox.showinfo(APP_NAME, "Select files to delete.",
                                    parent=win)
                return
            if not messagebox.askyesno(
                    APP_NAME,
                    f"Delete {len(chosen)} file(s)?\n"
                    "Partial downloads that are still needed cannot be resumed.",
                    parent=win):
                return
            deleted, failed = cleanup_orphans(chosen)
            for path, reason in failed:
                messagebox.showerror(APP_NAME, f"Could not delete:\n{path}\n{reason}",
                                     parent=win)
            scan()
            self.status_var.set(f"Cleanup: deleted {deleted} file(s)")

        ttk.Button(btns, text="Scan", command=scan).pack(side="left")
        ttk.Button(btns, text="Delete Selected", command=delete).pack(
            side="right", padx=(4, 0))
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")

    def show_details(self) -> None:
        """Show the full, untruncated state of the selected job."""
        sel = self._selected()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a download first.")
            return
        dl = sel[0]
        s = dl.snapshot()

        def fmt_count(n: int) -> str:
            return f"{n:,}"

        lines = [
            f"File:        {s['name']}",
            f"Status:      {s['status']}",
            f"URL:         {s['url']}",
        ]
        if s["final_url"] and s["final_url"] != s["url"]:
            lines.append(f"Final URL:   {s['final_url']}")
        lines += [
            f"Destination: {s['dir']}",
            f"Path:        {s['path'] or '-'}",
            f"Size:        {human_size(s['size']) if s['size'] else 'unknown'}"
            f"  ({fmt_count(s['size'])} bytes)",
            f"Downloaded:  {human_size(s['downloaded'])}"
            f"  ({s['progress'] * 100:5.1f}%)",
            f"Threads:     {s['threads']}",
            f"Limit:       "
            + (f"{s['speed_limit'] / 1024:g} KB/s" if s["speed_limit"] else "none"),
            f"Global cap:  "
            + (f"{global_speed_limit() / 1024:g} KB/s for all downloads"
               if global_speed_limit() else "none"),
        ]
        if s.get("pieces") is not None:
            lines.append(
                f"Pieces:      {s['pieces']} "
                f"({s.get('splits', 0)} split dynamically)")
        if s.get("checksum"):
            lines.append(f"Checksum:    {s['checksum']}")
            if s.get("checksum_result"):
                lines.append(f"Verified:    {s['checksum_result']}")
        if s["error"]:
            lines.append("")
            lines.append(f"Error:       {s['error']}")
        messagebox.showinfo(f"{APP_NAME} - details", "\n".join(lines))

    def _edit_headers(self) -> None:
        """Dialog for per-download headers (Referer, Cookie, Authorization...)."""
        win = tk.Toplevel(self.root)
        win.title("Custom request headers")
        win.geometry("520x320")
        win.transient(self.root)
        ttk.Label(
            win,
            text=("One header per line, e.g.  Referer: https://example.com/\n"
                  "Cookie: auth=secret   |   Authorization: Bearer ..."),
            padding=(8, 8, 8, 4),
        ).pack(anchor="w")
        text = tk.Text(win, height=12, wrap="none")
        text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        text.insert("1.0", "\n".join(f"{k}: {v}" for k, v in self.extra_headers.items()))
        btns = ttk.Frame(win, padding=(8, 0, 8, 8))
        btns.pack(fill="x")

        def apply() -> None:
            parsed: dict[str, str] = {}
            for line in text.get("1.0", "end").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                if key.strip():
                    parsed[key.strip()] = value.strip()
            self.extra_headers = parsed
            self.status_var.set(f"{len(parsed)} custom header(s) active")
            win.destroy()

        ttk.Button(btns, text="Apply", command=apply).pack(side="right", padx=(4, 0))
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Clear",
                   command=lambda: text.delete("1.0", "end")).pack(side="left")

    def _browser_dialog(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Browser handoff")
        win.transient(self.root)
        win.geometry("560x430")
        pad = {"padx": 12, "pady": 6}

        if self.control is not None and self.control.running:
            state = f"running on 127.0.0.1:{self.control.port}"
        elif self.control is not None and self.control.last_error:
            state = f"unavailable ({self.control.last_error})"
        else:
            state = "stopped"
        ttk.Label(win, text=f"Control server: {state}",
                  font=("", 10, "bold")).pack(anchor="w", **pad)
        ttk.Checkbutton(win, text="Accept downloads from the browser",
                        variable=self.browser_enabled_var,
                        command=self._toggle_control).pack(anchor="w", **pad)

        ttk.Label(win, text="Token (paste into the extension's options):").pack(
            anchor="w", padx=12)
        row = ttk.Frame(win)
        row.pack(fill="x", padx=12, pady=(0, 6))
        token = self.control.token if self.control is not None else ""
        tok_var = tk.StringVar(value=token)
        entry = ttk.Entry(row, textvariable=tok_var, state="readonly")
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Copy", command=self._copy_token).pack(
            side="left", padx=(6, 0))

        ttk.Button(win, text="Export extension...",
                   command=self._export_extension).pack(anchor="w", **pad)
        row = ttk.Frame(win)
        row.pack(anchor="w", padx=12)
        ttk.Button(row, text="Export for Firefox...",
                   command=lambda: self._export_extension("firefox")
                   ).pack(side="left")
        ttk.Button(row, text="Install native host",
                   command=self._install_native_host).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Remove native host",
                   command=self._uninstall_native_host).pack(side="left", padx=(8, 0))

        native_state = ("installed" if native_host.is_installed()
                        else "not installed")
        ttk.Label(win, text=f"Native host (lets the browser start FreeDM): "
                            f"{native_state}").pack(anchor="w", padx=12)

        help_text = (
            "1. Click Export extension and load the folder via\n"
            "   chrome://extensions  >  Developer mode  >  Load unpacked.\n"
            "2. Open the extension's Options, paste the token above, Save.\n"
            "3. Keep FreeDM running; browser downloads are handed over\n"
            "   and the browser's own copy is cancelled.\n\n"
            "If FreeDM is closed, downloads stay in the browser as usual.\n"
            "Token file: " + token_path()
        )
        msg = ttk.Label(win, text=help_text, justify="left", wraplength=520)
        msg.pack(anchor="w", **pad)
