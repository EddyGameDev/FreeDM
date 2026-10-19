# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Persistent job store for FreeDM (W3).

SQLite database that records the download queue, status transitions and
segment offsets so the queue survives app restarts and reboots.

Design rules:
- The database is a *queue index*, not the payload. The bytes stay in the
  destination `.part` file; the `.part.state.json` sidecar remains a crash
  fallback.
- Every write is best-effort: a database failure must never abort or corrupt
  an in-progress download. Errors are captured in ``last_error``.
- One connection guarded by a re-entrant lock; SQLite serialises writers and
  the volume here is tiny (a few rows twice a second).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

APP_DIR_NAME = "FreeDM"
DB_FILE_NAME = "freedm.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT    NOT NULL,
    final_url     TEXT,
    dest_dir      TEXT,
    filename      TEXT,
    size          INTEGER DEFAULT 0,
    downloaded    INTEGER DEFAULT 0,
    threads       INTEGER DEFAULT 8,
    speed_limit   REAL    DEFAULT 0,
    checksum      TEXT    DEFAULT '',
    checksum_result TEXT  DEFAULT '',
    start_at      REAL    DEFAULT 0,
    mirrors       TEXT    DEFAULT '[]',
    status        TEXT    DEFAULT 'idle',
    headers_json  TEXT    DEFAULT '{}',
    etag          TEXT,
    last_modified TEXT,
    error         TEXT,
    created_at    REAL,
    updated_at    REAL
);
CREATE TABLE IF NOT EXISTS segments (
    download_id INTEGER NOT NULL,
    idx         INTEGER NOT NULL,
    start       INTEGER NOT NULL,
    end         INTEGER NOT NULL,
    downloaded  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (download_id, idx)
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_downloads_created ON downloads(created_at);
"""


def app_data_dir() -> str:
    """Per-user FreeDM data directory (queue, token, exported extension)."""
    override = os.environ.get("FREEDM_HOME")
    if override:
        return override
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_DIR_NAME)


def default_db_path() -> str:
    """Return the per-user database path.

    ``FREEDM_DB`` overrides it (used by tests). ``FREEDM_DB=:memory:`` is
    supported too.
    """
    override = os.environ.get("FREEDM_DB")
    if override:
        return override
    return os.path.join(app_data_dir(), DB_FILE_NAME)


class JobStore:
    """Thin, thread-safe wrapper around the FreeDM SQLite database."""

    def __init__(self, path: str | None = None):
        self.path = path or default_db_path()
        self.last_error: str | None = None
        self._lock = threading.RLock()
        if self.path != ":memory:":
            parent = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(
            self.path, timeout=10, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_SCHEMA)
            self._migrate()
            self._conn.commit()
        except sqlite3.Error as exc:       # pragma: no cover - rare
            self.last_error = str(exc)

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created.

        Older FreeDM databases lack ``speed_limit``/``checksum``; ALTER TABLE
        keeps existing queues usable instead of forcing users to delete their
        history."""
        try:
            cols = {row["name"] for row in
                    self._conn.execute("PRAGMA table_info(downloads)")}
            if "speed_limit" not in cols:
                self._conn.execute(
                    "ALTER TABLE downloads ADD COLUMN speed_limit REAL DEFAULT 0")
            if "checksum" not in cols:
                self._conn.execute(
                    "ALTER TABLE downloads ADD COLUMN checksum TEXT DEFAULT ''")
            if "checksum_result" not in cols:
                self._conn.execute(
                    "ALTER TABLE downloads ADD COLUMN"
                    " checksum_result TEXT DEFAULT ''")
            if "start_at" not in cols:
                self._conn.execute(
                    "ALTER TABLE downloads ADD COLUMN start_at REAL DEFAULT 0")
            if "mirrors" not in cols:
                self._conn.execute(
                    "ALTER TABLE downloads ADD COLUMN mirrors TEXT DEFAULT '[]'")
        except sqlite3.Error as exc:       # pragma: no cover - rare
            self.last_error = str(exc)

    # -- low level ---------------------------------------------------------
    def _write(self, sql: str, params: tuple = ()) -> bool:
        with self._lock:
            try:
                self._conn.execute(sql, params)
                self._conn.commit()
                return True
            except sqlite3.Error as exc:
                self.last_error = str(exc)
                return False

    def _read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            try:
                return list(self._conn.execute(sql, params))
            except sqlite3.Error as exc:
                self.last_error = str(exc)
                return []

    # -- downloads ---------------------------------------------------------
    def add(self, dl: Any) -> int | None:
        """Insert a job row for a ``Download`` and return its id."""
        now = time.time()
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO downloads"
                    " (url, final_url, dest_dir, filename, size, downloaded,"
                    "  threads, speed_limit, checksum, checksum_result, start_at,"
                    "  mirrors, status, headers_json, etag, last_modified, error,"
                    "  created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        dl.url, dl.final_url, dl.dest_dir, dl.filename,
                        int(dl.total_size or 0), int(dl.downloaded or 0),
                        int(dl.num_threads), float(getattr(dl, "speed_limit", 0) or 0),
                        getattr(dl, "checksum", "") or "",
                        getattr(dl, "checksum_result", "") or "",
                        float(getattr(dl, "start_at", 0) or 0),
                        json.dumps(list(getattr(dl, "mirrors", []) or [])),
                        dl.status,
                        json.dumps(dl.headers or {}),
                        dl.etag, dl.last_modified, dl.error, now, now,
                    ),
                )
                self._conn.commit()
                return int(cur.lastrowid)
            except sqlite3.Error as exc:
                self.last_error = str(exc)
                return None

    def save(self, dl: Any) -> bool:
        """Update the row for ``dl``. No-op when it has no job id."""
        job_id = getattr(dl, "job_id", None)
        if not job_id:
            return False
        return self._write(
            "UPDATE downloads SET final_url=?, dest_dir=?, filename=?,"
            " size=?, downloaded=?, threads=?, speed_limit=?, checksum=?,"
            " checksum_result=?, start_at=?, mirrors=?, status=?,"
            " headers_json=?, etag=?, last_modified=?, error=?, updated_at=?"
            " WHERE id=?",
            (
                dl.final_url, dl.dest_dir, dl.filename,
                int(dl.total_size or 0), int(dl.downloaded or 0),
                int(dl.num_threads), float(getattr(dl, "speed_limit", 0) or 0),
                getattr(dl, "checksum", "") or "",
                getattr(dl, "checksum_result", "") or "",
                float(getattr(dl, "start_at", 0) or 0),
                json.dumps(list(getattr(dl, "mirrors", []) or [])),
                dl.status,
                json.dumps(dl.headers or {}),
                dl.etag, dl.last_modified, dl.error, time.time(), job_id,
            ),
        )

    def save_segments(self, job_id: int, segments) -> bool:
        """Replace all segment rows for a job in one transaction."""
        if not job_id:
            return False
        with self._lock:
            try:
                self._conn.execute(
                    "DELETE FROM segments WHERE download_id=?", (job_id,))
                self._conn.executemany(
                    "INSERT INTO segments"
                    " (download_id, idx, start, end, downloaded)"
                    " VALUES (?,?,?,?,?)",
                    [
                        (job_id, s.index, s.start, s.end, s.downloaded)
                        for s in segments
                    ],
                )
                self._conn.commit()
                return True
            except sqlite3.Error as exc:
                self.last_error = str(exc)
                return False

    def update_status(self, job_id: int, status: str,
                      error: str | None = None) -> bool:
        return self._write(
            "UPDATE downloads SET status=?, error=?, updated_at=? WHERE id=?",
            (status, error, time.time(), job_id),
        )

    def get(self, job_id: int) -> dict | None:
        rows = self._read("SELECT * FROM downloads WHERE id=?", (job_id,))
        return dict(rows[0]) if rows else None

    def list_all(self) -> list[dict]:
        """All jobs, oldest first, so the GUI restores the original order."""
        return [dict(r) for r in self._read(
            "SELECT * FROM downloads ORDER BY created_at, id")]

    def delete(self, job_id: int) -> bool:
        with self._lock:
            try:
                self._conn.execute(
                    "DELETE FROM segments WHERE download_id=?", (job_id,))
                self._conn.execute(
                    "DELETE FROM downloads WHERE id=?", (job_id,))
                self._conn.commit()
                return True
            except sqlite3.Error as exc:
                self.last_error = str(exc)
                return False

    def load_segments(self, job_id: int) -> list[dict]:
        return [dict(r) for r in self._read(
            "SELECT idx, start, end, downloaded FROM segments"
            " WHERE download_id=? ORDER BY idx", (job_id,))]

    # -- settings ----------------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        rows = self._read("SELECT value FROM settings WHERE key=?", (key,))
        return rows[0]["value"] if rows else default

    def set_setting(self, key: str, value: str) -> bool:
        return self._write(
            "INSERT INTO settings(key, value) VALUES(?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
