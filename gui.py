"""FreeDM Tkinter GUI - a free Internet Download Manager style front-end."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import urlparse

from engine import (
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
    set_global_speed_limit,
    global_speed_limit,
)
from store import JobStore
from settings import load as load_settings, save as save_settings
from batch import parse_urls, find_url
from categories import (default_rules, format_rules, load_rules, parse_rules,
                        classify, destination_for, matches_filter,
                        export_queue, import_queue, STATUS_FILTERS)
from verify import (ALGORITHMS, parse_checksum, find_orphans, cleanup_orphans)
from scheduler import Scheduler
from control_server import ControlServer, export_extension, token_path

APP_NAME = "FreeDM - Free Download Manager"


class App:
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
        self.scheduler = Scheduler(
            int(self.prefs["max_active"]),
            int(self.prefs["max_connections"]),
            int(self.prefs["max_per_host"]))

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

    # -- UI construction ---------------------------------------------------
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

    # -- N5: filtering, categories, import/export ---------------------------
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

    # -- actions -----------------------------------------------------------
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

    # -- N2: batch add & clipboard watch -----------------------------------
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
                      else checksum, dest_resolver=resolver, **kwargs)
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

    # -- N1: per-download limit & job details ------------------------------
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

    # -- browser handoff (W1) ---------------------------------------------
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

    def _notify_status(self, text: str) -> None:
        var = getattr(self, "status_var", None)
        if var is not None:
            var.set(text)

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

    def _export_extension(self) -> None:
        try:
            dest = export_extension()
        except Exception as exc:       # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Could not export the extension: {exc}")
            return
        messagebox.showinfo(
            APP_NAME,
            "Extension exported to:\n" + dest
            + "\n\nLoad it via chrome://extensions > Developer mode > Load unpacked.")
        self._open(dest)

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

    def _add_from_browser(self, payload: dict) -> None:
        """Create a download from a validated extension payload (main thread)."""
        url = payload.get("url") or ""
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
            dest_resolver=self._dest_resolver(), store=self.store)
        self._enqueue(dl)
        self.status_var.set(f"Browser: {url}")

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
            elif self.auto_resume_var.get():
                resumed += 1
                self.scheduler.submit(dl)
            else:
                dl.status = PAUSED
        if restored:
            self.status_var.set(
                f"Restored {restored} job(s), auto-resumed {resumed}")

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

    # -- refresh loop ------------------------------------------------------
    def _on_close(self) -> None:
        """Preserve partial data for running jobs before the app exits."""
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
        self.root.after(500, self._poll)


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


if __name__ == "__main__":
    run_gui()
