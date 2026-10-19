# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""W2 tests: HTTP session, cookies, headers, redirect handling.

Run with:  python tests/test_w2.py
       or:  python -m pytest tests/test_w2.py
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
from freedm.engine import Download, DONE, ERROR, CANCELED  # noqa: E402


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


class W2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = range_server.start_server(0, 5)   # 5 MB
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="freedm_w2_")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    # -- backwards compatibility -----------------------------------------
    def test_no_headers_still_works(self):
        dl = Download(self.base + "/test.bin", dest_dir=self.out, num_threads=8)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertEqual(sha256(dl.path), range_server.file_hash())

    # -- referer gating ---------------------------------------------------
    def test_referer_gate_succeeds(self):
        dl = Download(self.base + "/protected/test.bin", dest_dir=self.out,
                      num_threads=8,
                      headers={"Referer": "http://freedm-test/page.html"})
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertEqual(sha256(dl.path), range_server.file_hash())

    def test_referer_gate_fails_without_header(self):
        dl = Download(self.base + "/protected/test.bin", dest_dir=self.out,
                      num_threads=8)
        dl.start()
        self.assertEqual(wait_for(dl), ERROR)
        self.assertIn("403", dl.error or "")

    # -- cookie gating ----------------------------------------------------
    def test_cookie_gate_dict(self):
        dl = Download(self.base + "/cookie/test.bin", dest_dir=self.out,
                      num_threads=8, cookies={"auth": "secret"})
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)

    def test_cookie_gate_string(self):
        dl = Download(self.base + "/cookie/test.bin", dest_dir=self.out,
                      num_threads=8, cookies="other=1; auth=secret")
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)

    def test_cookie_gate_extension_list(self):
        dl = Download(self.base + "/cookie/test.bin", dest_dir=self.out,
                      num_threads=8,
                      cookies=[{"name": "auth", "value": "secret",
                                "domain": "127.0.0.1", "path": "/"}])
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)

    def test_cookie_gate_fails_without_cookie(self):
        dl = Download(self.base + "/cookie/test.bin", dest_dir=self.out,
                      num_threads=8)
        dl.start()
        self.assertEqual(wait_for(dl), ERROR)
        self.assertIn("403", dl.error or "")

    # -- headers reach every segment -------------------------------------
    def test_segment_requests_carry_headers(self):
        """A gated 5 MB file with 8 threads only succeeds if every segment
        request carries the cookie/referer."""
        dl = Download(self.base + "/cookie/test.bin", dest_dir=self.out,
                      num_threads=8, cookies={"auth": "secret"})
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertGreater(len(dl.segments), 1)
        self.assertEqual(sha256(dl.path), range_server.file_hash())

    # -- redirects --------------------------------------------------------
    def test_redirect_captures_final_url(self):
        dl = Download(self.base + "/redirect/test.bin", dest_dir=self.out,
                      num_threads=8)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertEqual(dl.final_url, self.base + "/test.bin")
        self.assertEqual(sha256(dl.path), range_server.file_hash())

    def test_redirect_with_cookie_still_works(self):
        dl = Download(self.base + "/redirect/test.bin", dest_dir=self.out,
                      num_threads=8, cookies={"auth": "secret"})
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
