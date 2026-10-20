# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Part of the Download class: The destination file and the resume state (W3, W5)."""
from __future__ import annotations

import json
import os
import shutil
import time

from freedm.engine.constants import DISK_MARGIN, DONE
from urllib.parse import unquote, urlparse
import re
from freedm.engine.errors import DownloadCanceled
from freedm.engine.formatting import human_size, sanitize_filename
from freedm.engine.segments import Segment


class FilesMixin:
    """The destination file and the resume state (W3, W5).

The state sidecar lives next to the file; the overwrite policy
and the disk-space check live here too."""

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
