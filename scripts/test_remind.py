#!/usr/bin/env python3
"""Stdlib unittest coverage for remind/scripts/remind.py. Run with:

    python -m unittest discover -s scripts -p "test_*.py"

Temp HOME and CLAUDE_SWITCH_HOME, a fake registry and usage cache, an
injected clock. Every scheduler call is mocked: nothing is ever scheduled.
"""
import base64
import contextlib
import datetime
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "remind" / "scripts" / "remind.py"
SWITCH = ROOT / "switch" / "scripts" / "claude_switch.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rm = load(SCRIPT, "remind_under_test")
NOW = datetime.datetime(2026, 10, 17, 12, 0).timestamp()  # local noon: clock-time cases are exact


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="remind-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.sw = self.tmp / "sw"
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("CLAUDE_SWITCH_", "CLAUDE_REMIND_", "CLAUDE_CONFIG_DIR"))}
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), CLAUDE_SWITCH_HOME=str(self.sw))
        for p in (mock.patch.dict(os.environ, env, clear=True),
                  mock.patch.object(rm, "now", lambda: self.t),
                  mock.patch.object(rm, "_run", self.fake_run)):
            p.start()
            self.addCleanup(p.stop)
        rm._SWITCH.clear()
        self.addCleanup(rm._SWITCH.clear)
        self.t = NOW
        self.calls = []
        self.run_result = (0, "", "")

    def fake_run(self, argv, **kw):
        xml = None
        if "/XML" in argv:
            xml = Path(argv[argv.index("/XML") + 1]).read_text(encoding="utf-16")
        self.calls.append((list(argv), kw.get("input"), xml))
        rc, out, err = self.run_result
        return subprocess.CompletedProcess(argv, rc, out, err)

    def register(self, *names, current=None):
        reg = {"accounts": [{"name": n, "dir": str(self.tmp / ("cfg-" + n))} for n in names]}
        self.sw.mkdir(parents=True, exist_ok=True)
        (self.sw / "accounts.json").write_text(json.dumps(reg))
        if current:
            os.environ["CLAUDE_SWITCH_ACCOUNT"] = current

    def usage(self, name, five=None, five_resets=None, week=None, week_resets=None, seen=None):
        data = {"seen": NOW if seen is None else seen}
        if five is not None:
            data["five_hour"] = {"pct": five, "resets_at": NOW + 3600 if five_resets is None else five_resets}
        if week is not None:
            data["seven_day"] = {"pct": week, "resets_at": NOW + 86400 if week_resets is None else week_resets}
        p = self.sw / "usage" / ("%s.json" % name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data))

    def main(self, *argv, plat="win32"):
        out, err = io.StringIO(), io.StringIO()
        real = rm.schedule
        with mock.patch.object(rm, "schedule", lambda r: real(r, plat)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = rm.main(list(argv))
            except SystemExit as e:
                rc = e.code
                if isinstance(rc, str):  # SystemExit("remind: ...") prints to stderr, exits 1
                    err.write(rc + "\n")
                    rc = 1
        return rc, out.getvalue() + err.getvalue()

    def store(self):
        return json.loads(rm.store_path().read_text())

    def hook(self):
        out = io.StringIO()
        stdin = mock.Mock(buffer=io.BytesIO(b'{"prompt": "hi"}'))
        with mock.patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(rm.main(["hook"]), 0)
        return json.loads(out.getvalue())["systemMessage"] if out.getvalue().strip() else None


class ParseTest(Base):
    def at(self, s):
        return datetime.datetime.fromtimestamp(rm.parse_at(s, NOW)).strftime("%Y-%m-%d %H:%M")

    def test_in(self):
        self.assertEqual(rm.parse_in("2h", NOW), NOW + 7200)
        self.assertEqual(rm.parse_in("1h30m", NOW), NOW + 5400)
        self.assertEqual(rm.parse_in("90min", NOW), NOW + 5400)
        self.assertEqual(rm.parse_in("1d", NOW), NOW + 86400)
        for bad in ("", "0m", "2x", "h", "-1h"):
            with self.assertRaises(SystemExit):
                rm.parse_in(bad, NOW)

    def test_at(self):
        self.assertEqual(self.at("15:00"), "2026-10-17 15:00")
        self.assertEqual(self.at("3pm"), "2026-10-17 15:00")
        self.assertEqual(self.at("3:30 PM"), "2026-10-17 15:30")
        self.assertEqual(self.at("9am"), "2026-10-18 09:00")  # past today: tomorrow
        self.assertEqual(self.at("12am"), "2026-10-18 00:00")
        self.assertEqual(self.at("12pm"), "2026-10-18 12:00")  # exactly now is past
        self.assertEqual(self.at("tomorrow 9am"), "2026-10-18 09:00")
        self.assertEqual(self.at("2026-10-20 08:05"), "2026-10-20 08:05")
        self.assertEqual(self.at("2026-10-20T08:05"), "2026-10-20 08:05")
        for bad in ("25:00", "13pm", "0am", "noonish", "2026-13-01 10:00", "2026-10-16 10:00"):
            with self.assertRaises(SystemExit, msg=bad):
                rm.parse_at(bad, NOW)


class StoreTest(Base):
    def test_add_list_cancel(self):
        rc, out = self.main("add", "in", "--", "2h", "check the deploy")
        self.assertEqual(rc, 0, out)
        self.assertIn("reminder 1 at 14:00: check the deploy", out)
        rc, out = self.main("add", "at", "--", "tomorrow 9am", "it's -v time")
        self.assertIn("reminder 2 at tomorrow 09:00: it's -v time", out)
        rc, out = self.main("list")
        self.assertIn("1  14:00", out)
        self.assertIn("2  tomorrow 09:00", out)
        self.assertEqual([r["id"] for r in self.store()["reminders"]], [1, 2])
        self.calls.clear()
        rc, out = self.main("cancel", "1")
        self.assertIn("cancelled 1: check the deploy", out)
        self.assertEqual(self.calls[0][0], ["schtasks", "/Delete", "/TN", "claude-remind-1", "/F"])
        self.assertEqual([r["id"] for r in self.store()["reminders"]], [2])
        rc, out = self.main("cancel", "1")
        self.assertNotEqual(rc, 0)
        self.assertIn("no reminder 1", out)
        self.main("cancel", "2")
        self.main("add", "in", "--", "1m", "x")
        self.assertEqual(self.store()["reminders"][0]["id"], 3)  # ids never reused
        self.assertEqual([p.name for p in rm.home().iterdir() if p.name.endswith(".tmp")], [])

    def test_text_needed(self):
        rc, out = self.main("add", "in", "--", "2h")
        self.assertIn("usage: add in DURATION TEXT", out)
        self.assertFalse(rm.store_path().exists())

    def test_corrupt_store(self):
        rm.store_path().parent.mkdir(parents=True)
        rm.store_path().write_text("{not json")
        self.assertIsNone(self.hook())  # hook: no crash, no write
        self.assertEqual(rm.store_path().read_text(), "{not json")
        self.assertIn("no reminders", self.main("list")[1])
        rc, out = self.main("add", "in", "--", "5m", "x")
        self.assertEqual(rc, 0)
        self.assertIn("unreadable", out)
        aside = [p for p in rm.home().iterdir() if p.name.startswith("reminders.corrupt-")]
        self.assertEqual(aside[0].read_text(), "{not json")
        self.assertEqual(len(self.store()["reminders"]), 1)

    def test_scheduling_failure_keeps_reminder(self):
        self.run_result = (1, "", "ERROR: Access is denied.")
        rc, out = self.main("add", "in", "--", "5m", "x")
        self.assertEqual(rc, 0)
        self.assertIn("no toast (schtasks: ERROR: Access is denied.); in-session only", out)
        self.assertNotIn("notify", self.store()["reminders"][0])
        self.calls.clear()
        self.main("cancel", "1")
        self.assertEqual(self.calls, [])  # nothing booked, nothing to delete

    def test_copies_itself_next_to_store(self):
        self.main("add", "in", "--", "5m", "x")
        self.assertEqual((self.home / ".claude-remind" / "remind.py").read_bytes(), SCRIPT.read_bytes())


class NoSwitchTest(Base):
    def test_store_in_home_and_account_kinds_refused(self):
        self.main("add", "in", "--", "1h", "stretch")
        self.assertTrue((self.home / ".claude-remind" / "reminders.json").is_file())
        self.assertFalse(self.sw.exists())
        rc, out = self.main("add", "reset", "--account", "work")
        self.assertNotEqual(rc, 0)
        self.assertIn("need the switch skill", out)
        out = self.main("add", "in", "--", "1h", "x")[1]
        self.assertIn("add this UserPromptSubmit hook command once (README): ", out)
        self.assertIn("/.claude-remind/remind.py hook", out)


class AccountTest(Base):
    def setUp(self):
        super().setUp()
        self.register("work", "personal", current="work")

    def test_reset_uses_cache_and_current_account(self):
        self.usage("work", five=80, five_resets=NOW + 5400)
        rc, out = self.main("add", "reset")
        self.assertEqual(rc, 0, out)
        self.assertIn("reminder 1 at 13:30: work's session limit reset", out)
        r = self.store()["reminders"][0]
        self.assertEqual((r["kind"], r["account"], r["at"]), ("reset", "work", NOW + 5400))
        self.assertTrue((self.sw / "reminders.json").is_file())  # next to the registry

    def test_weekly_named_account_with_text(self):
        self.usage("personal", week=40, week_resets=NOW + 3 * 86400)
        rc, out = self.main("add", "weekly", "--account", "personal", "--", "plan the week")
        self.assertIn("personal's weekly limit reset: plan the week", out)

    def test_never_guesses(self):
        rc, out = self.main("add", "reset", "--account", "nobody")
        self.assertIn("no account 'nobody' (have: work, personal)", out)
        rc, out = self.main("add", "reset")
        self.assertIn("no usage cached for 'work'", out)
        self.usage("work", week=10)
        self.assertIn("no session reset time cached", self.main("add", "reset")[1])
        self.usage("work", five=50, five_resets=NOW - 60)
        self.assertIn("already reset at 11:59", self.main("add", "reset")[1])
        os.environ.pop("CLAUDE_SWITCH_ACCOUNT")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp / "elsewhere")
        self.assertIn("not sure which account", self.main("add", "reset")[1])
        self.assertFalse((self.sw / "reminders.json").exists())

    def test_under(self):
        self.usage("personal", five=70, week=30)
        rc, out = self.main("add", "under", "--account", "personal", "--", "50%")
        self.assertEqual(rc, 0, out)
        self.assertIn("personal is under 50%", out)
        self.assertIn("in-session only (no fixed time)", out)
        self.assertEqual(self.calls, [])  # no OS notification for it
        self.assertIn("already under 80% (70%)", self.main("add", "under", "--account", "personal", "80")[1])
        self.assertIn("PCT 1-100", self.main("add", "under", "--account", "personal", "150")[1])
        self.assertIn("PCT 1-100", self.main("add", "under", "--account", "personal")[1])

    def test_due_per_kind(self):
        self.usage("work", five=95, five_resets=NOW + 600, week=60, week_resets=NOW + 86400)
        self.main("add", "reset")
        self.main("add", "weekly")
        self.main("add", "under", "--", "50")
        self.main("add", "in", "--", "5m", "tea")
        self.assertIsNone(self.hook())
        self.t = NOW + 300
        self.assertEqual(self.hook(), "Reminder 4: tea")
        self.t = NOW + 600  # session window resets: usage now counts the week only
        self.assertEqual(self.hook(), "Reminder 1: work's session limit reset")
        self.t = NOW + 86400
        self.assertEqual(self.hook(), "Reminder 2: work's weekly limit reset\nReminder 3: work is under 50%")
        self.assertIsNone(self.hook())
        self.assertIn("no reminders", self.main("list")[1])

    def test_under_stays_while_cache_missing(self):
        self.usage("work", five=95)
        self.main("add", "under", "--", "50")
        (self.sw / "usage" / "work.json").unlink()
        self.assertIsNone(self.hook())


class HookTest(Base):
    def test_once_then_done_and_late_note(self):
        self.main("add", "in", "--", "5m", "tea")
        self.t = NOW + 3600
        self.assertEqual(self.hook(), "Reminder 1 (due 12:05): tea")
        self.assertIsNone(self.hook())
        self.assertEqual(self.store()["reminders"][0]["done"], NOW + 3600)
        self.t = NOW + 3600 + rm.KEEP_DONE_SECS
        self.main("add", "in", "--", "5m", "x")
        self.assertEqual([r["id"] for r in self.store()["reminders"]], [2])  # old done one pruned

    def test_cancel_after_fired_leaves_task_alone(self):
        self.main("add", "in", "--", "5m", "tea")
        self.t = NOW + 600
        self.hook()
        self.calls.clear()
        self.assertIn("cancelled 1", self.main("cancel", "1")[1])
        self.assertEqual(self.calls, [])

    def test_stale_lock_broken(self):
        self.main("add", "in", "--", "5m", "tea")
        lock = rm.home() / "reminders.lock"
        lock.mkdir()
        os.utime(lock, (time.time() - 60, time.time() - 60))
        self.t = NOW + 360
        self.assertEqual(self.hook(), "Reminder 1: tea")
        self.assertFalse(lock.exists())


class SwitchHookTest(Base):
    """switch's own hook delivers reminders through remind.py's copy in its registry dir."""

    def switch_hook(self):
        cs = load(SWITCH, "switch_for_remind_test")
        out = io.StringIO()
        stdin = mock.Mock(buffer=io.BytesIO(b'{"prompt": "hi"}'))
        with mock.patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cs.main(["hook", "--claude-switch"]), 0)
        return json.loads(out.getvalue())["systemMessage"] if out.getvalue().strip() else None

    def test_merged_with_guard_once(self):
        self.register("work", "personal", current="work")
        shutil.copy(SWITCH, self.sw / "claude_switch.py")  # switch setup's stable copy
        self.usage("work", five=92, five_resets=time.time() + 3600)
        self.usage("personal", five=10, five_resets=time.time() + 3600)
        self.main("add", "in", "--", "5m", "tea")
        self.assertIn("in-session: next prompt after it's due", self.main("add", "in", "--", "5m", "x")[1])
        self.assertTrue((self.sw / "remind.py").is_file())
        data = self.store()
        data["reminders"][0]["at"] = time.time() - 1  # the copy runs on the real clock
        (self.sw / "reminders.json").write_text(json.dumps(data))
        self.assertEqual(self.switch_hook(), "work at 92%: run /switch personal\nReminder 1: tea")
        self.assertIsNone(self.switch_hook())

    def test_broken_copy_never_breaks_guard(self):
        self.register("work", "personal", current="work")
        self.usage("work", five=92, five_resets=time.time() + 3600)
        (self.sw / "remind.py").write_text("raise RuntimeError('boom')\n")
        self.assertEqual(self.switch_hook(), "work at 92%: run /switch personal")

    def test_no_copy_no_change(self):
        self.register("work")
        self.assertIsNone(self.switch_hook())


class SchedulerTest(Base):
    R = {"id": 7, "kind": "at", "at": NOW + 3600, "text": "it's 'quoted' & <tagged>"}

    def test_windows_task_xml(self):
        handle, note = rm.schedule(dict(self.R), "win32")
        self.assertEqual(handle, {"task": "claude-remind-7"})
        argv, _, xml = self.calls[0]
        self.assertEqual(argv[:5] + argv[6:], ["schtasks", "/Create", "/TN", "claude-remind-7", "/XML", "/F"])
        self.assertFalse(Path(argv[5]).exists())  # temp XML removed
        self.assertIn("<StartBoundary>2026-10-17T13:00:00</StartBoundary>", xml)
        self.assertIn("<EndBoundary>2026-10-18T13:00:00</EndBoundary>", xml)
        self.assertIn("<DeleteExpiredTaskAfter>PT0S</DeleteExpiredTaskAfter>", xml)
        self.assertIn("<LogonType>InteractiveToken</LogonType>", xml)
        self.assertIn("WindowsPowerShell\\v1.0\\powershell.exe</Command>", xml)
        enc = xml.split("-EncodedCommand ")[1].split("<")[0]
        ps = base64.b64decode(enc).decode("utf-16-le")
        self.assertIn("&lt;tagged&gt;", ps)  # toast XML escaped
        self.assertIn("it''s ''quoted''", ps)  # PowerShell single quotes doubled
        self.assertIn("& msg.exe '*' 'Claude reminder: it''s ''quoted'' & <tagged>'", ps)

    def test_windows_prefix_env(self):
        os.environ["CLAUDE_REMIND_TASK_PREFIX"] = "claude-remind-test-"
        self.assertEqual(rm.schedule(dict(self.R), "win32")[0], {"task": "claude-remind-test-7"})

    def test_at_darwin(self):
        self.run_result = (0, "", "job 12 at Sat Oct 17 13:00:00 2026\n")
        with mock.patch.object(rm.shutil, "which", lambda n: "/usr/bin/" + n):
            handle, note = rm.schedule(dict(self.R), "darwin")
        self.assertEqual(handle, {"at_job": "12"})
        argv, stdin, _ = self.calls[0]
        self.assertEqual(argv, ["at", "-t", "202610171300.00"])
        self.assertTrue(stdin.startswith("osascript -e "), stdin)
        self.assertIn("with title", stdin)
        self.calls.clear()
        self.assertIsNone(rm.unschedule(handle))
        self.assertEqual(self.calls[0][0], ["atrm", "12"])

    def test_at_linux(self):
        self.run_result = (0, "", "warning: commands will be executed using /bin/sh\njob 3 at ...\n")
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
        with mock.patch.object(rm.shutil, "which", lambda n: "/usr/bin/" + n):
            handle, note = rm.schedule(dict(self.R), "linux")
        self.assertEqual(handle, {"at_job": "3"})
        stdin = self.calls[0][1]
        self.assertIn("DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus notify-send 'Claude reminder' ", stdin)

    def test_unix_without_at_or_notifier(self):
        with mock.patch.object(rm.shutil, "which", lambda n: None):
            self.assertEqual(rm.schedule(dict(self.R), "linux"), (None, "no `at` command here: in-session only"))
        with mock.patch.object(rm.shutil, "which", lambda n: "/usr/bin/at" if n == "at" else None):
            self.assertEqual(rm.schedule(dict(self.R), "linux"), (None, "no notify-send here: in-session only"))
        self.assertEqual(self.calls, [])

    def test_add_on_mac_records_job(self):
        self.run_result = (0, "", "job 5 at ...\n")
        with mock.patch.object(rm.shutil, "which", lambda n: "/usr/bin/" + n):
            rc, out = self.main("add", "in", "--", "1h", "x", plat="darwin")
        self.assertIn("notification at 13:00 (at job 5)", out)
        self.assertEqual(self.store()["reminders"][0]["notify"], {"at_job": "5"})


if __name__ == "__main__":
    unittest.main()
