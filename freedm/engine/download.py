# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""The Download class: one job."""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from urllib.parse import urlparse

import requests

from freedm.engine.constants import (CANCELED, CHUNK,
                                   CONNECT_TIMEOUT,
                                   DISK_MARGIN, DOWNLOADING, DONE,
                                   ERROR, IDLE, MAX_PIECE_SIZE,
                                   MAX_RETRIES, MAX_SEGMENTS,
                                   MIN_PIECE_SIZE, MIN_SEGMENT_SIZE,
                                   MIN_SPLIT_SIZE, PAUSED, PROBING,
                                   QUEUED, READ_TIMEOUT, SCHEDULED,
                                   USER_AGENT)
from freedm.engine.errors import (AuthRequiredError,
                                   DownloadCanceled, FileChangedError,
                                   RangeNotSupportedError,
                                   VerificationError)
from freedm.engine.files import FilesMixin
from freedm.engine.formatting import (human_size, human_speed,
                                     human_time, sanitize_filename)
from freedm.engine.limits import (GLOBAL_LIMITER, GlobalRateLimiter,
                                  RateLimiter, global_speed_limit,
                                  set_global_speed_limit)
from freedm.engine.network import NetworkMixin
from freedm.engine.segments import SegmentsMixin, Segment
from freedm.engine.streaming import StreamingMixin
from freedm.engine.verification import VerificationMixin
from freedm.engine.workers import WorkersMixin
from freedm.network import PROXY, mirror_path
from freedm.stream import (check_segment_url, is_stream_url,
                           output_name as stream_output_name)


class Download(FilesMixin, NetworkMixin, SegmentsMixin,
             StreamingMixin, VerificationMixin, WorkersMixin):
    """One download job.

    The class is split over several mixins, one per concern; this is
    the part that holds them together: the constructor, the public
    API and the bookkeeping.
    """

    def __init__(self, url: str, dest_dir: str | None = None,
                 filename: str | None = None, num_threads: int = 8,
                 headers: dict | None = None, speed_limit: float = 0.0,
                 verify_ssl: bool = True, on_existing: str = "rename",
                 confirm_overwrite=None, cookies=None,
                 store=None, job_id: int | None = None, checksum: str = "",
                 dest_resolver=None, mirrors=None,
                 allow_private_segments: bool = False):
        """on_existing: 'rename' (safe default) | 'overwrite' | 'cancel'.
        confirm_overwrite: optional callable(path) -> action, called when the
        destination already exists; overrides on_existing.
        cookies: dict[str,str], "a=1; b=2", or list of
        {name,value,domain,path} dicts (e.g. supplied by a browser extension).
        headers: job headers (Referer, User-Agent, Authorization, Cookie, ...).
        store: optional JobStore; when set, status/segment changes are persisted
        and job_id identifies the database row.
        checksum: expected digest, e.g. "sha256:ab12..." or a bare 64-hex
        sha256 digest. Verified when the download finishes (N3).
        dest_resolver: optional callable(filename) -> folder, called once the
        real file name is known (N5 category sorting).
        mirrors: optional list of alternative source base URLs (N7)."""
        self.url = url.strip()
        self.num_threads = max(1, min(int(num_threads), 32))
        self.headers = dict(headers or {})
        self.headers.setdefault("User-Agent", USER_AGENT)
        self.verify_ssl = verify_ssl
        self.speed_limit = max(0.0, float(speed_limit))
        self.rate = RateLimiter(self.speed_limit)
        self.on_existing = on_existing
        self.confirm_overwrite = confirm_overwrite
        if on_existing not in ("rename", "overwrite", "cancel"):
            raise ValueError("on_existing must be rename, overwrite, or cancel")

        # One HTTP session per download: carries cookies, reuses connections
        # and keeps a single redirect/authentication context.
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        if "Accept-Encoding" not in self.headers:
            # Ranges must address the raw bytes, never a compressed stream.
            self.session.headers["Accept-Encoding"] = "identity"
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=16, pool_maxsize=64, max_retries=0)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        # N7: the shared proxy configuration applies to every request.
        self.session.proxies = PROXY.proxies()
        self.final_url: str = self.url
        self._apply_cookies(cookies)
        self._apply_cookie_header()

        # N7: alternative sources for the same file (mirror base URLs).
        self.mirrors: list[str] = []
        self._source_index = 0

        # W3: optional persistent queue backing.
        self.store = store
        self.job_id = job_id
        if mirrors:
            self.set_mirrors(list(mirrors))
        self.restored_status: str | None = None
        self._needs_prepare = False
        self._abandoned = False
        self._stored_etag: str | None = None
        self._stored_last_modified: str | None = None
        self._stored_size = 0

        self.dest_dir = os.path.abspath(dest_dir or os.getcwd())
        self.dest_resolver = dest_resolver
        self.filename = sanitize_filename(filename) if filename else None
        self.path: str | None = None
        self.part_path: str | None = None
        self.state_path: str | None = None

        self.total_size = 0
        self.downloaded = 0
        self.segments: list[Segment] = []
        self.supports_range = False

        # N3: expected checksum for this job and the last verification result.
        self.checksum = (checksum or "").strip()
        self.checksum_result = ""

        # N6: when this job should start (Unix timestamp); 0/None = right away.
        self.start_at: float | None = None

        # N10: streaming media (HLS/DASH) instead of a single file.
        self.is_stream = False
        # G1: a playlist may only reach the local network if the user says so.
        self.allow_private_segments = bool(allow_private_segments)
        self.stream_playlist = None
        self.stream_segments = 0
        self.stream_encrypted = False

        self.status = IDLE
        self.error: str | None = None
        self.speed = 0.0
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self._single_complete = False

        # Remote-file validators used to make resume safe.
        self.etag: str | None = None
        self.last_modified: str | None = None
        self.validator: str | None = None
        self._resuming = False
        self._restarted = False

        # An RLock so helpers that snapshot the segment list can be called
        # from code that already holds it (N4).
        self._lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._pause = threading.Event()
        self._pause.set()          # set == running, clear == paused
        self._cancel = threading.Event()
        self._abort = threading.Event()
        self._worker_error: Exception | None = None
        self._workers: list[threading.Thread] = []
        self._monitor: threading.Thread | None = None
        self._last_bytes = 0
        self._last_time = 0.0
        self._run_thread: threading.Thread | None = None

        # --- N4: dynamic segmentation state -------------------------------
        self._pending: dict[int, Segment] = {}   # index -> piece awaiting work
        self._next_index = 0                      # next fresh piece index
        self._piece_speeds: list[float] = []      # recent piece throughput
        self.split_count = 0                      # how many pieces were split
        self.initial_piece_count = 0              # pieces before any splitting

    def start(self) -> None:
        if self._run_thread is not None and self._run_thread.is_alive():
            return
        if self.status == DONE:
            return
        self.error = None
        self._cancel.clear()
        self._abort.clear()
        self._abandoned = False
        self._worker_error = None
        self._pause.set()
        self.status = PROBING        # visible synchronously for the scheduler
        self._run_thread = threading.Thread(target=self._run, daemon=True)
        self._run_thread.start()

    def pause(self) -> None:
        with self._lock:
            if self.status not in (PROBING, DOWNLOADING):
                return
            self._pause.clear()
            self.status = PAUSED
        self._save_state()
        self._store_save()

    def resume(self) -> None:
        if self.status in (PAUSED, ERROR, CANCELED):
            if self.status in (ERROR, CANCELED):
                # Re-probe and re-validate before reusing an old part file.
                self._needs_prepare = True
            # A restored job has no live run thread; start a fresh pass.
            if self._run_thread is None or not self._run_thread.is_alive():
                self.start()
            else:
                self.status = DOWNLOADING
                self._pause.set()

    def abandon(self, wait: float = 10.0) -> None:
        """Stop threads but keep partial data (app shutdown / handover)."""
        self._abandoned = True
        self._store_save()
        self._cancel.set()
        self._abort.set()
        self._pause.set()
        if self._run_thread and self._run_thread.is_alive():
            self._run_thread.join(timeout=wait)
        for t in list(self._workers):
            if t.is_alive():
                t.join(timeout=min(wait, 5))
        if self._monitor is not None and self._monitor.is_alive():
            self._monitor.join(timeout=2)
        try:
            self.session.close()
        except Exception:       # noqa: BLE001
            pass

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.set()          # unblock any waiting workers
        if self.status not in (DONE,):
            self.status = CANCELED

    @property
    def progress(self) -> float:
        if self.total_size > 0:
            return min(1.0, self.downloaded / self.total_size)
        return 0.0

    @property
    def eta(self) -> float:
        if self.total_size > 0 and self.speed > 0:
            return max(0.0, (self.total_size - self.downloaded) / self.speed)
        return 0.0

    @property
    def name(self) -> str:
        return self.filename or os.path.basename(urlparse(self.url).path) or "download"

    def apply_record(self, record: dict) -> None:
        """Restore queue metadata loaded from a JobStore.

        The engine re-probes on the next start; this seeds identity, the
        destination and display fields so the job can be shown immediately.
        """
        self.job_id = int(record.get("id") or self.job_id or 0) or None
        self.restored_status = record.get("status")
        self._stored_etag = record.get("etag")
        self._stored_last_modified = record.get("last_modified")
        self._stored_size = int(record.get("size") or 0)
        self.final_url = record.get("final_url") or self.final_url
        self.dest_dir = record.get("dest_dir") or self.dest_dir
        self.filename = record.get("filename") or self.filename
        self.num_threads = max(
            1, min(int(record.get("threads") or self.num_threads), 32))
        limit = float(record.get("speed_limit") or 0)
        if limit > 0:
            self.speed_limit = limit
            self.rate.set_rate(limit)
        self.total_size = int(record.get("size") or 0)
        self.downloaded = int(record.get("downloaded") or 0)
        self.checksum = (record.get("checksum") or "").strip()
        self.checksum_result = record.get("checksum_result") or ""
        try:
            self.start_at = float(record.get("start_at") or 0) or None
        except (TypeError, ValueError):
            self.start_at = None
        try:
            mirrors = json.loads(record.get("mirrors") or "[]")
        except (TypeError, ValueError):
            mirrors = []
        self.mirrors = [str(m) for m in mirrors] if isinstance(mirrors, list) else []
        self.etag = record.get("etag") or self.etag
        self.last_modified = record.get("last_modified") or self.last_modified
        self.validator = self.etag or self.last_modified
        try:
            headers = json.loads(record.get("headers_json") or "{}")
        except (TypeError, ValueError):
            headers = {}
        if isinstance(headers, dict) and headers:
            self.headers.update(headers)
            self.session.headers.update(self.headers)
            # The restored header set may carry a Cookie again: put it back
            # into the jar and keep it out of the raw request headers.
            self._apply_cookie_header()
        if self.dest_dir and self.filename:
            self.path = os.path.join(self.dest_dir, self.filename)
            self.part_path = self.path + ".part"
            self.state_path = self.path + ".part.state.json"
        self.status = IDLE
        self._needs_prepare = True

    def _store_save(self) -> None:
        """Best-effort persistence of metadata + segment offsets."""
        if not self.store or not self.job_id:
            return
        try:
            with self._lock:
                segs = list(self.segments)
            self.store.save(self)
            self.store.save_segments(self.job_id, segs)
        except Exception:       # noqa: BLE001 - never break the download
            pass

    def set_speed_limit(self, bps: float) -> None:
        """Change the live rate cap (bytes/s); 0 or less means unlimited.

        Safe to call while the download is running: worker threads consult the
        shared token bucket before every chunk. The new value is persisted for
        the job so it survives a restart."""
        value = max(0.0, float(bps))
        self.speed_limit = value
        self.rate.set_rate(value)
        self._store_save()

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "final_url": self.final_url,
            "size": self.total_size,
            "downloaded": self.downloaded,
            "progress": self.progress,
            "speed": self.speed,
            "eta": self.eta,
            "status": self.status,
            "error": self.error,
            "dir": self.dest_dir,
            "path": self.path,
            "threads": self.num_threads,
            "speed_limit": self.speed_limit,
            "checksum": self.checksum,
            "checksum_result": self.checksum_result,
            "supports_range": self.supports_range,
            "job_id": self.job_id,
            "pieces": len(self.segments),
            "splits": self.split_count,
            "start_at": self.start_at,
        }

    def set_start_at(self, when: float | None) -> None:
        """Set (or clear) the moment this job should start (Unix timestamp).

        A time in the future keeps the job in the ``scheduled`` state; the
        scheduler starts it when the time comes. The value is persisted so a
        scheduled job survives a restart."""
        self.start_at = float(when) if when else None
        self._store_save()

    def mark_queued(self) -> None:
        """Set the scheduler's waiting state and persist it."""
        if self.status != DONE:
            self.status = QUEUED
            self._store_save()

    def mark_scheduled(self) -> None:
        """Set the 'waiting for its start time' state and persist it."""
        if self.status != DONE:
            self.status = SCHEDULED
            self._store_save()

    @staticmethod
    def _parse_retry_after(value: str | None, attempt: int) -> float:
        """Seconds to wait from a Retry-After header (or exponential backoff)."""
        if value:
            value = value.strip()
            if value.isdigit():
                return min(float(value), 120.0)
            try:
                from datetime import datetime, timezone
                from email.utils import parsedate_to_datetime
                when = parsedate_to_datetime(value)
                if when is not None:
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    return max(0.0, min(
                        (when - datetime.now(timezone.utc)).total_seconds(), 120.0))
            except (TypeError, ValueError, OverflowError):
                pass
        return min(2.0 ** max(1, attempt), 30.0)

    def _sleep_cancelable(self, seconds: float) -> bool:
        """Sleep in small slices; return False if the job was canceled."""
        end = time.monotonic() + max(0.0, seconds)
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return True
            if self._cancel.is_set() or self._abort.is_set():
                return False
            if not self._pause.is_set():
                # Paused: stop the wait; the retry restarts after resume.
                return False
            time.sleep(min(0.1, remaining))
