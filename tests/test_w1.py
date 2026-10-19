# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""W1 tests: local browser-handoff control server.

Run with:  python tests/test_w1.py
       or:  python -m pytest tests/test_w1.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import requests  # noqa: E402

from control_server import (  # noqa: E402
    ControlServer,
    export_extension,
    load_or_create_token,
)
from engine import Download  # noqa: E402

TOKEN = "test-token-1234567890"


class W1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freedm_w1_")
        self._old_home = os.environ.get("FREEDM_HOME")
        os.environ["FREEDM_HOME"] = self.tmp
        self.added: list[dict] = []
        self.server = ControlServer(
            on_add=lambda payload: (self.added.append(payload), 7)[1],
            token=TOKEN, port=0)
        self.assertTrue(self.server.start(), self.server.last_error)
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()
        if self._old_home is None:
            os.environ.pop("FREEDM_HOME", None)
        else:
            os.environ["FREEDM_HOME"] = self._old_home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {TOKEN}"}

    # -- health -----------------------------------------------------------
    def test_ping_needs_no_token(self):
        r = requests.get(f"{self.base}/ping", timeout=5)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["app"], "FreeDM")
        self.assertEqual(body["port"], self.server.port)

    def test_unknown_path_is_404(self):
        self.assertEqual(
            requests.get(f"{self.base}/nope", timeout=5).status_code, 404)
        self.assertEqual(
            requests.post(f"{self.base}/nope", json={}, timeout=5).status_code,
            404)

    # -- auth -------------------------------------------------------------
    def test_add_without_token_is_403(self):
        r = requests.post(f"{self.base}/add", json={"url": "http://x/y"},
                          timeout=5)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.added, [])

    def test_add_with_wrong_token_is_403(self):
        r = requests.post(f"{self.base}/add", json={"url": "http://x/y"},
                          headers={"Authorization": "Bearer nope"}, timeout=5)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.added, [])

    def test_rejected_posts_always_return_a_clean_response(self):
        """Regression: the server must read the body before rejecting it.

        Answering 403 while the client was still uploading produced a
        connection reset (WinError 10053) on Windows instead of the 403."""
        payload = {"url": "http://example.com/file.bin", "data": "x" * 40000}
        for _ in range(25):
            r = requests.post(f"{self.base}/add", json=payload,
                              headers={"Authorization": "Bearer nope"},
                              timeout=5)
            self.assertEqual(r.status_code, 403)
            self.assertFalse(r.json()["ok"])
        self.assertEqual(self.added, [])

    def test_rejected_posts_always_return_a_clean_response(self):
        """Regression: the server must read the body before rejecting it.

        Answering 403 while the client is still uploading produced a
        connection reset (WinError 10053) on Windows instead of the 403."""
        payload = {"url": "http://example.com/file.bin", "data": "x" * 40000}
        for _ in range(25):
            r = requests.post(f"{self.base}/add", json=payload,
                              headers={"Authorization": "Bearer nope"},
                              timeout=5)
            self.assertEqual(r.status_code, 403)
            self.assertFalse(r.json()["ok"])
        self.assertEqual(self.added, [])

    def test_add_accepts_x_freedm_token_header(self):
        r = requests.post(f"{self.base}/add", json={"url": "http://x/y"},
                          headers={"X-FreeDM-Token": TOKEN}, timeout=5)
        self.assertEqual(r.status_code, 200)

    # -- payloads ---------------------------------------------------------
    def test_add_forwards_cookies_referer_and_ua(self):
        payload = {
            "url": "http://example.com/file.bin",
            "cookies": [{"name": "a", "value": "b", "domain": ".example.com",
                         "path": "/"}],
            "referer": "http://example.com/page",
            "user_agent": "Mozilla/5.0 Test",
            "filename": "file.bin",
            "headers": {"X-Custom": "1"},
            "threads": 4,
        }
        r = requests.post(f"{self.base}/add", json=payload,
                          headers=self._auth(), timeout=5)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["id"], 7)
        self.assertEqual(len(self.added), 1)
        job = self.added[0]
        self.assertEqual(job["url"], payload["url"])
        self.assertEqual(job["referer"], payload["referer"])
        self.assertEqual(job["user_agent"], payload["user_agent"])
        self.assertEqual(job["cookies"], payload["cookies"])
        self.assertEqual(job["filename"], "file.bin")
        self.assertEqual(job["threads"], 4)
        self.assertEqual(job["headers"], {"X-Custom": "1"})

    def test_add_rejects_non_http_url(self):
        r = requests.post(f"{self.base}/add", json={"url": "ftp://x/y"},
                          headers=self._auth(), timeout=5)
        self.assertEqual(r.status_code, 400)

    def test_add_rejects_invalid_json(self):
        r = requests.post(f"{self.base}/add", data="{not json",
                          headers={**self._auth(),
                                   "Content-Type": "application/json"},
                          timeout=5)
        self.assertEqual(r.status_code, 400)

    def test_threads_are_clamped(self):
        requests.post(f"{self.base}/add",
                      json={"url": "http://x/y", "threads": 999},
                      headers=self._auth(), timeout=5)
        self.assertEqual(self.added[0]["threads"], 32)

    def test_preflight_options(self):
        # Security: only a browser extension may talk to the control server.
        # A web page must not get the CORS headers that would let it read
        # the answers (see docs/SECURITY.md, finding S2).
        r = requests.options(f"{self.base}/add",
                             headers={"Origin": "https://evil.example"},
                             timeout=5)
        self.assertEqual(r.status_code, 204)
        self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))

    def test_preflight_allows_the_extension_origin(self):
        origin = "chrome-extension://abcdefghijklmnop"
        r = requests.options(f"{self.base}/add", headers={"Origin": origin},
                             timeout=5)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), origin)

    # -- token + extension files -----------------------------------------
    def test_token_file_created_once_and_stable(self):
        first = load_or_create_token()
        self.assertTrue(os.path.exists(os.path.join(self.tmp,
                                                    "control_token.txt")))
        self.assertEqual(first, load_or_create_token())
        self.assertGreaterEqual(len(first), 20)

    def test_export_extension_copies_files(self):
        dest = export_extension()
        for name in ("manifest.json", "background.js", "options.html",
                     "options.js"):
            self.assertTrue(os.path.exists(os.path.join(dest, name)), name)
        with open(os.path.join(dest, "manifest.json"),
                  encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["manifest_version"], 3)

    # -- engine robustness -----------------------------------------------
    def test_cookie_without_domain_is_skipped_not_fatal(self):
        dl = Download("http://127.0.0.1:1/x.bin",
                      cookies=[{"name": "a", "value": "b"},
                               {"name": "c", "value": "d",
                                "domain": "example.com", "path": "/"}])
        names = {c.name for c in dl.session.cookies}
        self.assertIn("c", names)
        dl.session.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
