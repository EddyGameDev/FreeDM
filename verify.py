# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""File integrity verification and orphan cleanup (Milestone 2, goal N3).

Deliberately headless - no Tkinter, no network - so the engine, the GUI and the
tests all share one definition of "is this file intact?".

What it provides:
- :func:`parse_checksum` - read a user-supplied checksum ("sha256:ab12..." or
  a bare 64-hex digest) into an (algorithm, digest) pair.
- :func:`file_digest` - hash a file with a streaming read (constant memory).
- :func:`verify_size` - compare the bytes on disk with the advertised size.
- :func:`verify_checksum` - hash the file and compare with the expected digest.
- :func:`find_orphans` / :func:`cleanup_orphans` - locate and delete abandoned
  ``.part`` / ``.part.state.json`` leftovers from jobs the user gave up on.

The orphan helpers only ever look at files whose names match the resume-file
patterns FreeDM itself creates, and only when they are older than the given
age, so an in-progress download is never touched.
"""
from __future__ import annotations

import hashlib
import os
import time

#: Supported checksum algorithms, mapped to their hashlib constructor.
ALGORITHMS: dict[str, str] = {
    "sha256": "sha256",
    "sha512": "sha512",
    "sha1": "sha1",
    "md5": "md5",
}

#: Expected hex length per algorithm (used to validate a pasted digest).
HEX_LENGTHS: dict[str, int] = {
    "sha256": 64,
    "sha512": 128,
    "sha1": 40,
    "md5": 32,
}

#: Filename suffixes that mark an abandoned FreeDM partial download.
ORPHAN_SUFFIXES = (".part", ".part.state.json", ".part.state.json.tmp")

_CHUNK = 1 << 20


def parse_checksum(spec: str | None) -> tuple[str, str]:
    """Parse a checksum specification into ``(algorithm, hex_digest)``.

    Accepted forms:
    - ``""`` / ``None``            -> ``("", "")`` (no checksum)
    - ``"sha256:ab12..."``         -> explicit algorithm
    - ``"ab12..."`` (64 hex chars) -> assumed sha256

    Raises ``ValueError`` with a clear message for an unknown algorithm, a
    malformed digest or a digest of the wrong length.
    """
    if spec is None:
        return "", ""
    text = str(spec).strip().replace(" ", "").replace("-", "")
    if not text:
        return "", ""

    algo = "sha256"
    digest = text
    if ":" in text:
        algo, digest = text.split(":", 1)
        algo = algo.strip().lower()
        digest = digest.strip().lower()
    else:
        digest = digest.lower()

    if algo not in ALGORITHMS:
        raise ValueError(
            f"unknown checksum algorithm {algo!r}; "
            f"use one of {', '.join(sorted(ALGORITHMS))}")
    if not all(c in "0123456789abcdef" for c in digest):
        raise ValueError("checksum must be a hexadecimal digest")
    expected_len = HEX_LENGTHS[algo]
    if len(digest) != expected_len:
        raise ValueError(
            f"{algo} checksum must be {expected_len} hex characters, "
            f"got {len(digest)}")
    return algo, digest


def file_digest(path: str, algo: str = "sha256") -> str:
    """Return the hex digest of ``path`` (streamed, constant memory)."""
    name = (algo or "sha256").lower()
    if name not in ALGORITHMS:
        raise ValueError(f"unknown checksum algorithm {name!r}")
    digest = hashlib.new(ALGORITHMS[name])
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_size(path: str, expected: int) -> tuple[bool, str]:
    """Compare the file's size with ``expected`` bytes.

    Returns ``(ok, message)``. An unknown/zero ``expected`` means "cannot
    verify" and is reported as ok with an empty message.
    """
    try:
        expected = int(expected or 0)
    except (TypeError, ValueError):
        return True, ""
    if expected <= 0:
        return True, ""
    try:
        actual = os.path.getsize(path)
    except OSError as exc:
        return False, f"cannot read the finished file: {exc}"
    if actual != expected:
        return False, (f"size mismatch: expected {expected} bytes, "
                       f"got {actual}")
    return True, ""


def verify_checksum(path: str, spec: str | None) -> tuple[bool, str, str]:
    """Hash ``path`` and compare it with ``spec``.

    Returns ``(ok, message, status)`` where ``status`` is one of
    ``"none"``, ``"verified"`` or ``"mismatch"``. A mismatch message shows
    **both** digests so the user can tell which one is wrong.
    """
    try:
        algo, digest = parse_checksum(spec)
    except ValueError as exc:
        return False, f"invalid checksum: {exc}", "invalid"
    if not algo:
        return True, "", "none"
    try:
        actual = file_digest(path, algo)
    except OSError as exc:
        return False, f"cannot read the finished file: {exc}", "error"
    if actual == digest:
        return True, f"{algo} checksum verified", "verified"
    return False, (f"{algo} checksum mismatch: expected {digest}, "
                   f"got {actual}"), "mismatch"


def is_orphan_name(name: str) -> bool:
    """True when ``name`` looks like a FreeDM partial/resume file."""
    return any(name.endswith(suffix) for suffix in ORPHAN_SUFFIXES)


def find_orphans(folder: str, min_age_days: float = 30.0) -> list[str]:
    """Find abandoned partial/resume files under ``folder``.

    Only files whose name matches FreeDM's own patterns *and* whose
    modification time is older than ``min_age_days`` are returned, so running
    downloads are never touched. ``min_age_days <= 0`` disables the scan.
    """
    try:
        age = float(min_age_days)
    except (TypeError, ValueError):
        return []
    if age <= 0 or not folder or not os.path.isdir(folder):
        return []
    cutoff = time.time() - age * 86400.0
    found: list[str] = []
    for root, _dirs, names in os.walk(folder):
        for name in names:
            if not is_orphan_name(name):
                continue
            full = os.path.join(root, name)
            try:
                if os.path.getmtime(full) < cutoff:
                    found.append(full)
            except OSError:
                continue
    return sorted(found)


def cleanup_orphans(paths: list[str]) -> tuple[int, list[str]]:
    """Delete the given orphan files.

    Returns ``(deleted, failed)`` where ``failed`` holds ``(path, reason)``
    pairs for files that could not be removed.
    """
    deleted = 0
    failed: list[tuple[str, str]] = []
    for path in paths:
        try:
            os.remove(path)
            deleted += 1
        except FileNotFoundError:
            continue
        except OSError as exc:
            failed.append((path, str(exc)))
    return deleted, failed
