# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Part of the Download class: The download loops: the probe, the workers and the monitor"""
from __future__ import annotations

import os
import threading
import time

import requests

from freedm.engine.constants import (CANCELED, CHUNK,
                                   CONNECT_TIMEOUT, DONE,
                                   DOWNLOADING, ERROR, PAUSED,
                                   PROBING, MAX_RETRIES, READ_TIMEOUT)
from freedm.engine.limits import GLOBAL_LIMITER
from freedm.engine.formatting import sanitize_filename
from freedm.stream import output_name as stream_output_name
from freedm.engine.errors import (AuthRequiredError,
                                       DownloadCanceled,
                                       FileChangedError,
                                       RangeNotSupportedError)
from freedm.engine.segments import Segment


class WorkersMixin:
    """The download loops: the probe, the workers and the monitor
that keeps the progress and the speed up to date."""

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
