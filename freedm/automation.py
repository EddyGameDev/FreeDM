"""Scheduled starts, allowed download windows and shut-down-when-done
(Milestone 2, goal N6).

Headless - no Tkinter, no downloads - so the scheduler, the GUI and the tests
all agree on what "02:30" means and when a job is allowed to run.

Two independent mechanisms:

- **A start time for one job** (``start_at``): the job waits in the
  ``scheduled`` state until that moment, then joins the normal queue. The
  moment is stored as a Unix timestamp so it survives a restart.
- **A daily window** (``window_start`` / ``window_end``): while the window is
  closed, *no* job starts. The window may wrap past midnight (23:00 -> 06:00).
  An empty start or end means "no restriction"; start == end also means
  "no restriction".
"""
from __future__ import annotations

import datetime
import re
import time

_TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{1,2})$")

#: Minutes in a day.
DAY_MINUTES = 24 * 60


def parse_time(text: str | None) -> int | None:
    """Parse ``"02:30"`` (or ``"2.30"``) into minutes after midnight.

    Returns ``None`` for anything unparseable, so a bad value simply means
    "no schedule" instead of raising in the middle of the GUI."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    match = _TIME_RE.match(raw)
    if not match:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2))
    if hours > 23 or minutes > 59:
        return None
    return hours * 60 + minutes


def format_time(minutes: int | None) -> str:
    """Render minutes after midnight as ``"02:30"``."""
    if minutes is None:
        return ""
    minutes = int(minutes) % DAY_MINUTES
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def in_window(now: datetime.datetime, start: int | None,
              end: int | None) -> bool:
    """Is ``now`` inside the daily window ``start``..``end``?

    The window may wrap past midnight. An unset start or end (or a zero-length
    window) means "always allowed"."""
    if start is None or end is None or start == end:
        return True
    current = now.hour * 60 + now.minute
    if start < end:
        return start <= current < end
    # Wraps midnight, e.g. 23:00 -> 06:00
    return current >= start or current < end


def seconds_until_minutes(now: datetime.datetime,
                           minutes: int | None) -> float:
    """Seconds until the next time-of-day ``minutes`` (e.g. "02:30")."""
    if minutes is None:
        return 0.0
    current = now.hour * 3600 + now.minute * 60 + now.second
    delta = int(minutes) * 60 - current
    if delta <= 0:
        delta += 24 * 3600
    return float(delta)


def seconds_until_epoch(target: float | None, now: float | None = None) -> float:
    """Seconds until ``target`` (a Unix timestamp); 0 when unset or past."""
    if not target:
        return 0.0
    now = time.time() if now is None else now
    return max(0.0, float(target) - float(now))


def next_window_opens(now: datetime.datetime, start: int | None,
                      end: int | None) -> float:
    """Seconds until the daily window opens.

    Returns 0 when the window is already open (or unset)."""
    if start is None or end is None or start == end:
        return 0.0
    if in_window(now, start, end):
        return 0.0
    return seconds_until_minutes(now, start)


def describe_schedule(start_at: float | None) -> str:
    """A short human description of a job's start time."""
    if not start_at:
        return "not scheduled"
    when = datetime.datetime.fromtimestamp(float(start_at))
    stamp = when.strftime("%d %b %H:%M")
    delta = float(start_at) - time.time()
    if delta <= 0:
        return f"now ({stamp})"
    if delta < 3600:
        return f"in {round(delta / 60)} min ({stamp})"
    return stamp


# -- shut-down when the queue drains ----------------------------------------
SHUTDOWN = "shutdown"
SLEEP = "sleep"


def shutdown_command(mode: str, delay_seconds: int = 30,
                     platform: str | None = None) -> list[str] | None:
    """The command that powers the machine down or puts it to sleep.

    ``None`` means "not supported on this platform" - the caller must not
    pretend the action happened. ``platform`` defaults to the running system
    and can be given explicitly so the command can be checked on any
    machine."""
    import sys

    platform = platform or sys.platform
    if platform.startswith("win"):
        if mode == SLEEP:
            # Suspend to disk without hibernation.
            return ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
        return ["shutdown", "/s", "/t", str(max(0, int(delay_seconds)))]
    if mode == SLEEP:
        return ["systemctl", "suspend"]
    return ["shutdown", "-h", "now"]
