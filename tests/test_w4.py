# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""W4 tests: active/connection/host caps, FIFO queue, Retry-After.

Run with:  python tests/test_w4.py
       or:  python -m pytest tests/test_w4.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import range_server  # noqa: E402
from engine import Download, DONE, ERROR, PAUSED, PROBING, DOWNLOADING, QUEUED  # noqa: E402
from scheduler import Scheduler  # noqa: E402


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wait_until(pred, timeout: float = 30) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.05)
    return False


def wait_done(dl: Download, timeout: float = 60) -> str:
    wait_until(lambda: dl.status in (DONE, ERROR), timeout)
    return dl.status


class W4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = range_server.start_server(0, 5)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.expected = range_server.file_hash()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freedm_w4_")
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)
        self.schedulers: list[Scheduler] = []
        self.jobs: list[Download] = []

    def tearDown(self):
        for s in self.schedulers:
            s.shutdown()
        for dl in self.jobs:
            try:
                dl.cancel()
                dl.abandon(wait=2)
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sched(self, **kw) -> Scheduler:
        s = Scheduler(**kw)
        self.schedulers.append(s)
        return s

    def _make(self, name: str, url_path: str = "/test.bin",
              **kw) -> Download:
        dl = Download(self.base + url_path, dest_dir=self.out,
                      filename=name, **kw)
        self.jobs.append(dl)
        return dl

    # -- caps --------------------------------------------------------------
    def test_active_download_cap(self):
        s = self._sched(max_active=2, max_connections=64, max_per_host=64)
        jobs = [self._make(f"a{i}.bin", num_threads=2, speed_limit=120_000)
                for i in range(6)]
        for dl in jobs:
            s.submit(dl)
        self.assertTrue(wait_until(lambda: len(s.active()) == 2, 10))
        for _ in range(20):
            self.assertLessEqual(len(s.active()), 2)
            self.assertGreaterEqual(len(s.queued()), 1)
            time.sleep(0.05)

    def test_total_connection_cap(self):
        s = self._sched(max_active=3, max_connections=6, max_per_host=64)
        jobs = [self._make(f"t{i}.bin", num_threads=8, speed_limit=100_000)
                for i in range(3)]
        for dl in jobs:
            s.submit(dl)
        self.assertTrue(wait_until(lambda: len(s.active()) == 1, 10))
        active = s.active()
        self.assertEqual(sum(j.num_threads for j in active), 6)
        self.assertTrue(all(j.num_threads == 6 for j in active))
        self.assertEqual(len(s.queued()), 2)

    def test_per_host_connection_cap(self):
        s = self._sched(max_active=3, max_connections=64, max_per_host=5)
        a = self._make("h1.bin", num_threads=8, speed_limit=100_000)
        b = self._make("h2.bin", num_threads=8, speed_limit=100_000)
        s.submit(a)
        s.submit(b)
        self.assertTrue(wait_until(lambda: len(s.active()) == 1, 10))
        self.assertEqual(s.active()[0].num_threads, 5)
        self.assertEqual(len(s.queued()), 1)

    def test_thread_count_restored_after_finish(self):
        s = self._sched(max_active=2, max_connections=4, max_per_host=64)
        dl = self._make("restore.bin", num_threads=8)
        s.submit(dl)
        self.assertEqual(wait_done(dl), DONE, dl.error)
        self.assertTrue(wait_until(lambda: dl.num_threads == 8, 5))

    # -- ordering ----------------------------------------------------------
    def test_fifo_start_now_and_move(self):
        s = self._sched(max_active=1, max_connections=64, max_per_host=64)
        a = self._make("q1.bin", num_threads=2, speed_limit=80_000)
        b = self._make("q2.bin", num_threads=2, speed_limit=80_000)
        c = self._make("q3.bin", num_threads=2, speed_limit=80_000)
        for dl in (a, b, c):
            s.submit(dl)
        self.assertTrue(wait_until(lambda: len(s.active()) == 1, 10))
        self.assertEqual(s.queued(), [b, c])

        self.assertTrue(s.move_up(c))
        self.assertEqual(s.queued(), [c, b])
        self.assertTrue(s.move_down(c))
        self.assertEqual(s.queued(), [b, c])

        s.start_now(c)
        self.assertEqual(s.queued()[0], c)
        s.pause(a)
        self.assertTrue(wait_until(lambda: c.status in (PROBING, DOWNLOADING), 10))
        self.assertEqual(s.queued(), [b])

    def test_pause_and_resume_queued_job(self):
        s = self._sched(max_active=1, max_connections=64, max_per_host=64)
        a = self._make("p1.bin", num_threads=2, speed_limit=80_000)
        b = self._make("p2.bin", num_threads=2, speed_limit=80_000)
        s.submit(a)
        s.submit(b)
        self.assertTrue(wait_until(lambda: len(s.queued()) == 1, 10))
        s.pause(b)
        self.assertEqual(b.status, PAUSED)
        self.assertEqual(s.queued(), [])
        s.resume(b)
        self.assertEqual(s.queued(), [b])
        self.assertEqual(b.status, QUEUED)

    # -- Retry-After -------------------------------------------------------
    def test_retry_after_is_honoured(self):
        range_server.reset_retry(2)
        dl = self._make("retry.bin", url_path="/retry/test.bin",
                        num_threads=1)
        t0 = time.monotonic()
        dl.start()
        self.assertEqual(wait_done(dl, 30), DONE, dl.error)
        elapsed = time.monotonic() - t0
        self.assertGreaterEqual(elapsed, 1.8,
                                f"retried too early: {elapsed:.2f}s")
        self.assertEqual(sha256(dl.path), self.expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
