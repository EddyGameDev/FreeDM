# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Milestone 2 / goal N4 tests: dynamic segmentation, adaptive piece sizing
and the global (cross-download) speed limit.

Run with:  python tests/test_n4.py
       or:  python -m pytest tests/test_n4.py
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
import freedm.engine as engine                            # noqa: E402
from freedm.engine import (Download, Segment, DONE, ERROR,  # noqa: E402
                     set_global_speed_limit, global_speed_limit)
from gui_testcase import GuiTestCase      # noqa: E402


def wait_for(dl: Download, timeout: float = 180) -> str:
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


class PieceLayoutTests(unittest.TestCase):
    """The pieces must always tile the file exactly."""

    def test_pieces_are_valid_helper(self):
        good = [Segment(0, 0, 99), Segment(1, 100, 199)]
        self.assertTrue(Download._pieces_are_valid(good, 200))
        # gap
        self.assertFalse(Download._pieces_are_valid(
            [Segment(0, 0, 99), Segment(1, 101, 199)], 200))
        # overlap
        self.assertFalse(Download._pieces_are_valid(
            [Segment(0, 0, 100), Segment(1, 100, 199)], 200))
        # does not start at 0
        self.assertFalse(Download._pieces_are_valid(
            [Segment(0, 1, 199)], 200))
        # wrong total
        self.assertFalse(Download._pieces_are_valid(good, 300))
        # empty
        self.assertFalse(Download._pieces_are_valid([], 200))

    def test_split_preserves_bytes_and_order(self):
        dl = Download("http://example.com/f.bin")
        dl.segments = [Segment(0, 0, 9_999_999)]
        dl.segments[0].downloaded = 1234
        dl._next_index = 1
        head, tail = dl._split_piece(dl.segments[0], 2_000_000)
        self.assertIsNotNone(head)
        self.assertEqual(head.start, 0)
        self.assertEqual(head.end, 1_999_999)
        self.assertEqual(tail.start, 2_000_000)
        self.assertEqual(tail.end, 9_999_999)
        # downloaded bytes are moved to the right piece, total unchanged
        self.assertEqual(head.downloaded, 1234)
        self.assertEqual(tail.downloaded, 0)
        self.assertEqual(head.downloaded + tail.downloaded, 1234)
        # the list still tiles the file and is ordered by start
        starts = [s.start for s in dl.segments]
        self.assertEqual(starts, sorted(starts))
        self.assertTrue(Download._pieces_are_valid(dl.segments, 10_000_000))
        self.assertEqual(dl.split_count, 1)

    def test_split_moves_partial_bytes_to_the_tail(self):
        dl = Download("http://example.com/f.bin")
        dl.segments = [Segment(0, 0, 9_999_999)]
        dl.segments[0].downloaded = 5_000_000      # already past the split point
        dl._next_index = 1
        head, tail = dl._split_piece(dl.segments[0], 2_000_000)
        self.assertEqual(head.downloaded, 2_000_000)
        self.assertEqual(tail.downloaded, 3_000_000)

    def test_split_refuses_tiny_pieces(self):
        dl = Download("http://example.com/f.bin")
        small = Segment(0, 0, 1000)
        dl.segments = [small]
        dl._next_index = 1
        self.assertIsNone(dl._split_piece(small, 512 * 1024))

    def test_piece_target_is_adaptive(self):
        dl = Download("http://example.com/f.bin")
        # Nothing measured yet: conservative, so the first pieces are small.
        self.assertEqual(dl._piece_target(), engine.MIN_PIECE_SIZE)
        # A fast connection raises it, but never above the cap.
        dl._piece_speeds.append(100 * 1024 * 1024)   # 100 MB/s
        self.assertEqual(dl._piece_target(), engine.MAX_PIECE_SIZE)
        # A medium connection -> proportional to the speed.
        dl._piece_speeds.clear()
        dl._piece_speeds.append(1 * 1024 * 1024)     # 1 MB/s -> 5 s -> 5 MB
        self.assertEqual(dl._piece_target(),
                         int(1 * 1024 * 1024 * engine.SPLIT_TARGET_SECONDS))
        # The slowest sample wins, not the average: one slow pipe drags the
        # target down to the floor.
        dl._piece_speeds.append(100 * 1024)          # one slow pipe, 100 KB/s
        self.assertEqual(dl._piece_target(), engine.MIN_PIECE_SIZE)

    def test_initial_segments_never_exceed_the_piece_cap(self):
        dl = Download("http://example.com/f.bin")
        dl.total_size = 100 * 1024 * 1024      # 100 MB
        dl.num_threads = 4
        segs = dl._make_segments()
        self.assertTrue(all(s.size <= engine.MAX_PIECE_SIZE for s in segs))
        self.assertTrue(Download._pieces_are_valid(segs, dl.total_size))


class DynamicSegmentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 64 MB so the initial pieces (64/32 = 2 MB) are larger than the
        # 1 MB floor and dynamic splitting has something to do.
        cls.httpd = range_server.start_server(0, 64)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="freedm_n4_")
        range_server.set_throttle(0)

    def tearDown(self):
        range_server.set_throttle(0)
        shutil.rmtree(self.out, ignore_errors=True)

    def test_download_is_byte_identical_with_dynamic_pieces(self):
        dl = Download(self.base + "/test.bin", dest_dir=self.out, num_threads=8)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertEqual(sha256_file(dl.path), range_server.file_hash())

    def test_pieces_never_exceed_the_cap(self):
        dl = Download(self.base + "/test.bin", dest_dir=self.out, num_threads=8)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertTrue(all(s.size <= engine.MAX_PIECE_SIZE
                            for s in dl.segments),
                        f"piece too large: {max(s.size for s in dl.segments)}")
        self.assertTrue(Download._pieces_are_valid(dl.segments, dl.total_size))

    def test_pieces_still_tile_the_file_after_the_run(self):
        dl = Download(self.base + "/test.bin", dest_dir=self.out, num_threads=8)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        segs = sorted(dl.segments, key=lambda s: s.start)
        self.assertEqual(segs[0].start, 0)
        self.assertEqual(segs[-1].end, dl.total_size - 1)
        self.assertEqual(sum(s.size for s in segs), dl.total_size)
        self.assertTrue(all(s.done for s in segs))

    def test_splitting_actually_happens(self):
        dl = Download(self.base + "/test.bin", dest_dir=self.out, num_threads=8)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertGreater(dl.split_count, 0,
                           "expected the pieces to be split dynamically")

    def test_splitting_can_be_switched_off(self):
        """The old fixed-segment behaviour is still available."""
        dl = Download(self.base + "/test.bin", dest_dir=self.out, num_threads=8)
        with mock.patch.object(engine, "DYNAMIC_SPLITTING", False):
            dl.start()
            self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertEqual(dl.split_count, 0)
        self.assertEqual(len(dl.segments), dl.initial_piece_count)

    def test_piece_count_stays_within_the_cap(self):
        dl = Download(self.base + "/test.bin", dest_dir=self.out, num_threads=8)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertLessEqual(len(dl.segments), engine.MAX_SEGMENTS)

    def test_resume_after_a_pause_keeps_the_file_correct(self):
        dl = Download(self.base + "/test.bin", dest_dir=self.out, num_threads=4,
                      speed_limit=3 * 1024 * 1024)
        dl.start()
        time.sleep(1.2)
        dl.pause()
        time.sleep(0.6)
        self.assertIn(dl.status, ("paused", "done"))
        if dl.status != "done":
            dl.resume()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertEqual(sha256_file(dl.path), range_server.file_hash())

    def test_state_file_is_valid_after_a_pause(self):
        dl = Download(self.base + "/test.bin", dest_dir=self.out, num_threads=4,
                      speed_limit=2 * 1024 * 1024)
        dl.start()
        time.sleep(1.0)
        dl.pause()
        time.sleep(0.6)
        import json
        with open(dl.state_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        segs = [Segment.from_dict(d) for d in data["segments"]]
        self.assertTrue(Download._pieces_are_valid(segs, data["total_size"]))

    def test_a_corrupt_state_file_is_refused(self):
        """A state file whose pieces do not tile the file must be ignored."""
        dl = Download(self.base + "/test.bin", dest_dir=self.out, num_threads=4)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        # Re-create a bogus state file next to a fresh .part and check the
        # engine refuses to resume from it.
        import json
        os.makedirs(self.out, exist_ok=True)
        part = os.path.join(self.out, "bogus.bin.part")
        with open(part, "wb") as fh:
            fh.write(b"\0" * 1024)
        state = part + ".state.json"
        with open(state, "w", encoding="utf-8") as fh:
            json.dump({"url": dl.url, "total_size": 1024,
                       "segments": [{"index": 0, "start": 0, "end": 511,
                                     "downloaded": 0},
                                    {"index": 1, "start": 900, "end": 1023,
                                     "downloaded": 0}]}, fh)
        check = Download(dl.url, dest_dir=self.out, num_threads=2)
        check.state_path = state
        check.part_path = part
        check.total_size = 1024
        self.assertFalse(check._load_state())


class GlobalLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = range_server.start_server(0, 8)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="freedm_n4_gl_")
        set_global_speed_limit(0)

    def tearDown(self):
        set_global_speed_limit(0)
        shutil.rmtree(self.out, ignore_errors=True)

    def test_limit_is_off_by_default(self):
        self.assertEqual(global_speed_limit(), 0.0)

    def test_set_and_read(self):
        set_global_speed_limit(1000)
        self.assertEqual(global_speed_limit(), 1000.0)
        set_global_speed_limit(0)
        self.assertEqual(global_speed_limit(), 0.0)

    def test_global_limit_caps_combined_throughput(self):
        """Two downloads together may not exceed the global cap."""
        limit = 600 * 1024            # 600 KB/s for everything
        set_global_speed_limit(limit)
        dls = [Download(self.base + "/test.bin", dest_dir=self.out,
                        num_threads=2, filename=f"g{i}.bin")
               for i in range(2)]
        for dl in dls:
            dl.start()
        t0 = time.time()
        time.sleep(2.0)
        combined = sum(dl.downloaded for dl in dls)
        elapsed = time.time() - t0
        for dl in dls:
            dl.cancel()
        observed = combined / elapsed
        # Allow slack for the token bucket's first-chunk burst.
        self.assertLessEqual(observed, limit * 1.6,
                             f"combined {observed:.0f} B/s > cap {limit}")

    def test_per_download_limit_still_works_alongside(self):
        dl = Download(self.base + "/test.bin", dest_dir=self.out,
                      num_threads=4, speed_limit=300 * 1024)
        dl.start()
        time.sleep(1.5)
        self.assertLess(dl.downloaded, 1_200 * 1024)
        dl.cancel()


class ThrottledServerTests(unittest.TestCase):
    """Dynamic splitting must not be slower than fixed splitting when one
    connection is slow."""

    @classmethod
    def setUpClass(cls):
        # 32 MB with 4 threads -> 2 MB fixed pieces, so the slow pipe has
        # something big to hold back.
        cls.httpd = range_server.start_server(0, 32)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="freedm_n4_th_")

    def tearDown(self):
        range_server.set_throttle(0)
        shutil.rmtree(self.out, ignore_errors=True)

    def _time_download(self, fixed: bool) -> tuple[float, int]:
        """Download the throttled file; ``fixed`` disables the splitting.

        Returns (seconds, size of the first piece the slow pipe received)."""
        range_server.set_throttle(400 * 1024)      # 400 KB/s on one pipe
        dl = Download(self.base + "/throttle/test.bin", dest_dir=self.out,
                      num_threads=4)
        with mock.patch.object(engine, "DYNAMIC_SPLITTING", not fixed):
            dl.start()
            t0 = time.time()
            self.assertEqual(wait_for(dl), DONE, dl.error)
            elapsed = time.time() - t0
        _served, first = range_server.throttled_stats()
        return elapsed, first

    def test_the_slow_connection_gets_a_smaller_piece(self):
        """This is the mechanism: a slow pipe must hold less data back.

        With fixed pieces the slow connection keeps a whole 2 MB piece; with
        dynamic pieces it only ever holds a 1 MB piece, so the file finishes
        sooner instead of waiting for that one pipe."""
        fixed_time, fixed_piece = self._time_download(fixed=True)
        dynamic_time, dynamic_piece = self._time_download(fixed=False)
        self.assertGreater(fixed_piece, 0, "the slow pipe was never used")
        self.assertGreater(dynamic_piece, 0, "the slow pipe was never used")
        self.assertLess(dynamic_piece, fixed_piece,
                        f"the slow pipe still holds {dynamic_piece} bytes "
                        f"(fixed: {fixed_piece})")
        # ... and the download must not get slower because of it.
        self.assertLessEqual(dynamic_time, fixed_time * 1.25,
                             f"dynamic {dynamic_time:.1f}s was much slower "
                             f"than fixed {fixed_time:.1f}s")


class GuiIntegrationTests(GuiTestCase):
    """The global limit and the new details fields work in the real GUI."""

    prefix = "freedm_n4_gui_"

    def setUp(self):
        super().setUp()
        set_global_speed_limit(0)

    def test_global_limit_is_applied_and_persisted(self):
        with mock.patch.object(self.tk.simpledialog, "askstring",
                               return_value="64"):
            self.app.global_limit_dialog()
        self.assertEqual(global_speed_limit(), 64 * 1024)
        from freedm.settings import load
        self.assertEqual(load(self.store)["global_speed_limit"], 64 * 1024)

    def test_global_limit_can_be_cleared(self):
        self.app.global_limit = 1000
        set_global_speed_limit(1000)
        with mock.patch.object(self.tk.simpledialog, "askstring",
                               return_value="0"):
            self.app.global_limit_dialog()
        self.assertEqual(global_speed_limit(), 0.0)

    def test_details_dialog_shows_pieces_and_the_global_cap(self):
        dl = self.app._add_url("https://example.com/f.bin")
        rows = self.app.tree.get_children()
        self.app.tree.selection_set(rows[0])
        set_global_speed_limit(128 * 1024)
        with mock.patch.object(self.tk.messagebox, "showinfo") as info:
            self.app.show_details()
        text = info.call_args[0][1]
        self.assertIn("Pieces:", text)
        self.assertIn("Global cap:", text)

    def test_gui_exposes_the_global_limit_dialog(self):
        from freedm import gui
        self.assertTrue(hasattr(gui.App, "global_limit_dialog"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
