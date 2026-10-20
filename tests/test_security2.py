"""Security regression tests, round two (Milestone 3, goal G1).

The first round is in `test_security.py` and covers the code up to N6. This
file covers the modules that were added afterwards - the network options, the
native messaging host, the update check, the log file, the streaming path and
the category rules - and the findings in `docs/SECURITY.md` (round two).

Run with:  python tests/test_security2.py
       or:  python -m pytest tests/test_security2.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import range_server                      # noqa: E402
from freedm import categories, native_host, network, stream  # noqa: E402
from freedm.engine import Download        # noqa: E402
from freedm.store import JobStore         # noqa: E402
from gui_testcase import GuiTestCase      # noqa: E402

ROOT = os.path.dirname(_HERE)


class StreamUrlPolicyTests(unittest.TestCase):
    """S9 - a playlist may only name http(s) URLs."""

    def test_a_file_url_is_refused(self):
        with self.assertRaises(stream.StreamError):
            stream.resolve_url("file:///C:/Windows/System32/config/SAM",
                               "http://host/media.m3u8")

    def test_a_ftp_url_is_refused(self):
        with self.assertRaises(stream.StreamError):
            stream.resolve_url("ftp://host/file.ts", "http://host/m.m3u8")

    def test_a_scheme_less_url_is_refused(self):
        with self.assertRaises(stream.StreamError):
            stream.resolve_url("//host/seg.ts", "")

    def test_http_and_https_are_allowed(self):
        self.assertEqual(stream.resolve_url("http://a/x.ts", ""),
                         "http://a/x.ts")
        self.assertEqual(stream.resolve_url("https://a/x.ts", ""),
                         "https://a/x.ts")

    def test_a_relative_url_is_resolved(self):
        self.assertEqual(stream.resolve_url("seg.ts", "http://h/d/m.m3u8"),
                         "http://h/d/seg.ts")


class PrivateAddressTests(unittest.TestCase):
    """S9 - a playlist must not reach the local network by default."""

    def test_loopback_is_private(self):
        self.assertTrue(stream.is_private_host("127.0.0.1"))
        self.assertTrue(stream.is_private_host("::1"))
        self.assertTrue(stream.is_private_host("localhost"))

    def test_private_ranges_are_private(self):
        for host in ("10.0.0.5", "192.168.1.10", "172.16.0.1", "169.254.1.1"):
            self.assertTrue(stream.is_private_host(host), host)

    def test_public_addresses_are_not_private(self):
        for host in ("8.8.8.8", "1.1.1.1", "93.184.216.34"):
            self.assertFalse(stream.is_private_host(host), host)

    def test_a_private_segment_is_refused(self):
        with self.assertRaises(stream.StreamError) as ctx:
            stream.check_segment_url("http://192.168.1.10/seg.ts",
                                     "http://media.example/m.m3u8")
        self.assertIn("private address", str(ctx.exception))

    def test_the_playlist_own_host_is_allowed(self):
        # The user chose this address, so it is fine.
        url = stream.check_segment_url("http://192.168.1.10/seg.ts",
                                       "http://192.168.1.10/m.m3u8")
        self.assertEqual(url, "http://192.168.1.10/seg.ts")

    def test_private_addresses_can_be_allowed_on_purpose(self):
        url = stream.check_segment_url("http://192.168.1.10/seg.ts",
                                       "http://media.example/m.m3u8",
                                       allow_private=True)
        self.assertEqual(url, "http://192.168.1.10/seg.ts")

    def test_a_name_that_resolves_to_a_private_address_is_caught(self):
        self.assertTrue(stream.is_private_host("localhost"))


class StreamHeaderTests(unittest.TestCase):
    """S10 - the user's own headers must not follow a playlist to a new host."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = range_server.start_server(0, 1)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="freedm_sec2_")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def _download(self, headers=None):
        dl = Download(self.base + "/hls/media.m3u8", dest_dir=self.out,
                      headers=headers or {})
        return dl

    def test_the_users_headers_go_to_the_playlists_own_host(self):
        dl = self._download({"Authorization": "Bearer secret",
                              "Referer": "http://ref/"})
        same = dl._stream_headers(self.base + "/hls/seg0.ts")
        self.assertEqual(same.get("Authorization"), "Bearer secret")
        self.assertEqual(same.get("Referer"), "http://ref/")

    def test_the_users_headers_do_not_go_to_another_host(self):
        dl = self._download({"Authorization": "Bearer secret"})
        other = dl._stream_headers("http://elsewhere.example/seg.ts")
        self.assertNotIn("Authorization", other)
        self.assertNotIn("Referer", other)

    def test_a_playlist_naming_a_private_address_fails_the_job(self):
        dl = Download(self.base + "/hls/media.m3u8", dest_dir=self.out)
        # Pretend the playlist pointed at the local network.
        dl._check_stream_url = lambda url: (_ for _ in ()).throw(
            stream.StreamError("private address"))
        with self.assertRaises(Exception):
            dl._check_stream_url("http://192.168.1.10/seg.ts")

    def test_the_default_is_to_refuse_private_addresses(self):
        dl = Download(self.base + "/hls/media.m3u8", dest_dir=self.out)
        self.assertFalse(dl.allow_private_segments)


class NativeHostTests(unittest.TestCase):
    """S11 - the host should name the extension that may call it."""

    def test_the_wildcard_is_the_fallback(self):
        manifest = native_host.build_manifest()
        self.assertIn("chrome-extension://*", manifest["allowed_origins"])
        self.assertIn("ANY installed extension", manifest["_note"])

    def test_a_known_extension_id_is_named_exactly(self):
        origins = native_host.extension_origins("abcdefghijklmnop")
        self.assertEqual(origins, ["chrome-extension://abcdefghijklmnop",
                                   "moz-extension://abcdefghijklmnop"])
        manifest = native_host.build_manifest(origins)
        self.assertNotIn("chrome-extension://*", manifest["allowed_origins"])
        self.assertIn("chrome-extension://abcdefghijklmnop",
                      manifest["allowed_origins"])
        self.assertIn("moz-extension://abcdefghijklmnop",
                      manifest["allowed_origins"])

    def test_no_extension_id_means_no_origins(self):
        self.assertIsNone(native_host.extension_origins(None))
        self.assertIsNone(native_host.extension_origins("  "))

    def test_the_manifest_never_leaks_a_password(self):
        manifest = native_host.build_manifest()
        self.assertNotIn("password", json_text(manifest).lower())


class ProxyTests(unittest.TestCase):
    """S13 - the proxy URL is handled correctly and never shown in full."""

    def test_a_url_with_existing_credentials_is_not_mangled(self):
        proxy = network.ProxyConfig()
        proxy.configure("http://user:pass@proxy:8080", "bob", "secret")
        url = proxy.proxies()["https"]
        self.assertIn("bob:secret@", url)
        self.assertIn("proxy:8080", url)
        self.assertNotIn("user:pass@", url)

    def test_a_url_without_a_scheme_gets_one(self):
        proxy = network.ProxyConfig()
        proxy.configure("127.0.0.1:8080")
        self.assertEqual(proxy.proxies()["http"], "http://127.0.0.1:8080")

    def test_the_summary_never_shows_the_password(self):
        proxy = network.ProxyConfig()
        proxy.configure("http://p:8080", "bob", "secret")
        self.assertNotIn("secret", proxy.summary())


class CategoryFolderTests(unittest.TestCase):
    """S12 - a category name is used as a folder name, so it is sanitised."""

    def test_a_traversing_name_cannot_escape(self):
        name = categories.safe_folder_name("..\\..\\Windows\\System32")
        self.assertNotIn("\\", name)
        self.assertNotIn("/", name)
        self.assertNotIn("..", name)

    def test_illegal_windows_characters_are_replaced(self):
        name = categories.safe_folder_name("a:b*c?d")
        for char in ':*?"<>|':
            self.assertNotIn(char, name)

    def test_an_empty_name_becomes_other(self):
        self.assertEqual(categories.safe_folder_name(""), "Other")
        self.assertEqual(categories.safe_folder_name("   "), "Other")

    def test_the_destination_stays_inside_the_base_folder(self):
        rules = {"..\\..\\evil": [".zip"]}
        dest = categories.destination_for("x.zip", "D:/dl", rules)
        self.assertTrue(dest.startswith("D:/dl"), dest)
        self.assertNotIn("..", dest)

    def test_a_normal_category_is_unchanged(self):
        self.assertEqual(categories.safe_folder_name("Video"), "Video")


class UpdateCheckTests(unittest.TestCase):
    """S14 - the update check only ever reads the project's own file."""

    def test_the_default_url_is_the_project_own_file(self):
        self.assertIn("raw.githubusercontent.com/EddyGameDev/FreeDM",
                       __import__("freedm.update", fromlist=["x"])
                       .DEFAULT_VERSION_URL)

    def test_it_sends_nothing_about_the_user(self):
        from freedm import update
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["headers"] = dict(request.headers)
            captured["url"] = request.full_url

            class Response:
                def read(self):
                    return b'{"version": "9.9.9"}'

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False
            return Response()

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            update.check_for_update("1.0.0")
        headers = {k.lower() for k in captured["headers"]}
        self.assertIn("user-agent", headers)
        for forbidden in ("cookie", "authorization", "x-freedm-token"):
            self.assertNotIn(forbidden, headers)


class LogFileTests(unittest.TestCase):
    """S15 - the log must never hold the user's data."""

    def test_the_logging_module_never_sees_user_data(self):
        source = open(os.path.join(ROOT, "freedm", "logsetup.py"),
                      encoding="utf-8").read()
        for forbidden in ("dl.url", "self.url", "self.cookies",
                          "control.token", "self.checksum", "proxy_pass"):
            self.assertNotIn(forbidden, source)

    def test_the_log_lives_in_the_per_user_folder(self):
        from freedm import logsetup
        self.assertIn("FreeDM", logsetup.log_path())
        self.assertTrue(logsetup.log_path().endswith("freedm.log"))


class ExtensionIdTests(unittest.TestCase):
    """The extension tells the app its id, so the host can name it."""

    def test_the_payload_may_carry_an_extension_id(self):
        from freedm.control_server import _normalise
        job = _normalise({"url": "http://x/y", "extension_id": "abc123"})
        self.assertEqual(job["extension_id"], "abc123")

    def test_an_absurd_extension_id_is_dropped(self):
        from freedm.control_server import _normalise
        job = _normalise({"url": "http://x/y", "extension_id": "x" * 500})
        self.assertIsNone(job["extension_id"])

    def test_the_extension_really_sends_it(self):
        source = open(os.path.join(ROOT, "extension", "background.js"),
                      encoding="utf-8").read()
        self.assertIn("extension_id: chrome.runtime.id", source)


def json_text(value) -> str:
    import json
    return json.dumps(value)


class GuiIntegrationTests(GuiTestCase):
    """The GUI must remember the extension id and offer the private switch."""

    prefix = "freedm_sec2_gui_"

    def test_the_extension_id_is_remembered(self):
        from freedm import settings as S
        self.app._add_from_browser({"url": "https://example.com/f.bin",
                                     "extension_id": "abcdefghijklmnop"})
        self.assertEqual(self.app.extension_id, "abcdefghijklmnop")
        self.assertEqual(S.load(self.store)["extension_id"],
                         "abcdefghijklmnop")

    def test_installing_the_host_uses_the_known_id(self):
        self.app.extension_id = "abcdefghijklmnop"
        with mock.patch("freedm.native_host.install_host",
                        return_value=(True, "ok")) as install:
            with mock.patch.object(self.tk.messagebox, "showinfo"):
                self.app._install_native_host()
        self.assertTrue(install.called)
        origins = install.call_args[0][0]
        self.assertIn("chrome-extension://abcdefghijklmnop", origins)

    def test_the_private_address_switch_is_a_setting(self):
        from freedm import settings as S
        self.assertFalse(S.load(self.store)["allow_private_segments"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
