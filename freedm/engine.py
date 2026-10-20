# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""FreeDM download engine.

Multi-threaded, segmented HTTP/HTTPS downloads using HTTP Range requests,
with pause / resume / cancel, crash-safe resume state, retries with
exponential backoff, and an optional rate limiter.

100% free: only depends on `requests` (BSD) and the Python standard library.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from urllib.parse import unquote, urlparse

import requests

from freedm.verify import (ALGORITHMS, parse_checksum, file_digest, verify_size,
                    verify_checksum)
from freedm.network import PROXY, mirror_path
from freedm.stream import (StreamError, parse_m3u8, parse_mpd, is_stream_url,
                           decrypt_aes128, key_from_data,
                           check_segment_url, host_of as stream_host_of,
                           output_name as stream_output_name)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
CHUNK = 128 * 1024                 # read/write chunk size
MIN_SEGMENT_SIZE = 1 * 1024 * 1024  # never split files smaller than this
MAX_RETRIES = 6                     # retries per segment before giving up
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 60

# --- N4: dynamic segmentation ---------------------------------------------
MAX_PIECE_SIZE = 8 * 1024 * 1024    # no single piece may exceed this
MIN_PIECE_SIZE = 1 * 1024 * 1024    # never create a piece smaller than this
MIN_SPLIT_SIZE = 1 * 1024 * 1024    # both halves of a split must reach this
MAX_SEGMENTS = 1024                 # hard cap on the number of pieces
SPLIT_TARGET_SECONDS = 5.0          # aim for pieces that take ~this long
PIECE_SPEED_SAMPLES = 8             # recent piece speeds kept for the target
DYNAMIC_SPLITTING = True            # master switch for N4 dynamic pieces

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) FreeDM/1.0"
)

# Status values
IDLE = "idle"
QUEUED = "queued"
SCHEDULED = "scheduled"
PROBING = "probing"
DOWNLOADING = "downloading"
PAUSED = "paused"
DONE = "done"
ERROR = "error"
CANCELED = "canceled"

# Free space kept free on the destination drive (headroom for the OS).
DISK_MARGIN = 64 * 1024 * 1024


class GlobalRateLimiter:
    """One token bucket shared by *every* download (N4, technical debt #4).

    Per-download limits cap one job; this caps the combined throughput of
    all jobs, which is what a user on a metered or shared link needs.
    A rate of 0 (the default) means unlimited."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rate = 0.0
        self._allowance = 0.0
        self._last = time.monotonic()

    @property
    def rate(self) -> float:
        with self._lock:
            return self._rate

    def set_rate(self, rate: float) -> None:
        with self._lock:
            self._rate = max(0.0, float(rate))
            self._allowance = 0.0
            self._last = time.monotonic()

    def consume(self, n: int) -> None:
        if n <= 0:
            return
        while True:
            with self._lock:
                if self._rate <= 0:
                    return
                now = time.monotonic()
                self._allowance += (now - self._last) * self._rate
                self._last = now
                burst = max(self._rate, float(n))
                if self._allowance > burst:
                    self._allowance = burst
                if self._allowance >= n:
                    self._allowance -= n
                    return
                need = n - self._allowance
            time.sleep(min(need / self._rate, 0.5))


#: The process-wide limiter consulted by every download.
GLOBAL_LIMITER = GlobalRateLimiter()


def set_global_speed_limit(bps: float) -> None:
    """Cap the combined throughput of all downloads (0 = unlimited)."""
    GLOBAL_LIMITER.set_rate(bps)


def global_speed_limit() -> float:
    """The current combined throughput cap in bytes/s (0 = unlimited)."""
    return GLOBAL_LIMITER.rate


class DownloadCanceled(Exception):
    """Raised when an existing destination file is protected and the user
    declines to overwrite (or the policy is 'cancel')."""


class FileChangedError(IOError):
    """The remote file changed between requests, so a resume would corrupt it.
    The caller should restart the download from zero."""


class RangeNotSupportedError(IOError):
    """The server stopped honouring Range requests mid-download."""


class AuthRequiredError(IOError):
    """The server rejected the request (401/403); cookies or headers are needed."""


class VerificationError(IOError):
    """The finished file failed its size or checksum verification (N3)."""


def human_size(n: float) -> str:
    if not n or n <= 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} TB"


def human_speed(bps: float) -> str:
    return f"{human_size(bps)}/s" if bps and bps > 0 else "-"


def human_time(seconds: float) -> str:
    if not seconds or seconds <= 0 or seconds == float("inf"):
        return "-"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def sanitize_filename(name: str) -> str:
    name = name.strip().replace("\r", "").replace("\n", "")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(" .")
    return name or "download"


# ---------------------------------------------------------------------------
# Rate limiter (token bucket)
# ---------------------------------------------------------------------------
class RateLimiter:
    """Token-bucket limiter. rate <= 0 means unlimited."""

    def __init__(self, rate: float = 0.0):
        self.rate = float(rate)
        self._allowance = 0.0
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def set_rate(self, rate: float) -> None:
        with self._lock:
            self.rate = float(rate)
            self._allowance = 0.0
            self._last = time.monotonic()

    def consume(self, n: int) -> None:
        if self.rate <= 0 or n <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                self._allowance += (now - self._last) * self.rate
                self._last = now
                # Allow one chunk-sized burst even when a single read is
                # larger than the per-second rate (otherwise n can never fit
                # under the cap and the loop would spin forever).
                burst = max(self.rate, float(n))
                if self._allowance > burst:
                    self._allowance = burst
                if self._allowance >= n:
                    self._allowance -= n
                    return
                need = n - self._allowance
            time.sleep(min(need / self.rate, 0.5))


# ---------------------------------------------------------------------------
# Segment
# ---------------------------------------------------------------------------
class Segment:
    __slots__ = ("index", "start", "end", "downloaded")

    def __init__(self, index: int, start: int, end: int, downloaded: int = 0):
        self.index = index
        self.start = start
        self.end = end              # inclusive
        self.downloaded = downloaded

    @property
    def size(self) -> int:
        return self.end - self.start + 1

    @property
    def remaining(self) -> int:
        return max(0, self.size - self.downloaded)

    @property
    def done(self) -> bool:
        return self.downloaded >= self.size

    def to_dict(self) -> dict:
        return {"index": self.index, "start": self.start, "end": self.end,
                "downloaded": self.downloaded}

    @classmethod
    def from_dict(cls, d: dict) -> "Segment":
        return cls(d["index"], d["start"], d["end"], d.get("downloaded", 0))


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
class Download:
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

    # -- public API --------------------------------------------------------
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

    # -- derived progress --------------------------------------------------
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

    # -- internals ---------------------------------------------------------
    def _run(self) -> None:
        try:
            if self.path is None or self._needs_prepare:
                self.status = PROBING
                self._probe()
                self._prepare_files()
                self._needs_prepare = False
                self._store_save()
            # Pause may have arrived during probe/prepare; make it stick
            # instead of overwriting PAUSED with DOWNLOADING.
            with self._lock:
                self.status = DOWNLOADING if self._pause.is_set() else PAUSED
            if self.status == PAUSED:
                self._store_save()
                return
            self.started_at = self.started_at or time.time()
            self._start_monitor()

            ok = False
            while True:
                try:
                    if self.is_stream:
                        # N10: a playlist is downloaded segment by segment.
                        ok = self._run_stream()
                    else:
                        ok = self._run_once()
                    break
                except FileChangedError:
                    if self._restarted:
                        raise
                    self._restarted = True
                    self._reset_for_restart()
                    self.status = DOWNLOADING
                    self._start_monitor()
                    continue

            if self._cancel.is_set():
                if not self._abandoned:
                    self.status = CANCELED
                    self._cleanup_partial()
            elif ok:
                self._check_complete()
                self._finalize()
            else:
                self.status = ERROR
                self.error = self.error or "download did not complete"
        except DownloadCanceled as exc:
            if self._abandoned:
                self.status = PAUSED
            else:
                self.status = CANCELED
                self.error = str(exc)
                self._cleanup_partial()
        except Exception as exc:       # noqa: BLE001
            if self._cancel.is_set():
                if self._abandoned:
                    self.status = PAUSED
                else:
                    self.status = CANCELED
                    self._cleanup_partial()
            else:
                self.status = ERROR
                self.error = str(exc)
        finally:
            self._store_save()

    def _run_once(self) -> bool:
        if self.supports_range and len(self.segments) > 1:
            try:
                self._download_segmented()
            except RangeNotSupportedError:
                # The server stopped honouring Range; degrade to one stream.
                self.supports_range = False
                self.segments = [Segment(0, 0, max(0, self.total_size - 1))]
                self._preallocate()
                self._download_single()
                return self._single_complete
            return all(s.done for s in self.segments)
        self._download_single()
        return self._single_complete

    def _check_complete(self) -> None:
        """N3: refuse to call a short download complete.

        The server told us how many bytes to expect; if fewer arrived the file
        is truncated, so the job fails loudly instead of being reported as
        done. The partial file is kept so the user can resume it."""
        if self.total_size <= 0:
            return
        if self.downloaded == self.total_size:
            return
        raise VerificationError(
            f"incomplete download: expected {self.total_size} bytes, "
            f"got {self.downloaded}")

    # -- streaming media (N10) ---------------------------------------------
    def _looks_like_playlist(self, content_type: str, url: str) -> bool:
        """True when the response is a stream playlist, not a file."""
        kind = (content_type or "").split(";")[0].strip().lower()
        if kind in ("application/vnd.apple.mpegurl", "application/x-mpegurl",
                    "audio/mpegurl", "application/dash+xml"):
            return True
        return is_stream_url(url)

    def _fetch_playlist(self, url: str):
        """Download and parse one playlist."""
        response = self.session.get(
            url, headers=self._session_headers(),
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            proxies=self._proxies_for(url),
            verify=self.verify_ssl, allow_redirects=True)
        try:
            text = response.text
            final = response.url or url
            kind = (response.headers.get("Content-Type") or "").lower()
        finally:
            response.close()
        if "dash+xml" in kind or final.lower().endswith(".mpd"):
            return parse_mpd(text, final)
        return parse_m3u8(text, final)

    def _load_playlist(self):
        """The playlist of this stream (a master playlist is followed)."""
        playlist = self._fetch_playlist(self._request_url)
        if playlist.is_master:
            best = playlist.best_variant()
            if best is None:
                raise StreamError("the master playlist has no variants")
            playlist = self._fetch_playlist(best.url)
        return playlist

    def _run_stream(self) -> bool:
        """Download a stream's segments into the .part file.

        The segments are written one after the other, so the result is the
        whole stream in one file. A small sidecar remembers what is already
        on disk, so an interrupted stream continues instead of starting over.
        """
        playlist = self._load_playlist()
        segments = playlist.segments
        if not segments:
            raise StreamError("the playlist contains no segments")
        self.stream_playlist = playlist
        self.stream_segments = len(segments)
        self.stream_encrypted = playlist.encrypted

        state_file = (self.state_path or "") + ".stream.json"
        sizes = self._read_stream_state(state_file)
        skip = min(len(sizes), len(segments))
        done_bytes = sum(sizes[:skip])
        if done_bytes and os.path.exists(self.part_path or ""):
            try:
                with open(self.part_path, "r+b") as fh:
                    fh.truncate(done_bytes)
            except OSError:
                skip, done_bytes = 0, 0

        appending = bool(done_bytes) and os.path.exists(self.part_path or "")
        with open(self.part_path, "ab" if appending else "wb") as out:
            if not appending:
                self.downloaded = 0
            for index in range(skip, len(segments)):
                data = self._fetch_segment(segments[index], index)
                out.write(data)
                done_bytes += len(data)
                self.downloaded = done_bytes
                self._store_save()
                self._save_stream_state(state_file, segments, index + 1)
        self.total_size = max(self.total_size, done_bytes)
        return True

    def _read_stream_state(self, path: str) -> list[int]:
        """The sizes of the segments already written (for a resume)."""
        if not path or not os.path.exists(path):
            return []
        try:
            import json
            with open(path, "r", encoding="utf-8") as fh:
                saved = json.load(fh)
            if saved.get("url") != self.url:
                return []
            return [int(s) for s in saved.get("sizes", [])]
        except (OSError, ValueError, TypeError):
            return []

    def _save_stream_state(self, path: str, segments, count: int) -> None:
        """Remember what is on disk, so an interrupted stream can continue."""
        if not path:
            return
        try:
            import json
            sizes = self._read_stream_state(path)
            while len(sizes) < count:
                sizes.append(0)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"url": self.url, "sizes": sizes[:count]}, fh)
        except OSError:
            pass

    def _stream_headers(self, url: str) -> dict:
        """The user's own headers only go to the playlist's own host.

        A playlist is data from a third party: it must not be able to make
        FreeDM send the user's ``Authorization`` (or ``Referer``) header to a
        host the user never chose."""
        if stream_host_of(url) == stream_host_of(self._request_url):
            return self._session_headers()
        return {}

    def _check_stream_url(self, url: str) -> str:
        """Apply the playlist URL policy (see freedm/stream.py)."""
        return check_segment_url(url, self._request_url,
                                allow_private=bool(self.allow_private_segments))

    def _fetch_segment(self, segment, index: int) -> bytes:
        """Fetch one segment, decrypting it when the playlist says so."""
        segment.url = self._check_stream_url(segment.url)
        headers = self._stream_headers(segment.url)
        if segment.byte_range:
            length, offset = segment.byte_range
            headers["Range"] = f"bytes={offset}-{offset + length - 1}"
        attempt = 0
        while True:
            try:
                response = self.session.get(
                    segment.url, headers=headers,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    proxies=self._proxies_for(segment.url),
                    verify=self.verify_ssl, allow_redirects=True)
                try:
                    if response.status_code >= 400:
                        raise IOError(f"HTTP {response.status_code}")
                    data = response.content
                finally:
                    response.close()
                break
            except Exception as exc:      # noqa: BLE001
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise IOError(f"segment {index} failed: {exc}") from exc
                time.sleep(min(2 ** attempt * 0.5, 10))
        if segment.key_url:
            key = self._fetch_key(segment)
            iv = segment.key_iv or index.to_bytes(16, "big")
            data = decrypt_aes128(data, key, iv)
        return data

    def _fetch_key(self, segment) -> bytes:
        """Fetch an AES-128 key."""
        segment.key_url = self._check_stream_url(segment.key_url)
        response = self.session.get(
            segment.key_url, headers=self._stream_headers(segment.key_url),
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            proxies=self._proxies_for(segment.key_url),
            verify=self.verify_ssl, allow_redirects=True)
        try:
            data = response.content
        finally:
            response.close()
        return key_from_data(segment.key_url, data)

    def _reset_for_restart(self) -> None:
        """Discard partial data after the remote file changed, then re-probe."""
        for p in (self.part_path, self.state_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        keep_name = self.filename
        self._probe()
        self.filename = keep_name
        self.downloaded = 0
        self._single_complete = False
        self._worker_error = None
        self._abort.clear()
        self._resuming = False
        self.split_count = 0
        if self.supports_range:
            self.segments = self._make_segments()
        else:
            self.segments = [Segment(0, 0, max(0, self.total_size - 1))]
        self._preallocate()

    def _session_headers(self) -> dict:
        # The cookie is carried by the jar, not as a raw header: a raw
        # `Cookie` header is dropped on every redirect and would be sent to
        # any host the session talks to.
        return {name: value for name, value in self.headers.items()
                if name.lower() != "cookie"}

    # -- N7: proxy and mirrors ---------------------------------------------
    def _proxies_for(self, url: str) -> dict | None:
        """Per-request proxy override (``None`` = use the session's)."""
        return PROXY.proxies_for(url)

    def set_mirrors(self, mirrors: list[str] | None) -> None:
        """Set the alternative sources for this job (mirror base URLs)."""
        clean = []
        for item in (mirrors or []):
            text = str(item).strip()
            if text and text not in clean:
                clean.append(text)
        self.mirrors = clean
        self._source_index = 0
        self._store_save()

    @property
    def _source_count(self) -> int:
        return 1 + len(self.mirrors)

    def _advance_source(self) -> bool:
        """Move to the next mirror. True when there was one."""
        if self._source_index + 1 >= self._source_count:
            self._source_index = 0
            return False
        self._source_index += 1
        return True

    @property
    def _source_url(self) -> str:
        """The URL of the source currently in use."""
        if self._source_index == 0:
            return self.final_url or self.url
        return mirror_path(self.mirrors[self._source_index - 1],
                           self.final_url or self.url)

    @property
    def _request_url(self) -> str:
        """URL after redirects, so signed/CDN URLs are requested directly."""
        return self.final_url or self.url

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

    def set_start_at(self, when: float | None) -> None:
        """Set (or clear) the moment this job should start (Unix timestamp).

        A time in the future keeps the job in the ``scheduled`` state; the
        scheduler starts it when the time comes. The value is persisted so a
        scheduled job survives a restart."""
        self.start_at = float(when) if when else None
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

    def _apply_cookies(self, cookies) -> None:
        if not cookies:
            return
        if isinstance(cookies, str):
            jar = {}
            for part in cookies.split(";"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    jar[key.strip()] = value.strip()
            self.session.cookies.update(requests.utils.cookiejar_from_dict(jar))
        elif isinstance(cookies, dict):
            self.session.cookies.update(requests.utils.cookiejar_from_dict(cookies))
        else:
            for c in cookies:
                if not isinstance(c, dict):
                    continue
                try:
                    self.session.cookies.set(
                        str(c.get("name", "")), str(c.get("value", "")),
                        domain=str(c.get("domain") or ""),
                        path=str(c.get("path") or "/"))
                except (AttributeError, ValueError):
                    # Malformed cookie entries (e.g. missing domain) are skipped
                    # rather than aborting the whole download.
                    continue

    def _apply_cookie_header(self) -> None:
        """Move a hand-written ``Cookie:`` header into the cookie jar.

        ``requests`` drops a raw ``Cookie`` header whenever it follows a
        redirect, and a session-level header is sent to *every* host the
        session talks to. Putting the value in the jar instead means it
        survives redirects to the same host and is never sent anywhere else.

        The header itself stays in ``self.headers`` so it is still saved with
        the job and restored on the next start; it is only kept out of the
        raw request headers."""
        raw = None
        for name, value in self.headers.items():
            if name.lower() == "cookie":
                raw = value
                break
        if not raw:
            return
        # The session must not send it raw.
        for name in list(self.session.headers):
            if name.lower() == "cookie":
                self.session.headers.pop(name, None)
        jar = {}
        for part in str(raw).split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                key, value = key.strip(), value.strip()
                if key:
                    jar[key] = value
        if not jar:
            return
        try:
            host = urlparse(self.final_url or self.url).hostname or ""
        except ValueError:
            host = ""
        if not host:
            return
        for key, value in jar.items():
            try:
                self.session.cookies.set(
                    key, value, domain=host, path="/")
            except (AttributeError, ValueError):
                continue

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

    def _validator_changed(self) -> bool:
        """True if a fresh HEAD shows a different ETag/Last-Modified."""
        if not self.validator:
            return False
        try:
            r = self.session.head(self._request_url, headers=self._session_headers(),
                                  allow_redirects=True,
                                  timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                                  proxies=self._proxies_for(self._request_url),
                                  verify=self.verify_ssl)
            current = r.headers.get("ETag") or r.headers.get("Last-Modified")
        except Exception:       # noqa: BLE001
            return False
        return bool(current and current != self.validator)

    def _source_base_url(self) -> str:
        """The URL of the source currently selected (primary or a mirror)."""
        if self._source_index == 0:
            return self.url
        return mirror_path(self.mirrors[self._source_index - 1], self.url)

    def _probe(self) -> None:
        """Figure out total size, range support, filename and final URL.

        N7: each source is tried in turn - the primary first, then the
        mirrors - so a dead primary does not fail the whole download."""
        size = 0
        accept_ranges = False
        fname = None
        auth_status = None
        content_type = ""
        final_url = self.final_url

        for index in range(self._source_count):
            self._source_index = index
            url = self._source_base_url()
            size = 0
            accept_ranges = False
            fname = None
            auth_status = None
            found_url = self.final_url

            # 1) HEAD request
            try:
                r = self.session.head(url, headers=self._session_headers(),
                                      allow_redirects=True,
                                      timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                                      proxies=self._proxies_for(url),
                                      verify=self.verify_ssl)
                found_url = r.url or found_url
                if r.status_code in (401, 403):
                    auth_status = r.status_code
                elif r.status_code < 400:
                    size = int(r.headers.get("Content-Length", 0) or 0)
                    content_type = r.headers.get("Content-Type", "")
                    accept_ranges = (r.headers.get("Accept-Ranges", "")
                                     .lower() == "bytes")
                    fname = self._filename_from_headers(r.headers)
                    self.etag = r.headers.get("ETag") or self.etag
                    self.last_modified = (r.headers.get("Last-Modified")
                                          or self.last_modified)
            except Exception:       # noqa: BLE001
                pass

            # 2) Fall back to a tiny ranged GET if HEAD was not conclusive
            if not accept_ranges or size == 0:
                try:
                    h = self._session_headers()
                    h["Range"] = "bytes=0-0"
                    r = self.session.get(self._source_url, headers=h,
                                         stream=True, allow_redirects=True,
                                         timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                                         proxies=self._proxies_for(self._source_url),
                                         verify=self.verify_ssl)
                    try:
                        found_url = r.url or found_url
                        content_type = content_type or r.headers.get(
                            "Content-Type", "")
                        if r.status_code in (401, 403):
                            auth_status = r.status_code
                        self.etag = r.headers.get("ETag") or self.etag
                        self.last_modified = (r.headers.get("Last-Modified")
                                              or self.last_modified)
                        if r.status_code == 206:
                            accept_ranges = True
                            cr = r.headers.get("Content-Range", "")
                            if "/" in cr:
                                total = cr.rsplit("/", 1)[-1]
                                if total.isdigit():
                                    size = int(total)
                            fname = fname or self._filename_from_headers(r.headers)
                        elif r.status_code == 200:
                            size = int(r.headers.get("Content-Length", 0) or size)
                            fname = fname or self._filename_from_headers(r.headers)
                    finally:
                        r.close()
                except Exception:       # noqa: BLE001
                    pass

            if size or accept_ranges or auth_status:
                final_url = found_url
                break

        self.final_url = final_url
        if auth_status and size == 0:
            raise AuthRequiredError(
                f"HTTP {auth_status}: the server requires cookies or headers "
                f"(e.g. Cookie, Referer, Authorization) for {self.url}")

        self.total_size = size
        self.supports_range = accept_ranges and size > 0
        self.validator = self.etag or self.last_modified
        if fname and not self.filename:
            self.filename = sanitize_filename(fname)
        # N10: a playlist is not a file - it points at many segments.
        self.is_stream = self._looks_like_playlist(content_type, self.url)
        if self.is_stream:
            self.supports_range = False
            self.total_size = 0
            if not self.filename:
                self.filename = sanitize_filename(
                    stream_output_name(self.url, container=".ts"))

    @staticmethod
    def _filename_from_headers(headers) -> str | None:
        cd = headers.get("Content-Disposition", "")
        if cd:
            m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.I)
            if not m:
                m = re.search(r'filename=\s*"?([^";]+)"?', cd, re.I)
            if m:
                return unquote(m.group(1).strip().strip('"'))
        return None

    def _guess_filename(self) -> str:
        parsed = urlparse(self.url)
        name = unquote(os.path.basename(parsed.path))
        if not name:
            host = parsed.netloc.split("@")[-1] or "download"
            name = host
        return sanitize_filename(name)

    def _prepare_files(self) -> None:
        base = self.filename or self._guess_filename()
        self.filename = base
        if self.dest_resolver is not None:
            # N5: the final name is only known after the probe, so the
            # category folder can only be chosen now.
            try:
                resolved = self.dest_resolver(base)
            except Exception:       # noqa: BLE001 - keep the current folder
                resolved = None
            if resolved:
                self.dest_dir = os.path.abspath(resolved)
        os.makedirs(self.dest_dir, exist_ok=True)
        self.path = os.path.join(self.dest_dir, base)
        self._apply_existing_policy()
        self.part_path = self.path + ".part"
        self.state_path = self.path + ".part.state.json"

        # Build segments based on the probe result
        if self.supports_range:
            self.segments = self._make_segments()
        else:
            self.segments = [Segment(0, 0, max(0, self.total_size - 1))]

        # Try to resume from an existing state file
        if not self._load_state() and not self._load_db_segments():
            self._preallocate()

    def _apply_existing_policy(self) -> None:
        """Never silently destroy an existing file.

        Policy is chosen per download: 'rename' (default), 'overwrite',
        'cancel', or a confirm_overwrite callback returning one of those.
        """
        if not self.path or not os.path.exists(self.path):
            return
        action = self.on_existing
        if self.confirm_overwrite is not None:
            action = self.confirm_overwrite(self.path) or "cancel"
        if action == "cancel":
            raise DownloadCanceled(
                f"destination already exists and overwrite was declined: {self.path}")
        if action == "overwrite":
            return
        self.path = self._unique_path(self.path)
        self.filename = os.path.basename(self.path)

    @staticmethod
    def _unique_path(path: str) -> str:
        """Return 'name (1).ext', 'name (2).ext', ... so nothing is clobbered."""
        root, ext = os.path.splitext(path)
        i = 1
        while True:
            candidate = f"{root} ({i}){ext}"
            if not os.path.exists(candidate) and not os.path.exists(candidate + ".part"):
                return candidate
            i += 1

    def _make_segments(self) -> list[Segment]:
        size = self.total_size
        n = self.num_threads
        if size <= MIN_SEGMENT_SIZE:
            n = 1
        else:
            n = min(self.num_threads * 4, max(self.num_threads, size // MIN_SEGMENT_SIZE))
        n = max(1, int(n))
        # N4: no single piece may be larger than MAX_PIECE_SIZE, so a slow
        # connection can only hold back a bounded amount of the file.
        if size > MAX_PIECE_SIZE:
            n = max(n, -(-size // MAX_PIECE_SIZE))

        base = size // n
        segs: list[Segment] = []
        start = 0
        for i in range(n):
            end = size - 1 if i == n - 1 else start + base - 1
            segs.append(Segment(i, start, end))
            start = end + 1
        return segs

    def _preallocate(self) -> None:
        if self.supports_range and self.total_size > 0:
            self._check_disk_space(self.total_size)
            with open(self.part_path, "wb") as f:
                f.seek(self.total_size - 1)
                f.write(b"\0")
        else:
            # truncate any stale partial file
            with open(self.part_path, "wb"):
                pass
        self.downloaded = 0
        self._save_state()

    def _check_disk_space(self, needed: int) -> None:
        try:
            free = shutil.disk_usage(self.dest_dir).free
        except OSError:
            return
        if free < needed + DISK_MARGIN:
            raise IOError(
                f"not enough disk space: need {human_size(needed)} "
                f"(+{human_size(DISK_MARGIN)} headroom), only "
                f"{human_size(free)} free in {self.dest_dir}")

    # -- state persistence -------------------------------------------------
    def _save_state(self) -> None:
        if not self.state_path:
            return
        # N4: workers split pieces while this runs, so snapshot the list
        # under the lock before serialising it.
        with self._lock:
            segs = [s.to_dict() for s in self.segments]
        data = {
            "url": self.url,
            "final_url": self.final_url,
            "total_size": self.total_size,
            "supports_range": self.supports_range,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "segments": segs,
        }
        tmp = self.state_path + ".tmp"
        with self._state_lock:
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.replace(tmp, self.state_path)
            except OSError:
                pass
        self._store_save()

    def _load_state(self) -> bool:
        if not self.state_path or not os.path.exists(self.state_path):
            return False
        if not os.path.exists(self.part_path):
            return False
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False
        if data.get("url") != self.url:
            return False

        # Refuse to resume if the remote file changed (size or validator).
        stored_size = int(data.get("total_size", 0) or 0)
        if self.total_size and stored_size and stored_size != self.total_size:
            return False
        stored_etag = data.get("etag")
        stored_lm = data.get("last_modified")
        if stored_etag and self.etag and stored_etag != self.etag:
            return False
        if stored_lm and self.last_modified and stored_lm != self.last_modified:
            return False

        segs = [Segment.from_dict(d) for d in data.get("segments", [])]
        if not segs:
            return False
        if not self._pieces_are_valid(segs, stored_size):
            return False
        self.segments = segs
        if not self.total_size:
            self.total_size = stored_size
        self.supports_range = data.get("supports_range", self.supports_range)
        self.final_url = data.get("final_url") or self.final_url
        self.downloaded = sum(s.downloaded for s in self.segments)
        self._single_complete = False
        self._resuming = True
        return True

    @staticmethod
    def _pieces_are_valid(segs: list[Segment], total_size: int = 0) -> bool:
        """True when the pieces tile the file exactly: no gaps, no overlaps.

        N4 splits pieces while downloading, so a resume must be able to
        trust the stored layout. Anything that does not tile the file is
        refused, which makes the engine restart cleanly instead of
        producing a corrupt file."""
        if not segs:
            return False
        segs = sorted(segs, key=lambda s: s.start)
        if segs[0].start != 0:
            return False
        previous_end = -1
        for s in segs:
            if s.start != previous_end + 1:
                return False
            if s.end < s.start:
                return False
            if s.downloaded < 0 or s.downloaded > s.size:
                return False
            previous_end = s.end
        if total_size and previous_end != total_size - 1:
            return False
        return True

    def _load_db_segments(self) -> bool:
        """Resume from the queue DB when the JSON sidecar is unavailable.

        The DB is authoritative for the queue, but only trust its ranges when
        the `.part` payload exists, the ranges tile the probed size, and the
        stored validators still match the live file.
        """
        if not self.store or not self.job_id or not self.part_path:
            return False
        if not os.path.exists(self.part_path):
            return False
        if self._stored_size and self.total_size and \
                self._stored_size != self.total_size:
            return False
        if self._stored_etag and self.etag and \
                self._stored_etag != self.etag:
            return False
        if self._stored_last_modified and self.last_modified and \
                self._stored_last_modified != self.last_modified:
            return False
        rows = self.store.load_segments(self.job_id)
        if not rows:
            return False
        segs: list[Segment] = []
        for r in rows:
            try:
                segs.append(Segment(int(r["idx"]), int(r["start"]),
                                    int(r["end"]), int(r["downloaded"])))
            except (KeyError, TypeError, ValueError):
                return False
        segs.sort(key=lambda s: s.start)
        if self.total_size:
            if not self._pieces_are_valid(segs, self.total_size):
                return False
        elif not self._pieces_are_valid(segs):
            return False
        self.segments = segs
        self.downloaded = sum(s.downloaded for s in segs)
        self._resuming = True
        return True

    # -- monitor / speed ---------------------------------------------------
    def _start_monitor(self) -> None:
        if self._monitor is not None and self._monitor.is_alive():
            return
        self._last_bytes = self.downloaded
        self._last_time = time.monotonic()

        def loop() -> None:
            while not self._cancel.is_set() and self.status not in (DONE, ERROR, CANCELED):
                time.sleep(0.5)
                cur = self.downloaded
                now = time.monotonic()
                dt = now - self._last_time
                if dt > 0:
                    self.speed = (cur - self._last_bytes) / dt
                self._last_bytes = cur
                self._last_time = now
                if self.status == DOWNLOADING:
                    self._save_state()

        self._monitor = threading.Thread(target=loop, daemon=True)
        self._monitor.start()

    # -- segmented engine (N4: dynamic segmentation) -----------------------
    def _prepare_pending(self) -> None:
        """Build the pending work set from the current pieces."""
        with self._lock:
            self._pending = {}
            for s in self.segments:
                if not s.done:
                    self._pending[s.index] = s
            self._next_index = max(
                (s.index for s in self.segments), default=-1) + 1
            self.initial_piece_count = len(self.segments)

    def _piece_target(self) -> int:
        """How many bytes a piece should hold (adaptive, N4).

        The target follows the *slowest* recent connection, not the average:
        one slow pipe is what decides when the file is really finished, so
        the pieces handed out stay small enough that a stalled connection
        can only hold back a little data. A fast link raises the target, so
        large files need fewer requests."""
        with self._lock:
            samples = list(self._piece_speeds)
        if not samples:
            # Nothing measured yet: be conservative so the very first pieces
            # are already small enough to be safe on a slow connection.
            return MIN_PIECE_SIZE
        target = int(min(samples) * SPLIT_TARGET_SECONDS)
        return max(MIN_PIECE_SIZE, min(MAX_PIECE_SIZE, target))

    def _note_piece_speed(self, nbytes: int, seconds: float) -> None:
        """Remember how fast the last piece was (drives the piece size)."""
        if nbytes <= 0 or seconds <= 0:
            return
        speed = nbytes / seconds
        with self._lock:
            self._piece_speeds.append(speed)
            if len(self._piece_speeds) > PIECE_SPEED_SAMPLES:
                del self._piece_speeds[:-PIECE_SPEED_SAMPLES]

    def _split_piece(self, seg: Segment, target: int) -> tuple[Segment, Segment] | None:
        """Split ``seg`` into a head of ~``target`` bytes plus the remainder.

        The already-downloaded bytes are moved to the right piece so the
        total never changes. Returns ``None`` when the piece is too small to
        split safely."""
        head_size = min(target, seg.size - MIN_SPLIT_SIZE)
        if head_size < MIN_SPLIT_SIZE:
            return None
        mid = seg.start + head_size - 1
        head = Segment(self._next_index, seg.start, mid,
                       downloaded=min(seg.downloaded, head_size))
        tail = Segment(self._next_index + 1, mid + 1, seg.end,
                       downloaded=max(0, seg.downloaded - head_size))
        self._next_index += 2
        try:
            pos = self.segments.index(seg)
        except ValueError:
            pos = -1
        if pos >= 0:
            self.segments[pos:pos + 1] = [head, tail]
        else:
            self.segments.extend((head, tail))
            self.segments.sort(key=lambda s: s.start)
        self.split_count += 1
        return head, tail

    def _claim_piece(self) -> Segment | None:
        """Take the next piece of work, splitting a large one when useful.

        The largest pending piece is always preferred, so the remaining work
        stays evenly divided and no single piece can dominate the tail. When
        that piece is much bigger than the adaptive target it is split and
        the worker takes the small half, leaving the rest for later."""
        with self._lock:
            if not self._pending:
                return None
            seg = max(self._pending.values(), key=lambda s: s.remaining)
            target = self._piece_target()
            if (DYNAMIC_SPLITTING
                    and len(self.segments) < MAX_SEGMENTS
                    and seg.remaining > target
                    and seg.size >= 2 * MIN_SPLIT_SIZE):
                pair = self._split_piece(seg, target)
                if pair is not None:
                    head, tail = pair
                    self._pending.pop(seg.index, None)
                    self._pending[tail.index] = tail
                    return head
            self._pending.pop(seg.index, None)
            return seg

    def _download_segmented(self) -> None:
        self._worker_error = None
        self._abort.clear()
        self._prepare_pending()
        n = min(self.num_threads, max(1, len(self._pending)))
        self._workers = []
        for _ in range(n):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self._workers.append(t)
        for t in self._workers:
            t.join()
        if self._worker_error is not None:
            raise self._worker_error

    def _worker(self) -> None:
        while not self._cancel.is_set() and not self._abort.is_set():
            seg = self._claim_piece()
            if seg is None:
                return
            try:
                before = seg.downloaded
                started = time.monotonic()
                self._download_segment(seg)
                self._note_piece_speed(
                    seg.downloaded - before, time.monotonic() - started)
            except Exception as exc:      # noqa: BLE001
                with self._lock:
                    if self._worker_error is None:
                        self._worker_error = exc
                self._abort.set()
                self._pause.set()          # release paused workers
                return

    def _download_segment(self, seg: Segment) -> None:
        attempt = 0
        while (not self._cancel.is_set() and not self._abort.is_set()
               and not seg.done):
            self._pause.wait()
            if self._cancel.is_set() or self._abort.is_set():
                return
            pos = seg.start + seg.downloaded
            headers = self._session_headers()
            headers["Range"] = f"bytes={pos}-{seg.end}"
            if self.validator and self.downloaded > 0:
                headers["If-Range"] = self.validator
            try:
                with self.session.get(self._source_url, headers=headers, stream=True,
                                      timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                                      proxies=self._proxies_for(self._source_url),
                                      verify=self.verify_ssl, allow_redirects=True) as r:
                    if r.status_code in (401, 403):
                        raise AuthRequiredError(
                            f"HTTP {r.status_code}: authorization expired or "
                            f"missing; cookies/headers are required")
                    if r.status_code == 416:      # already have everything
                        with self._lock:
                            self.downloaded += seg.remaining
                            seg.downloaded = seg.size
                        return
                    if r.status_code in (429, 503):
                        attempt += 1
                        if attempt > MAX_RETRIES:
                            raise IOError(
                                f"HTTP {r.status_code} after {MAX_RETRIES} retries")
                        wait = self._parse_retry_after(
                            r.headers.get("Retry-After"), attempt)
                        if not self._sleep_cancelable(wait):
                            return
                        continue
                    if r.status_code == 200:
                        # Either the file changed (If-Range did not match) or
                        # the server ignored our Range request.
                        if self._validator_changed():
                            raise FileChangedError(
                                "remote file changed during the download")
                        raise RangeNotSupportedError(
                            "server does not honour Range requests")
                    if r.status_code != 206:
                        raise IOError(f"HTTP {r.status_code}")
                    with open(self.part_path, "r+b") as f:
                        f.seek(pos)
                        for chunk in r.iter_content(CHUNK):
                            if self._cancel.is_set() or self._abort.is_set():
                                return
                            self._pause.wait()
                            if self._cancel.is_set() or self._abort.is_set():
                                return
                            if not chunk:
                                continue
                            self.rate.consume(len(chunk))
                            GLOBAL_LIMITER.consume(len(chunk))
                            f.write(chunk)
                            with self._lock:
                                seg.downloaded += len(chunk)
                                self.downloaded += len(chunk)
                attempt = 0
            except (FileChangedError, RangeNotSupportedError, AuthRequiredError):
                raise
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as exc:
                # N7: the source is unreachable - try a mirror before giving up.
                if self._advance_source():
                    continue
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise IOError(f"segment {seg.index} failed: {exc}") from exc
                time.sleep(min(2 ** attempt * 0.5, 10))
            except Exception as exc:      # noqa: BLE001
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise IOError(f"segment {seg.index} failed: {exc}") from exc
                time.sleep(min(2 ** attempt * 0.5, 10))

    # -- single-stream engine ---------------------------------------------
    def _download_single(self) -> None:
        resume = (self.supports_range and self.downloaded > 0
                  and os.path.exists(self.part_path))
        attempt = 0
        while not self._cancel.is_set() and not self._abort.is_set():
            self._pause.wait()
            if self._cancel.is_set() or self._abort.is_set():
                return
            headers = self._session_headers()
            mode = "ab" if resume else "wb"
            if resume:
                headers["Range"] = f"bytes={self.downloaded}-"
                if self.validator:
                    headers["If-Range"] = self.validator
            else:
                self.downloaded = 0
            try:
                with self.session.get(self._source_url, headers=headers, stream=True,
                                      timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                                      proxies=self._proxies_for(self._source_url),
                                      verify=self.verify_ssl, allow_redirects=True) as r:
                    if r.status_code in (401, 403):
                        raise AuthRequiredError(
                            f"HTTP {r.status_code}: authorization expired or "
                            f"missing; cookies/headers are required")
                    if resume and r.status_code == 200:
                        if self._validator_changed():
                            raise FileChangedError(
                                "remote file changed during the download")
                        # Server ignored If-Range; restart cleanly from zero.
                        self.downloaded = 0
                        resume = False
                        continue
                    if r.status_code in (429, 503):
                        attempt += 1
                        if attempt > MAX_RETRIES:
                            raise IOError(
                                f"HTTP {r.status_code} after {MAX_RETRIES} retries")
                        wait = self._parse_retry_after(
                            r.headers.get("Retry-After"), attempt)
                        if not self._sleep_cancelable(wait):
                            return
                        continue
                    if r.status_code not in (200, 206):
                        raise IOError(f"HTTP {r.status_code}")
                    if self.total_size == 0:
                        if r.status_code == 206 and "Content-Range" in r.headers:
                            total = r.headers["Content-Range"].rsplit("/", 1)[-1]
                            if total.isdigit():
                                self.total_size = int(total)
                        else:
                            self.total_size = int(r.headers.get("Content-Length", 0) or 0)
                    with open(self.part_path, mode) as f:
                        for chunk in r.iter_content(CHUNK):
                            if self._cancel.is_set() or self._abort.is_set():
                                return
                            self._pause.wait()
                            if self._cancel.is_set() or self._abort.is_set():
                                return
                            if not chunk:
                                continue
                            self.rate.consume(len(chunk))
                            GLOBAL_LIMITER.consume(len(chunk))
                            f.write(chunk)
                            with self._lock:
                                self.downloaded += len(chunk)
                self._single_complete = True
                return
            except (FileChangedError, RangeNotSupportedError, AuthRequiredError):
                raise
            except Exception as exc:      # noqa: BLE001
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise IOError(f"download failed: {exc}") from exc
                time.sleep(min(2 ** attempt * 0.5, 10))

    # -- finishing ---------------------------------------------------------
    def _finalize(self) -> None:
        # Windows can briefly refuse the rename while an indexer/AV or a
        # just-closed worker handle still has the .part open. Retry, then fail.
        last_exc: OSError | None = None
        for attempt in range(6):
            try:
                os.replace(self.part_path, self.path)
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.2)
        if last_exc is not None:
            raise last_exc
        if self.state_path and os.path.exists(self.state_path):
            try:
                os.remove(self.state_path)
            except OSError:
                pass
        # N10: the stream sidecar goes with the state file.
        stream_state = (self.state_path or "") + ".stream.json"
        if stream_state and os.path.exists(stream_state):
            try:
                os.remove(stream_state)
            except OSError:
                pass
        self.finished_at = time.time()
        self.downloaded = self.total_size or self.downloaded
        self.speed = 0.0
        # N3: the file is complete on disk - now prove it (size + checksum).
        self._verify_result()
        self.status = DONE

    # -- verification (N3) -------------------------------------------------
    def _verify_result(self) -> None:
        """Check the finished file's size and optional checksum.

        Raises :class:`VerificationError` with a clear, user-facing message
        when the file is short/long or the checksum does not match. The file
        itself is never deleted - the user may still want it."""
        path = self.path
        if not path or not os.path.exists(path):
            raise VerificationError("the finished file is missing")
        ok, message = verify_size(path, self.total_size)
        if not ok:
            self.checksum_result = message
            raise VerificationError(message)
        if self.checksum:
            ok, message, _status = verify_checksum(path, self.checksum)
            self.checksum_result = message
            if not ok:
                raise VerificationError(message)

    def verify_now(self) -> tuple[bool, str]:
        """Re-run size/checksum verification on the finished file.

        Returns ``(ok, message)``. A finished job that fails verification is
        marked ``error``; a job that is not finished keeps its status."""
        was_done = self.status == DONE
        try:
            self._verify_result()
        except VerificationError as exc:
            self.checksum_result = str(exc)
            if was_done:
                self.status = ERROR
                self.error = str(exc)
            self._store_save()
            return False, str(exc)
        if was_done:
            self.error = None
            self._store_save()
        return True, self.checksum_result

    def set_checksum(self, spec: str) -> tuple[bool, str]:
        """Set the expected checksum ("sha256:ab12...") and re-verify.

        Returns ``(ok, message)``; an invalid checksum is rejected with an
        explanation and nothing is changed."""
        try:
            algo, digest = parse_checksum(spec)
        except ValueError as exc:
            return False, str(exc)
        self.checksum = f"{algo}:{digest}" if algo else ""
        self._store_save()
        if self.status == DONE and self.path:
            return self.verify_now()
        return True, f"{algo} checksum set" if algo else "checksum cleared"

    def _cleanup_partial(self) -> None:
        for p in (self.part_path, self.state_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        self.speed = 0.0
        self.downloaded = 0
        self.segments = []
        self._single_complete = False
        self._needs_prepare = True

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
