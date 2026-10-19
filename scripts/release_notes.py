"""Extract the release notes for one version from CHANGELOG.md.

The changelog is the single source of truth for the patch notes, so the notes
on the GitHub release page always match the code.

Usage:
    python scripts/release_notes.py v1.1.0          # print the section
    python scripts/release_notes.py v1.1.0 --md     # include the heading
    python scripts/release_notes.py --list          # list the versions
    python scripts/release_notes.py v1.1.0 --file notes.md
"""
from __future__ import annotations

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHANGELOG = os.path.join(os.path.dirname(HERE), "CHANGELOG.md")

#: A version heading: "## [v1.0.0] - 2026-10-19" or "## [Unreleased]".
_HEADING = re.compile(r"^##\s+\[(?P<version>[^\]]+)\](?P<rest>.*)$")


def read_changelog(path: str = CHANGELOG) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def versions(text: str) -> list[str]:
    """Every version heading in the changelog, newest first."""
    found = []
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            found.append(match.group("version").strip())
    return found


def section(text: str, version: str) -> str | None:
    """The body of one version's section (without its ``##`` heading)."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if match and match.group("version").strip() == version:
            start = index
            break
    if start is None:
        return None
    body: list[str] = []
    for line in lines[start + 1:]:
        if _HEADING.match(line):
            break
        body.append(line)
    # Trim the blank lines at both ends.
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(body)


def notes(text: str, version: str, with_heading: bool = False) -> str | None:
    """The release notes for a version."""
    body = section(text, version)
    if body is None:
        return None
    if not with_heading:
        return body
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match and match.group("version").strip() == version:
            return f"{line}\n\n{body}"
    return body


def sha256_of(path: str) -> str:
    """The SHA-256 of a file, as a lowercase hex string."""
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?",
                        help="the version to print, e.g. v1.1.0")
    parser.add_argument("--md", action="store_true",
                        help="include the '## [version]' heading")
    parser.add_argument("--list", action="store_true",
                        help="list the versions in the changelog")
    parser.add_argument("--file", help="write the notes to this file")
    parser.add_argument("--hash", metavar="FILE",
                        help="print the SHA-256 of FILE and exit")
    parser.add_argument("--changelog", default=CHANGELOG,
                        help="path to CHANGELOG.md")
    args = parser.parse_args(argv)

    if args.hash:
        print(sha256_of(args.hash))
        return 0

    try:
        text = read_changelog(args.changelog)
    except OSError as exc:
        print(f"cannot read the changelog: {exc}", file=sys.stderr)
        return 2

    if args.list:
        for version in versions(text):
            print(version)
        return 0

    if not args.version:
        parser.error("a version is required (or use --list)")
    result = notes(text, args.version, with_heading=args.md)
    if result is None:
        print(f"no section for {args.version!r} in {args.changelog}",
              file=sys.stderr)
        print("known versions: " + ", ".join(versions(text)), file=sys.stderr)
        return 1
    if args.file:
        with open(args.file, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(result + "\n")
        print(f"wrote {args.file}")
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
