# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Human readable sizes, speeds and times."""
from __future__ import annotations

import re


def human_size(n: float) -> str:
    if not n or n <= 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} TB"


def human_speed(bps: float) -> str:
    return f"{human_size(bps)}/s" if bps and bps > 0 else "-"


def human_time(seconds: float) -> str:
    if not seconds or seconds <= 0 or seconds == float("inf"):
        return "-"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def sanitize_filename(name: str) -> str:
    name = name.strip().replace("\r", "").replace("\n", "")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(" .")
    return name or "download"
