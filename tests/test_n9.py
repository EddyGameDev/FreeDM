"""Milestone 2 / goal N9 tests: packaging and quality - pytest collection,
the console build, the icon, the update check, the log file and the installer.

Run with:  python tests/test_n9.py
       or:  python -m pytest tests/test_n9.py
"""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from freedm import logsetup, update            # noqa: E402
from freedm.store import JobStore              # noqa: E402
from gui_testcase import GuiTestCase           # noqa: E402

ROOT = os.path.dirname(_HERE)


class ProjectLayoutTests(unittest.TestCase):
    """The packaging files the build and the release depend on."""

    def test_pytest_configuration_exists(self):
        path = os.path.join(ROOT, "pytest.ini")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("testpaths = tests", text)
        self.assertIn("python_files = test_*.py", text)

    def test_conftest_makes_the_package_importable(self):
        path = os.path.join(ROOT, "conftest.py")
        self.assertTrue(os.path.exists(path))

    def test_the_icon_exists_and_has_every_size(self):
        path = os.path.join(ROOT, "icon.ico")
        self.assertTrue(os.path.exists(path))
        self.assertGreater(os.path.getsize(path), 1000)
        try:
            from PIL import Image
        except ImportError:
            return                      # Pillow is optional at runtime
        with Image.open(path) as image:
            sizes = {s[0] for s in image.info.get("sizes", [])}
        for size in (16, 32, 48, 256):
            self.assertIn(size, sizes)

    def test_the_icon_script_regenerates_it(self):
        path = os.path.join(ROOT, "scripts", "make_icon.py")
        self.assertTrue(os.path.exists(path))

    def test_the_build_script_builds_both_executables(self):
        path = os.path.join(ROOT, "build.ps1")
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("FreeDM-cli", text)
        self.assertIn("--console", text)
        self.assertIn("--icon", text)
        self.assertIn("freedm\\main.py", text)

    def test_the_installer_script_is_present_and_sane(self):
        path = os.path.join(ROOT, "installer", "FreeDM.iss")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        for needed in ("[Setup]", "[Files]", "[Icons]", "[Run]",
                       "LICENSE", "NOTICE"):
            self.assertIn(needed, text)

    def test_the_installer_version_matches_the_app(self):
        """The installer must never ship a stale version number."""
        from freedm import __version__
        with open(os.path.join(ROOT, "installer", "FreeDM.iss"), "r",
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(f'#define AppVersion "{__version__}"', text)

    def test_the_version_file_matches_the_app(self):
        from freedm import __version__
        with open(os.path.join(ROOT, "VERSION.json"), "r",
                  encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["version"], __version__)

    def test_the_changelog_has_a_section_for_the_current_version(self):
        from freedm import __version__
        import sys as _sys
        _sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import release_notes
        text = release_notes.read_changelog()
        # The changelog uses "v1.2.3" headings.
        self.assertIn(f"v{__version__}", release_notes.versions(text))

    def test_the_ci_workflow_is_present(self):
        path = os.path.join(ROOT, ".github", "workflows", "ci.yml")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("python -m pytest", text)
        self.assertIn("windows-latest", text)
        self.assertIn("ubuntu-latest", text)
        self.assertIn("build.ps1", text)

    def test_the_version_file_is_present_and_valid(self):
        path = os.path.join(ROOT, "VERSION.json")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("version", data)
        self.assertRegex(data["version"], r"^\d+\.\d+\.\d+")

    def test_the_gitignore_keeps_the_build_artefacts_out(self):
        path = os.path.join(ROOT, ".gitignore")
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        for entry in ("build/", "dist/", "__pycache__/"):
            self.assertIn(entry, text)


class VersionTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(update.parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(update.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(update.parse_version("2.0"), (2, 0))
        self.assertEqual(update.parse_version(""), (0,))
        self.assertEqual(update.parse_version("nonsense"), (0,))

    def test_is_newer(self):
        self.assertTrue(update.is_newer("1.3.0", "1.2.9"))
        self.assertFalse(update.is_newer("1.2.9", "1.3.0"))
        self.assertFalse(update.is_newer("1.3.0", "1.3.0"))

    def test_check_reports_a_newer_version(self):
        payload = json.dumps({"version": "9.9.9", "url": "https://x/y"}).encode()
        response = mock.Mock()
        response.read.return_value = payload
        response.__enter__ = lambda s: s
        response.__exit__ = lambda *a: False
        with mock.patch("urllib.request.urlopen", return_value=response):
            newer, message = update.check_for_update("1.0.0")
        self.assertTrue(newer)
        self.assertIn("9.9.9", message)

    def test_check_reports_the_current_version(self):
        payload = json.dumps({"version": "1.0.0"}).encode()
        response = mock.Mock()
        response.read.return_value = payload
        response.__enter__ = lambda s: s
        response.__exit__ = lambda *a: False
        with mock.patch("urllib.request.urlopen", return_value=response):
            newer, message = update.check_for_update("1.0.0")
        self.assertFalse(newer)
        self.assertIn("up to date", message)

    def test_check_survives_a_network_error(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=OSError("no network")):
            newer, message = update.check_for_update("1.0.0")
        self.assertFalse(newer)
        self.assertIn("Could not check", message)

    def test_check_survives_a_broken_file(self):
        response = mock.Mock()
        response.read.return_value = b"not json"
        response.__enter__ = lambda s: s
        response.__exit__ = lambda *a: False
        with mock.patch("urllib.request.urlopen", return_value=response):
            newer, message = update.check_for_update("1.0.0")
        self.assertFalse(newer)
        self.assertIn("Could not check", message)


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freedm_n9_log_")
        self.patcher = mock.patch.object(logsetup, "app_data_dir",
                                        return_value=self.tmp)
        self.patcher.start()
        logsetup.enable(False)

    def tearDown(self):
        logsetup.enable(False)
        self.patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_log_is_off_by_default(self):
        self.assertFalse(logsetup.is_enabled())
        self.assertFalse(os.path.exists(logsetup.log_path()))

    def test_enabling_writes_the_file(self):
        path = logsetup.enable(True)
        self.assertTrue(logsetup.is_enabled())
        self.assertTrue(path.endswith("freedm.log"))
        logsetup.get_logger("freedm.test").info("hello")
        for handler in logsetup.get_logger("freedm").handlers:
            handler.flush()
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as fh:
            self.assertIn("hello", fh.read())

    def test_disabling_removes_the_file_handlers(self):
        logsetup.enable(True)
        logsetup.enable(False)
        self.assertFalse(logsetup.is_enabled())
        self.assertEqual(len(logsetup.get_logger("freedm").handlers), 1)
        self.assertIsInstance(logsetup.get_logger("freedm").handlers[0],
                              logging.NullHandler)

    def test_the_log_never_holds_urls_or_tokens(self):
        """The log records the app's events, not the user's data."""
        source = open(os.path.join(ROOT, "freedm", "logsetup.py"),
                      encoding="utf-8").read()
        for forbidden in ("dl.url", "self.url", "self.cookies",
                          "control.token", "self.checksum"):
            self.assertNotIn(forbidden, source)


class SettingsTests(unittest.TestCase):
    def test_new_defaults(self):
        from freedm import settings as S
        prefs = S.load(None)
        self.assertFalse(prefs["log_enabled"])
        self.assertFalse(prefs["check_updates"])

    def test_round_trip(self):
        from freedm import settings as S
        store = JobStore(":memory:")
        try:
            S.save(store, log_enabled=True, check_updates=True)
            prefs = S.load(store)
            self.assertIs(prefs["log_enabled"], True)
            self.assertIs(prefs["check_updates"], True)
        finally:
            store.close()


class PytestCollectionTests(unittest.TestCase):
    """pytest must be able to collect and run the whole suite."""

    def test_pytest_collects_the_suites(self):
        try:
            import pytest
        except ImportError:
            self.skipTest("pytest is not installed")
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=ROOT, capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stdout[-2000:])
        self.assertIn("test", result.stdout)

    def test_every_suite_is_named_test_something(self):
        suites = [f for f in os.listdir(os.path.join(ROOT, "tests"))
                  if f.endswith(".py")]
        suites = [f for f in suites if not f.startswith("gui_testcase")
                  and not f.startswith("range_server")
                  and not f.startswith("crash_session")]
        self.assertTrue(suites)
        for name in suites:
            self.assertTrue(name.startswith("test_"), name)


class GuiIntegrationTests(GuiTestCase):
    """The About dialog exposes the update check and the log switch."""

    prefix = "freedm_n9_gui_"

    def test_about_dialog_exists(self):
        from freedm import gui
        self.assertTrue(hasattr(gui.App, "about_dialog"))
        self.assertTrue(hasattr(gui.App, "_toggle_log"))

    def test_toggling_the_log_persists_it(self):
        from freedm import settings as S
        self.app.log_var.set(True)
        self.app._toggle_log()
        self.assertTrue(S.load(self.store)["log_enabled"])
        self.app.log_var.set(False)
        self.app._toggle_log()
        self.assertFalse(S.load(self.store)["log_enabled"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
