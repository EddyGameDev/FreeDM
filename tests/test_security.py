"""Security regression tests (Milestone 2, security review 2026-10-19).

Each test pins one finding from `docs/SECURITY.md` so a later change cannot
silently reopen it.

Run with:  python tests/test_security.py
       or:  python -m pytest tests/test_security.py
"""
from __future__ import annotations

import json
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

import control_server                    # noqa: E402
import requests                          # noqa: E402
from control_server import ControlServer, _host_allowed, _normalise  # noqa: E402
from engine import Download, sanitize_filename  # noqa: E402
from gui_testcase import GuiTestCase      # noqa: E402

TOKEN = "test-token-0123456789"


class HostHeaderTests(unittest.TestCase):
    """S3 - the server only answers for loopback names."""

    def test_loopback_hosts_are_allowed(self):
        for host in ("127.0.0.1", "127.0.0.1:6801", "localhost",
                     "localhost:6801", "[::1]:6801", "::1"):
            self.assertTrue(_host_allowed(host), host)

    def test_other_hosts_are_refused(self):
        for host in ("evil.example", "evil.example:6801", "127.0.0.1.evil.com",
                     "192.168.1.5", "", None, "localhost.evil.com"):
            self.assertFalse(_host_allowed(host), host)


class ControlServerSecurityTests(unittest.TestCase):
    """S1/S2/S3/S5/S6 - the loopback control server."""

    def setUp(self):
        self.added = []
        self.server = ControlServer(on_add=self.added.append, token=TOKEN,
                                    port=0)
        self.assertTrue(self.server.start())
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()

    def test_a_foreign_host_header_is_refused(self):
        response = requests.get(f"{self.base}/ping",
                                headers={"Host": "evil.example"}, timeout=5)
        self.assertEqual(response.status_code, 403)

    def test_a_foreign_host_header_is_refused_on_post(self):
        response = requests.post(
            f"{self.base}/add", json={"url": "http://x/y"},
            headers={"Host": "evil.example",
                     "Authorization": f"Bearer {TOKEN}"}, timeout=5)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.added, [])

    def test_a_web_page_gets_no_cors_permission(self):
        response = requests.get(f"{self.base}/ping",
                                headers={"Origin": "https://evil.example"},
                                timeout=5)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_an_extension_origin_gets_cors_permission(self):
        response = requests.get(
            f"{self.base}/ping",
            headers={"Origin": "chrome-extension://abcdefghijklmnop"},
            timeout=5)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"),
                         "chrome-extension://abcdefghijklmnop")

    def test_the_error_message_does_not_leak_internals(self):
        def boom(_job):
            raise RuntimeError("secret path C:\\Users\\someone\\secret")
        self.server.on_add = boom
        response = requests.post(
            f"{self.base}/add", json={"url": "http://x/y"},
            headers={"Authorization": f"Bearer {TOKEN}"}, timeout=5)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret", response.text)
        self.assertIn("internal error", response.text)

    def test_a_dest_dir_that_is_not_a_folder_is_ignored(self):
        job = _normalise({"url": "http://x/y", "dest_dir": "C:/nope/nope"})
        self.assertIsNone(job["dest_dir"])

    def test_a_real_dest_dir_is_kept(self):
        folder = tempfile.mkdtemp(prefix="freedm_sec_")
        try:
            job = _normalise({"url": "http://x/y", "dest_dir": folder})
            self.assertEqual(job["dest_dir"], folder)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_the_token_is_still_required(self):
        response = requests.post(f"{self.base}/add",
                                 json={"url": "http://x/y"}, timeout=5)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.added, [])


class ExtensionManifestTests(unittest.TestCase):
    """S1/S4 - the extension must not ask for more than it uses."""

    def setUp(self):
        here = os.path.dirname(_HERE)
        self.root = os.path.join(here, "extension")
        with open(os.path.join(self.root, "manifest.json"),
                  "r", encoding="utf-8") as fh:
            self.manifest = json.load(fh)

    def test_the_unused_webrequest_permission_is_gone(self):
        self.assertNotIn("webRequest", self.manifest["permissions"])

    def test_only_the_needed_permissions_are_requested(self):
        self.assertEqual(sorted(self.manifest["permissions"]),
                         ["cookies", "downloads", "storage"])

    def test_loopback_is_in_the_host_permissions(self):
        hosts = self.manifest["host_permissions"]
        self.assertIn("http://127.0.0.1/*", hosts)

    def test_the_token_is_not_stored_in_sync_storage(self):
        """S1 - the token must stay on the device."""
        for name in ("background.js", "options.js"):
            with open(os.path.join(self.root, name), "r",
                      encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("chrome.storage.sync", text, name)
            self.assertIn("chrome.storage.local", text, name)

    def test_the_options_page_does_not_use_innerhtml(self):
        for name in ("options.js", "background.js"):
            with open(os.path.join(self.root, name), "r",
                      encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("innerHTML", text, name)
            self.assertNotIn("eval(", text, name)


class FilenameTests(unittest.TestCase):
    """The file name from a server must never escape the destination."""

    def test_path_separators_are_replaced(self):
        for raw in ("../../evil.exe", "..\\..\\evil.exe", "a/b/c.txt"):
            safe = sanitize_filename(raw)
            self.assertNotIn("/", safe)
            self.assertNotIn("\\", safe)

    def test_a_dot_dot_name_cannot_escape(self):
        safe = sanitize_filename("..")
        self.assertNotIn("..", os.path.normpath(safe))

    def test_windows_reserved_names_are_neutralised(self):
        # A leading dot is stripped, so ".hidden" keeps working but ".." does not.
        self.assertEqual(sanitize_filename(".."), "download")
        self.assertEqual(sanitize_filename("   "), "download")

    def test_control_characters_are_removed(self):
        # Newlines are dropped, other control characters become "_".
        self.assertEqual(sanitize_filename("a\x00b\nc"), "a_bc")


class CookieHeaderTests(unittest.TestCase):
    """S8 - a hand-written Cookie header belongs in the jar."""

    def test_the_cookie_moves_into_the_jar(self):
        dl = Download("http://example.com/f.bin",
                      headers={"Cookie": "a=1; b=2", "Referer": "http://x/"})
        cookies = {c.name: c.value for c in dl.session.cookies}
        self.assertEqual(cookies.get("a"), "1")
        self.assertEqual(cookies.get("b"), "2")
        # The raw header must not be sent any more...
        self.assertNotIn("Cookie", dl.session.headers)
        self.assertNotIn("Cookie", dl._session_headers())
        # ... but it is still kept with the job, so it survives a restart.
        self.assertIn("Cookie", dl.headers)

    def test_the_cookie_is_scoped_to_the_host(self):
        dl = Download("http://example.com/f.bin",
                      headers={"Cookie": "a=1"})
        domains = {c.domain for c in dl.session.cookies}
        self.assertIn("example.com", domains)

    def test_other_headers_are_untouched(self):
        dl = Download("http://example.com/f.bin",
                      headers={"Referer": "http://x/", "X-Test": "1"})
        headers = dl._session_headers()
        self.assertEqual(headers.get("Referer"), "http://x/")
        self.assertEqual(headers.get("X-Test"), "1")


class GuiExecutableTests(GuiTestCase):
    """S7 - an executable is never launched without a confirmation."""

    prefix = "freedm_sec_gui_"

    def _make_done(self, name: str):
        dl = self.app._add_url(f"https://example.com/{name}")
        dl.status = "done"
        return dl

    def test_opening_an_executable_asks_first(self):
        import gui
        self.assertIn(".exe", gui.EXECUTABLE_EXTENSIONS)
        self.assertIn(".bat", gui.EXECUTABLE_EXTENSIONS)
        self.assertIn(".ps1", gui.EXECUTABLE_EXTENSIONS)

    def test_a_plain_file_is_not_asked_about(self):
        import gui
        self.assertNotIn(".txt", gui.EXECUTABLE_EXTENSIONS)
        self.assertNotIn(".zip", gui.EXECUTABLE_EXTENSIONS)

    def test_open_file_asks_before_running_an_exe(self):
        dl = self._make_done("setup.exe")
        target = os.path.join(self.tmp, "setup.exe")
        with open(target, "wb") as fh:
            fh.write(b"MZ")
        dl.path = target
        rows = self.app.tree.get_children()
        self.app.tree.selection_set(rows[0])
        with mock.patch.object(self.tk.messagebox, "askyesno",
                               return_value=False) as ask:
            with mock.patch.object(self.app, "_open") as opener:
                self.app.open_file()
        self.assertTrue(ask.called)
        self.assertFalse(opener.called, "must not open the file without a yes")

    def test_open_file_proceeds_after_a_yes(self):
        dl = self._make_done("setup.exe")
        target = os.path.join(self.tmp, "setup.exe")
        with open(target, "wb") as fh:
            fh.write(b"MZ")
        dl.path = target
        rows = self.app.tree.get_children()
        self.app.tree.selection_set(rows[0])
        with mock.patch.object(self.tk.messagebox, "askyesno",
                               return_value=True):
            with mock.patch.object(self.app, "_open") as opener:
                self.app.open_file()
        self.assertTrue(opener.called)

    def test_a_document_is_opened_without_asking(self):
        dl = self._make_done("notes.txt")
        target = os.path.join(self.tmp, "notes.txt")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("hello")
        dl.path = target
        rows = self.app.tree.get_children()
        self.app.tree.selection_set(rows[0])
        with mock.patch.object(self.tk.messagebox, "askyesno") as ask:
            with mock.patch.object(self.app, "_open") as opener:
                self.app.open_file()
        self.assertFalse(ask.called)
        self.assertTrue(opener.called)


if __name__ == "__main__":
    unittest.main(verbosity=2)
