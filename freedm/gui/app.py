# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""The FreeDM window."""
from __future__ import annotations

from __future__ import annotations
import os
import queue
import subprocess
import sys
import datetime
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import urlparse
from freedm.engine import (
    Download,
    human_size,
    human_speed,
    human_time,
    DONE,
    ERROR,
    CANCELED,
    PAUSED,
    DOWNLOADING,
    PROBING,
    IDLE,
    QUEUED,
    SCHEDULED,
    set_global_speed_limit,
    global_speed_limit,
)
from freedm.store import JobStore
from freedm.settings import load as load_settings, save as save_settings
from freedm.batch import parse_urls, find_url
from freedm.automation import (parse_time, format_time, in_window, describe_schedule,
                        seconds_until_epoch, shutdown_command, SHUTDOWN, SLEEP)
from freedm.categories import (default_rules, format_rules, load_rules, parse_rules,
                        classify, destination_for, matches_filter,
                        export_queue, import_queue, STATUS_FILTERS)
from freedm.network import PROXY, install_address_preference, address_preference
from freedm import native_host
from freedm import logsetup
from freedm import update
from freedm.verify import (ALGORITHMS, parse_checksum, find_orphans, cleanup_orphans)
from freedm.scheduler import Scheduler
from freedm.control_server import ControlServer, export_extension, token_path
from freedm.gui.automation import AutomationMixin
from freedm.gui.browser import BrowserMixin
from freedm.gui.constants import APP_NAME, EXECUTABLE_EXTENSIONS
from freedm.gui.dialogs import DialogsMixin


class App(AutomationMixin, BrowserMixin, DialogsMixin):
    """The main window."""

    def __init__(self, root: tk.Tk, store: JobStore | None = None):
        self.root = root
        root.title(APP_NAME)
        root.geometry("960x560")
        root.minsize(760, 420)

        self.downloads: list[Download] = []
        self.rows: dict[str, Download] = {}      # tree iid -> Download
        self._counter = 0
        self.extra_headers: dict[str, str] = {}  # applied to new downloads
        self.store = store

        # N1: all persisted preferences (queue behaviour, browser handoff,
        # last folder, threads, default speed limit, window geometry).
        self.prefs = load_settings(store)
        self.auto_resume_var = tk.BooleanVar(value=bool(self.prefs["auto_resume"]))
        self.max_active_var = tk.IntVar(value=int(self.prefs["max_active"]))
        self.default_limit = float(self.prefs["speed_limit"])
        # N2: opt-in clipboard watch. `_last_clipboard` remembers the last text
        # we looked at so a URL is offered at most once until it changes.
        self.clipboard_var = tk.BooleanVar(value=bool(self.prefs["clipboard_monitor"]))
        self._last_clipboard = ""
        # N3: expected checksum for new downloads + orphan-cleanup age.
        self.default_checksum = (self.prefs.get("default_checksum") or "").strip()
        self.cleanup_days = int(self.prefs.get("cleanup_days") or 0)
        # N4: one cap shared by every download (0 = unlimited).
        self.global_limit = float(self.prefs.get("global_speed_limit") or 0)
        set_global_speed_limit(self.global_limit)
        # N5: categories, auto-sort and the list filter.
        self.category_rules = load_rules(self.prefs.get("category_rules") or "")
        self.auto_sort_var = tk.BooleanVar(value=bool(self.prefs["auto_sort"]))
        self.filter_text = tk.StringVar(value=self.prefs.get("filter_text") or "")
        self.filter_status = tk.StringVar(
            value=self.prefs.get("filter_status") or "(all)")
        self._visible: set[str] = set()      # iids currently shown in the tree
        # N6: scheduled starts, the daily window and shut-down-when-done.
        self.window_start = parse_time(self.prefs.get("window_start") or "")
        self.window_end = parse_time(self.prefs.get("window_end") or "")
        self.shutdown_when_done = bool(self.prefs.get("shutdown_when_done"))
        self.shutdown_mode = (self.prefs.get("shutdown_mode") or SHUTDOWN)
        self._shutdown_armed = False         # asked the user already?
        self._poll_handle: str | None = None
        self.shutdown_var = tk.BooleanVar(value=self.shutdown_when_done)
        # N7: proxy configuration and address-family preference.
        self.proxy_url = (self.prefs.get("proxy_url") or "").strip()
        self.proxy_user = (self.prefs.get("proxy_user") or "").strip()
        self.proxy_pass = self.prefs.get("proxy_pass") or ""
        self.proxy_bypass = (self.prefs.get("proxy_bypass") or "").strip()
        self.prefer_ipv4 = bool(self.prefs.get("prefer_ipv4", True))
        # N11: the id of the extension that talked to us, so the native
        # host can be registered for that extension alone.
        self.extension_id = (self.prefs.get("extension_id") or "").strip()
        self.allow_private_segments = bool(
            self.prefs.get("allow_private_segments", False))
        self._apply_network_settings()
        # N9: the log file is opt-in; it is off unless the user turned it on.
        self.log_var = tk.BooleanVar(value=bool(self.prefs.get("log_enabled")))
        logsetup.enable(self.log_var.get())
        self.scheduler = Scheduler(
            int(self.prefs["max_active"]),
            int(self.prefs["max_connections"]),
            int(self.prefs["max_per_host"]))
        self.scheduler.set_window(self.window_start, self.window_end)

        # W1: browser handoff via a token-protected localhost server.
        self.control: ControlServer | None = None
        self._incoming: queue.Queue = queue.Queue()
        control_on = bool(self.prefs["control_enabled"])
        self.browser_enabled_var = tk.BooleanVar(value=control_on)
        if control_on:
            self._start_control()

        self._build_toolbar()
        self._build_filterbar()
        self._build_tree()
        self._build_buttons()
        self._build_statusbar()

        self._poll()
        self._restore_jobs()
        self._restore_window()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _restore_window(self) -> None:
        """Apply the saved window geometry once the widgets exist."""
        geom = (self.prefs.get("window") or "").strip()
        if not geom:
            return
        try:
            self.root.geometry(geom)
        except tk.TclError:
            pass

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        bar.pack(fill="x")

        ttk.Label(bar, text="URL(s):").grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(bar, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=1, columnspan=6, sticky="ew", padx=(4, 4))
        self.url_entry.bind("<Return>", lambda _e: self.add_download())

        ttk.Label(bar, text="Save to:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        default_dir = (self.prefs.get("last_dir")
                       or os.path.join(os.path.expanduser("~"), "Downloads"))
        self.dir_var = tk.StringVar(value=default_dir)
        ttk.Entry(bar, textvariable=self.dir_var).grid(
            row=1, column=1, columnspan=4, sticky="ew", padx=(4, 4), pady=(6, 0))
        ttk.Button(bar, text="Browse...", command=self._browse_dir).grid(
            row=1, column=5, sticky="w", pady=(6, 0))

        ttk.Label(bar, text="Threads:").grid(row=1, column=6, sticky="e", pady=(6, 0))
        self.threads_var = tk.IntVar(value=int(self.prefs["threads"]))
        ttk.Spinbox(bar, from_=1, to=32, width=4, textvariable=self.threads_var,
                    command=self._change_threads).grid(
            row=1, column=7, sticky="w", padx=(4, 8), pady=(6, 0))

        ttk.Button(bar, text="Add Download", command=self.add_download).grid(
            row=0, column=7, sticky="ew", padx=(4, 0))
        ttk.Button(bar, text="Headers...", command=self._edit_headers).grid(
            row=0, column=8, sticky="ew", padx=(4, 0))
        ttk.Button(bar, text="Browser...", command=self._browser_dialog).grid(
            row=0, column=9, sticky="ew", padx=(4, 0))
        ttk.Checkbutton(bar, text="Auto-resume", variable=self.auto_resume_var,
                        command=self._toggle_auto_resume).grid(
            row=1, column=8, sticky="w", padx=(4, 0), pady=(6, 0))
        ttk.Label(bar, text="Active:").grid(
            row=1, column=9, sticky="e", pady=(6, 0))
        ttk.Spinbox(bar, from_=1, to=16, width=4,
                    textvariable=self.max_active_var,
                    command=self._change_max_active).grid(
            row=1, column=10, sticky="w", padx=(4, 0), pady=(6, 0))
        # N2: clipboard watch lives on row 0 so row 1 stays uncluttered.
        ttk.Checkbutton(bar, text="Watch clipboard", variable=self.clipboard_var,
                        command=self._toggle_clipboard).grid(
            row=0, column=10, sticky="w", padx=(8, 0))

        bar.columnconfigure(1, weight=1)

    def _build_filterbar(self) -> None:
        """Search box, status filter, auto-sort toggle and category rules."""
        bar = ttk.Frame(self.root, padding=(8, 0, 8, 4))
        bar.pack(fill="x")

        ttk.Label(bar, text="Search:").pack(side="left")
        entry = ttk.Entry(bar, textvariable=self.filter_text, width=28)
        entry.pack(side="left", padx=(4, 10))
        entry.bind("<KeyRelease>", lambda _e: self._apply_filter())

        ttk.Label(bar, text="Status:").pack(side="left")
        combo = ttk.Combobox(bar, textvariable=self.filter_status,
                             state="readonly", width=12,
                             values=["(all)"] + list(STATUS_FILTERS[1:]))
        combo.pack(side="left", padx=(4, 10))
        combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filter())

        ttk.Checkbutton(bar, text="Sort into category folders",
                        variable=self.auto_sort_var,
                        command=self._toggle_auto_sort).pack(side="left")
        ttk.Button(bar, text="Categories...", command=self.categories_dialog
                   ).pack(side="left", padx=(10, 0))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(bar, text="Window:").pack(side="left")
        self.window_start_var = tk.StringVar(
            value=format_time(self.window_start))
        ttk.Entry(bar, textvariable=self.window_start_var, width=6
                  ).pack(side="left", padx=(4, 2))
        ttk.Label(bar, text="-").pack(side="left")
        self.window_end_var = tk.StringVar(
            value=format_time(self.window_end))
        ttk.Entry(bar, textvariable=self.window_end_var, width=6
                  ).pack(side="left", padx=(2, 8))
        ttk.Button(bar, text="Apply", command=self._apply_window
                   ).pack(side="left")
        ttk.Checkbutton(bar, text="Shut down when done",
                        variable=self.shutdown_var,
                        command=self._toggle_shutdown).pack(side="left", padx=(10, 0))
        ttk.Button(bar, text="Network...", command=self.network_dialog
                   ).pack(side="left", padx=(10, 0))

    def _build_tree(self) -> None:
        frame = ttk.Frame(self.root, padding=(8, 4))
        frame.pack(fill="both", expand=True)

        cols = ("name", "size", "progress", "speed", "eta", "status")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        headings = {
            "name": ("File", 300),
            "size": ("Size", 90),
            "progress": ("Progress", 150),
            "speed": ("Speed", 100),
            "eta": ("ETA", 80),
            "status": ("Status", 100),
        }
        for c, (text, width) in headings.items():
            self.tree.heading(c, text=text)
            self.tree.column(c, width=width, anchor="w" if c == "name" else "center")

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self.open_file())

    def _build_buttons(self) -> None:
        bar = ttk.Frame(self.root, padding=(8, 0, 8, 4))
        bar.pack(fill="x")
        for text, cmd in (
            ("Pause", self.pause_selected),
            ("Resume", self.resume_selected),
            ("Cancel", self.cancel_selected),
            ("Start Now", self.start_now_selected),
            ("Schedule...", self.schedule_dialog),
            ("Mirrors...", self.mirrors_dialog),
            ("Limit...", self.limit_selected),
            ("Global Limit...", self.global_limit_dialog),
            ("Checksum...", self.checksum_dialog),
            ("Details...", self.show_details),
            ("Clean Up...", self.cleanup_dialog),
            ("Move Up", self.move_up_selected),
            ("Move Down", self.move_down_selected),
            ("Remove", self.remove_selected),
            ("Open File", self.open_file),
            ("Open Folder", self.open_folder),
            ("Show in Folder", self.show_in_folder),
            ("Export...", self.export_queue_dialog),
            ("Import...", self.import_queue_dialog),
            ("Clear Completed", self.clear_completed),
        ):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 6))

    def _build_statusbar(self) -> None:
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var, relief="sunken",
                  anchor="w", padding=(6, 2)).pack(fill="x", side="bottom")

    def _browse_dir(self) -> None:
        d = filedialog.askdirectory(initialdir=self.dir_var.get() or os.getcwd())
        if d:
            self.dir_var.set(d)

    def _toggle_auto_resume(self) -> None:
        save_settings(self.store, auto_resume=self.auto_resume_var.get())
        self.status_var.set(
            "Auto-resume on launch: "
            + ("on" if self.auto_resume_var.get() else "off"))

    def _change_max_active(self) -> None:
        try:
            value = int(self.max_active_var.get())
        except (tk.TclError, ValueError):
            return
        self.scheduler.set_max_active(value)
        save_settings(self.store, max_active=self.scheduler.max_active)

    def _change_threads(self) -> None:
        try:
            value = int(self.threads_var.get())
        except (tk.TclError, ValueError):
            return
        save_settings(self.store, threads=max(1, min(value, 32)))

    def _toggle_clipboard(self) -> None:
        save_settings(self.store, clipboard_monitor=self.clipboard_var.get())
        if self.clipboard_var.get():
            # Don't offer whatever is already on the clipboard right now.
            self._last_clipboard = self._read_clipboard()
            self.status_var.set("Clipboard watch: on")
        else:
            self.status_var.set("Clipboard watch: off")

    def _read_clipboard(self) -> str:
        try:
            return self.root.clipboard_get()
        except tk.TclError:
            return ""

    def _known_urls(self) -> set[str]:
        urls = {dl.url for dl in self.downloads}
        urls.update(dl.final_url for dl in self.downloads if dl.final_url)
        return urls

    def _check_clipboard(self) -> None:
        """Offer a newly copied link (never adds without confirmation)."""
        if not self.clipboard_var.get():
            return
        text = self._read_clipboard()
        if not text or text == self._last_clipboard:
            return
        self._last_clipboard = text
        url = find_url(text, exclude=self._known_urls())
        if not url:
            return
        if messagebox.askyesno(
                APP_NAME, f"Download this link with FreeDM?\n\n{url}"):
            try:
                self._add_url(url)
            except Exception:       # noqa: BLE001 - never break the UI loop
                pass

    def _new_download(self, url: str, **kwargs) -> Download:
        """Create a Download with the current GUI defaults and enqueue it.

        ``filename`` is used to pick the category folder when auto-sort is
        on; the real name is only known after the server is probed, so the
        folder is chosen from the URL's extension as a best guess."""
        filename = kwargs.pop("filename", None)
        dest = kwargs.pop("dest_dir", None)
        if not dest:
            dest = self._target_dir(filename or self._name_from_url(url))
        resolver = kwargs.pop("dest_resolver", "auto")
        if resolver == "auto":
            resolver = self._dest_resolver()
        threads = kwargs.pop("num_threads", None)
        if threads is None:
            try:
                threads = int(self.threads_var.get())
            except (tk.TclError, ValueError):
                threads = 8
        checksum = kwargs.pop("checksum", None)
        dl = Download(url, dest_dir=dest, num_threads=threads,
                      speed_limit=self.default_limit, store=self.store,
                      checksum=self.default_checksum if checksum is None
                      else checksum, dest_resolver=resolver,
                      allow_private_segments=self.allow_private_segments,
                      **kwargs)
        self._enqueue(dl)
        return dl

    @staticmethod
    def _name_from_url(url: str) -> str:
        """Best-effort file name from a URL (used before the probe)."""
        try:
            path = urlparse(url).path
        except ValueError:
            return ""
        return os.path.basename(path) or ""

    def _add_url(self, url: str) -> Download:
        return self._new_download(url, headers=dict(self.extra_headers))

    def _enqueue(self, dl: Download) -> None:
        if self.store is not None and not dl.job_id:
            dl.job_id = self.store.add(dl)
        self._counter += 1
        iid = f"dl{self._counter}"
        self.downloads.append(dl)
        self.rows[iid] = dl
        if self._row_matches(dl):
            self.tree.insert("", "end", iid=iid,
                             values=(dl.name, "-", "0%", "-", "-", QUEUED))
            self._visible.add(iid)
        self.scheduler.submit(dl)

    def _status_filter(self) -> str:
        value = (self.filter_status.get() or "").strip()
        return "" if value in ("", "(all)") else value

    def _row_matches(self, dl: Download) -> bool:
        return matches_filter(dl.name, dl.url, dl.status,
                              self.filter_text.get(), self._status_filter())

    def _apply_filter(self) -> None:
        """Show only the rows that match the search / status filter."""
        needle = self.filter_text.get()
        status = self._status_filter()
        save_settings(self.store, filter_text=needle, filter_status=status)
        self._refresh_visible()

    def _refresh_visible(self) -> None:
        """Rebuild the tree so it shows exactly the matching rows."""
        wanted = {iid for iid, dl in self.rows.items() if self._row_matches(dl)}
        if wanted == self._visible:
            return
        current = set(self.tree.get_children())
        for iid in current - wanted:
            self.tree.delete(iid)
        for iid in wanted - current:
            dl = self.rows.get(iid)
            if dl is None:
                continue
            self.tree.insert("", "end", iid=iid,
                             values=(dl.name, "-", "0%", "-", "-", dl.status))
        self._visible = wanted

    def _selected(self) -> list[Download]:
        return [self.rows[i] for i in self.tree.selection() if i in self.rows]

    def pause_selected(self) -> None:
        for dl in self._selected():
            self.scheduler.pause(dl)

    def resume_selected(self) -> None:
        for dl in self._selected():
            self.scheduler.resume(dl)

    def cancel_selected(self) -> None:
        for dl in self._selected():
            self.scheduler.cancel(dl)

    def start_now_selected(self) -> None:
        for dl in self._selected():
            self.scheduler.start_now(dl)

    def move_up_selected(self) -> None:
        for dl in reversed(self._selected()):
            self.scheduler.move_up(dl)

    def move_down_selected(self) -> None:
        for dl in self._selected():
            self.scheduler.move_down(dl)

    def remove_selected(self) -> None:
        for iid in list(self.tree.selection()):
            dl = self.rows.pop(iid, None)
            if dl is not None:
                self.scheduler.remove(dl)
                dl.cancel()
                if self.store is not None and dl.job_id:
                    self.store.delete(dl.job_id)
                if dl in self.downloads:
                    self.downloads.remove(dl)
            self.tree.delete(iid)
            self._visible.discard(iid)

    def clear_completed(self) -> None:
        for iid, dl in list(self.rows.items()):
            if dl.status == DONE:
                self.rows.pop(iid, None)
                if self.store is not None and dl.job_id:
                    self.store.delete(dl.job_id)
                if dl in self.downloads:
                    self.downloads.remove(dl)
                self.tree.delete(iid)
                self._visible.discard(iid)

    def open_file(self) -> None:
        for dl in self._selected():
            if dl.status == DONE and dl.path and os.path.exists(dl.path):
                # Security: never launch an executable or a script without
                # asking - a download manager handles dangerous files.
                if os.path.splitext(dl.path)[1].lower() in EXECUTABLE_EXTENSIONS:
                    if not messagebox.askyesno(
                            APP_NAME,
                            f"This file can run code:\n\n{dl.path}\n\n"
                            "Open it anyway?"):
                        return
                self._open(dl.path)
                return
        # N5: the file is gone (or still downloading) - show where it was.
        for dl in self._selected():
            if dl.path and os.path.isdir(os.path.dirname(dl.path)):
                self._open(os.path.dirname(dl.path))
                return

    def open_folder(self) -> None:
        sel = self._selected()
        target = None
        for dl in sel:
            if dl.path:
                target = os.path.dirname(dl.path)
                break
            target = dl.dest_dir
        target = target or self.dir_var.get()
        if target and os.path.isdir(target):
            self._open(target)

    def _open(self, path: str) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)      # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def _notify_status(self, text: str) -> None:
        var = getattr(self, "status_var", None)
        if var is not None:
            var.set(text)

    def add_download(self) -> None:
        raw = self.url_var.get()
        valid, invalid, dupes = parse_urls(raw)
        if not valid and not invalid:
            return
        if invalid:
            preview = ", ".join(invalid[:5])
            more = f" (+{len(invalid) - 5} more)" if len(invalid) > 5 else ""
            messagebox.showerror(
                APP_NAME,
                f"Not a valid http(s) URL: {preview}{more}")
            if not valid:
                return
        dest = self.dir_var.get().strip() or os.getcwd()
        try:
            threads = int(self.threads_var.get())
        except (tk.TclError, ValueError):
            threads = 8
        save_settings(self.store, last_dir=dest, threads=threads)
        for url in valid:
            self._new_download(url, headers=dict(self.extra_headers))
        self.url_var.set("")
        parts = [f"Added {len(valid)} download(s)"]
        if dupes:
            parts.append(f"skipped {dupes} duplicate(s)")
        if invalid:
            parts.append(f"ignored {len(invalid)} invalid")
        self.status_var.set(" - ".join(parts))

    def _restore_jobs(self) -> None:
        """Reload the queue from the DB and resume unfinished work."""
        if self.store is None:
            self.status_var.set("Ready (queue persistence unavailable)")
            return
        try:
            records = self.store.list_all()
        except Exception:
            records = []
        restored = resumed = 0
        for record in records:
            try:
                dl = Download(
                    record.get("url", ""),
                    dest_dir=record.get("dest_dir") or None,
                    filename=record.get("filename") or None,
                    num_threads=record.get("threads") or 8,
                    store=self.store,
                    job_id=record.get("id"),
                )
                dl.apply_record(record)
            except Exception:
                continue
            restored += 1
            self._counter += 1
            iid = f"dl{self._counter}"
            self.downloads.append(dl)
            self.rows[iid] = dl
            if self._row_matches(dl):
                self.tree.insert("", "end", iid=iid,
                                 values=(dl.name, "-", "0%", "-", "-", IDLE))
                self._visible.add(iid)

            status = record.get("status") or IDLE
            if status == DONE:
                dl.status = DONE
                if not (dl.path and os.path.exists(dl.path)):
                    dl.status = ERROR
                    dl.error = "file no longer exists"
            elif status == PAUSED:
                dl.status = PAUSED
            elif status == ERROR:
                dl.status = ERROR
                dl.error = record.get("error")
            elif status == CANCELED:
                dl.status = CANCELED
            elif status == SCHEDULED or (dl.start_at
                                         and dl.start_at > time.time()):
                # N6: a job with a start time waits for it, even when
                # auto-resume is off - the user asked for that time.
                dl.status = SCHEDULED
                self.scheduler.submit(dl)
            elif self.auto_resume_var.get():
                resumed += 1
                self.scheduler.submit(dl)
            else:
                dl.status = PAUSED
        if restored:
            self.status_var.set(
                f"Restored {restored} job(s), auto-resumed {resumed}")

    def _on_close(self) -> None:
        """Preserve partial data for running jobs before the app exits."""
        try:
            self.root.after_cancel(self._poll_handle)
        except Exception:       # noqa: BLE001 - the timer may be gone
            pass
        self.scheduler.shutdown()
        if self.control is not None:
            self.control.stop()
            self.control = None
        for dl in list(self.downloads):
            if dl.status in (DOWNLOADING, PROBING):
                dl.pause()
                dl.abandon(wait=1.5)
        save_settings(
            self.store,
            last_dir=self.dir_var.get().strip(),
            speed_limit=self.default_limit,
            window=self.root.winfo_geometry())
        if self.store is not None:
            self.store.close()
        self.root.destroy()

    def _poll(self) -> None:
        while True:
            try:
                payload = self._incoming.get_nowait()
            except queue.Empty:
                break
            try:
                self._add_from_browser(payload)
            except Exception:       # noqa: BLE001 - never break the UI loop
                pass

        try:
            self._check_clipboard()
        except Exception:           # noqa: BLE001 - never break the UI loop
            pass

        try:
            self._check_shutdown_when_done()
        except Exception:           # noqa: BLE001 - never break the UI loop
            pass

        active = 0
        queued = 0
        total_speed = 0.0
        # N5: a status change can make a row appear or disappear.
        try:
            self._refresh_visible()
        except Exception:           # noqa: BLE001 - never break the UI loop
            pass
        for iid, dl in list(self.rows.items()):
            if not self.tree.exists(iid):
                continue
            s = dl.snapshot()
            size = human_size(s["size"]) if s["size"] else "-"
            if s["size"]:
                pct = f"{s['progress'] * 100:5.1f}%"
            else:
                pct = human_size(s["downloaded"])
            speed = human_speed(s["speed"]) if s["status"] == DOWNLOADING else "-"
            eta = human_time(s["eta"]) if s["status"] == DOWNLOADING else "-"
            status = s["status"]
            if status == ERROR and s["error"]:
                status = f"error: {s['error'][:40]}"
            elif status == SCHEDULED:
                status = f"scheduled: {describe_schedule(s.get('start_at'))}"
            self.tree.item(iid, values=(s["name"], size, pct, speed, eta, status))
            if s["status"] in (DOWNLOADING, PROBING):
                active += 1
                total_speed += s["speed"]
            elif s["status"] == QUEUED:
                queued += 1

        if active or queued:
            parts = []
            if active:
                parts.append(f"{active} active")
            if queued:
                parts.append(f"{queued} queued")
            self.status_var.set(
                " - ".join(parts) + f" - {human_speed(total_speed)} total")
        self._poll_handle = self.root.after(500, self._poll)
