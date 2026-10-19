"""W3 tests: persistent SQLite queue, DB-backed resume, failure isolation.

Run with:  python tests/test_w3.py
       or:  python -m pytest tests/test_w3.py
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
from engine import Download, DONE, ERROR, PAUSED, Segment  # noqa: E402
from store import JobStore  # noqa: E402


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wait_until(pred, timeout: float = 120) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.1)
    return False


def wait_done(dl: Download, timeout: float = 120) -> str:
    wait_until(lambda: dl.status in (DONE, ERROR), timeout)
    return dl.status


class W3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = range_server.start_server(0, 5)   # 5 MB
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.expected = range_server.file_hash()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freedm_w3_")
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)
        self.db = os.path.join(self.tmp, "queue.db")
        self.store = JobStore(self.db)

    def tearDown(self):
        try:
            self.store.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make(self, name: str, **kw) -> Download:
        dl = Download(self.base + "/test.bin", dest_dir=self.out,
                      filename=name, store=self.store, **kw)
        dl.job_id = self.store.add(dl)
        return dl

    # -- store basics ------------------------------------------------------
    def test_store_roundtrip(self):
        dl = self._make("roundtrip.bin", num_threads=4)
        dl.total_size = 1000
        dl.downloaded = 250
        dl.status = DONE
        dl.headers["Referer"] = "http://ref/"
        self.assertTrue(self.store.save(dl))
        self.assertTrue(self.store.save_segments(dl.job_id, [
            Segment(0, 0, 499, 250), Segment(1, 500, 999, 0)]))

        self.store.close()
        self.store = JobStore(self.db)
        row = self.store.get(dl.job_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["filename"], "roundtrip.bin")
        self.assertEqual(row["status"], DONE)
        self.assertEqual(row["downloaded"], 250)
        self.assertEqual(row["threads"], 4)
        self.assertIn("Referer", row["headers_json"])
        segs = self.store.load_segments(dl.job_id)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["downloaded"], 250)

    def test_list_order_and_delete(self):
        ids = [self._make(f"job{i}.bin").job_id for i in range(3)]
        rows = self.store.list_all()
        self.assertEqual([r["id"] for r in rows], ids)
        self.assertTrue(self.store.delete(ids[1]))
        self.assertEqual(len(self.store.list_all()), 2)
        self.assertIsNone(self.store.get(ids[1]))

    def test_settings_roundtrip(self):
        self.store.set_setting("auto_resume", "0")
        self.store.close()
        self.store = JobStore(self.db)
        self.assertEqual(self.store.get_setting("auto_resume"), "0")
        self.assertEqual(self.store.get_setting("missing", "dflt"), "dflt")

    # -- engine persistence ------------------------------------------------
    def test_engine_persists_completion(self):
        dl = self._make("done.bin", num_threads=4)
        dl.start()
        self.assertEqual(wait_done(dl), DONE, dl.error)
        self.assertEqual(sha256(dl.path), self.expected)
        row = self.store.get(dl.job_id)
        self.assertEqual(row["status"], DONE)
        self.assertEqual(row["size"], os.path.getsize(dl.path))
        self.assertEqual(row["downloaded"], row["size"])

    def test_pause_writes_status_and_offsets(self):
        dl = self._make("paused.bin", speed_limit=150_000)
        dl.start()
        self.assertTrue(wait_until(lambda: dl.downloaded > 100_000, 60))
        dl.pause()
        self.assertTrue(wait_until(lambda: dl.status == PAUSED, 10))
        row = self.store.get(dl.job_id)
        self.assertEqual(row["status"], PAUSED)
        segs = self.store.load_segments(dl.job_id)
        self.assertTrue(segs)
        self.assertGreater(sum(s["downloaded"] for s in segs), 0)
        dl.abandon()

    def test_db_failure_never_breaks_download(self):
        dl = self._make("broken_db.bin", num_threads=4)
        self.store._conn.close()          # simulate a dead/unwritable DB
        dl.start()
        self.assertEqual(wait_done(dl), DONE, dl.error)
        self.assertEqual(sha256(dl.path), self.expected)
        self.assertIsNotNone(self.store.last_error)

    # -- restart / resume --------------------------------------------------
    def test_restart_resumes_from_db_segments(self):
        dl = self._make("resume.bin", speed_limit=150_000)
        dl.start()
        self.assertTrue(wait_until(lambda: dl.downloaded > 150_000, 60))
        dl.pause()
        self.assertTrue(wait_until(lambda: dl.status == PAUSED, 10))
        dl.abandon()

        self.store.close()
        self.store = JobStore(self.db)
        record = self.store.get(dl.job_id)
        self.assertEqual(record["status"], PAUSED)
        self.assertGreater(record["downloaded"], 0)

        dl2 = Download(record["url"], dest_dir=record["dest_dir"],
                       filename=record["filename"], num_threads=8,
                       store=self.store, job_id=record["id"])
        dl2.apply_record(record)
        dl2.start()
        self.assertEqual(wait_done(dl2), DONE, dl2.error)
        self.assertEqual(sha256(dl2.path), self.expected)

    def test_db_segments_used_when_sidecar_missing(self):
        dl = self._make("nsidecar.bin", speed_limit=150_000)
        dl.start()
        self.assertTrue(wait_until(lambda: dl.downloaded > 150_000, 60))
        dl.pause()
        self.assertTrue(wait_until(lambda: dl.status == PAUSED, 10))
        dl.abandon()
        os.remove(dl.state_path)          # DB is now the only resume source

        self.store.close()
        self.store = JobStore(self.db)
        record = self.store.get(dl.job_id)
        dl2 = Download(record["url"], dest_dir=record["dest_dir"],
                       filename=record["filename"], store=self.store,
                       job_id=record["id"])
        dl2.apply_record(record)
        # Run preparation synchronously to prove offsets came from the DB.
        dl2._probe()
        dl2._prepare_files()
        self.assertGreater(dl2.downloaded, 0)
        dl2.start()
        self.assertEqual(wait_done(dl2), DONE, dl2.error)
        self.assertEqual(sha256(dl2.path), self.expected)

    # -- acceptance: five jobs survive a close ----------------------------
    def test_five_jobs_survive_close_and_auto_resume(self):
        jobs: list[Download] = []
        for i in range(5):
            dl = self._make(f"batch{i}.bin", num_threads=4,
                            speed_limit=120_000)
            dl.start()
            jobs.append(dl)
        self.assertTrue(wait_until(
            lambda: all(j.downloaded > 60_000 for j in jobs), 60))
        for dl in jobs:
            dl.pause()
        self.assertTrue(wait_until(
            lambda: all(j.status == PAUSED for j in jobs), 15))
        for dl in jobs:
            dl.abandon()

        self.store.close()
        self.store = JobStore(self.db)
        records = self.store.list_all()
        self.assertEqual(len(records), 5)
        self.assertTrue(all(r["status"] == PAUSED for r in records))
        self.assertTrue(all(r["downloaded"] > 0 for r in records))

        restored = []
        for r in records:
            dl = Download(r["url"], dest_dir=r["dest_dir"],
                          filename=r["filename"], num_threads=8,
                          store=self.store, job_id=r["id"])
            dl.apply_record(r)
            dl.start()
            restored.append(dl)
        for dl in restored:
            self.assertEqual(wait_done(dl), DONE, dl.error)
            self.assertEqual(sha256(dl.path), self.expected)
        self.assertTrue(all(r["status"] == DONE
                            for r in self.store.list_all()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
