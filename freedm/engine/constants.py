# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""The tunables and the status strings of the engine."""
from __future__ import annotations


CHUNK = 128 * 1024                 # read/write chunk size

MIN_SEGMENT_SIZE = 1 * 1024 * 1024  # never split files smaller than this

MAX_RETRIES = 6                     # retries per segment before giving up

CONNECT_TIMEOUT = 15

READ_TIMEOUT = 60

MAX_PIECE_SIZE = 8 * 1024 * 1024    # no single piece may exceed this

MIN_PIECE_SIZE = 1 * 1024 * 1024    # never create a piece smaller than this

MIN_SPLIT_SIZE = 1 * 1024 * 1024    # both halves of a split must reach this

MAX_SEGMENTS = 1024                 # hard cap on the number of pieces

SPLIT_TARGET_SECONDS = 5.0          # aim for pieces that take ~this long

PIECE_SPEED_SAMPLES = 8             # recent piece speeds kept for the target

DYNAMIC_SPLITTING = True            # master switch for N4 dynamic pieces

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) FreeDM/1.0"
)

IDLE = "idle"

QUEUED = "queued"

SCHEDULED = "scheduled"

PROBING = "probing"

DOWNLOADING = "downloading"

PAUSED = "paused"

DONE = "done"

ERROR = "error"

CANCELED = "canceled"

DISK_MARGIN = 64 * 1024 * 1024
