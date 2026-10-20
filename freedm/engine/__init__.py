# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""The FreeDM download engine.

The public API lives here, so ``from freedm.engine import Download``
keeps working no matter how the code is split up inside.
"""
from __future__ import annotations

from freedm.engine.constants import (CHUNK, CONNECT_TIMEOUT,
                                   CANCELED, DISK_MARGIN, DONE,
                                   DOWNLOADING, DYNAMIC_SPLITTING,
                                   ERROR, IDLE, MAX_PIECE_SIZE,
                                   MAX_RETRIES, MAX_SEGMENTS,
                                   MIN_PIECE_SIZE, MIN_SEGMENT_SIZE,
                                   MIN_SPLIT_SIZE, PAUSED,
                                   PIECE_SPEED_SAMPLES, PROBING, QUEUED,
                                   READ_TIMEOUT, SCHEDULED,
                                   SPLIT_TARGET_SECONDS, USER_AGENT)
from freedm.engine.download import Download
from freedm.engine.errors import (AuthRequiredError,
                                   DownloadCanceled, FileChangedError,
                                   RangeNotSupportedError,
                                   VerificationError)
from freedm.engine.formatting import (human_size, human_speed,
                                     human_time, sanitize_filename)
from freedm.engine.limits import (GLOBAL_LIMITER, GlobalRateLimiter,
                                  RateLimiter, global_speed_limit,
                                  set_global_speed_limit)
from freedm.engine.segments import Segment

__all__ = [
    "Download", "Segment", "RateLimiter", "GlobalRateLimiter",
    "GLOBAL_LIMITER", "set_global_speed_limit", "global_speed_limit",
    "human_size", "human_speed", "human_time", "sanitize_filename",
    "DownloadCanceled", "FileChangedError", "RangeNotSupportedError",
    "AuthRequiredError", "VerificationError",
    "IDLE", "QUEUED", "SCHEDULED", "PROBING", "DOWNLOADING",
    "PAUSED", "DONE", "ERROR", "CANCELED",
    "CHUNK", "MIN_SEGMENT_SIZE", "MAX_RETRIES", "CONNECT_TIMEOUT",
    "READ_TIMEOUT", "USER_AGENT", "DISK_MARGIN",
    "MAX_PIECE_SIZE", "MIN_PIECE_SIZE", "MIN_SPLIT_SIZE",
    "MAX_SEGMENTS", "SPLIT_TARGET_SECONDS", "PIECE_SPEED_SAMPLES",
    "DYNAMIC_SPLITTING",
]
