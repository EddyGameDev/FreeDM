# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Milestone 2 / goal N1 tests: settings persistence, live speed limit,
job-details data and the ``speed_limit`` DB migration.

Run with:  python tests/test_n1.py
       or:  python -m pytest tests/test_n1.py
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import range_server                      # noqa: E402
from freedm.engine import Download, RateLimiter, DONE, ERROR, CANCELED  # noqa: E402
from freedm.store import JobStore               # noqa: E402
from freedm import settings as S                     # noqa: E402


def wait_for(dl: Download, timeout: float = 120) -> str:
    t0 = time.time()
    while dl.status not in (DONE, ERROR, CANCELED) and time.time() - t0 < timeout:
        time.sleep(0.2)
    return dl.status


class SettingsTests(unittest.TestCase):
    def test_defaults_without_store_are_typed(self):
        prefs = S.load(None)
        self.assertEqual(prefs["threads"], 8)
        self.assertEqual(prefs["speed_limit"], 0.0)
        self.assertIs(prefs["auto_resume"], True)
        self.assertEqual(prefs["last_dir"], "")
        self.assertIsInstance(prefs["max_active"], int)

    def test_round_trip(self):
        store = JobStore(":memory:")
        try:
            S.save(store, last_dir="D:/dl", threads=12, speed_limit=2048.0,
                   auto_resume=False, window="900x500+10+20")
            prefs = S.load(store)
            self.assertEqual(prefs["last_dir"], "D:/dl")
            self.assertEqual(prefs["threads"], 12)
            self.assertEqual(prefs["speed_limit"], 2048.0)
            self.assertIs(prefs["auto_resume"], False)
            self.assertEqual(prefs["window"], "900x500+10+20")
        finally:
            store.close()

    def test_bool_parsing(self):
        store = JobStore(":memory:")
        try:
            for raw, expected in (("1", True), ("0", False), ("false", False),
                                  ("off", False), ("yes", True)):
                store.set_setting("auto_resume", raw)
                self.assertIs(S.get_bool(store, "auto_resume"), expected, raw)
        finally:
            store.close()

    def test_bad_values_fall_back(self):
        store = JobStore(":memory:")
        try:
            store.set_setting("threads", "not-a-number")
            store.set_setting("speed_limit", "")
            self.assertEqual(S.get_int(store, "threads", 8), 8)
            self.assertEqual(S.get_float(store, "speed_limit", 0.0), 0.0)
        finally:
            store.close()

    def test_save_without_store_is_noop(self):
        S.save(None, threads=4)          # must not raise
        self.assertEqual(S.get_int(None, "threads"), 8)

    def test_every_default_key_is_loadable(self):
        prefs = S.load(None)
        self.assertEqual(set(prefs), set(S.DEFAULTS))


class MigrationTests(unittest.TestCase):
    def test_old_database_gains_speed_limit_column(self):
        tmp = tempfile.mkdtemp(prefix="freedm_n1_mig_")
        try:
            path = os.path.join(tmp, "old.db")
            # Simulate a pre-N1 database: the real W3 schema minus speed_limit.
            conn = sqlite3.connect(path)
            conn.executescript(
                "CREATE TABLE downloads ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL,"
                " final_url TEXT, dest_dir TEXT, filename TEXT,"
                " size INTEGER DEFAULT 0, downloaded INTEGER DEFAULT 0,"
                " threads INTEGER DEFAULT 8, status TEXT DEFAULT 'idle',"
                " headers_json TEXT DEFAULT '{}', etag TEXT,"
                " last_modified TEXT, error TEXT, created_at REAL,"
                " updated_at REAL);"
                "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);")
            conn.execute("INSERT INTO downloads (url, created_at)"
                         " VALUES ('http://x/y', 1.0)")
            conn.commit()
            conn.close()

            store = JobStore(path)       # opens + migrates
            try:
                self.assertIsNone(store.last_error)
                cols = {r["name"] for r in store._read(
                    "PRAGMA table_info(downloads)")}
                self.assertIn("speed_limit", cols)
                self.assertEqual(len(store.list_all()), 1)
            finally:
                store.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class SpeedLimitTests(unittest.TestCase):
    def test_set_speed_limit_updates_rate_and_clamps(self):
        dl = Download("http://example.com/f.bin", speed_limit=1000)
        self.assertEqual(dl.speed_limit, 1000.0)
        self.assertEqual(dl.rate.rate, 1000.0)
        dl.set_speed_limit(4096)
        self.assertEqual(dl.speed_limit, 4096.0)
        self.assertEqual(dl.rate.rate, 4096.0)
        dl.set_speed_limit(-5)           # negative -> unlimited
        self.assertEqual(dl.speed_limit, 0.0)
        self.assertEqual(dl.rate.rate, 0.0)

    def test_snapshot_reports_limit(self):
        dl = Download("http://example.com/f.bin", speed_limit=2048)
        self.assertEqual(dl.snapshot()["speed_limit"], 2048.0)

    def test_rate_limiter_throttles(self):
        limiter = RateLimiter(8192)      # 8 KB/s
        t0 = time.monotonic()
        limiter.consume(8192)            # must wait ~1s for the tokens
        elapsed = time.monotonic() - t0
        self.assertGreaterEqual(elapsed, 0.5)
        self.assertLess(elapsed, 5.0)

    def test_limit_persists_per_job(self):
        store = JobStore(":memory:")
        try:
            dl = Download("http://example.com/f.bin", store=store)
            dl.job_id = store.add(dl)
            dl.set_speed_limit(3072)
            row = store.get(dl.job_id)
            self.assertEqual(float(row["speed_limit"]), 3072.0)
        finally:
            store.close()

    def test_apply_record_restores_limit(self):
        store = JobStore(":memory:")
        try:
            dl = Download("http://example.com/f.bin", store=store)
            dl.job_id = store.add(dl)
            dl.set_speed_limit(5120)
            record = store.get(dl.job_id)
            fresh = Download(record["url"], store=store, job_id=record["id"])
            fresh.apply_record(record)
            self.assertEqual(fresh.speed_limit, 5120.0)
            self.assertEqual(fresh.rate.rate, 5120.0)
        finally:
            store.close()


class LiveLimitIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = range_server.start_server(0, 10)   # 10 MB
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="freedm_n1_")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_single_thread_limit_caps_throughput_then_finishes(self):
        dl = Download(self.base + "/test.bin", dest_dir=self.out,
                      num_threads=1, speed_limit=100 * 1024)
        dl.start()
        time.sleep(1.5)
        self.assertEqual(dl.status, "downloading")
        # ~150 KB should have arrived in 1.5s at 100 KB/s; allow generous slack
        # for the first-chunk burst and scheduler jitter.
        self.assertLess(dl.downloaded, 400 * 1024,
                        f"limit not enforced: {dl.downloaded} bytes in 1.5s")
        dl.set_speed_limit(0)            # lift the cap and finish
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertEqual(dl.speed_limit, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
