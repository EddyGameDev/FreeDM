"""Milestone 2 / goal N8 tests: the Firefox extension, the context menu and
the native messaging host.

Run with:  python tests/test_n8.py
       or:  python -m pytest tests/test_n8.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import control_server                    # noqa: E402
import native_host                       # noqa: E402
from control_server import export_extension  # noqa: E402
from gui_testcase import GuiTestCase      # noqa: E402


class ExtensionManifestTests(unittest.TestCase):
    """The Chrome and Firefox manifests must both be valid and complete."""

    def setUp(self):
        self.root = os.path.join(os.path.dirname(_HERE), "extension")
        with open(os.path.join(self.root, "manifest.json"), "r",
                  encoding="utf-8") as fh:
            self.chrome = json.load(fh)
        with open(os.path.join(self.root, "manifest.firefox.json"), "r",
                  encoding="utf-8") as fh:
            self.firefox = json.load(fh)

    def test_both_are_manifest_v3(self):
        self.assertEqual(self.chrome["manifest_version"], 3)
        self.assertEqual(self.firefox["manifest_version"], 3)

    def test_chrome_uses_a_service_worker(self):
        self.assertIn("service_worker", self.chrome["background"])

    def test_firefox_uses_an_event_page(self):
        # Firefox runs the script in a background page, not a service worker.
        self.assertIn("scripts", self.firefox["background"])
        self.assertEqual(self.firefox["background"]["scripts"], ["background.js"])

    def test_firefox_has_a_gecko_id(self):
        gecko = self.firefox["browser_specific_settings"]["gecko"]
        self.assertTrue(gecko["id"])
        self.assertIn("strict_min_version", gecko)

    def test_firefox_uses_an_options_tab(self):
        self.assertIn("options_ui", self.firefox)
        self.assertEqual(self.firefox["options_ui"]["page"], "options.html")

    def test_both_request_the_same_permissions(self):
        self.assertEqual(sorted(self.chrome["permissions"]),
                         sorted(self.firefox["permissions"]))

    def test_the_context_menu_permission_is_present(self):
        for manifest in (self.chrome, self.firefox):
            self.assertIn("contextMenus", manifest["permissions"])

    def test_both_allow_loopback(self):
        for manifest in (self.chrome, self.firefox):
            self.assertIn("http://127.0.0.1/*", manifest["host_permissions"])

    def test_the_background_script_has_the_context_menu(self):
        with open(os.path.join(self.root, "background.js"), "r",
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("Download with FreeDM", text)
        self.assertIn("contextMenus", text)
        self.assertIn("onClicked", text)

    def test_the_background_script_uses_the_native_host(self):
        with open(os.path.join(self.root, "background.js"), "r",
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("sendNativeMessage", text)
        self.assertIn("org.freedm.app", text)

    def test_the_context_menu_picks_the_right_url(self):
        with open(os.path.join(self.root, "background.js"), "r",
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("info.linkUrl", text)
        self.assertIn("info.mediaSrcUrl", text)
        self.assertIn("info.srcUrl", text)


class ExportTests(unittest.TestCase):
    """Exporting for Firefox must produce a loadable folder."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freedm_n8_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_chrome_export_uses_the_chrome_manifest(self):
        dest = export_extension(os.path.join(self.tmp, "chrome"),
                                browser="chrome")
        with open(os.path.join(dest, "manifest.json"), "r",
                  encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertIn("service_worker", manifest["background"])
        self.assertFalse(os.path.exists(
            os.path.join(dest, "manifest.firefox.json")))

    def test_firefox_export_uses_the_firefox_manifest(self):
        dest = export_extension(os.path.join(self.tmp, "firefox"),
                                browser="firefox")
        with open(os.path.join(dest, "manifest.json"), "r",
                  encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertIn("scripts", manifest["background"])
        self.assertIn("browser_specific_settings", manifest)
        self.assertFalse(os.path.exists(
            os.path.join(dest, "manifest.firefox.json")))

    def test_the_export_contains_the_script_files(self):
        dest = export_extension(os.path.join(self.tmp, "files"),
                                browser="chrome")
        for name in ("manifest.json", "background.js", "options.html",
                     "options.js", "README.md"):
            self.assertTrue(os.path.exists(os.path.join(dest, name)), name)


class NativeHostTests(unittest.TestCase):
    """The native messaging protocol and the host's answers."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freedm_n8_host_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_manifest_names_the_host(self):
        manifest = native_host.build_manifest()
        self.assertEqual(manifest["name"], "org.freedm.app")
        self.assertEqual(manifest["type"], "stdio")
        self.assertTrue(manifest["path"])
        self.assertTrue(manifest["allowed_origins"])

    def test_the_manifest_is_written(self):
        with mock.patch.object(native_host, "app_data_dir",
                               return_value=self.tmp):
            path = native_host.write_manifest()
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["name"], "org.freedm.app")

    def test_the_wire_format_round_trips(self):
        stream = io.BytesIO()
        native_host.write_message(stream, {"ok": True, "app": "FreeDM"})
        data = stream.getvalue()
        (length,) = struct.unpack("<I", data[:4])
        self.assertEqual(length, len(data) - 4)
        self.assertEqual(json.loads(data[4:].decode()), {"ok": True,
                                                          "app": "FreeDM"})

    def test_reading_a_message(self):
        stream = io.BytesIO()
        native_host.write_message(stream, {"action": "ping"})
        stream.seek(0)
        self.assertEqual(native_host.read_message(stream), {"action": "ping"})

    def test_reading_a_truncated_message(self):
        self.assertIsNone(native_host.read_message(io.BytesIO(b"")))
        self.assertIsNone(native_host.read_message(io.BytesIO(b"\x01\x02")))

    def test_ping_is_answered(self):
        answer = native_host.handle_message({"action": "ping"})
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["app"], "FreeDM")

    def test_launch_starts_the_app(self):
        with mock.patch.object(native_host, "launch_app",
                               return_value=True) as launch:
            answer = native_host.handle_message({"action": "launch"})
        self.assertTrue(launch.called)
        self.assertTrue(answer["launched"])
        self.assertGreater(answer["wait"], 0)

    def test_launch_reports_a_failure(self):
        with mock.patch.object(native_host, "launch_app", return_value=False):
            answer = native_host.handle_message({"action": "launch"})
        self.assertFalse(answer["launched"])

    def test_an_unknown_action_is_refused(self):
        answer = native_host.handle_message({"action": "delete-everything"})
        self.assertFalse(answer["ok"])

    def test_the_registry_key_names_the_host(self):
        self.assertIn("org.freedm.app", native_host._registry_key("chrome"))
        self.assertIn("org.freedm.app", native_host._registry_key("firefox"))
        self.assertIn("Google", native_host._registry_key("chrome"))
        self.assertIn("Mozilla", native_host._registry_key("firefox"))


class MainEntryPointTests(unittest.TestCase):
    def test_the_native_host_mode_is_wired(self):
        import main
        with mock.patch.object(native_host, "main", return_value=0) as host:
            code = main.main(["--native-host"])
        self.assertEqual(code, 0)
        self.assertTrue(host.called)


class GuiIntegrationTests(GuiTestCase):
    """The Browser dialog offers the Firefox export and the native host."""

    prefix = "freedm_n8_gui_"

    def test_the_gui_exposes_the_new_actions(self):
        import gui
        for name in ("_export_extension", "_install_native_host",
                     "_uninstall_native_host"):
            self.assertTrue(hasattr(gui.App, name), name)

    def test_export_for_firefox_uses_the_firefox_manifest(self):
        folder = os.path.join(self.tmp, "ff")
        with mock.patch("gui.export_extension",
                        return_value=folder) as export:
            # `_open` would start Explorer: never do that in a test.
            with mock.patch.object(self.app, "_open"):
                with mock.patch.object(self.tk.messagebox, "showinfo"):
                    self.app._export_extension("firefox")
        self.assertTrue(export.called)
        self.assertEqual(export.call_args.kwargs.get("browser"), "firefox")

    def test_export_for_chrome_uses_the_chrome_manifest(self):
        folder = os.path.join(self.tmp, "cr")
        with mock.patch("gui.export_extension",
                        return_value=folder) as export:
            with mock.patch.object(self.app, "_open"):
                with mock.patch.object(self.tk.messagebox, "showinfo"):
                    self.app._export_extension()
        self.assertTrue(export.called)
        self.assertEqual(export.call_args.kwargs.get("browser"), "chrome")

    def test_installing_the_native_host_reports_the_result(self):
        with mock.patch("gui.native_host.install_host",
                        return_value=(True, "installed ok")) as install:
            with mock.patch.object(self.tk.messagebox, "showinfo") as info:
                self.app._install_native_host()
        self.assertTrue(install.called)
        self.assertTrue(info.called)

    def test_uninstalling_the_native_host_reports_the_result(self):
        with mock.patch("gui.native_host.uninstall_host",
                        return_value=(True, "removed")) as remove:
            with mock.patch.object(self.tk.messagebox, "showinfo") as info:
                self.app._uninstall_native_host()
        self.assertTrue(remove.called)
        self.assertTrue(info.called)


if __name__ == "__main__":
    unittest.main(verbosity=2)
