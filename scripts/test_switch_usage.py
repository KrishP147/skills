#!/usr/bin/env python3
"""Stdlib unittest coverage for the switch statusline, usage guard, prompt
hook, settings.json install and per-account theme. Run with:

    python -m unittest discover -s scripts -p "test_*.py"

Temp HOME, registry and settings only; a generated script stands in for
claude and for the user's own statusline. The real claude is never run.
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_switch import FAKE, SCRIPT, SID, Base, cs  # noqa: E402

STATUS = SCRIPT.parent / "statusline.py"
_spec = importlib.util.spec_from_file_location("switch_statusline", STATUS)
sl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sl)  # imports claude_switch: the module test_switch loaded

NOW = 1_800_000_000
THEIRS = r'''
import json, sys
d = json.loads(sys.stdin.read())
print("theirs %s" % d.get("session_id"))
print("second line")
'''


def rate(five=None, week=None, five_left=2 * 3600 + 13 * 60 + 30, week_left=4 * 86400 + 6 * 3600 + 600):
    rl = {}
    if five is not None:
        rl["five_hour"] = {"used_percentage": five, "resets_at": NOW + five_left}
    if week is not None:
        rl["seven_day"] = {"used_percentage": week, "resets_at": NOW + week_left}
    return {"session_id": SID, "rate_limits": rl}


class StdinBytes:
    def __init__(self, data):
        self.buffer = io.BytesIO(data if isinstance(data, bytes) else data.encode("utf-8"))


class StatuslineTest(Base):
    def setUp(self):
        super().setUp()
        self.reg = self.register("main", "alt")

    def render(self, data, env=None):
        with mock.patch.dict(os.environ, env or {}):
            return sl.render(data, cs.load(), json.dumps(data).encode(), NOW)

    def test_with_data_and_cache(self):
        out = self.render(rate(42.4, 18), {"CLAUDE_SWITCH_ACCOUNT": "alt"})
        colour = cs.ANSI[cs.find(self.reg, "alt")["colour"]]
        self.assertEqual(out, "\x1b[1;%dmalt\x1b[0m  session 42%% · 2h13m left  week 18%% · 4d6h left"
                         % colour)
        cache = json.loads(cs.usage_path("alt").read_text())
        self.assertEqual(cache["five_hour"], {"pct": 42.4, "resets_at": NOW + 8010})
        self.assertEqual(cache["seven_day"]["pct"], 18.0)
        self.assertEqual(cache["seen"], NOW)
        self.assertFalse(cs.usage_path("main").exists())

    def test_without_data_keeps_cache(self):
        self.render(rate(50), {"CLAUDE_SWITCH_ACCOUNT": "alt"})
        before = cs.usage_path("alt").read_text()
        out = self.render({"session_id": SID}, {"CLAUDE_SWITCH_ACCOUNT": "alt"})
        self.assertTrue(out.endswith("alt\x1b[0m  session -  week -"), out)
        self.assertEqual(cs.usage_path("alt").read_text(), before)
        out = self.render(rate(7), {"CLAUDE_SWITCH_ACCOUNT": "alt"})  # one window only
        self.assertIn("session 7% · 2h13m left  week -", out)

    def test_account_by_dir(self):
        alt_dir = cs.find(self.reg, "alt")["dir"]
        self.assertIn("alt\x1b[0m", self.render({}, {"CLAUDE_CONFIG_DIR": alt_dir}))
        self.assertIn("main\x1b[0m", self.render({}))  # unset: ~/.claude
        # a stale name (renamed mid-session) falls back to the dir
        self.assertIn("alt\x1b[0m", self.render({}, {"CLAUDE_SWITCH_ACCOUNT": "old", "CLAUDE_CONFIG_DIR": alt_dir}))

    def test_time_left(self):
        cases = {0: "<1m", 59: "<1m", 60: "1m", 3599: "59m", 3600: "1h00m", 2 * 3600 + 5 * 60: "2h05m",
                 86400: "1d0h", 4 * 86400 + 6 * 3600 + 3599: "4d6h"}
        for secs, want in cases.items():
            self.assertEqual(sl.time_left(secs), want, secs)
        self.assertEqual(sl.window("week", {"used_percentage": 5, "resets_at": NOW - 1}, NOW), "week 5%")
        self.assertEqual(sl.window("week", {"used_percentage": "5"}, NOW), "week -")

    def run_script(self, stdin, env=None):
        e = dict(os.environ, CLAUDE_SWITCH_ACCOUNT="main", **(env or {}))
        return subprocess.run([sys.executable, str(STATUS)], input=stdin, env=e, capture_output=True, timeout=60)

    def test_wraps_original_same_stdin(self):
        theirs = self.tmp / "their statusline.py"
        theirs.write_text(THEIRS)
        reg = cs.load()
        reg["settings"] = {"installed": True, "statusline_original": {
            "type": "command", "command": cs.command_line(sys.executable, theirs)}}
        cs.save(reg)
        r = self.run_script(json.dumps(rate(10, 20)).encode())
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.decode("utf-8").splitlines()
        self.assertEqual(len(lines), 2, lines)
        self.assertIn("session 10%", lines[0])
        self.assertTrue(lines[0].endswith("left  theirs %s" % SID), lines[0])
        self.assertEqual(lines[1], "second line")

    def test_own_command_never_run_as_original(self):
        reg = cs.load()
        reg["settings"] = {"statusline_original": {"type": "command", "command": cs.statusline_command()}}
        cs.save(reg)
        self.assertEqual(sl.run_original(reg["settings"]["statusline_original"], b"{}"), "")

    def test_bad_stdin_never_crashes(self):
        for stdin in (b"not json", b"", b"[1,2]", b'{"rate_limits": 5}', b'{"rate_limits": {"five_hour": 3}}',
                      b"\xff\xfe"):
            r = self.run_script(stdin)
            self.assertEqual(r.returncode, 0, (stdin, r.stderr))
            self.assertIn(b"session -  week -", r.stdout, stdin)
        cs.registry_path().write_text("{broken")
        r = self.run_script(b"{}")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, b"session -  week -"))


class GuardTest(Base):
    def usage(self, name, five=None, resets=None, seen=NOW, week=None):
        data = {"seen": seen}
        if five is not None:
            data["five_hour"] = {"pct": five, "resets_at": resets if resets is not None else NOW + 3600}
        if week is not None:
            data["seven_day"] = {"pct": week, "resets_at": NOW + 86400}
        cs.atomic_write(cs.usage_path(name), json.dumps(data))

    def guard(self, account="main"):
        with mock.patch.dict(os.environ, {"CLAUDE_SWITCH_ACCOUNT": account}):
            return cs.guard(cs.load(), NOW)

    def test_needs_two_accounts(self):
        self.register("main")
        self.usage("main", 99)
        self.assertIsNone(self.guard())

    def test_thresholds_once_each(self):
        self.register("main", "alt")
        self.usage("main", 89.9)
        self.assertIsNone(self.guard())
        self.usage("main", 91.2)
        self.assertEqual(self.guard(), "main at 91%: run /switch alt")
        self.assertIsNone(self.guard())
        self.usage("main", 95)
        self.assertIsNone(self.guard())
        self.usage("main", 97.5)
        self.assertEqual(self.guard(), "main at 97%: run /switch alt")
        self.usage("main", 100)
        self.assertIsNone(self.guard())
        self.usage("main", 92, resets=NOW + 7200)  # next window: warns again
        self.assertEqual(self.guard(), "main at 92%: run /switch alt")

    def test_jump_straight_to_97_warns_once(self):
        self.register("main", "alt")
        self.usage("main", week=98)
        self.assertEqual(self.guard(), "main at 98%: run /switch alt")
        self.assertIsNone(self.guard())

    def test_most_headroom_and_stale(self):
        self.register("main", "alt", "work", "job")
        self.usage("main", 95)
        self.usage("alt", 40)
        self.usage("work", 99, resets=NOW - 10)  # past reset: counts as 0
        self.usage("job", 30)
        self.assertEqual(self.guard(), "main at 95%: run /switch work")
        cs.usage_path("work").unlink()  # no cache at all: 0 too, first in registration order wins ties
        cs.usage_path("main", ".warned").unlink()
        self.assertEqual(self.guard(), "main at 95%: run /switch work")

    def test_current_past_reset_or_stale_seen(self):
        self.register("main", "alt")
        self.usage("main", 99, resets=NOW - 1)
        self.assertIsNone(self.guard())
        data = {"seen": NOW - 6 * 3600, "five_hour": {"pct": 99, "resets_at": None}}
        cs.atomic_write(cs.usage_path("main"), json.dumps(data))
        self.assertIsNone(self.guard())


class HookTest(Base):
    def setUp(self):
        super().setUp()
        self.register("main", "alt", "work")
        self.env = {"CLAUDE_SWITCH_LAUNCHER": "4242", "CLAUDE_SWITCH_ACCOUNT": "main"}

    def hook(self, prompt, env=None, raw=None):
        data = raw if raw is not None else json.dumps({"session_id": SID, "prompt": prompt,
                                                       "hook_event_name": "UserPromptSubmit"})
        out = io.StringIO()
        with mock.patch.dict(os.environ, env or {}), mock.patch.object(sys, "stdin", StdinBytes(data)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = cs.main(["hook", cs.MARK])
        self.assertEqual(rc, 0)
        return json.loads(out.getvalue()) if out.getvalue().strip() else None

    def test_switch_name_writes_request_and_blocks(self):
        out = self.hook("/switch alt", self.env)
        self.assertEqual(out["decision"], "block")
        self.assertIn("switching to 'alt'", out["reason"])
        self.assertTrue(out["hookSpecificOutput"]["suppressOriginalPrompt"])
        self.assertEqual(json.loads((self.sw / "requests" / "4242.json").read_text()),
                         {"target": "alt", "session": SID})

    def test_bare_and_namespaced(self):
        out = self.hook("  /switch  ", dict(self.env, CLAUDE_SWITCH_PREVIOUS="work"))
        self.assertIn("switching to 'work'", out["reason"])
        out = self.hook("/skills:switch alt", self.env)
        self.assertEqual(out["decision"], "block")
        self.assertEqual(json.loads((self.sw / "requests" / "4242.json").read_text())["target"], "alt")

    def test_unknown_blocks_without_request(self):
        out = self.hook("/switch nope", self.env)
        self.assertEqual(out["decision"], "block")
        self.assertIn("unknown account 'nope'", out["reason"])
        self.assertEqual(self.requests(), [])

    def test_passes_through(self):
        for prompt in ("/switch add work2", "/switch remove alt", "/switch list", "/switch a b",
                       "/switcher alt", "please /switch alt", "hello"):
            self.assertIsNone(self.hook(prompt, self.env), prompt)
        self.assertIsNone(self.hook("/switch alt"))  # not under a launcher: the skill shows setup steps
        self.assertIsNone(self.hook(None, self.env, raw=b"not json"))
        self.assertIsNone(self.hook(None, self.env, raw=b"[]"))
        self.assertEqual(self.requests(), [])

    def test_guard_message_on_prompt(self):
        cs.atomic_write(cs.usage_path("main"), json.dumps(
            {"seen": time.time(), "five_hour": {"pct": 93, "resets_at": time.time() + 3600}}))
        self.assertEqual(self.hook("hello", self.env), {"systemMessage": "main at 93%: run /switch alt"})
        self.assertIsNone(self.hook("hello", self.env))


class SettingsTest(Base):
    def setUp(self):
        super().setUp()
        self.settings = self.home / ".claude" / "settings.json"
        self.bashrc = self.tmp / "profiles" / ".bashrc"

    def setup(self, *extra):
        return self.main("setup", "--profile=bash=%s" % self.bashrc, "--yes", *extra)

    def read(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def our_hooks(self, s):
        return [h for g in s.get("hooks", {}).get("UserPromptSubmit", []) for h in g["hooks"] if cs.is_our_hook(h)]

    def test_none_before(self):
        rc, out = self.setup()
        self.assertEqual(rc, 0, out)
        s = self.read()
        self.assertEqual(s["statusLine"]["refreshInterval"], 60)
        self.assertTrue(cs.is_our_statusline(s["statusLine"]))
        self.assertIn("statusline.py", s["statusLine"]["command"])
        self.assertTrue((self.sw / "statusline.py").is_file())
        self.assertEqual(len(self.our_hooks(s)), 1)
        self.assertEqual(self.our_hooks(s)[0]["timeout"], 10)
        self.assertIsNone(cs.load()["settings"]["statusline_original"])
        if os.name == "nt":
            self.assertNotIn("\\", s["statusLine"]["command"])
        rc, out = self.setup()
        self.assertIn("up to date", out)
        rc, out = self.setup("--uninstall")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.read(), {})
        self.assertNotIn("settings", cs.load())
        rc, out = self.setup("--uninstall")
        self.assertIn("no statusline or hook of ours", out)

    def test_one_before_restored(self):
        theirs = {"type": "command", "command": "~/.claude/mine.sh", "padding": 1}
        user_hook = {"hooks": [{"type": "command", "command": "user-prompt.sh"}]}
        before = {"theme": "dark", "statusLine": theirs,
                  "hooks": {"UserPromptSubmit": [user_hook], "Stop": [{"hooks": [{"type": "command", "command": "s"}]}]}}
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps(before))
        rc, out = self.setup()
        self.assertEqual(rc, 0, out)
        s = self.read()
        self.assertTrue(cs.is_our_statusline(s["statusLine"]))
        self.assertEqual(s["statusLine"]["padding"], 1)
        self.assertEqual(s["hooks"]["UserPromptSubmit"][0], user_hook)
        self.assertEqual(len(self.our_hooks(s)), 1)
        self.assertEqual(s["hooks"]["Stop"], before["hooks"]["Stop"])
        self.assertEqual(cs.load()["settings"]["statusline_original"], theirs)
        backups = list((self.sw / "backups").iterdir())
        self.assertEqual([json.loads(b.read_text()) for b in backups], [before])
        self.setup()  # ours already there: original kept, nothing duplicated
        self.assertEqual(self.read(), s)
        self.assertEqual(cs.load()["settings"]["statusline_original"], theirs)
        rc, out = self.setup("--uninstall")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.read(), before)

    def test_ours_there_without_record(self):
        self.setup()
        reg = cs.load()
        del reg["settings"]  # registry lost: our own command must not become "the original"
        cs.save(reg)
        self.setup()
        self.assertIsNone(cs.load()["settings"]["statusline_original"])
        self.setup("--uninstall")
        self.assertNotIn("statusLine", self.read())

    def test_hook_refreshed_in_place(self):
        self.setup()
        s = self.read()
        s["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] = "/old/python /old/claude_switch.py hook " + cs.MARK
        s["hooks"]["UserPromptSubmit"].append({"hooks": [{"type": "command", "command": "after.sh"}]})
        self.settings.write_text(json.dumps(s))
        self.setup()
        groups = self.read()["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["hooks"][0]["command"], cs.hook_command())
        self.assertEqual(groups[1]["hooks"][0]["command"], "after.sh")
        self.setup("--uninstall")
        self.assertEqual(self.read()["hooks"], {"UserPromptSubmit": [{"hooks": [{"type": "command",
                                                                                  "command": "after.sh"}]}]})

    def test_hardlinked_settings_stay_shared(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text('{"a": 1}')
        other = self.tmp / "cfg-alt" / "settings.json"
        other.parent.mkdir()
        os.link(self.settings, other)
        self.setup()
        self.assertTrue(os.path.samefile(self.settings, other))
        self.assertIn("statusLine", json.loads(other.read_text()))

    def test_bad_json_left_alone(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text("{oops")
        rc, out = self.setup()
        self.assertEqual(rc, 0, out)
        self.assertIn("not a JSON object", out)
        self.assertEqual(self.settings.read_text(), "{oops")
        self.assertIn("claude()", self.bashrc.read_text())

    def test_declined_writes_nothing(self):
        with mock.patch("builtins.input", side_effect=EOFError):
            rc, out = self.main("setup", "--profile=bash=%s" % self.bashrc)
        self.assertEqual(rc, 1)
        self.assertIn('+  "statusLine": {', out)
        self.assertFalse(self.settings.exists())


class ThemeTest(Base):
    def test_overlay_and_merge(self):
        acct = {"name": "a", "theme": "dark"}
        self.assertEqual(cs.with_theme({"name": "a", "theme": None}, ["-p", "x"]), ["-p", "x"])
        self.assertEqual(cs.with_theme(acct, ["--resume", SID]), ["--settings", '{"theme":"dark"}', "--resume", SID])
        out = cs.with_theme(acct, ["--settings", '{"model": "m"}', "--verbose"])
        self.assertEqual((out[0], json.loads(out[1]), out[2:]), ("--settings", {"theme": "dark", "model": "m"},
                                                                 ["--verbose"]))
        f = self.tmp / "s.json"
        f.write_text('{"theme": "light", "a": 1}')
        out = cs.with_theme(acct, ["--settings=%s" % f])
        self.assertEqual(json.loads(out[1]), {"theme": "light", "a": 1})  # theirs wins
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cs.with_theme(acct, ["--settings", str(self.tmp / "missing.json")]),
                             ["--settings", str(self.tmp / "missing.json")])
        self.assertIn("theme not applied", err.getvalue())

    def test_theme_command(self):
        self.register("main", "alt")
        rc, out = self.main("theme", "alt", "light")
        self.assertEqual(cs.find(cs.load(), "alt")["theme"], "light")
        rc, out = self.main("theme", "alt")
        self.assertIn("alt: light", out)
        self.main("theme", "alt", "-")
        self.assertIsNone(cs.find(cs.load(), "alt")["theme"])
        with self.assertRaises(SystemExit):
            self.main("theme", "alt", "Bad Theme")

    def test_title(self):
        tty = io.StringIO()
        tty.isatty = lambda: True
        with mock.patch.object(sys, "stdout", tty):
            cs.set_title({"name": "work"})
        self.assertEqual(tty.getvalue(), "\x1b]0;claude: work\x07")


class LauncherThemeTest(Base):
    def setUp(self):
        super().setUp()
        self.register("main", "alt")
        self.fake = self.tmp / "fake.py"
        self.fake.write_text(FAKE)

    def launch(self, *argv, **fake_env):
        env = dict(os.environ, CLAUDE_SWITCH_CLAUDE=json.dumps([sys.executable, str(self.fake)]),
                   FAKE_LOG=str(self.tmp / "log.jsonl"), FAKE_SCRIPT=str(SCRIPT), **fake_env)
        p = subprocess.run([sys.executable, str(SCRIPT), "run"] + list(argv), env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
        return p.returncode, p.stderr, [json.loads(x) for x in (self.tmp / "log.jsonl").read_text().splitlines()]

    def test_theme_argv_in_fake_claude(self):
        self.main("theme", "main", "dark")
        rc, err, log = self.launch("main", "--settings", '{"model": "m"}', FAKE_SWITCH_TO="alt", FAKE_SESSION=SID)
        self.assertEqual(rc, 0, err)
        self.assertEqual(log[0]["args"][0], "--settings")
        self.assertEqual(json.loads(log[0]["args"][1]), {"theme": "dark", "model": "m"})
        self.assertEqual(log[1]["args"], ["--resume", SID])  # alt has no theme

    def test_rename_current_mid_session(self):
        rc, err, log = self.launch("main", FAKE_RENAME="main boss", FAKE_SWITCH_TO="alt", FAKE_SESSION=SID)
        self.assertEqual(rc, 0, err)
        self.assertEqual(log[1]["previous"], "boss")
        self.assertIn("boss -> alt", err)


if __name__ == "__main__":
    unittest.main()
