# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Typed settings access for FreeDM (Milestone 2, goal N1).

Settings live in the same SQLite database as the queue (the ``settings``
key/value table), so there is no second file to keep in sync and the queue and
preferences survive together.

This module is deliberately headless - no Tkinter, no threads - so the GUI,
the CLI and the tests all share one definition of the defaults and their types.

Usage::

    from freedm.settings import load, save
    prefs = load(store)            # dict[str, object], typed
    save(store, last_dir="D:/dl", threads=12)

Every accessor tolerates ``store is None`` (the GUI still starts when the
database is unavailable) and falls back to :data:`DEFAULTS`.
"""
from __future__ import annotations

from typing import Any

#: Canonical default values, stored as strings in the ``settings`` table.
DEFAULTS: dict[str, str] = {
    # Queue behaviour
    "auto_resume": "1",
    "max_active": "3",
    "max_connections": "64",
    "max_per_host": "12",
    # W1 browser handoff
    "control_enabled": "1",
    # N1 additions
    "threads": "8",
    "speed_limit": "0",     # bytes/s, 0 = unlimited
    "last_dir": "",         # last "Save to" folder
    "window": "",           # Tk geometry string, e.g. "960x560+120+80"
    # N2 additions
    "clipboard_monitor": "0",   # opt-in: offer links copied to the clipboard
    # N3 additions
    "default_checksum": "",     # expected digest for new downloads
    "cleanup_days": "30",       # age (days) for orphan .part cleanup; 0 = off
    # N4 additions
    "global_speed_limit": "0",  # combined cap for ALL downloads; 0 = off
    # N5 additions
    "auto_sort": "0",           # sort new downloads into category folders
    "category_rules": "",       # user-edited category rules (blank = default)
    "filter_text": "",          # last used search text
    "filter_status": "",        # last used status filter
    # N6 additions
    "window_start": "",         # daily window start, "HH:MM" (blank = no limit)
    "window_end": "",           # daily window end, "HH:MM"
    "shutdown_when_done": "0",  # power off when the queue drains
    "shutdown_mode": "shutdown",  # "shutdown" | "sleep"
    # N7 additions
    "proxy_url": "",            # e.g. http://127.0.0.1:8080
    "proxy_user": "",           # optional proxy user name
    "proxy_pass": "",           # optional proxy password (plain text!)
    "proxy_bypass": "",         # comma separated hosts that skip the proxy
    "prefer_ipv4": "1",         # prefer IPv4 when a host has both
}

#: Keys whose value is an integer.
_INT_KEYS = frozenset({"max_active", "max_connections", "max_per_host", "threads",
                       "cleanup_days"})
#: Keys whose value is a boolean ("1"/"0").
_BOOL_KEYS = frozenset({"auto_resume", "control_enabled", "clipboard_monitor",
                        "auto_sort", "shutdown_when_done", "prefer_ipv4"})
#: Keys whose value is a float.
_FLOAT_KEYS = frozenset({"speed_limit", "global_speed_limit"})


def _raw(store: Any, key: str) -> str:
    if store is None:
        return DEFAULTS.get(key, "")
    try:
        return store.get_setting(key, DEFAULTS.get(key, ""))
    except Exception:       # noqa: BLE001 - settings must never crash startup
        return DEFAULTS.get(key, "")


def get_str(store: Any, key: str, default: str | None = None) -> str:
    fallback = DEFAULTS.get(key, "") if default is None else default
    return _raw(store, key) or fallback


def get_int(store: Any, key: str, default: int | None = None) -> int:
    fallback = int(DEFAULTS.get(key, 0)) if default is None else int(default)
    try:
        return int(float(_raw(store, key)))
    except (TypeError, ValueError):
        return fallback


def get_float(store: Any, key: str, default: float | None = None) -> float:
    fallback = float(DEFAULTS.get(key, 0)) if default is None else float(default)
    try:
        return float(_raw(store, key))
    except (TypeError, ValueError):
        return fallback


def get_bool(store: Any, key: str, default: bool = True) -> bool:
    raw = _raw(store, key)
    if raw == "":
        return default
    return raw not in ("0", "false", "False", "no", "off")


def load(store: Any) -> dict[str, Any]:
    """Return every known setting, converted to its natural type."""
    prefs: dict[str, Any] = {}
    for key in DEFAULTS:
        if key in _INT_KEYS:
            prefs[key] = get_int(store, key)
        elif key in _FLOAT_KEYS:
            prefs[key] = get_float(store, key)
        elif key in _BOOL_KEYS:
            prefs[key] = get_bool(store, key)
        else:
            prefs[key] = get_str(store, key)
    return prefs


def save(store: Any, **values: Any) -> None:
    """Persist the given settings (best effort, never raises).

    Booleans are stored as "1"/"0"; everything else as its string form.
    Unknown keys are written too, so callers can extend settings without
    touching this module.
    """
    if store is None:
        return
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool):
            text = "1" if value else "0"
        else:
            text = str(value)
        try:
            store.set_setting(key, text)
        except Exception:       # noqa: BLE001
            pass
