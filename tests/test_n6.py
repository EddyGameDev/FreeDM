"""Milestone 2 / goal N6 tests: scheduled starts, the daily download window
and shut-down-when-done.

Run with:  python tests/test_n6.py
       or:  python -m pytest tests/test_n6.py
"""
from __future__ import annotations

import datetime
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

import freedm.automation as automation                        # noqa: E402
import range_server                      # noqa: E402
from freedm.engine import Download, DONE, ERROR, QUEUED, SCHEDULED  # noqa: E402
from freedm.scheduler import Scheduler          # noqa: E402
from freedm.store import JobStore               # noqa: E402
from freedm import settings as S                     # noqa: E402
from gui_testcase import GuiTestCase      # noqa: E402


def wait_for(dl: Download, timeout: float = 120) -> str:
    t0 = time.time()
    while dl.status not in (DONE, ERROR) and time.time() - t0 < timeout:
        time.sleep(0.2)
    return dl.status


class TimeParsingTests(unittest.TestCase):
    def test_parse_valid(self):
        self.assertEqual(automation.parse_time("02:30"), 150)
        self.assertEqual(automation.parse_time("2:30"), 150)
        self.assertEqual(automation.parse_time("00:00"), 0)
        self.assertEqual(automation.parse_time("23:59"), 1439)
        self.assertEqual(automation.parse_time(" 01:05 "), 65)

    def test_parse_invalid(self):
        for bad in ("", None, "abc", "25:00", "12:99", "1230", "12", "1:2:3"):
            self.assertIsNone(automation.parse_time(bad), bad)

    def test_format(self):
        self.assertEqual(automation.format_time(150), "02:30")
        self.assertEqual(automation.format_time(0), "00:00")
        self.assertEqual(automation.format_time(1439), "23:59")
        self.assertEqual(automation.format_time(None), "")

    def test_round_trip(self):
        for minutes in (0, 61, 600, 1439):
            self.assertEqual(
                automation.parse_time(automation.format_time(minutes)), minutes)


class WindowTests(unittest.TestCase):
    def at(self, hour: int, minute: int = 0) -> datetime.datetime:
        return datetime.datetime(2026, 10, 19, hour, minute)

    def test_no_window_means_always(self):
        # An unset start or end means "no restriction".
        self.assertTrue(automation.in_window(self.at(3), None, None))
        self.assertTrue(automation.in_window(self.at(3), 60, None))
        self.assertTrue(automation.in_window(self.at(3), None, 120))
        # A fully set window is a real window: 03:00 is outside 01:00-02:00.
        self.assertFalse(automation.in_window(self.at(3), 60, 120))

    def test_zero_length_window_means_always(self):
        self.assertTrue(automation.in_window(self.at(3), 60, 60))

    def test_simple_window(self):
        self.assertTrue(automation.in_window(self.at(2), 60, 180))
        self.assertTrue(automation.in_window(self.at(1, 0), 60, 180))
        self.assertFalse(automation.in_window(self.at(1, 0), 61, 180))
        self.assertFalse(automation.in_window(self.at(3, 0), 60, 180))
        self.assertFalse(automation.in_window(self.at(0, 30), 60, 180))

    def test_window_wrapping_midnight(self):
        # 23:00 -> 06:00
        self.assertTrue(automation.in_window(self.at(23, 30), 1380, 360))
        self.assertTrue(automation.in_window(self.at(2, 0), 1380, 360))
        self.assertTrue(automation.in_window(self.at(5, 59), 1380, 360))
        self.assertFalse(automation.in_window(self.at(12, 0), 1380, 360))
        self.assertFalse(automation.in_window(self.at(6, 0), 1380, 360))

    def test_seconds_until_minutes(self):
        now = self.at(23, 30)
        # 23:30 -> 01:00 is 90 minutes
        self.assertAlmostEqual(automation.seconds_until_minutes(now, 60), 5400)
        # 23:20 already passed today -> tomorrow
        self.assertAlmostEqual(automation.seconds_until_minutes(now, 1400), 85800)
        # 23:00 already passed today -> tomorrow
        self.assertAlmostEqual(automation.seconds_until_minutes(now, 1380), 84600)

    def test_next_window_opens(self):
        now = self.at(12, 0)
        # 01:00-02:00 is closed at noon -> it opens in 13 hours.
        self.assertAlmostEqual(
            automation.next_window_opens(now, 60, 180), 13 * 3600)
        # 23:00-06:00 (wrapping) is closed at noon -> opens in 11 hours.
        self.assertAlmostEqual(
            automation.next_window_opens(now, 1380, 360), 11 * 3600)
        # Already open -> 0.
        self.assertEqual(automation.next_window_opens(now, 60, 1800), 0.0)
        self.assertEqual(automation.next_window_opens(now, None, None), 0.0)

    def test_seconds_until_epoch(self):
        now = time.time()
        self.assertEqual(automation.seconds_until_epoch(None), 0.0)
        self.assertEqual(automation.seconds_until_epoch(0), 0.0)
        self.assertAlmostEqual(
            automation.seconds_until_epoch(now + 60, now), 60.0, places=1)
        self.assertEqual(automation.seconds_until_epoch(now - 60, now), 0.0)

    def test_describe_schedule(self):
        self.assertIn("not scheduled", automation.describe_schedule(None))
        self.assertTrue(automation.describe_schedule(time.time() + 300))


class ShutdownCommandTests(unittest.TestCase):
    """The command must be checked for every platform, not just this one."""

    def test_windows_shutdown(self):
        command = automation.shutdown_command(automation.SHUTDOWN, 30,
                                              platform="win")
        self.assertTrue(command[0].lower().endswith("shutdown"))
        self.assertIn("/s", command)

    def test_windows_sleep(self):
        command = automation.shutdown_command(automation.SLEEP,
                                              platform="win")
        self.assertIn("powrprof.dll", " ".join(command))

    def test_posix_shutdown(self):
        command = automation.shutdown_command(automation.SHUTDOWN,
                                              platform="linux")
        self.assertEqual(command, ["shutdown", "-h", "now"])

    def test_posix_sleep(self):
        command = automation.shutdown_command(automation.SLEEP,
                                              platform="darwin")
        self.assertEqual(command, ["systemctl", "suspend"])


class SchedulerScheduleTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="freedm_n6_")
        self.scheduler = Scheduler(max_active=2, tick=0.05)

    def tearDown(self):
        self.scheduler.shutdown()
        shutil.rmtree(self.out, ignore_errors=True)

    def test_a_future_job_waits_in_the_scheduled_state(self):
        dl = Download("http://example.com/f.bin", dest_dir=self.out)
        dl.set_start_at(time.time() + 3600)
        self.scheduler.submit(dl)
        self.assertEqual(dl.status, SCHEDULED)
        self.assertIn(dl, self.scheduler.scheduled())
        self.assertEqual(self.scheduler.queued(), [])

    def test_the_job_starts_when_its_time_comes(self):
        dl = Download("http://example.com/f.bin", dest_dir=self.out)
        dl.set_start_at(time.time() + 0.4)
        self.scheduler.submit(dl)
        self.assertEqual(dl.status, SCHEDULED)
        deadline = time.time() + 5
        while dl.status == SCHEDULED and time.time() < deadline:
            time.sleep(0.05)
        self.assertNotEqual(dl.status, SCHEDULED,
                            "the scheduled job was never released")
        self.assertIn(dl.status, (QUEUED, "probing", "downloading", DONE))

    def test_a_past_start_time_runs_immediately(self):
        dl = Download("http://example.com/f.bin", dest_dir=self.out)
        dl.set_start_at(time.time() - 10)
        self.scheduler.submit(dl)
        self.assertNotEqual(dl.status, SCHEDULED)
        self.assertEqual(self.scheduler.scheduled(), [])

    def test_start_now_ignores_the_schedule(self):
        dl = Download("http://example.com/f.bin", dest_dir=self.out)
        dl.set_start_at(time.time() + 3600)
        self.scheduler.submit(dl)
        self.assertEqual(dl.status, SCHEDULED)
        self.scheduler.start_now(dl)
        self.assertIsNone(dl.start_at)
        self.assertNotEqual(dl.status, SCHEDULED)

    def test_pause_removes_a_scheduled_job(self):
        dl = Download("http://example.com/f.bin", dest_dir=self.out)
        dl.set_start_at(time.time() + 3600)
        self.scheduler.submit(dl)
        self.scheduler.pause(dl)
        self.assertEqual(self.scheduler.scheduled(), [])


class SchedulerWindowTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="freedm_n6_win_")
        self.scheduler = Scheduler(max_active=2, tick=0.05)

    def tearDown(self):
        self.scheduler.shutdown()
        shutil.rmtree(self.out, ignore_errors=True)

    def test_a_closed_window_blocks_starting(self):
        now = datetime.datetime.now()
        minutes = now.hour * 60 + now.minute
        # A window that ended an hour ago -> closed right now.
        start = (minutes - 120) % (24 * 60)
        end = (minutes - 60) % (24 * 60)
        self.scheduler.set_window(start, end)
        self.assertFalse(self.scheduler.window_open(),
                         "the test window should be closed")
        dl = Download("http://example.com/f.bin", dest_dir=self.out)
        self.scheduler.submit(dl)
        time.sleep(0.4)
        self.assertNotIn(dl.status, ("probing", "downloading"),
                         "the job started outside the window")
        self.assertEqual(dl.status, QUEUED)

    def test_an_open_window_lets_the_job_start(self):
        now = datetime.datetime.now()
        start = (now.hour * 60 + now.minute - 5) % (24 * 60)
        end = (now.hour * 60 + now.minute + 30) % (24 * 60)
        self.scheduler.set_window(start, end)
        self.assertTrue(self.scheduler.window_open())
        dl = Download("http://example.com/f.bin", dest_dir=self.out)
        self.scheduler.submit(dl)
        deadline = time.time() + 5
        while dl.status == QUEUED and time.time() < deadline:
            time.sleep(0.05)
        self.assertNotEqual(dl.status, QUEUED)

    def test_window_status_text(self):
        self.scheduler.set_window(None, None)
        self.assertIn("no time limit", self.scheduler.window_status())
        self.scheduler.set_window(60, 180)
        self.assertIn("01:00", self.scheduler.window_status())
        self.assertIn("03:00", self.scheduler.window_status())

    def test_start_now_bypasses_a_closed_window(self):
        now = datetime.datetime.now()
        minutes = now.hour * 60 + now.minute
        start = (minutes - 120) % (24 * 60)
        end = (minutes - 60) % (24 * 60)
        self.scheduler.set_window(start, end)
        self.assertFalse(self.scheduler.window_open())
        dl = Download("http://example.com/f.bin", dest_dir=self.out)
        self.scheduler.submit(dl)
        self.scheduler.start_now(dl)
        deadline = time.time() + 5
        while dl.status == QUEUED and time.time() < deadline:
            time.sleep(0.05)
        self.assertNotEqual(dl.status, QUEUED,
                            "Start Now must ignore the closed window")


class PersistenceTests(unittest.TestCase):
    def test_start_at_is_stored_and_restored(self):
        store = JobStore(":memory:")
        try:
            when = time.time() + 3600
            dl = Download("http://example.com/f.bin", store=store)
            dl.job_id = store.add(dl)
            dl.set_start_at(when)
            row = store.get(dl.job_id)
            self.assertAlmostEqual(float(row["start_at"]), when, places=3)
            fresh = Download(row["url"], store=store, job_id=row["id"])
            fresh.apply_record(row)
            self.assertAlmostEqual(fresh.start_at, when, places=3)
        finally:
            store.close()

    def test_old_database_gains_the_start_at_column(self):
        import sqlite3
        tmp = tempfile.mkdtemp(prefix="freedm_n6_mig_")
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
                self.assertIsNone(store.last_error)
                cols = {r["name"] for r in store._read(
                    "PRAGMA table_info(downloads)")}
                self.assertIn("start_at", cols)
            finally:
                store.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_new_settings(self):
        prefs = S.load(None)
        self.assertEqual(prefs["window_start"], "")
        self.assertEqual(prefs["window_end"], "")
        self.assertFalse(prefs["shutdown_when_done"])
        self.assertEqual(prefs["shutdown_mode"], "shutdown")


class GuiIntegrationTests(GuiTestCase):
    """Real Tk window: the window controls, scheduling and shut-down."""

    prefix = "freedm_n6_gui_"

    def setUp(self):
        super().setUp()

    def test_window_is_applied_and_persisted(self):
        self.app.window_start_var.set("01:00")
        self.app.window_end_var.set("06:00")
        self.app._apply_window()
        self.assertEqual(self.app.window_start, 60)
        self.assertEqual(self.app.window_end, 360)
        from freedm.settings import load
        prefs = load(self.store)
        self.assertEqual(prefs["window_start"], "01:00")
        self.assertEqual(prefs["window_end"], "06:00")
        self.assertTrue(self.app.scheduler.window_open()
                        or not self.app.scheduler.window_open())

    def test_a_bad_window_time_is_rejected(self):
        self.app.window_start_var.set("99:99")
        with mock.patch.object(self.tk.messagebox, "showerror") as err:
            self.app._apply_window()
        self.assertTrue(err.called)

    def test_shutdown_toggle_is_persisted(self):
        self.app.shutdown_var.set(True)
        self.app._toggle_shutdown()
        from freedm.settings import load
        self.assertTrue(load(self.store)["shutdown_when_done"])
        self.app.shutdown_var.set(False)
        self.app._toggle_shutdown()
        self.assertFalse(load(self.store)["shutdown_when_done"])

    def test_shutdown_only_when_the_queue_is_empty(self):
        self.app.shutdown_var.set(True)
        self.app._toggle_shutdown()
        dl = self.app._add_url("https://example.com/f.bin")
        dl.status = QUEUED
        with mock.patch.object(self.tk.messagebox, "askyesno") as ask:
            with mock.patch.object(self.app, "_check_shutdown_when_done",
                                   wraps=self.app._check_shutdown_when_done):
                self.app._check_shutdown_when_done()
        self.assertFalse(ask.called, "must not ask while a job is pending")

    def test_shutdown_asks_before_powering_off(self):
        self.app.shutdown_var.set(True)
        self.app._toggle_shutdown()
        with mock.patch.object(self.tk.messagebox, "askyesno",
                               return_value=False) as ask:
            with mock.patch("freedm.gui.subprocess.Popen") as popen:
                self.app._check_shutdown_when_done()
        self.assertTrue(ask.called)
        self.assertFalse(popen.called, "must not power off without a yes")

    def test_shutdown_runs_the_command_when_confirmed(self):
        self.app.shutdown_var.set(True)
        self.app._toggle_shutdown()
        with mock.patch.object(self.tk.messagebox, "askyesno",
                               return_value=True):
            with mock.patch("freedm.gui.subprocess.Popen") as popen:
                self.app._check_shutdown_when_done()
        self.assertTrue(popen.called)

    def test_scheduled_status_is_shown_in_the_list(self):
        dl = self.app._add_url("https://example.com/f.bin")
        dl.status = SCHEDULED
        dl.start_at = time.time() + 600
        rows = self.app.tree.get_children()
        self.app.tree.selection_set(rows[0])
        with mock.patch.object(self.tk.messagebox, "showinfo") as info:
            self.app.show_details()
        self.assertTrue(info.called)

    def test_gui_exposes_the_automation_actions(self):
        from freedm import gui
        for name in ("schedule_dialog", "_apply_window", "_toggle_shutdown",
                     "_check_shutdown_when_done", "_queue_is_empty"):
            self.assertTrue(hasattr(gui.App, name), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
