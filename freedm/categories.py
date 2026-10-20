# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Categories, folder rules, list filtering and queue import/export
(Milestone 2, goal N5).

Deliberately headless - no Tkinter - so the GUI and the tests share one
definition of "which folder does this file belong in?" and "does this row
match the current search?".

Category rules are stored as plain text, one category per line::

    Video: .mp4, .mkv, .avi
    Music: .mp3, .flac

The format is intentionally simple so the user can edit it in a text box and
so it round-trips through the settings table without a schema.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse

#: The categories FreeDM ships with. The user may edit or extend them.
DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Video": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
              ".mpg", ".mpeg", ".ts", ".m2ts", ".3gp", ".vob"],
    "Music": [".mp3", ".flac", ".aac", ".ogg", ".oga", ".wav", ".wma", ".m4a",
              ".opus", ".aiff"],
    "Documents": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                  ".txt", ".rtf", ".odt", ".ods", ".csv", ".md", ".epub", ".djvu"],
    "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".zst",
                 ".tgz", ".iso", ".cab"],
    "Programs": [".exe", ".msi", ".apk", ".deb", ".rpm", ".dmg", ".appimage",
                 ".jar", ".msu", ".appx"],
    "Other": [],
}

#: Where files that match no rule go.
FALLBACK_CATEGORY = "Other"

#: Status values offered in the GUI filter.
STATUS_FILTERS = ("", "downloading", "queued", "paused", "done", "error")

_LINE_RE = re.compile(r"^\s*([^:#]+?)\s*:\s*(.*)$")


def normalise_ext(ext: str) -> str:
    """Normalise an extension to lower-case with a leading dot."""
    e = (ext or "").strip().lower()
    if not e:
        return ""
    if not e.startswith("."):
        e = "." + e
    return e


def default_rules() -> dict[str, list[str]]:
    """A fresh copy of the shipped category rules."""
    return {name: list(exts) for name, exts in DEFAULT_CATEGORIES.items()}


def format_rules(rules: dict[str, list[str]]) -> str:
    """Render the rules as the editable text form."""
    lines = []
    for name, exts in rules.items():
        lines.append(f"{name}: " + ", ".join(exts))
    return "\n".join(lines)


def parse_rules(text: str) -> tuple[dict[str, list[str]], list[str]]:
    """Parse the editable text form into ``(rules, errors)``.

    A line is ``Category: .ext, .ext``. Blank lines and lines starting with
    ``#`` are ignored. Extensions are normalised; a line without a category
    name or with a malformed extension is reported in ``errors`` and skipped.
    """
    rules: dict[str, list[str]] = {}
    errors: list[str] = []
    for number, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_RE.match(line)
        if not match:
            errors.append(f"line {number}: expected 'Category: .ext, .ext'")
            continue
        name = match.group(1).strip()
        if not name:
            errors.append(f"line {number}: missing category name")
            continue
        exts: list[str] = []
        for token in match.group(2).split(","):
            token = token.strip()
            if not token:
                continue
            ext = normalise_ext(token)
            if not re.fullmatch(r"\.[a-z0-9]{1,12}", ext):
                errors.append(f"line {number}: bad extension {token!r}")
                continue
            if ext not in exts:
                exts.append(ext)
        rules[name] = exts
    if not rules:
        errors.append("no categories defined")
    return rules, errors


def load_rules(text: str | None) -> dict[str, list[str]]:
    """Load the user's rules, falling back to the defaults when unusable."""
    if not text:
        return default_rules()
    rules, errors = parse_rules(text)
    if errors or not rules:
        return default_rules()
    return rules


def safe_folder_name(name: str) -> str:
    """Turn a category name into a safe folder name.

    A category name comes from the user's own rules, but it is used as a
    *folder name*, so it must not be able to point outside the download
    folder (``..\\..\\Windows``) and must not contain characters that are
    illegal on Windows (``:*?"<>|``)."""
    import re
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or "").strip())
    cleaned = cleaned.strip(" .")
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    return cleaned or "Other"


def classify(filename: str, rules: dict[str, list[str]] | None = None) -> str:
    """Return the category a file name belongs to."""
    rules = rules or default_rules()
    ext = normalise_ext(os.path.splitext(filename or "")[1])
    if not ext:
        return FALLBACK_CATEGORY
    for name, exts in rules.items():
        if ext in exts:
            return name
    return FALLBACK_CATEGORY


def destination_for(filename: str, base_dir: str,
                    rules: dict[str, list[str]] | None = None) -> str:
    """The folder a file should be saved into (base + category subfolder)."""
    category = classify(filename, rules)
    if not category:
        return base_dir
    return os.path.join(base_dir, safe_folder_name(category))


def matches_filter(name: str, url: str, status: str, needle: str = "",
                   status_filter: str = "") -> bool:
    """True when a row matches the current search.

    ``needle`` is matched case-insensitively against the file name, the URL
    and the host. ``status_filter`` is an exact status match ("" = any)."""
    if status_filter and (status or "").lower() != status_filter.lower():
        return False
    needle = (needle or "").strip().lower()
    if not needle:
        return True
    haystacks = [(name or "").lower(), (url or "").lower()]
    host = ""
    try:
        host = (urlparse(url or "").netloc or "").lower()
    except ValueError:
        host = ""
    haystacks.append(host)
    return any(needle in item for item in haystacks)


def export_queue(jobs: list[dict]) -> str:
    """Serialise jobs into the importable JSON text format.

    Each job keeps its URL, file name, destination folder, thread count and
    expected checksum, so an export/import round-trip loses nothing that
    FreeDM knows about the job."""
    payload = {
        "format": "freedm-queue",
        "version": 1,
        "jobs": [
            {
                "url": job.get("url", ""),
                "filename": job.get("filename") or None,
                "dest_dir": job.get("dest_dir") or None,
                "threads": job.get("threads") or None,
                "checksum": job.get("checksum") or None,
            }
            for job in jobs
        ],
    }
    return json.dumps(payload, indent=2)


def import_queue(text: str) -> tuple[list[dict], list[str]]:
    """Parse an exported queue (JSON) or a plain list of URLs.

    Returns ``(jobs, errors)``. Plain text lines are accepted too, so a
    list of URLs copied from anywhere can be imported."""
    jobs: list[dict] = []
    errors: list[str] = []
    text = (text or "").strip()
    if not text:
        return jobs, ["nothing to import"]
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except ValueError as exc:
            return jobs, [f"not valid JSON: {exc}"]
        if not isinstance(payload, dict):
            return jobs, ["not a FreeDM queue file"]
        raw_jobs = payload.get("jobs")
        if not isinstance(raw_jobs, list):
            return jobs, ["the file has no 'jobs' list"]
        for index, item in enumerate(raw_jobs, start=1):
            if not isinstance(item, dict):
                errors.append(f"job {index}: not an object")
                continue
            url = (item.get("url") or "").strip()
            if not url:
                errors.append(f"job {index}: missing url")
                continue
            jobs.append({
                "url": url,
                "filename": item.get("filename") or None,
                "dest_dir": item.get("dest_dir") or None,
                "threads": item.get("threads") or None,
                "checksum": item.get("checksum") or None,
            })
        return jobs, errors
    # Plain text: one URL per line.
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not (line.lower().startswith("http://")
                or line.lower().startswith("https://")):
            errors.append(f"line {number}: not an http(s) URL")
            continue
        jobs.append({"url": line, "filename": None, "dest_dir": None,
                     "threads": None, "checksum": None})
    return jobs, errors
