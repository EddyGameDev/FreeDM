"""Opt-in update check (N9, roadmap P7.4).

FreeDM never phones home on its own: the check only runs when the user
asks for it (the **About** dialog). It reads one small JSON file and
compares the version with the running one - no account, no API key, no
telemetry.

The file it reads is the ``VERSION.json`` in the repository, so the project
can publish a new version by editing one line.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

#: Where the version file lives.
DEFAULT_VERSION_URL = ("https://raw.githubusercontent.com/EddyGameDev/FreeDM/"
                        "main/VERSION.json")

#: How long to wait for the server.
TIMEOUT = 15


def parse_version(text: str) -> tuple:
    """Turn "1.2.3" into a comparable tuple.

    Anything unparseable becomes ``(0,)`` so it never looks newer than the
    running version."""
    parts = []
    for chunk in str(text or "").strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def is_newer(remote: str, current: str) -> bool:
    """True when ``remote`` is a newer version than ``current``."""
    return parse_version(remote) > parse_version(current)


def fetch_version_info(url: str = DEFAULT_VERSION_URL,
                       timeout: int = TIMEOUT) -> dict:
    """Read the version file. Returns a dict; never raises."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "FreeDM/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    try:
        data = json.loads(body)
    except ValueError as exc:
        return {"ok": False, "error": f"the version file is not valid JSON: {exc}"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "the version file is not an object"}
    return {"ok": True, "version": str(data.get("version") or ""),
            "url": str(data.get("url") or ""),
            "notes": str(data.get("notes") or "")}


def check_for_update(current: str, url: str = DEFAULT_VERSION_URL,
                     timeout: int = TIMEOUT) -> tuple[bool, str]:
    """Check whether a newer version exists.

    Returns ``(is_newer, message)``. The message says what to do, so the
    caller can show it as-is."""
    info = fetch_version_info(url, timeout)
    if not info.get("ok"):
        return False, f"Could not check for updates: {info.get('error')}"
    remote = info.get("version") or ""
    if not remote:
        return False, "The version file did not name a version."
    if is_newer(remote, current):
        message = f"FreeDM {remote} is available (you have {current})."
        if info.get("url"):
            message += f"\n{info['url']}"
        return True, message
    return False, f"You are up to date (FreeDM {current})."
