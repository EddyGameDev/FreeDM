# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""The speed limiters: one per download, one for all."""
from __future__ import annotations

import threading
import time


class GlobalRateLimiter:
    """One token bucket shared by *every* download (N4, technical debt #4).

    Per-download limits cap one job; this caps the combined throughput of
    all jobs, which is what a user on a metered or shared link needs.
    A rate of 0 (the default) means unlimited."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rate = 0.0
        self._allowance = 0.0
        self._last = time.monotonic()

    @property
    def rate(self) -> float:
        with self._lock:
            return self._rate

    def set_rate(self, rate: float) -> None:
        with self._lock:
            self._rate = max(0.0, float(rate))
            self._allowance = 0.0
            self._last = time.monotonic()

    def consume(self, n: int) -> None:
        if n <= 0:
            return
        while True:
            with self._lock:
                if self._rate <= 0:
                    return
                now = time.monotonic()
                self._allowance += (now - self._last) * self._rate
                self._last = now
                burst = max(self._rate, float(n))
                if self._allowance > burst:
                    self._allowance = burst
                if self._allowance >= n:
                    self._allowance -= n
                    return
                need = n - self._allowance
            time.sleep(min(need / self._rate, 0.5))


GLOBAL_LIMITER = GlobalRateLimiter()


def set_global_speed_limit(bps: float) -> None:
    """Cap the combined throughput of all downloads (0 = unlimited)."""
    GLOBAL_LIMITER.set_rate(bps)


def global_speed_limit() -> float:
    """The current combined throughput cap in bytes/s (0 = unlimited)."""
    return GLOBAL_LIMITER.rate


class RateLimiter:
    """Token-bucket limiter. rate <= 0 means unlimited."""

    def __init__(self, rate: float = 0.0):
        self.rate = float(rate)
        self._allowance = 0.0
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def set_rate(self, rate: float) -> None:
        with self._lock:
            self.rate = float(rate)
            self._allowance = 0.0
            self._last = time.monotonic()

    def consume(self, n: int) -> None:
        if self.rate <= 0 or n <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                self._allowance += (now - self._last) * self.rate
                self._last = now
                # Allow one chunk-sized burst even when a single read is
                # larger than the per-second rate (otherwise n can never fit
                # under the cap and the loop would spin forever).
                burst = max(self.rate, float(n))
                if self._allowance > burst:
                    self._allowance = burst
                if self._allowance >= n:
                    self._allowance -= n
                    return
                need = n - self._allowance
            time.sleep(min(need / self.rate, 0.5))
