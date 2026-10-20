"""Opt-in rotating log file (N9, roadmap P7.8).

The log is **off by default**: FreeDM writes nothing about the user unless
the user turns it on (the **About** dialog). When it is on, the log lives in
``%APPDATA%\\FreeDM\\freedm.log``, is rotated at 2 MB and three old files are
kept - enough for a bug report, small enough to forget about.

The log records the app's own events (start, errors, settings changes); it
never records URLs, file names, cookies or tokens.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import threading

from freedm.store import app_data_dir

LOG_NAME = "freedm.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3

_lock = threading.Lock()
_configured = False


def log_path() -> str:
    """Where the log file lives."""
    return os.path.join(app_data_dir(), LOG_NAME)


def enable(enabled: bool = True) -> str:
    """Turn the log file on or off. Returns the log path."""
    global _configured
    with _lock:
        root = logging.getLogger("freedm")
        for handler in list(root.handlers):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:       # noqa: BLE001
                pass
        _configured = False
        if not enabled:
            root.addHandler(logging.NullHandler())
            return log_path()
        try:
            os.makedirs(app_data_dir(), exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                log_path(), maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                encoding="utf-8")
        except OSError:
            root.addHandler(logging.NullHandler())
            return log_path()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        _configured = True
        return log_path()


def is_enabled() -> bool:
    """True when the log file is being written."""
    return _configured


def get_logger(name: str = "freedm") -> logging.Logger:
    """The logger to use inside the app."""
    return logging.getLogger(name)


def log_exception(message: str, exc: BaseException) -> None:
    """Record an exception without letting it escape."""
    try:
        get_logger().exception("%s: %s", message, exc)
    except Exception:               # noqa: BLE001 - logging must never fail
        pass
