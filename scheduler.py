"""Polite concurrency scheduler for FreeDM (W4).

Caps how many downloads run at once, how many connections are used in total,
and how many connections go to any single host. Queued jobs are started FIFO
as slots free up; the user can reorder them or send one to the front.

Connection accounting is static: a job is assigned an effective thread count
when it starts, so ``sum(threads of active jobs)`` is the connection budget.
Per-host budgets are keyed by the URL netloc (including port).
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from urllib.parse import urlparse

from engine import (
    Download, DONE, ERROR, CANCELED, PAUSED, PROBING, DOWNLOADING, QUEUED,
)

DEFAULT_MAX_ACTIVE = 3
DEFAULT_MAX_CONNECTIONS = 64
DEFAULT_MAX_PER_HOST = 12


class Scheduler:
    def __init__(self, max_active: int = DEFAULT_MAX_ACTIVE,
                 max_connections: int = DEFAULT_MAX_CONNECTIONS,
                 max_per_host: int = DEFAULT_MAX_PER_HOST,
                 tick: float = 0.25):
        self.max_active = max(1, min(int(max_active), 32))
        self.max_connections = max(1, int(max_connections))
        self.max_per_host = max(1, int(max_per_host))
        self._tick = max(0.05, float(tick))
        self._lock = threading.RLock()
        self._queue: list[tuple[Download, str]] = []   # (job, start|resume)
        self._launched: list[Download] = []
        self._requested: dict[Download, int] = {}
        self._effective: dict[Download, int] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # -- introspection -----------------------------------------------------
    @staticmethod
    def _host(dl: Download) -> str:
        return (urlparse(dl.final_url or dl.url).netloc or "").lower()

    def active(self) -> list[Download]:
        with self._lock:
            self._reap()
            return list(self._launched)

    def queued(self) -> list[Download]:
        with self._lock:
            return [dl for dl, _ in self._queue]

    def effective_threads(self, dl: Download) -> int:
        with self._lock:
            return self._effective.get(dl, dl.num_threads)

    # -- queue operations --------------------------------------------------
    def submit(self, dl: Download, action: str = "start") -> None:
        """Queue a job (FIFO) and start it if a slot is free."""
        if dl.status == DONE:
            return
        with self._lock:
            self._requested.setdefault(dl, dl.num_threads)
            if any(j is dl for j, _ in self._queue):
                return
            if dl.status in (PROBING, DOWNLOADING):
                return
            dl.mark_queued()
            self._queue.append((dl, action))
        self.pump()

    def enqueue_resume(self, dl: Download) -> None:
        self.submit(dl, action="resume")

    def pause(self, dl: Download) -> None:
        with self._lock:
            self._queue = [(j, a) for j, a in self._queue if j is not dl]
            if dl.status == QUEUED:
                dl.status = PAUSED
                dl._store_save()
        if dl.status in (PROBING, DOWNLOADING):
            dl.pause()

    def resume(self, dl: Download) -> None:
        if dl.status in (ERROR, CANCELED):
            self.submit(dl, action="start")
        elif dl.status == PAUSED:
            self.submit(dl, action="resume")
        elif dl.status == QUEUED:
            self.pump()

    def cancel(self, dl: Download) -> None:
        with self._lock:
            self._queue = [(j, a) for j, a in self._queue if j is not dl]
        dl.cancel()

    def remove(self, dl: Download) -> None:
        """Forget a job entirely (caller decides whether to cancel it)."""
        with self._lock:
            self._queue = [(j, a) for j, a in self._queue if j is not dl]
            if dl in self._launched:
                self._launched.remove(dl)
            self._requested.pop(dl, None)
            self._effective.pop(dl, None)

    def start_now(self, dl: Download) -> None:
        """Move a queued job to the front of the queue."""
        with self._lock:
            for i, (j, action) in enumerate(self._queue):
                if j is dl:
                    self._queue.insert(0, self._queue.pop(i))
                    break
        self.pump()

    def move_up(self, dl: Download) -> bool:
        with self._lock:
            for i, (j, _a) in enumerate(self._queue):
                if j is dl and i > 0:
                    self._queue[i - 1], self._queue[i] = \
                        self._queue[i], self._queue[i - 1]
                    return True
        return False

    def move_down(self, dl: Download) -> bool:
        with self._lock:
            for i, (j, _a) in enumerate(self._queue):
                if j is dl and i < len(self._queue) - 1:
                    self._queue[i + 1], self._queue[i] = \
                        self._queue[i], self._queue[i + 1]
                    return True
        return False

    def set_max_active(self, n: int) -> None:
        self.max_active = max(1, min(int(n), 32))
        self.pump()

    # -- engine ------------------------------------------------------------
    def _reap(self) -> None:
        """Release finished/paused jobs and restore their thread counts."""
        for dl in list(self._launched):
            if dl.status in (DONE, ERROR, CANCELED, PAUSED):
                self._launched.remove(dl)
                self._effective.pop(dl, None)
                requested = self._requested.get(dl)
                if requested:
                    dl.num_threads = requested

    def pump(self) -> None:
        """Start queued jobs while active/connection/host budgets allow."""
        launched: list[tuple[Download, str]] = []
        with self._lock:
            self._reap()
            active = list(self._launched)
            total = sum(j.num_threads for j in active)
            hosts: Counter[str] = Counter()
            for j in active:
                hosts[self._host(j)] += j.num_threads
            for entry in list(self._queue):
                dl, action = entry
                if dl.status in (DONE, ERROR, CANCELED):
                    self._queue.remove(entry)
                    continue
                if len(active) + len(launched) >= self.max_active:
                    break
                if total >= self.max_connections:
                    break
                host = self._host(dl)
                host_budget = self.max_per_host - hosts.get(host, 0)
                if host_budget <= 0:
                    continue                      # try another host
                requested = self._requested.get(dl, dl.num_threads)
                eff = max(1, min(requested, self.max_connections - total,
                                 host_budget))
                self._queue.remove(entry)
                dl.num_threads = eff
                self._effective[dl] = eff
                self._launched.append(dl)
                total += eff
                hosts[host] += eff
                launched.append((dl, action))
        for dl, action in launched:
            if action == "resume":
                dl.resume()
            else:
                dl.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.pump()
            except Exception:       # noqa: BLE001 - keep the scheduler alive
                pass
            self._stop.wait(self._tick)

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
