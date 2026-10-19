# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Milestone 2 / goal N2 tests: batch URL parsing and clipboard detection.

Run with:  python tests/test_n2.py
       or:  python -m pytest tests/test_n2.py
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

import batch                              # noqa: E402
from store import JobStore                # noqa: E402
import settings as S                      # noqa: E402
from gui_testcase import GuiTestCase      # noqa: E402


class ParseUrlsTests(unittest.TestCase):
    def test_five_urls_one_paste(self):
        text = "\n".join(f"https://example.com/file{i}.bin" for i in range(5))
        valid, invalid, dupes = batch.parse_urls(text)
        self.assertEqual(len(valid), 5)
        self.assertEqual(invalid, [])
        self.assertEqual(dupes, 0)

    def test_space_separated_urls(self):
        # Simulates a widget that flattened newlines into spaces.
        text = "http://a/1 https://b/2 http://c/3"
        valid, invalid, dupes = batch.parse_urls(text)
        self.assertEqual(valid, ["http://a/1", "https://b/2", "http://c/3"])
        self.assertEqual(invalid, [])

    def test_wholly_invalid_line_reported_as_is(self):
        valid, invalid, _ = batch.parse_urls("http://a/1\nthis is not a link\n")
        self.assertEqual(valid, ["http://a/1"])
        self.assertEqual(invalid, ["this is not a link"])

    def test_mixed_line_reports_odd_token(self):
        valid, invalid, _ = batch.parse_urls("http://a/1 garbage")
        self.assertEqual(valid, ["http://a/1"])
        self.assertEqual(invalid, ["garbage"])

    def test_duplicates_are_skipped_and_counted(self):
        text = "http://a/1\nhttp://a/1\nhttp://b/2"
        valid, invalid, dupes = batch.parse_urls(text)
        self.assertEqual(valid, ["http://a/1", "http://b/2"])
        self.assertEqual(dupes, 1)
        self.assertEqual(invalid, [])

    def test_blank_lines_and_whitespace_ignored(self):
        valid, invalid, dupes = batch.parse_urls("\n\n   \n\thttp://a/1\t\n\n")
        self.assertEqual(valid, ["http://a/1"])
        self.assertEqual(invalid, [])
        self.assertEqual(dupes, 0)

    def test_non_http_schemes_are_invalid(self):
        valid, invalid, _ = batch.parse_urls("ftp://host/file\nmagnet:?xt=urn")
        self.assertEqual(valid, [])
        self.assertEqual(invalid, ["ftp://host/file", "magnet:?xt=urn"])

    def test_trailing_punctuation_trimmed(self):
        valid, _, _ = batch.parse_urls("https://example.com/x.\n(https://example.com/y)")
        self.assertEqual(valid, ["https://example.com/x", "https://example.com/y"])

    def test_empty_input(self):
        self.assertEqual(batch.parse_urls(""), ([], [], 0))
        self.assertEqual(batch.parse_urls(None), ([], [], 0))

    def test_case_insensitive_scheme(self):
        valid, _, _ = batch.parse_urls("HTTP://example.com/a")
        self.assertEqual(valid, ["HTTP://example.com/a"])


class FindUrlTests(unittest.TestCase):
    def test_url_inside_prose_and_brackets(self):
        self.assertEqual(
            batch.find_url("See (https://example.com/x)."),
            "https://example.com/x")

    def test_trailing_period(self):
        self.assertEqual(batch.find_url("link: http://ex.com/y."),
                         "http://ex.com/y")

    def test_balanced_parentheses_are_kept(self):
        self.assertEqual(batch.find_url("http://en.wikipedia.org/wiki/Foo_(bar)"),
                         "http://en.wikipedia.org/wiki/Foo_(bar)")

    def test_returns_none_without_a_url(self):
        self.assertIsNone(batch.find_url("nothing to see here"))
        self.assertIsNone(batch.find_url(""))

    def test_exclude_skips_known_urls(self):
        text = "http://a/1 and http://b/2"
        self.assertEqual(batch.find_url(text), "http://a/1")
        self.assertEqual(batch.find_url(text, exclude={"http://a/1"}), "http://b/2")

    def test_first_url_wins(self):
        self.assertEqual(batch.find_url("a http://one/ b http://two/"),
                         "http://one/")


class ClipboardSettingTests(unittest.TestCase):
    def test_default_is_off(self):
        self.assertFalse(S.load(None)["clipboard_monitor"])

    def test_round_trip(self):
        store = JobStore(":memory:")
        try:
            S.save(store, clipboard_monitor=True)
            self.assertTrue(S.load(store)["clipboard_monitor"])
            S.save(store, clipboard_monitor=False)
            self.assertFalse(S.load(store)["clipboard_monitor"])
        finally:
            store.close()


class GuiIntegrationTests(GuiTestCase):
    """Real Tk window: batch add and the clipboard confirmation flow."""

    prefix = "freedm_n2_gui_"

    def setUp(self):
        super().setUp()
        self.store.set_setting("control_enabled", "0")

    def _rows(self) -> int:
        return len(self.app.tree.get_children())

    def test_pasting_five_urls_creates_five_rows(self):
        self.app.url_var.set("\n".join(
            f"https://example.com/f{i}.bin" for i in range(5)))
        self.app.add_download()
        self.assertEqual(self._rows(), 5)
        self.assertEqual(len(self.app.downloads), 5)
        self.assertEqual(self.app.url_var.get(), "")   # box is cleared

    def test_duplicate_lines_are_skipped(self):
        self.app.url_var.set("http://a/1\nhttp://a/1\nhttp://b/2")
        self.app.add_download()
        self.assertEqual(self._rows(), 2)
        self.assertIn("duplicate", self.app.status_var.get())

    def test_invalid_line_is_reported_and_nothing_added(self):
        self.app.url_var.set("not a url")
        with mock.patch.object(self.tk.messagebox, "showerror") as err:
            self.app.add_download()
        self.assertTrue(err.called)
        self.assertEqual(self._rows(), 0)

    def test_valid_and_invalid_mixed_adds_only_valid(self):
        self.app.url_var.set("http://a/1\nnonsense")
        with mock.patch.object(self.tk.messagebox, "showerror") as err:
            self.app.add_download()
        self.assertTrue(err.called)          # the user is told about "nonsense"
        self.assertEqual(self._rows(), 1)    # but the valid URL was added

    def test_clipboard_watch_off_by_default_never_asks(self):
        self.root.clipboard_clear()
        self.root.clipboard_append("https://example.com/copied.bin")
        with mock.patch.object(self.tk.messagebox, "askyesno") as ask:
            self.app._check_clipboard()
        self.assertFalse(ask.called)
        self.assertEqual(self._rows(), 0)

    def test_clipboard_watch_asks_and_adds_when_confirmed(self):
        self.app.clipboard_var.set(True)
        self.root.clipboard_clear()
        self.root.clipboard_append("https://example.com/copied.bin")
        with mock.patch.object(self.tk.messagebox, "askyesno", return_value=True):
            self.app._check_clipboard()
        self.assertEqual(self._rows(), 1)
        self.assertEqual(self.app.downloads[0].url, "https://example.com/copied.bin")

    def test_clipboard_watch_declined_adds_nothing(self):
        self.app.clipboard_var.set(True)
        self.root.clipboard_clear()
        self.root.clipboard_append("https://example.com/copied.bin")
        with mock.patch.object(self.tk.messagebox, "askyesno", return_value=False):
            self.app._check_clipboard()
        self.assertEqual(self._rows(), 0)

    def test_clipboard_watch_offers_a_link_only_once(self):
        self.app.clipboard_var.set(True)
        self.root.clipboard_clear()
        self.root.clipboard_append("https://example.com/once.bin")
        with mock.patch.object(self.tk.messagebox, "askyesno", return_value=True) as ask:
            self.app._check_clipboard()
            self.app._check_clipboard()      # same clipboard content
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(self._rows(), 1)


class GuiSurfaceTests(unittest.TestCase):
    """The clipboard/batch wiring exists on the App class (no window created)."""

    def test_app_exposes_batch_and_clipboard_api(self):
        import gui
        for name in ("add_download", "_add_url", "_enqueue", "_new_download",
                     "_check_clipboard", "_toggle_clipboard", "_read_clipboard",
                     "_known_urls"):
            self.assertTrue(hasattr(gui.App, name), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
