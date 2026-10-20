"""Set the version of FreeDM everywhere at once (Milestone 3, goal G2).

The version appears in a few places, and they must not drift apart:

- ``freedm/__init__.py``     - the version the app reports
- ``VERSION.json``           - the file the update check reads
- ``installer/FreeDM.iss``   - the installer
- ``extension/manifest.json`` and ``extension/manifest.firefox.json`` - the
  browser extension

Usage:
    python scripts/set_version.py 1.7.0
    python scripts/set_version.py --show
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: The files that carry the version, and how to change it in each.
TARGETS = (
    ("freedm/__init__.py", r'__version__ = "[^"]+"',
     '__version__ = "{version}"'),
    ("installer/FreeDM.iss", r'#define AppVersion "[^"]+"',
     '#define AppVersion "{version}"'),
    ("extension/manifest.json", r'"version": "[^"]+"',
     '"version": "{version}"'),
    ("extension/manifest.firefox.json", r'"version": "[^"]+"',
     '"version": "{version}"'),
)

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def current_version() -> str:
    """The version the app reports."""
    sys.path.insert(0, ROOT)
    from freedm import __version__
    return __version__


def set_version(version: str) -> list[str]:
    """Write the version into every file. Returns the files that changed."""
    if not VERSION_RE.match(version):
        raise SystemExit(f"'{version}' is not a version like 1.2.3")
    changed = []
    for relative, pattern, template in TARGETS:
        path = os.path.join(ROOT, relative)
        with open(path, "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
        new = re.sub(pattern, template.format(version=version), text, count=1)
        if new != text:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(new)
            changed.append(relative)
    # VERSION.json is JSON, so it is written separately.
    path = os.path.join(ROOT, "VERSION.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    if data.get("version") != version:
        data["version"] = version
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        changed.append("VERSION.json")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?",
                        help="the new version, e.g. 1.7.0")
    parser.add_argument("--show", action="store_true",
                        help="print the current version and exit")
    args = parser.parse_args(argv)

    if args.show:
        print(current_version())
        return 0
    if not args.version:
        parser.error("a version is required (or use --show)")

    changed = set_version(args.version)
    print(f"version set to {args.version}")
    for name in sorted(changed):
        print(f"  {name}")
    if not changed:
        print("  (nothing changed - it was already right)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
