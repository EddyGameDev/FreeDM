# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Milestone 2 / goal N5 tests: categories, list filtering and queue
export/import.

Run with:  python tests/test_n5.py
       or:  python -m pytest tests/test_n5.py
"""
from __future__ import annotations

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

import freedm.categories as categories                        # noqa: E402
import range_server                      # noqa: E402
from freedm.engine import Download, DONE        # noqa: E402
from freedm.store import JobStore               # noqa: E402
from freedm import settings as S                     # noqa: E402
from gui_testcase import GuiTestCase      # noqa: E402


def wait_for(dl: Download, timeout: float = 120) -> str:
    t0 = time.time()
    while dl.status not in (DONE, "error") and time.time() - t0 < timeout:
        time.sleep(0.2)
    return dl.status


class RulesTests(unittest.TestCase):
    def test_default_rules_cover_the_usual_types(self):
        rules = categories.default_rules()
        self.assertIn("Video", rules)
        self.assertIn("Archives", rules)
        self.assertIn(".mp4", rules["Video"])
        self.assertIn(".zip", rules["Archives"])

    def test_classify(self):
        rules = categories.default_rules()
        self.assertEqual(categories.classify("movie.mp4", rules), "Video")
        self.assertEqual(categories.classify("song.FLAC", rules), "Music")
        self.assertEqual(categories.classify("book.epub", rules), "Documents")
        self.assertEqual(categories.classify("setup.msi", rules), "Programs")
        self.assertEqual(categories.classify("data.zzz", rules), "Other")
        self.assertEqual(categories.classify("noextension", rules), "Other")

    def test_destination_for(self):
        rules = categories.default_rules()
        dest = categories.destination_for("movie.mp4", "D:/dl", rules)
        self.assertEqual(dest, os.path.join("D:/dl", "Video"))
        self.assertEqual(categories.destination_for("x.bin", "D:/dl", rules),
                         os.path.join("D:/dl", "Other"))

    def test_parse_and_format_round_trip(self):
        rules, errors = categories.parse_rules(
            "Video: .mp4, .mkv\nMusic: .mp3\n")
        self.assertEqual(errors, [])
        self.assertEqual(rules["Video"], [".mp4", ".mkv"])
        text = categories.format_rules(rules)
        again, errors2 = categories.parse_rules(text)
        self.assertEqual(errors2, [])
        self.assertEqual(again, rules)

    def test_parse_reports_bad_lines(self):
        rules, errors = categories.parse_rules(
            "Video: .mp4\nthis line has no colon\nAudio: .mp3, bad..ext\n")
        self.assertIn("Video", rules)
        self.assertTrue(any("expected" in e for e in errors))
        self.assertTrue(any("bad extension" in e for e in errors))

    def test_parse_ignores_comments_and_blank_lines(self):
        rules, errors = categories.parse_rules("# a comment\n\nVideo: .mp4\n")
        self.assertEqual(errors, [])
        self.assertEqual(rules, {"Video": [".mp4"]})

    def test_load_rules_falls_back_to_defaults(self):
        self.assertEqual(categories.load_rules(""),
                         categories.default_rules())
        self.assertEqual(categories.load_rules("garbage"),
                         categories.default_rules())
        self.assertEqual(categories.load_rules("Video: .mp4"),
                         {"Video": [".mp4"]})

    def test_extensions_are_normalised(self):
        rules, errors = categories.parse_rules("Video: MP4, .mkv\n")
        self.assertEqual(errors, [])
        self.assertEqual(rules["Video"], [".mp4", ".mkv"])


class FilterTests(unittest.TestCase):
    def test_empty_filter_matches_everything(self):
        self.assertTrue(categories.matches_filter("a.zip", "http://x/y", "done"))

    def test_match_by_name(self):
        self.assertTrue(categories.matches_filter(
            "holiday.zip", "http://x/y", "done", "holiday"))
        self.assertFalse(categories.matches_filter(
            "holiday.zip", "http://x/y", "done", "work"))

    def test_match_by_host(self):
        self.assertTrue(categories.matches_filter(
            "a.zip", "http://example.com/f.zip", "done", "example.com"))
        self.assertFalse(categories.matches_filter(
            "a.zip", "http://example.com/f.zip", "done", "other.org"))

    def test_match_by_url(self):
        self.assertTrue(categories.matches_filter(
            "a.zip", "http://example.com/f.zip", "done", "f.zip"))

    def test_status_filter(self):
        self.assertTrue(categories.matches_filter(
            "a.zip", "http://x/y", "done", "", "done"))
        self.assertFalse(categories.matches_filter(
            "a.zip", "http://x/y", "done", "", "error"))

    def test_status_and_text_together(self):
        self.assertTrue(categories.matches_filter(
            "a.zip", "http://x/y", "done", "a", "done"))
        self.assertFalse(categories.matches_filter(
            "a.zip", "http://x/y", "error", "a", "done"))


class ExportImportTests(unittest.TestCase):
    def test_round_trip_keeps_every_field(self):
        jobs = [
            {"url": "http://a/1.zip", "filename": "1.zip",
             "dest_dir": "D:/dl", "threads": 8, "checksum": "sha256:aa"},
            {"url": "https://b/2.mp4", "filename": None,
             "dest_dir": None, "threads": None, "checksum": None},
        ]
        text = categories.export_queue(jobs)
        back, errors = categories.import_queue(text)
        self.assertEqual(errors, [])
        self.assertEqual(len(back), 2)
        self.assertEqual(back[0]["url"], "http://a/1.zip")
        self.assertEqual(back[0]["filename"], "1.zip")
        self.assertEqual(back[0]["dest_dir"], "D:/dl")
        self.assertEqual(back[0]["threads"], 8)
        self.assertEqual(back[0]["checksum"], "sha256:aa")
        self.assertEqual(back[1]["url"], "https://b/2.mp4")
        self.assertIsNone(back[1]["filename"])

    def test_import_plain_url_list(self):
        jobs, errors = categories.import_queue(
            "http://a/1\nhttps://b/2\n# comment\n\nnot a url\n")
        self.assertEqual([j["url"] for j in jobs], ["http://a/1", "https://b/2"])
        self.assertTrue(errors)

    def test_import_bad_json(self):
        jobs, errors = categories.import_queue("{not json")
        self.assertEqual(jobs, [])
        self.assertTrue(errors)

    def test_import_empty(self):
        jobs, errors = categories.import_queue("")
        self.assertEqual(jobs, [])
        self.assertTrue(errors)

    def test_import_json_without_jobs(self):
        jobs, errors = categories.import_queue('{"format": "freedm-queue"}')
        self.assertEqual(jobs, [])
        self.assertTrue(errors)


class AutoSortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = range_server.start_server(0, 2)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="freedm_n5_")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_resolver_picks_the_category_folder(self):
        rules = categories.default_rules()
        dl = Download(self.base + "/movie.mp4", dest_dir=self.out,
                      dest_resolver=lambda name: categories.destination_for(
                          name, self.out, rules))
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertEqual(os.path.basename(dl.dest_dir), "Video")
        self.assertTrue(os.path.exists(os.path.join(self.out, "Video")))

    def test_without_a_resolver_the_file_stays_in_the_base_folder(self):
        dl = Download(self.base + "/movie.mp4", dest_dir=self.out)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertEqual(os.path.basename(dl.dest_dir),
                         os.path.basename(self.out))


class SettingsTests(unittest.TestCase):
    def test_new_defaults(self):
        prefs = S.load(None)
        self.assertFalse(prefs["auto_sort"])
        self.assertEqual(prefs["category_rules"], "")
        self.assertEqual(prefs["filter_text"], "")
        self.assertEqual(prefs["filter_status"], "")

    def test_round_trip(self):
        store = JobStore(":memory:")
        try:
            S.save(store, auto_sort=True, category_rules="Video: .mp4\n",
                   filter_text="abc", filter_status="done")
            prefs = S.load(store)
            self.assertIs(prefs["auto_sort"], True)
            self.assertEqual(prefs["category_rules"], "Video: .mp4\n")
            self.assertEqual(prefs["filter_text"], "abc")
            self.assertEqual(prefs["filter_status"], "done")
        finally:
            store.close()


class GuiIntegrationTests(GuiTestCase):
    """Real Tk window: filtering, auto-sort and the import/export buttons."""

    prefix = "freedm_n5_gui_"

    def setUp(self):
        super().setUp()

    def _rows(self) -> int:
        return len(self.app.tree.get_children())

    def test_filter_by_name_hides_the_other_rows(self):
        self.app._add_url("https://example.com/holiday.zip")
        self.app._add_url("https://example.com/work.zip")
        self.assertEqual(self._rows(), 2)
        self.app.filter_text.set("holiday")
        self.app._apply_filter()
        self.assertEqual(self._rows(), 1)
        self.app.filter_text.set("")
        self.app._apply_filter()
        self.assertEqual(self._rows(), 2)

    def test_filter_by_status(self):
        self.app._add_url("https://example.com/a.zip")
        self.app.filter_status.set("done")
        self.app._apply_filter()
        # The new job is queued, not done, so nothing matches.
        self.assertEqual(self._rows(), 0)
        self.app.filter_status.set("(all)")
        self.app._apply_filter()
        self.assertEqual(self._rows(), 1)

    def test_filter_by_host(self):
        self.app._add_url("https://alpha.example.com/a.zip")
        self.app._add_url("https://beta.other.org/b.zip")
        self.app.filter_text.set("beta")
        self.app._apply_filter()
        self.assertEqual(self._rows(), 1)

    def test_filter_is_remembered(self):
        self.app.filter_text.set("keepme")
        self.app._apply_filter()
        from freedm.settings import load
        self.assertEqual(load(self.store)["filter_text"], "keepme")

    def test_auto_sort_uses_the_category_folder(self):
        self.app.auto_sort_var.set(True)
        self.app.dir_var.set(self.tmp)
        dl = self.app._add_url("https://example.com/movie.mp4")
        self.assertTrue(dl.dest_resolver is not None)
        self.assertEqual(os.path.basename(dl.dest_resolver("movie.mp4")),
                         "Video")

    def test_auto_sort_off_has_no_resolver(self):
        self.app.auto_sort_var.set(False)
        dl = self.app._add_url("https://example.com/movie.mp4")
        self.assertIsNone(dl.dest_resolver)

    def test_export_and_import_round_trip(self):
        self.app._add_url("https://example.com/one.zip")
        self.app._add_url("https://example.com/two.zip")
        path = os.path.join(self.tmp, "queue.json")
        with mock.patch.object(self.tk.filedialog, "asksaveasfilename",
                               return_value=path):
            self.app.export_queue_dialog()
        self.assertTrue(os.path.exists(path))
        before = self._rows()
        with mock.patch.object(self.tk.filedialog, "askopenfilename",
                               return_value=path):
            self.app.import_queue_dialog()
        self.assertEqual(self._rows(), before + 2)

    def test_import_a_plain_url_list(self):
        path = os.path.join(self.tmp, "urls.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("https://example.com/x.zip\nhttps://example.com/y.zip\n")
        with mock.patch.object(self.tk.filedialog, "askopenfilename",
                               return_value=path):
            self.app.import_queue_dialog()
        self.assertEqual(self._rows(), 2)

    def test_gui_exposes_the_new_actions(self):
        from freedm import gui
        for name in ("categories_dialog", "export_queue_dialog",
                     "import_queue_dialog", "show_in_folder", "_apply_filter",
                     "_refresh_visible", "_dest_resolver", "_target_dir"):
            self.assertTrue(hasattr(gui.App, name), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
