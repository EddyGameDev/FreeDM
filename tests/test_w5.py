# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""W5 tests: safe resume (validators), overwrite policy, disk-space precheck.

Run with:  python tests/test_w5.py
       or:  python -m pytest tests/test_w5.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import range_server  # noqa: E402
from engine import Download, DONE, ERROR, CANCELED  # noqa: E402


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wait_for(dl: Download, timeout: float = 120) -> str:
    t0 = time.time()
    while dl.status not in (DONE, ERROR, CANCELED) and time.time() - t0 < timeout:
        time.sleep(0.2)
    return dl.status


class W5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = range_server.start_server(0, 10)   # 10 MB, ephemeral port
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="freedm_w5_")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def url(self) -> str:
        return self.base + "/test.bin"

    # -- regressions ------------------------------------------------------
    def test_normal_download(self):
        dl = Download(self.url(), dest_dir=self.out, num_threads=8)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertEqual(sha256(dl.path), range_server.file_hash())

    def test_pause_resume_unchanged(self):
        dl = Download(self.url(), dest_dir=self.out, num_threads=4,
                      speed_limit=4 * 1024 * 1024)
        dl.start()
        time.sleep(0.9)
        dl.pause()
        time.sleep(0.2)
        self.assertEqual(dl.status, "paused")
        self.assertGreater(dl.downloaded, 0)
        dl.resume()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertEqual(sha256(dl.path), range_server.file_hash())

    # -- B6: resume integrity --------------------------------------------
    def test_state_validator_mismatch_blocks_resume(self):
        """A changed ETag must discard stale state instead of resuming onto it."""
        dl = Download(self.url(), dest_dir=self.out, num_threads=4)
        dl._probe()
        dl._prepare_files()
        self.assertTrue(os.path.exists(dl.state_path))
        old_etag = dl.etag

        range_server.mutate_file()

        dl2 = Download(self.url(), dest_dir=self.out, num_threads=4)
        dl2._probe()
        dl2._prepare_files()
        self.assertTrue(dl2.etag)              # server advertises an ETag
        self.assertNotEqual(dl2.etag, old_etag)
        self.assertFalse(dl2._resuming)        # stale state rejected
        self.assertEqual(dl2.downloaded, 0)    # fresh start

    def test_state_validator_match_allows_resume(self):
        dl = Download(self.url(), dest_dir=self.out, num_threads=4)
        dl._probe()
        dl._prepare_files()
        dl.segments[0].downloaded = 1024
        dl.downloaded = 1024
        dl._save_state()

        dl2 = Download(self.url(), dest_dir=self.out, num_threads=4)
        dl2._probe()
        dl2._prepare_files()
        self.assertTrue(dl2._resuming)
        self.assertEqual(dl2.downloaded, 1024)

    def test_resume_detects_change_same_session(self):
        """Pause, change the remote file, resume -> restart and match new bytes."""
        dl = Download(self.url(), dest_dir=self.out, num_threads=4,
                      speed_limit=4 * 1024 * 1024)
        dl.start()
        time.sleep(0.9)
        dl.pause()
        time.sleep(0.2)
        self.assertEqual(dl.status, "paused")
        self.assertGreater(dl.downloaded, 0)

        range_server.mutate_file()
        new_hash = range_server.file_hash()

        dl.resume()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertEqual(sha256(dl.path), new_hash)

    # -- B9: overwrite policy --------------------------------------------
    def _seed_existing(self) -> str:
        path = os.path.join(self.out, "test.bin")
        with open(path, "wb") as f:
            f.write(b"OLD CONTENT")
        return path

    def test_overwrite_rename_preserves_original(self):
        original = self._seed_existing()
        dl = Download(self.url(), dest_dir=self.out, num_threads=8,
                      on_existing="rename")
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        with open(original, "rb") as f:
            self.assertEqual(f.read(), b"OLD CONTENT")
        self.assertNotEqual(dl.path, original)
        self.assertTrue(os.path.exists(dl.path))
        self.assertEqual(sha256(dl.path), range_server.file_hash())

    def test_overwrite_cancel_preserves_original(self):
        original = self._seed_existing()
        dl = Download(self.url(), dest_dir=self.out, num_threads=8,
                      on_existing="cancel")
        dl.start()
        self.assertEqual(wait_for(dl), CANCELED)
        with open(original, "rb") as f:
            self.assertEqual(f.read(), b"OLD CONTENT")
        self.assertFalse(os.path.exists(original + ".part"))

    def test_overwrite_allowed(self):
        original = self._seed_existing()
        dl = Download(self.url(), dest_dir=self.out, num_threads=8,
                      on_existing="overwrite")
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertEqual(dl.path, original)
        self.assertEqual(sha256(original), range_server.file_hash())

    def test_confirm_overwrite_callback(self):
        self._seed_existing()
        calls = []

        def confirm(path):
            calls.append(path)
            return "cancel"

        dl = Download(self.url(), dest_dir=self.out, num_threads=8,
                      confirm_overwrite=confirm)
        dl.start()
        self.assertEqual(wait_for(dl), CANCELED)
        self.assertEqual(len(calls), 1)

    # -- B9: disk space ---------------------------------------------------
    def test_disk_space_precheck(self):
        dl = Download(self.url(), dest_dir=self.out, num_threads=4)
        with mock.patch("engine.shutil.disk_usage",
                        return_value=SimpleNamespace(free=0)):
            with self.assertRaises(IOError) as ctx:
                dl._probe()
                dl._prepare_files()
        self.assertIn("not enough disk space", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
