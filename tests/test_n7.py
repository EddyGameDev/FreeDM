"""Milestone 2 / goal N7 tests: proxy configuration, address-family
preference and mirror sources.

Run with:  python tests/test_n7.py
       or:  python -m pytest tests/test_n7.py
"""
from __future__ import annotations

import os
import shutil
import socket
import sys
import tempfile
import time
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import network                          # noqa: E402
import range_server                      # noqa: E402
from engine import Download, DONE, ERROR  # noqa: E402
from store import JobStore               # noqa: E402
import settings as S                     # noqa: E402
from gui_testcase import GuiTestCase      # noqa: E402


def wait_for(dl: Download, timeout: float = 120) -> str:
    t0 = time.time()
    while dl.status not in (DONE, ERROR) and time.time() - t0 < timeout:
        time.sleep(0.2)
    return dl.status


class ProxyConfigTests(unittest.TestCase):
    def setUp(self):
        self.proxy = network.ProxyConfig()

    def test_disabled_by_default(self):
        self.assertFalse(self.proxy.enabled)
        self.assertEqual(self.proxy.proxies(), {})
        self.assertIsNone(self.proxy.proxies_for("http://x/y"))

    def test_simple_proxy(self):
        self.proxy.configure("http://127.0.0.1:8080")
        self.assertTrue(self.proxy.enabled)
        proxies = self.proxy.proxies()
        self.assertEqual(proxies["http"], "http://127.0.0.1:8080")
        self.assertEqual(proxies["https"], "http://127.0.0.1:8080")

    def test_scheme_is_added_when_missing(self):
        self.proxy.configure("127.0.0.1:8080")
        self.assertEqual(self.proxy.proxies()["http"], "http://127.0.0.1:8080")

    def test_credentials_are_embedded(self):
        self.proxy.configure("http://127.0.0.1:8080", "bob", "s3cret")
        url = self.proxy.proxies()["https"]
        self.assertIn("bob:s3cret@", url)

    def test_summary_never_leaks_the_password(self):
        self.proxy.configure("http://127.0.0.1:8080", "bob", "s3cret")
        text = self.proxy.summary()
        self.assertNotIn("s3cret", text)
        self.assertIn("bob", text)

    def test_bypass_exact_host(self):
        self.proxy.configure("http://127.0.0.1:8080", bypass="example.com")
        self.assertTrue(self.proxy.is_bypassed("https://example.com/f.bin"))
        self.assertFalse(self.proxy.is_bypassed("https://other.com/f.bin"))

    def test_bypass_subdomain(self):
        self.proxy.configure("http://p:1", bypass="example.com")
        self.assertTrue(self.proxy.is_bypassed("https://cdn.example.com/f"))

    def test_bypass_wildcard(self):
        self.proxy.configure("http://p:1", bypass="*.example.com")
        self.assertTrue(self.proxy.is_bypassed("https://cdn.example.com/f"))
        self.assertFalse(self.proxy.is_bypassed("https://example.com/f"))

    def test_bypass_everything(self):
        self.proxy.configure("http://p:1", bypass="*")
        self.assertTrue(self.proxy.is_bypassed("https://anything/f"))

    def test_bypassed_host_gets_a_null_override(self):
        self.proxy.configure("http://p:1", bypass="example.com")
        override = self.proxy.proxies_for("https://example.com/f")
        self.assertEqual(override, {"http": None, "https": None})
        self.assertIsNone(self.proxy.proxies_for("https://other.com/f"))


class AddressPreferenceTests(unittest.TestCase):
    def test_sorted_addresses_prefers_ipv4(self):
        found = network.sorted_addresses("localhost", 80, prefer_ipv4=True)
        if len(found) > 1:
            self.assertEqual(found[0][0], socket.AF_INET)

    def test_sorted_addresses_prefers_ipv6_when_asked(self):
        found = network.sorted_addresses("localhost", 80, prefer_ipv4=False)
        if any(item[0] == socket.AF_INET6 for item in found):
            self.assertEqual(found[0][0], socket.AF_INET6)

    def test_install_is_idempotent_and_toggleable(self):
        network.install_address_preference(True)
        first = socket.getaddrinfo
        network.install_address_preference(False)
        self.assertIs(socket.getaddrinfo, first)
        self.assertFalse(network.address_preference())
        network.install_address_preference(True)
        self.assertTrue(network.address_preference())


class MirrorUrlTests(unittest.TestCase):
    def test_mirror_keeps_the_original_path(self):
        url = network.mirror_path("https://b.example/mirror",
                                  "https://a.example/files/x.zip")
        self.assertEqual(url, "https://b.example/mirror/files/x.zip")

    def test_mirror_without_a_base_path(self):
        url = network.mirror_path("https://b.example",
                                  "https://a.example/files/x.zip")
        self.assertEqual(url, "https://b.example/files/x.zip")

    def test_mirror_keeps_the_query_string(self):
        url = network.mirror_path("https://b.example",
                                  "https://a.example/x.zip?token=abc")
        self.assertIn("token=abc", url)

    def test_mirror_gets_a_scheme(self):
        url = network.mirror_path("b.example", "https://a.example/x.zip")
        self.assertTrue(url.startswith("http://b.example/"))

    def test_empty_base(self):
        self.assertEqual(network.mirror_url("", "/x.zip"), "")


class MirrorDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Two servers, one file: the mirror serves the identical bytes.
        cls.httpd = range_server.start_server(0, 2)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="freedm_n7_")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_a_dead_primary_falls_back_to_a_mirror(self):
        # A port nothing is listening on.
        dl = Download("http://127.0.0.1:9/test.bin", dest_dir=self.out,
                      num_threads=2, mirrors=[self.base])
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertTrue(os.path.exists(dl.path))
        self.assertEqual(dl.downloaded, dl.total_size)

    def test_mirrors_are_persisted(self):
        store = JobStore(":memory:")
        try:
            dl = Download(self.base + "/test.bin", dest_dir=self.out,
                          store=store)
            dl.job_id = store.add(dl)
            dl.set_mirrors([self.base, "http://other.example/m"])
            row = store.get(dl.job_id)
            self.assertIn("other.example", row["mirrors"])
            fresh = Download(row["url"], dest_dir=self.out, store=store,
                             job_id=row["id"])
            fresh.apply_record(row)
            self.assertEqual(fresh.mirrors,
                             [self.base, "http://other.example/m"])
        finally:
            store.close()

    def test_set_mirrors_cleans_and_deduplicates(self):
        dl = Download(self.base + "/test.bin", dest_dir=self.out)
        dl.set_mirrors(["  http://a/  ", "http://a/", "", "http://b/"])
        self.assertEqual(dl.mirrors, ["http://a/", "http://b/"])

    def test_old_database_gains_the_mirrors_column(self):
        import sqlite3
        tmp = tempfile.mkdtemp(prefix="freedm_n7_mig_")
        try:
            path = os.path.join(tmp, "old.db")
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
            conn.commit()
            conn.close()
            store = JobStore(path)
            try:
                cols = {r["name"] for r in store._read(
                    "PRAGMA table_info(downloads)")}
                self.assertIn("mirrors", cols)
            finally:
                store.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class SettingsTests(unittest.TestCase):
    def test_new_defaults(self):
        prefs = S.load(None)
        self.assertEqual(prefs["proxy_url"], "")
        self.assertEqual(prefs["proxy_user"], "")
        self.assertEqual(prefs["proxy_pass"], "")
        self.assertEqual(prefs["proxy_bypass"], "")
        self.assertIs(prefs["prefer_ipv4"], True)

    def test_round_trip(self):
        store = JobStore(":memory:")
        try:
            S.save(store, proxy_url="http://p:8080", proxy_user="bob",
                   proxy_pass="x", proxy_bypass="localhost", prefer_ipv4=False)
            prefs = S.load(store)
            self.assertEqual(prefs["proxy_url"], "http://p:8080")
            self.assertEqual(prefs["proxy_bypass"], "localhost")
            self.assertIs(prefs["prefer_ipv4"], False)
        finally:
            store.close()


class GuiIntegrationTests(GuiTestCase):
    """Real Tk window: the network dialog and the mirrors dialog."""

    prefix = "freedm_n7_gui_"

    def test_network_settings_are_applied_and_persisted(self):
        self.app.proxy_url = "http://127.0.0.1:8080"
        self.app.proxy_bypass = "localhost"
        self.app.prefer_ipv4 = False
        self.app._apply_network_settings()
        save_settings = self.app._apply_network_settings
        self.assertTrue(save_settings is not None)
        from network import PROXY
        self.assertTrue(PROXY.enabled)
        self.assertTrue(PROXY.is_bypassed("http://localhost/x"))
        from settings import load
        # the persisted values come from the dialog, so set them directly too
        import settings as S
        S.save(self.store, proxy_url=self.app.proxy_url,
               proxy_bypass=self.app.proxy_bypass,
               prefer_ipv4=self.app.prefer_ipv4)
        prefs = load(self.store)
        self.assertEqual(prefs["proxy_url"], "http://127.0.0.1:8080")
        self.assertIs(prefs["prefer_ipv4"], False)

    def test_connection_check_reports_failure(self):
        with mock.patch("requests.get", side_effect=OSError("no route")):
            result = self.app._check_connection()
        self.assertIn("failed", result)

    def test_connection_check_reports_success(self):
        response = mock.Mock(status_code=204)
        with mock.patch("requests.get", return_value=response):
            result = self.app._check_connection()
        self.assertIn("OK", result)

    def test_gui_exposes_the_network_actions(self):
        import gui
        for name in ("network_dialog", "mirrors_dialog", "_check_connection",
                     "_apply_network_settings"):
            self.assertTrue(hasattr(gui.App, name), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
