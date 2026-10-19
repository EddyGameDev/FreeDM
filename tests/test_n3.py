"""Milestone 2 / goal N3 tests: size verification, checksum verification and
orphan (.part) cleanup.

Run with:  python tests/test_n3.py
       or:  python -m pytest tests/test_n3.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import range_server                      # noqa: E402
import verify                            # noqa: E402
from engine import Download, DONE, ERROR  # noqa: E402
from store import JobStore               # noqa: E402
from gui_testcase import GuiTestCase      # noqa: E402


def wait_for(dl: Download, timeout: float = 120) -> str:
    t0 = time.time()
    while dl.status not in (DONE, ERROR) and time.time() - t0 < timeout:
        time.sleep(0.2)
    return dl.status


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ParseChecksumTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(verify.parse_checksum(""), ("", ""))
        self.assertEqual(verify.parse_checksum(None), ("", ""))

    def test_bare_sha256(self):
        digest = "a" * 64
        self.assertEqual(verify.parse_checksum(digest), ("sha256", digest))

    def test_explicit_algorithm(self):
        digest = "b" * 32
        self.assertEqual(verify.parse_checksum(f"md5:{digest}"), ("md5", digest))

    def test_case_and_separators(self):
        digest = "C" * 64
        algo, got = verify.parse_checksum(f"SHA-256:{digest[:32]}-{digest[32:]}")
        self.assertEqual(algo, "sha256")
        self.assertEqual(got, digest.lower())

    def test_unknown_algorithm(self):
        with self.assertRaises(ValueError) as ctx:
            verify.parse_checksum("crc32:" + "a" * 8)
        self.assertIn("unknown checksum algorithm", str(ctx.exception))

    def test_wrong_length(self):
        with self.assertRaises(ValueError) as ctx:
            verify.parse_checksum("sha256:" + "a" * 63)
        self.assertIn("64 hex characters", str(ctx.exception))

    def test_non_hex(self):
        with self.assertRaises(ValueError) as ctx:
            verify.parse_checksum("sha256:" + "z" * 64)
        self.assertIn("hexadecimal", str(ctx.exception))

    def test_all_algorithms_supported(self):
        for algo, length in verify.HEX_LENGTHS.items():
            algo_out, digest = verify.parse_checksum(f"{algo}:{'a' * length}")
            self.assertEqual(algo_out, algo)
            self.assertEqual(len(digest), length)


class VerifyHelpersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freedm_n3_")
        self.file = os.path.join(self.tmp, "data.bin")
        with open(self.file, "wb") as fh:
            fh.write(b"hello world" * 100)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_file_digest_matches_hashlib(self):
        expected = hashlib.sha256(open(self.file, "rb").read()).hexdigest()
        self.assertEqual(verify.file_digest(self.file, "sha256"), expected)

    def test_verify_size_ok(self):
        ok, message = verify.verify_size(self.file, 1100)
        self.assertTrue(ok)
        self.assertEqual(message, "")

    def test_verify_size_short(self):
        ok, message = verify.verify_size(self.file, 2200)
        self.assertFalse(ok)
        self.assertIn("size mismatch", message)
        self.assertIn("1100", message)

    def test_verify_size_unknown_is_ok(self):
        ok, message = verify.verify_size(self.file, 0)
        self.assertTrue(ok)
        self.assertEqual(message, "")

    def test_verify_checksum_match(self):
        digest = sha256_file(self.file)
        ok, message, status = verify.verify_checksum(self.file, f"sha256:{digest}")
        self.assertTrue(ok)
        self.assertEqual(status, "verified")
        self.assertIn("verified", message)

    def test_verify_checksum_mismatch_shows_both(self):
        ok, message, status = verify.verify_checksum(self.file, "sha256:" + "0" * 64)
        self.assertFalse(ok)
        self.assertEqual(status, "mismatch")
        self.assertIn("0" * 64, message)          # expected
        self.assertIn(sha256_file(self.file), message)   # actual

    def test_verify_checksum_none(self):
        ok, message, status = verify.verify_checksum(self.file, "")
        self.assertTrue(ok)
        self.assertEqual(status, "none")

    def test_verify_checksum_invalid_spec(self):
        ok, message, status = verify.verify_checksum(self.file, "sha256:zz")
        self.assertFalse(ok)
        self.assertEqual(status, "invalid")


class OrphanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freedm_n3_orphans_")
        self.old = os.path.join(self.tmp, "old.bin.part")
        self.old_state = os.path.join(self.tmp, "old.bin.part.state.json")
        self.new = os.path.join(self.tmp, "new.bin.part")
        self.plain = os.path.join(self.tmp, "keep.bin")
        for path in (self.old, self.old_state, self.new, self.plain):
            with open(path, "wb") as fh:
                fh.write(b"x")
        ancient = time.time() - 60 * 86400          # 60 days old
        for path in (self.old, self.old_state):
            os.utime(path, (ancient, ancient))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_find_orphans_respects_age(self):
        found = verify.find_orphans(self.tmp, min_age_days=30)
        self.assertIn(self.old, found)
        self.assertIn(self.old_state, found)
        self.assertNotIn(self.new, found)          # too recent
        self.assertNotIn(self.plain, found)         # not a FreeDM partial

    def test_find_orphans_disabled(self):
        self.assertEqual(verify.find_orphans(self.tmp, min_age_days=0), [])

    def test_find_orphans_missing_folder(self):
        self.assertEqual(
            verify.find_orphans(os.path.join(self.tmp, "nope"), 30), [])

    def test_cleanup_orphans_deletes_only_listed(self):
        found = verify.find_orphans(self.tmp, min_age_days=30)
        deleted, failed = verify.cleanup_orphans(found)
        self.assertEqual(deleted, 2)
        self.assertEqual(failed, [])
        self.assertFalse(os.path.exists(self.old))
        self.assertFalse(os.path.exists(self.old_state))
        self.assertTrue(os.path.exists(self.new))
        self.assertTrue(os.path.exists(self.plain))

    def test_is_orphan_name(self):
        self.assertTrue(verify.is_orphan_name("x.bin.part"))
        self.assertTrue(verify.is_orphan_name("x.bin.part.state.json"))
        self.assertFalse(verify.is_orphan_name("x.bin"))


class EngineVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = range_server.start_server(0, 4)     # 4 MB
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="freedm_n3_eng_")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def url(self) -> str:
        return self.base + "/test.bin"

    def test_correct_checksum_verifies(self):
        digest = range_server.file_hash()
        dl = Download(self.url(), dest_dir=self.out, num_threads=4,
                      checksum=f"sha256:{digest}")
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertIn("verified", dl.checksum_result)
        self.assertEqual(dl.snapshot()["checksum"], f"sha256:{digest}")

    def test_wrong_checksum_fails_with_both_digests(self):
        wrong = "0" * 64
        dl = Download(self.url(), dest_dir=self.out, num_threads=4,
                      checksum=f"sha256:{wrong}")
        dl.start()
        self.assertEqual(wait_for(dl), ERROR)
        self.assertIn("checksum mismatch", dl.error)
        self.assertIn(wrong, dl.error)
        self.assertIn(range_server.file_hash(), dl.error)

    def test_no_checksum_still_completes(self):
        dl = Download(self.url(), dest_dir=self.out, num_threads=4)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)

    def test_truncated_file_is_detected_by_verify_now(self):
        dl = Download(self.url(), dest_dir=self.out, num_threads=4)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        # Damage the finished file, then re-verify.
        with open(dl.path, "r+b") as fh:
            fh.truncate(max(0, os.path.getsize(dl.path) - 4096))
        ok, message = dl.verify_now()
        self.assertFalse(ok)
        self.assertIn("size mismatch", message)
        self.assertEqual(dl.status, ERROR)

    def test_set_checksum_rejects_bad_value(self):
        dl = Download(self.url(), dest_dir=self.out)
        ok, message = dl.set_checksum("sha256:nothex")
        self.assertFalse(ok)
        self.assertIn("hexadecimal", message)
        self.assertEqual(dl.checksum, "")

    def test_set_checksum_on_finished_job(self):
        dl = Download(self.url(), dest_dir=self.out, num_threads=4)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        ok, message = dl.set_checksum(f"sha256:{range_server.file_hash()}")
        self.assertTrue(ok)
        self.assertIn("verified", message)
        self.assertEqual(dl.status, DONE)

    def test_checksum_persists_in_db(self):
        store = JobStore(":memory:")
        try:
            digest = range_server.file_hash()
            dl = Download(self.url(), dest_dir=self.out, num_threads=4,
                          checksum=f"sha256:{digest}", store=store)
            dl.job_id = store.add(dl)
            dl.start()
            self.assertEqual(wait_for(dl), DONE, dl.error)
            row = store.get(dl.job_id)
            self.assertEqual(row["checksum"], f"sha256:{digest}")
            self.assertIn("verified", row["checksum_result"])
        finally:
            store.close()

    def test_apply_record_restores_checksum(self):
        store = JobStore(":memory:")
        try:
            digest = range_server.file_hash()
            dl = Download(self.url(), dest_dir=self.out, store=store,
                          checksum=f"sha256:{digest}")
            dl.job_id = store.add(dl)
            record = store.get(dl.job_id)
            fresh = Download(record["url"], dest_dir=self.out, store=store,
                             job_id=record["id"])
            fresh.apply_record(record)
            self.assertEqual(fresh.checksum, f"sha256:{digest}")
        finally:
            store.close()


class MigrationTests(unittest.TestCase):
    def test_old_database_gains_checksum_columns(self):
        tmp = tempfile.mkdtemp(prefix="freedm_n3_mig_")
        try:
            path = os.path.join(tmp, "old.db")
            import sqlite3
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
            store = JobStore(path)
            try:
                self.assertIsNone(store.last_error)
                cols = {r["name"] for r in store._read(
                    "PRAGMA table_info(downloads)")}
                self.assertIn("checksum", cols)
                self.assertIn("checksum_result", cols)
                self.assertEqual(len(store.list_all()), 1)
            finally:
                store.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class GuiIntegrationTests(GuiTestCase):
    """Real Tk window: default checksum, details dialog, cleanup settings."""

    prefix = "freedm_n3_gui_"

    def setUp(self):
        super().setUp()

    def test_new_download_uses_the_default_checksum(self):
        self.app.default_checksum = "sha256:" + "a" * 64
        self.app.url_var.set("https://example.com/f.bin")
        self.app.add_download()
        self.assertEqual(len(self.app.downloads), 1)
        self.assertEqual(self.app.downloads[0].checksum, "sha256:" + "a" * 64)

    def test_details_dialog_shows_the_checksum(self):
        dl = self.app._add_url("https://example.com/f.bin")
        dl.checksum = "sha256:" + "b" * 64
        dl.checksum_result = "sha256 checksum verified"
        rows = self.app.tree.get_children()
        self.app.tree.selection_set(rows[0])
        with mock.patch.object(self.tk.messagebox, "showinfo") as info:
            self.app.show_details()
        self.assertTrue(info.called)
        text = info.call_args[0][1]
        self.assertIn("sha256:" + "b" * 64, text)
        self.assertIn("sha256 checksum verified", text)

    def test_cleanup_age_round_trips_through_settings(self):
        self.app.cleanup_days = 14
        from settings import save
        save(self.store, cleanup_days=self.app.cleanup_days)
        from settings import load
        self.assertEqual(load(self.store)["cleanup_days"], 14)

    def test_gui_exposes_the_new_dialogs(self):
        import gui
        self.assertTrue(hasattr(gui.App, "checksum_dialog"))
        self.assertTrue(hasattr(gui.App, "cleanup_dialog"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
