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
from test_switch import FAKE, SCRIPT, SID, Base, agent_file, cs  # noqa: E402

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
        r = self.run_script(b"\xef\xbb\xbf" + json.dumps(rate(10, 20)).encode())  # PowerShell 5.1 pipe
        self.assertIn("session 10%", r.stdout.decode("utf-8"))
        self.assertIn("theirs %s" % SID, r.stdout.decode("utf-8"))  # theirs gets it without the BOM

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
                         {"target": "alt", "session": SID, "transcript": ""})

    def test_bom_stdin(self):
        raw = b"\xef\xbb\xbf" + json.dumps({"session_id": SID, "prompt": "/switch alt"}).encode()
        self.assertEqual(self.hook(None, self.env, raw=raw)["decision"], "block")

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
        for prompt in ("/switch add work2", "/switch remove alt", "/switch list extra", "/switch theme alt dark",
                       "/switch setup", "/switch setup work", "/switcher alt", "please /switch alt", "hello"):
            self.assertIsNone(self.hook(prompt, self.env), prompt)
        self.assertIsNone(self.hook("/switch alt"))  # not under a launcher: the skill shows setup steps
        self.assertIsNone(self.hook(None, self.env, raw=b"not json"))
        self.assertIsNone(self.hook(None, self.env, raw=b"[]"))
        self.assertEqual(self.requests(), [])

    def test_list_answered_with_or_without_launcher(self):
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / ".credentials.json").write_text("{}")
        for env in (self.env, {}):
            out = self.hook("  /switch list ", env)
            self.assertEqual(out["decision"], "block")
            self.assertTrue(out["hookSpecificOutput"]["suppressOriginalPrompt"])
            lines = out["reason"].splitlines()
            self.assertEqual(len(lines), 3)
            self.assertIn("logged in", lines[0])
            self.assertTrue(lines[0].endswith("(current)"))  # main: CLAUDE_CONFIG_DIR unset = ~/.claude
            self.assertNotIn("\x1b", out["reason"])
        self.assertEqual(self.hook("/skills:switch list")["decision"], "block")
        self.assertEqual(self.requests(), [])

    def test_list_broken_registry_passes_through(self):
        cs.registry_path().write_text("{broken")
        self.assertIsNone(self.hook("/switch list", self.env))

    def test_guard_message_on_prompt(self):
        cs.atomic_write(cs.usage_path("main"), json.dumps(
            {"seen": time.time(), "five_hour": {"pct": 93, "resets_at": time.time() + 3600}}))
        self.assertEqual(self.hook("hello", self.env), {"systemMessage": "main at 93%: run /switch alt"})
        self.assertIsNone(self.hook("hello", self.env))


class HookNeverAsksTest(Base):
    """The hook switches on the first /switch: Remote Control, live subagents and a trailing yes
    only change the printed lines."""
    hook = HookTest.hook

    def setUp(self):
        super().setUp()
        self.register("main", "alt", "work")
        self.env = {"CLAUDE_SWITCH_LAUNCHER": "4242", "CLAUDE_SWITCH_ACCOUNT": "main"}

    def target(self):
        return json.loads((self.sw / "requests" / "4242.json").read_text())["target"]

    def test_remote_control_info_line(self):
        out = self.hook("/switch alt", dict(self.env, CLAUDE_CODE_BRIDGE_SESSION_ID="b1"))
        self.assertIn("Remote Control ends with this session; run /remote-control on alt if you want it",
                      out["reason"])
        self.assertIn("switching to 'alt'", out["reason"])
        self.assertEqual(self.target(), "alt")

    def test_trailing_yes(self):
        out = self.hook("/switch work yes", self.env)
        self.assertIn("switching to 'work'", out["reason"])
        self.assertEqual(self.target(), "work")
        out = self.hook("/switch yes", dict(self.env, CLAUDE_SWITCH_PREVIOUS="alt"))
        self.assertIn("switching to 'alt'", out["reason"])

    def test_live_agent_from_transcript_path(self):
        t = self.tmp / "proj" / (SID + ".jsonl")
        t.parent.mkdir()
        t.write_text("{}\n")
        agent_file(t.with_suffix("") / "subagents", "x1", False, 3600)
        raw = json.dumps({"session_id": SID, "prompt": "/switch alt", "transcript_path": str(t),
                          "cwd": str(self.tmp)})
        out = self.hook(None, self.env, raw=raw)
        self.assertIn("  1 subagent (x1): paused by the switch", out["reason"])
        self.assertIn("switching to 'alt'", out["reason"])
        req = json.loads((self.sw / "requests" / "4242.json").read_text())
        self.assertEqual(req["transcript"], str(t.absolute()))
        self.assertIn("- cwd: %s" % self.tmp, (self.sw / "requests" / "4242.note.md").read_text())

    def test_extra_words_blocked_with_usage(self):
        for prompt in ("/switch alt now", "/switch a b yes", "/switch rc-ok alt on", "/switch alt no"):
            out = self.hook(prompt, self.env)
            self.assertEqual((out["decision"], out["reason"]), ("block", "usage: /switch [name]"), prompt)
        self.assertEqual(self.requests(), [])
        self.assertIsNone(self.hook("/switch alt now"))  # not under a launcher: the skill handles it


class SettingsTest(Base):
    def setUp(self):
        super().setUp()
        self.settings = self.home / ".claude" / "settings.json"
        self.bashrc = self.tmp / "profiles" / ".bashrc"

    def setup(self, *extra):
        return self.main("setup", "--profile=bash=%s" % self.bashrc, "--yes", *extra)

    def read(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def original(self):
        """main's recorded statusLine; the registry holds one entry per file."""
        states = cs.load()["settings"]
        self.assertEqual(list(states), [os.path.realpath(str(self.settings))])
        return states[os.path.realpath(str(self.settings))]["statusline_original"]

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
        self.assertIsNone(self.original())
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
        self.assertEqual(self.original(), theirs)
        backups = list((self.sw / "backups").iterdir())
        self.assertEqual([json.loads(b.read_text()) for b in backups], [before])
        self.setup()  # ours already there: original kept, nothing duplicated
        self.assertEqual(self.read(), s)
        self.assertEqual(self.original(), theirs)
        rc, out = self.setup("--uninstall")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.read(), before)

    def test_ours_there_without_record(self):
        self.setup()
        reg = cs.load()
        del reg["settings"]  # registry lost: our own command must not become "the original"
        cs.save(reg)
        self.setup()
        self.assertIsNone(self.original())
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


class AccountSettingsTest(Base):
    """Every account's own settings.json gets the statusline and hook; a linked one is written once."""
    THEIRS = {"type": "command", "command": "mine.sh"}

    def setUp(self):
        super().setUp()
        self.bashrc = self.tmp / "profiles" / ".bashrc"
        self.main_s = self.home / ".claude" / "settings.json"
        self.alt_s = self.tmp / "cfg-alt" / "settings.json"
        self.main_s.parent.mkdir(parents=True)
        self.alt_s.parent.mkdir(parents=True)
        self.main_s.write_text('{"a": 1}')
        self.alt_s.write_text(json.dumps({"statusLine": self.THEIRS}))

    def setup(self, *extra):
        return self.main("setup", "--profile=bash=%s" % self.bashrc, "--yes", "--account",
                         "main=%s" % self.main_s.parent, "--account", "alt=%s" % self.alt_s.parent, *extra)

    def hooks(self, p):
        s = json.loads(Path(p).read_text())
        return [h for g in s.get("hooks", {}).get("UserPromptSubmit", []) for h in g["hooks"] if cs.is_our_hook(h)]

    def originals(self):
        return {k: v["statusline_original"] for k, v in cs.load().get("settings", {}).items()}

    def key(self, p):
        return os.path.realpath(str(p))

    def test_two_unlinked_accounts(self):
        gone = self.tmp / "cfg-gone"
        rc, out = self.setup("--account", "gone=%s" % gone)
        self.assertEqual(rc, 0, out)
        for p in (self.main_s, self.alt_s):
            self.assertEqual(len(self.hooks(p)), 1, p)
            self.assertTrue(cs.is_our_statusline(json.loads(p.read_text())["statusLine"]))
        self.assertFalse(gone.exists())  # a dir that doesn't exist is skipped
        self.assertEqual(self.originals(), {self.key(self.main_s): None, self.key(self.alt_s): self.THEIRS})
        reg = cs.load()
        for acct, want in (("main", None), ("alt", self.THEIRS)):
            with mock.patch.dict(os.environ, {"CLAUDE_SWITCH_ACCOUNT": acct}):
                self.assertEqual(cs.statusline_original(reg), want)
        self.assertEqual(self.setup()[1].count("up to date"), 1)
        rc, out = self.setup("--uninstall")
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads(self.main_s.read_text()), {"a": 1})
        self.assertEqual(json.loads(self.alt_s.read_text()), {"statusLine": self.THEIRS})
        self.assertNotIn("settings", cs.load())

    def test_bad_file_skipped_others_written(self):
        self.alt_s.write_text("{oops")
        rc, out = self.setup()
        self.assertEqual(rc, 0, out)
        self.assertIn("%s is not a JSON object" % self.key(self.alt_s), out)
        self.assertEqual(self.alt_s.read_text(), "{oops")
        self.assertEqual(len(self.hooks(self.main_s)), 1)

    def check_linked_once(self):
        rc, out = self.setup()
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.count("+++ "), 3, out)  # registry, .bashrc, one settings.json
        self.assertEqual(len(list((self.sw / "backups").iterdir())), 1)
        self.assertEqual(len(self.hooks(self.alt_s)), 1)
        self.assertEqual(list(self.originals().values()), [None])
        self.setup("--uninstall")
        self.assertEqual(json.loads(self.alt_s.read_text()), {"a": 1})

    def test_hardlinked_written_once(self):
        self.alt_s.unlink()
        os.link(self.main_s, self.alt_s)
        self.check_linked_once()
        self.assertTrue(os.path.samefile(self.main_s, self.alt_s))

    def test_symlinked_written_once(self):
        self.alt_s.unlink()
        try:
            os.symlink(self.main_s, self.alt_s)
        except OSError:
            self.skipTest("no symlink rights")
        self.check_linked_once()
        self.assertTrue(self.alt_s.is_symlink())

    def test_old_registry_migrates(self):
        self.main_s.write_text(json.dumps({"statusLine": self.THEIRS}))
        self.main("setup", "--profile=bash=%s" % self.bashrc, "--yes", "--account", "main=%s" % self.main_s.parent)
        reg = cs.load()
        reg["settings"] = {"installed": True, "statusline_original": self.THEIRS}  # the one-file format
        cs.save(reg)
        with mock.patch.dict(os.environ, {"CLAUDE_SWITCH_ACCOUNT": "main"}):
            self.assertEqual(cs.statusline_original(reg), self.THEIRS)
        self.alt_s.write_text("{}")
        self.setup()
        self.assertEqual(self.originals(), {self.key(self.main_s): self.THEIRS, self.key(self.alt_s): None})
        self.setup("--uninstall")
        self.assertEqual(json.loads(self.main_s.read_text()), {"statusLine": self.THEIRS})
        self.assertEqual(json.loads(self.alt_s.read_text()), {})

    def test_add_migrate_remove(self):
        self.main("setup", "--profile=bash=%s" % self.bashrc, "--yes", "--account", "main=%s" % self.main_s.parent)
        rc, out = self.main("add", "alt", "--dir", str(self.alt_s.parent))  # own settings.json: left as is
        self.assertEqual(rc, 0, out)
        self.assertIn("updated %s" % self.key(self.alt_s), out)
        self.assertEqual(len(self.hooks(self.alt_s)), 1)
        self.assertEqual(self.originals()[self.key(self.alt_s)], self.THEIRS)
        rc, out = self.main("add", "work")  # linked: already has them
        self.assertNotIn("updated %s" % self.key(self.main_s), out)
        self.assertEqual(len(self.originals()), 2)
        mig = self.home / ".claude-mig"
        (mig / "projects").mkdir(parents=True)
        (mig / "settings.json").write_text("{}")
        rc, out = self.main("migrate")
        self.assertIn("updated %s" % self.key(mig / "settings.json"), out)
        self.assertEqual(len(self.hooks(mig / "settings.json")), 1)
        rc, out = self.main("remove", "work")  # its settings.json is main's: untouched
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.hooks(self.main_s)), 1)
        rc, out = self.main("remove", "alt")  # kept dir, own file: ours taken out
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads(self.alt_s.read_text()), {"statusLine": self.THEIRS})
        self.assertEqual(set(self.originals()), {self.key(self.main_s), self.key(mig / "settings.json")})

    def test_copy_inherits_original(self):
        """A copy of a written file (add's copy fallback, a split hardlink) gets the first file's original."""
        self.main_s.write_text(json.dumps({"statusLine": self.THEIRS}))
        self.main("setup", "--profile=bash=%s" % self.bashrc, "--yes", "--account", "main=%s" % self.main_s.parent)
        self.alt_s.write_text(self.main_s.read_text())
        rc, out = self.setup()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.originals()[self.key(self.alt_s)], self.THEIRS)
        self.setup("--uninstall")
        for p in (self.main_s, self.alt_s):
            self.assertEqual(json.loads(p.read_text()), {"statusLine": self.THEIRS}, p)


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


class ListTest(Base):
    def setUp(self):
        super().setUp()
        self.reg = self.register("main", "alt", "work")  # work's dir never created
        self.main_dir, self.alt_dir = self.home / ".claude", self.tmp / "cfg-alt"
        self.main_dir.mkdir()
        self.alt_dir.mkdir()

    def lines(self, env=None):
        with mock.patch.dict(os.environ, env or {}):
            return dict(zip(("main", "alt", "work"), cs.list_lines(cs.load(), NOW)))

    def test_login_and_email(self):
        (self.main_dir / ".credentials.json").write_text("{}")
        # ~/.claude keeps its .claude.json in HOME; a stray one inside the dir is ignored
        (self.home / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "ana@example.com"}}))
        (self.main_dir / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "old@example.com"}}))
        (self.alt_dir / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "sam@example.com"}}))
        out = self.lines()
        self.assertIn("  logged in   ana@example.com  ", out["main"])
        self.assertIn("  logged out  sam@example.com  ", out["alt"])  # no credentials file, not macOS
        self.assertIn("  logged out  -  ", out["work"])
        with mock.patch.object(cs, "MACOS", True):  # login in the Keychain: oauthAccount counts
            out = self.lines()
        self.assertIn("  logged in   sam@example.com", out["alt"])
        self.assertIn("  logged out  -  ", out["work"])

    def test_default_dir_falls_back_to_inner_file(self):
        (self.main_dir / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "ana@example.com"}}))
        self.assertIn("ana@example.com", self.lines()["main"])

    def test_bad_claude_json(self):
        for text in ("{not json", "[]", '{"oauthAccount": "x"}', '{"oauthAccount": {"emailAddress": 7}}', "\xff"):
            (self.alt_dir / ".claude.json").write_bytes(text.encode("latin-1"))
            with mock.patch.object(cs, "MACOS", True):
                self.assertIn("  logged %s  -  " % ("in " if "oauthAccount\": {" in text else "out"),
                              self.lines()["alt"], text)

    def test_usage_cells(self):
        cs.atomic_write(cs.usage_path("main"), json.dumps({
            "seen": NOW, "five_hour": {"pct": 42.4, "resets_at": NOW + 8010},
            "seven_day": {"pct": 18, "resets_at": NOW + 4 * 86400 + 6 * 3600 + 600}}))
        cs.atomic_write(cs.usage_path("alt"), "garbage")
        cs.atomic_write(cs.usage_path("work"), json.dumps({  # stale: past reset, and seen too long ago
            "seen": NOW - 6 * 3600, "five_hour": {"pct": 99, "resets_at": None},
            "seven_day": {"pct": 70, "resets_at": NOW - 1}}))
        out = self.lines()
        self.assertIn("session 42% (2h13m left)  week 18% (4d6h left)", out["main"])
        self.assertRegex(out["alt"], r"session -\s+week -\s+last used never")
        self.assertRegex(out["work"], r"session 0%\s+week 0%\s+last used never")

    def test_aligned_current_no_ansi(self):
        cs.touch("alt")
        out = self.lines({"CLAUDE_CONFIG_DIR": str(self.alt_dir)})
        cols = {line.index("session") for line in out.values()} | {line.index("last used") for line in out.values()}
        self.assertEqual(len(cols), 2)
        self.assertTrue(out["alt"].endswith("%s  (current)" % self.alt_dir))
        self.assertTrue(out["main"].startswith("main  cyan "))
        self.assertIn(" UTC  ", out["alt"])
        self.assertNotIn("\x1b", "".join(out.values()))
        with mock.patch.dict(os.environ, {"CLAUDE_SWITCH_ACCOUNT": "work"}):
            self.assertTrue(cs.list_lines(cs.load(), NOW, tty=True)[2].startswith("\x1b[43m  \x1b[0m work"))

    def test_empty(self):
        cs.save({"accounts": []})
        self.assertEqual(cs.list_lines(cs.load(), NOW), ["no accounts; run /switch setup, or migrate"])


if __name__ == "__main__":
    unittest.main()
