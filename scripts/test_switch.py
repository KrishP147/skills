#!/usr/bin/env python3
"""Stdlib unittest coverage for switch/scripts/claude_switch.py. Run with:

    python -m unittest discover -s scripts -p "test_*.py"

Every test uses a temp HOME, registry and profile dirs. A small generated
python script stands in for claude; the real one is never run.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "switch" / "scripts" / "claude_switch.py"
_spec = importlib.util.spec_from_file_location("claude_switch", SCRIPT)
cs = importlib.util.module_from_spec(_spec)
sys.modules["claude_switch"] = cs
_spec.loader.exec_module(cs)

SID = "0b9f2c4e-1d2a-4c3b-9e8f-7a6b5c4d3e2f"
FAKE = r'''
import json, os, subprocess, sys, time
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    rec = {k: os.environ.get(v) for k, v in (
        ("account", "CLAUDE_SWITCH_ACCOUNT"), ("config", "CLAUDE_CONFIG_DIR"),
        ("previous", "CLAUDE_SWITCH_PREVIOUS"), ("launcher", "CLAUDE_SWITCH_LAUNCHER"))}
    rec["args"] = args
    f.write(json.dumps(rec) + "\n")
if "--resume" in args and os.environ.get("FAKE_RESUME_FAIL"):
    sys.exit(1)
if args[:1] in (["--resume"], ["--continue"]):
    sys.exit(0)
if os.environ.get("FAKE_ADD"):
    subprocess.run([os.environ["CLAUDE_SWITCH_PYTHON"], os.environ["FAKE_SCRIPT"], "add",
                    os.environ["FAKE_ADD"], "--session", os.environ.get("FAKE_SESSION", "")])
    time.sleep(60)
if os.environ.get("FAKE_SWITCH_TO"):
    subprocess.run([os.environ["CLAUDE_SWITCH_PYTHON"], os.environ["FAKE_SCRIPT"], "request",
                    os.environ["FAKE_SWITCH_TO"], "--session", os.environ.get("FAKE_SESSION", "")])
    time.sleep(60)
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="switch-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.sw = self.tmp / "sw"
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("CLAUDE_SWITCH_", "CLAUDE_CONFIG_DIR", "FAKE_"))}
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), CLAUDE_SWITCH_HOME=str(self.sw))
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        # documents_dir() asks Windows for the REAL Documents folder: never fall back to it
        p = mock.patch.object(cs, "default_targets", lambda: {"bash": self.tmp / "default" / ".bashrc"})
        p.start()
        self.addCleanup(p.stop)

    def register(self, *names):
        reg = {"accounts": [], "profiles": {"bash": str(self.tmp / "profiles" / ".bashrc")}}
        for n in names:
            d = self.home / ".claude" if n == "main" else self.tmp / ("cfg-" + n)
            cs.upsert(reg, n, str(d))
        cs.save(reg)
        return reg

    def main(self, *argv, env=None):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out):
            rc = cs.main(list(argv))
        return rc, out.getvalue()

    def requests(self):
        d = self.sw / "requests"
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


class RegistryTest(Base):
    def test_roundtrip_and_atomic(self):
        self.register("main", "alt")
        reg = cs.load()
        self.assertEqual([a["name"] for a in reg["accounts"]], ["main", "alt"])
        self.assertEqual(set(reg["accounts"][0]), {"name", "dir", "colour", "theme", "last_used"})
        self.assertNotEqual(reg["accounts"][0]["colour"], reg["accounts"][1]["colour"])
        self.assertEqual([p.name for p in self.sw.iterdir() if p.name.endswith(".tmp")], [])

    def test_stale_file_moved_aside(self):
        self.sw.write_text("0123-old-session-id")
        with contextlib.redirect_stderr(io.StringIO()):
            self.register("main")
        self.assertTrue(self.sw.is_dir())
        stale = [p for p in self.tmp.iterdir() if p.name.startswith("sw.stale-")]
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0].read_text(), "0123-old-session-id")
        self.assertEqual(cs.find(cs.load(), "main")["dir"], str((self.home / ".claude").absolute()))

    def test_bad_name(self):
        with self.assertRaises(SystemExit):
            cs.upsert({"accounts": []}, "Bad Name", "x")

    def test_most_recent(self):
        reg = self.register("main", "alt", "work")
        self.assertEqual(cs.most_recent(reg)["name"], "main")  # none used: registration order
        cs.find(reg, "work")["last_used"] = "2026-01-02T00:00:00.000000Z"
        cs.find(reg, "alt")["last_used"] = "2026-01-01T00:00:00.000000Z"
        self.assertEqual(cs.most_recent(reg)["name"], "work")
        self.assertEqual(cs.most_recent(reg, exclude="work")["name"], "alt")

    def test_touch(self):
        self.register("main", "alt")
        cs.touch("alt")
        self.assertEqual(cs.most_recent(cs.load())["name"], "alt")


class ResolveTest(Base):
    def setUp(self):
        super().setUp()
        self.reg = self.register("main", "alt", "work")
        cs.find(self.reg, "work")["last_used"] = "2026-01-02T00:00:00.000000Z"

    def test_previous_wins(self):
        a, _ = cs.resolve_target(self.reg, None, "main", "alt")
        self.assertEqual(a["name"], "alt")

    def test_no_previous_most_recent_other(self):
        self.assertEqual(cs.resolve_target(self.reg, None, "main", None)[0]["name"], "work")
        self.assertEqual(cs.resolve_target(self.reg, None, "work", "work")[0]["name"], "main")
        self.assertEqual(cs.resolve_target(self.reg, None, "main", "gone")[0]["name"], "work")

    def test_named_unknown_same(self):
        self.assertEqual(cs.resolve_target(self.reg, "alt", "main", None)[0]["name"], "alt")
        a, msg = cs.resolve_target(self.reg, "nope", "main", None)
        self.assertIsNone(a)
        self.assertIn("main (current), alt, work", msg)
        a, msg = cs.resolve_target(self.reg, "main", "main", None)
        self.assertIsNone(a)
        self.assertIn("already on", msg)

    def test_only_account(self):
        reg = {"accounts": [self.reg["accounts"][0]]}
        a, msg = cs.resolve_target(reg, None, "main", None)
        self.assertIsNone(a)
        self.assertIn("no other account", msg)


class RequestTest(Base):
    def setUp(self):
        super().setUp()
        self.register("main", "alt")
        self.env = {"CLAUDE_SWITCH_LAUNCHER": "4242", "CLAUDE_SWITCH_ACCOUNT": "main"}

    def test_not_under_launcher(self):
        rc, out = self.main("request", "alt", "--session", SID)
        self.assertNotEqual(rc, 0)
        self.assertIn("setup", out)
        self.assertEqual(self.requests(), [])

    def test_unknown_name(self):
        rc, out = self.main("request", "nope", "--session", SID, env=self.env)
        self.assertEqual(rc, 1)
        self.assertIn("main (current), alt", out)
        self.assertEqual(self.requests(), [])

    def test_same_name(self):
        rc, out = self.main("request", "main", env=self.env)
        self.assertIn("already on 'main'", out)
        self.assertEqual(self.requests(), [])

    def test_writes_own_launcher_file(self):
        rc, out = self.main("request", "--session", SID, env=self.env)
        self.assertEqual(rc, 0)
        self.assertEqual(self.requests(), ["4242.json"])
        req = json.loads((self.sw / "requests" / "4242.json").read_text())
        self.assertEqual(req, {"target": "alt", "session": SID})


class SetupTest(Base):
    def profiles(self):
        p = self.tmp / "profiles"
        return {"bash": p / ".bashrc", "zsh": p / ".zshrc", "fish": p / "conf.d" / "claude-switch.fish",
                "powershell": p / "ps5" / "profile.ps1", "pwsh": p / "ps7" / "profile.ps1", "cmd": p / "bin"}

    def setup(self, *accounts, yes=True):
        argv = ["setup"] + ["--account=%s" % a for a in accounts]
        argv += ["--profile=%s=%s" % kv for kv in self.profiles().items()]
        if yes:
            argv.append("--yes")
        return self.main(*argv)

    def test_default_main(self):
        rc, _ = self.setup()
        self.assertEqual(rc, 0)
        reg = cs.load()
        self.assertEqual([(a["name"], a["dir"]) for a in reg["accounts"]],
                         [("main", str((self.home / ".claude").absolute()))])

    def test_generated_files(self):
        alt = self.tmp / "alt dir"
        rc, out = self.setup("main=%s" % (self.home / ".claude"), "alt=%s" % alt)
        self.assertEqual(rc, 0, out)
        p = self.profiles()
        py, script = sys.executable, str(SCRIPT)
        sh = lambda s: Path(s).as_posix() if os.name == "nt" else s
        bash = p["bash"].read_text()
        self.assertIn("claude() { '%s' '%s' run - \"$@\"; }" % (sh(py), sh(script)), bash)
        self.assertIn("claude-alt() {", bash)
        self.assertEqual(p["zsh"].read_text(), bash)
        fish = p["fish"].read_text()
        self.assertIn("function claude-alt; command '", fish)
        self.assertIn("run alt $argv; end", fish)
        for key in ("powershell", "pwsh"):
            raw = p[key].read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), key)  # new PS profile: BOM for 5.1
            self.assertIn("function claude-main { & '%s' '%s' run 'main' @args }" % (py, script),
                          raw.decode("utf-8-sig"))
        shims = sorted(x.name for x in p["cmd"].iterdir())
        self.assertEqual(shims, ["claude-alt.cmd", "claude-main.cmd", "claude.cmd"])
        cmd = (p["cmd"] / "claude-alt.cmd").read_text()
        self.assertIn(cs.SHIM_MARK, cmd)
        self.assertIn('"%s" "%s" run alt %%*' % (py, script), cmd)

    def test_idempotent_and_keeps_rest(self):
        p = self.profiles()
        p["bash"].parent.mkdir(parents=True)
        p["bash"].write_text("export A=1\nalias ll='ls -l'")
        self.setup("alt=%s" % self.tmp)
        first = {k: v.read_bytes() for k, v in p.items() if k != "cmd"}
        rc, out = self.setup()
        self.assertIn("up to date", out)
        self.assertEqual(first, {k: v.read_bytes() for k, v in p.items() if k != "cmd"})
        self.setup("work=%s" % self.tmp)  # new account: block replaced, not appended
        bash = p["bash"].read_text()
        self.assertTrue(bash.startswith("export A=1\nalias ll='ls -l'\n"))
        self.assertEqual(bash.count(cs.BEGIN), 1)
        self.assertIn("claude-work()", bash)

    def test_crlf_and_bom_kept(self):
        p = self.profiles()["powershell"]
        p.parent.mkdir(parents=True)
        p.write_bytes(b"\xef\xbb\xbfSet-Alias g git\r\n")
        self.setup()
        raw = p.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbfSet-Alias g git\r\n"))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_stale_shim_removed(self):
        self.setup("alt=%s" % self.tmp)
        reg = cs.load()
        reg["accounts"] = [a for a in reg["accounts"] if a["name"] != "alt"]
        cs.save(reg)
        (self.profiles()["cmd"] / "claude-mine.cmd").write_text("@echo off\r\n")  # not ours: kept
        self.setup()
        self.assertEqual(sorted(x.name for x in self.profiles()["cmd"].iterdir()),
                         ["claude-main.cmd", "claude-mine.cmd", "claude.cmd"])

    def test_non_utf8_profile_refused(self):
        p = self.profiles()["powershell"]
        p.parent.mkdir(parents=True)
        p.write_bytes(b"# caf\xe9\r\n")  # ANSI-encoded, as PowerShell 5.1 Set-Content writes
        with self.assertRaises(SystemExit) as e:
            self.setup()
        self.assertIn("not UTF-8", str(e.exception))
        self.assertEqual(p.read_bytes(), b"# caf\xe9\r\n")

    def test_cp1252_console_diff(self):
        p = self.profiles()["bash"]
        p.parent.mkdir(parents=True)
        p.write_text("# a → b\n", encoding="utf-8")
        raw = io.BytesIO()
        out = io.TextIOWrapper(raw, encoding="cp1252")
        argv = ["setup", "--profile=bash=%s" % p, "--yes"]
        with contextlib.redirect_stdout(out):
            rc = cs.main(argv)
        out.flush()
        self.assertEqual(rc, 0)
        self.assertIn(b"+claude() {", raw.getvalue())
        self.assertIn("# a → b\n", p.read_text(encoding="utf-8"))

    def test_no_yes_writes_nothing(self):
        with mock.patch("builtins.input", side_effect=EOFError):
            rc, out = self.setup("alt=%s" % self.tmp, yes=False)
        self.assertEqual(rc, 1)
        self.assertIn("+claude-alt() {", out)  # diff shown
        self.assertFalse(any(v.exists() for v in self.profiles().values()))
        self.assertFalse(cs.registry_path().exists())

    @unittest.skipUnless(shutil.which("bash") and os.name != "nt", "posix bash")
    def test_bash_block_runs_fake(self):
        self.setup("alt=%s" % (self.tmp / "alt"))
        log = self.tmp / "log.jsonl"
        fake = self.tmp / "fake.py"
        fake.write_text(FAKE)
        env = dict(os.environ, CLAUDE_SWITCH_CLAUDE=json.dumps([sys.executable, str(fake)]), FAKE_LOG=str(log))
        r = subprocess.run(["bash", "-c", 'source "$1"; claude-alt hi', "x", str(self.profiles()["bash"])],
                           env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(log.read_text())["account"], "alt")

    @unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell"), "no PowerShell")
    def test_powershell_parses(self):
        self.setup("alt=%s" % self.tmp)
        ps = shutil.which("pwsh") or shutil.which("powershell")
        for key in ("powershell", "pwsh"):
            path = str(self.profiles()[key]).replace("'", "''")
            r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command",
                                "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
                                "'%s', [ref]$null, [ref]$e); if ($e.Count) { $e; exit 1 }" % path],
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


def make_link(src, dst):
    """Junction on Windows, symlink elsewhere: what add creates for dirs."""
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(src), str(dst))
    else:
        os.symlink(str(src), str(dst), target_is_directory=True)


def tree_hash(root):
    """Every path under root (links not followed) with its link flag and bytes."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for n in dirnames + filenames:
            p = os.path.join(dirpath, n)
            rel = os.path.relpath(p, root)
            if cs.is_link(p):
                out[rel] = ("link", os.readlink(p))
            elif os.path.isfile(p):
                out[rel] = ("file", Path(p).read_bytes(), os.stat(p).st_mtime_ns)
            else:
                out[rel] = ("dir",)
        dirnames[:] = [d for d in dirnames if not cs.is_link(os.path.join(dirpath, d))]
    return out


class AccountsTest(Base):
    def setUp(self):
        super().setUp()
        self.register("main")
        self.main_dir = self.home / ".claude"
        (self.main_dir / "skills" / "s1").mkdir(parents=True)
        (self.main_dir / "skills" / "s1" / "SKILL.md").write_text("shared skill")
        (self.main_dir / "projects" / "p").mkdir(parents=True)
        (self.main_dir / "projects" / "p" / "session.jsonl").write_text("history")
        (self.main_dir / "settings.json").write_text('{"a": 1}')
        (self.main_dir / ".credentials.json").write_text("main secret")
        self.bashrc = self.tmp / "profiles" / ".bashrc"

    def add(self, name="work", *extra, env=None):
        rc, out = self.main("add", name, *extra, env=env)
        self.assertEqual(rc, 0, out)
        return out

    def test_add_links_shared_items(self):
        out = self.add()
        work = self.home / ".claude-work"
        for n in cs.SHARED_DIRS:
            self.assertTrue(cs.is_link(work / n), n)
            self.assertTrue((self.main_dir / n).is_dir(), n)  # missing ones created empty in the source
        self.assertEqual((work / "skills" / "s1" / "SKILL.md").read_text(), "shared skill")
        (work / "projects" / "p" / "new.jsonl").write_text("from work")
        self.assertEqual((self.main_dir / "projects" / "p" / "new.jsonl").read_text(), "from work")
        self.assertEqual((work / "settings.json").read_text(), '{"a": 1}')
        self.assertTrue(os.path.samefile(work / "settings.json", self.main_dir / "settings.json"))
        self.assertFalse(os.path.lexists(work / "CLAUDE.md"))
        self.assertIn("CLAUDE.md missing; not shared", out)
        self.assertFalse((work / ".credentials.json").exists())  # per account
        reg = cs.load()
        self.assertEqual([a["name"] for a in reg["accounts"]], ["main", "work"])
        self.assertNotEqual(reg["accounts"][0]["colour"], reg["accounts"][1]["colour"])
        self.assertIn("claude-work()", self.bashrc.read_text())
        self.assertIn("updated %s" % self.bashrc, out)
        self.assertIn("start it with claude-work", out)
        self.assertEqual(self.requests(), [])
        self.assertFalse((self.tmp / "default").exists())

    def test_add_keeps_existing_and_custom_dir(self):
        d = self.tmp / "custom"
        (d / "skills").mkdir(parents=True)
        out = self.add("job", "--dir", str(d))
        self.assertIn("already exists; left as is", out)
        self.assertFalse(cs.is_link(d / "skills"))
        self.assertTrue(cs.is_link(d / "projects"))
        self.assertEqual(cs.find(cs.load(), "job")["dir"], str(d))

    def test_add_refusals(self):
        self.add()
        for argv in (["add", "work"], ["add", "Bad Name"], ["add", "dup", "--dir", str(self.main_dir)]):
            with self.assertRaises(SystemExit, msg=argv):
                self.main(*argv)
        self.assertEqual([a["name"] for a in cs.load()["accounts"]], ["main", "work"])

    def test_file_fallbacks(self):
        src, dst = self.main_dir / "settings.json", self.tmp / "s1.json"
        with mock.patch.object(cs, "WINDOWS", True), \
                mock.patch.object(cs.os, "symlink", side_effect=OSError(1314, "privilege")):
            self.assertIn("hardlinked", cs.link_file(src, dst))
            self.assertTrue(os.path.samefile(src, dst))
            with mock.patch.object(cs.os, "link", side_effect=OSError("cross-device")):
                self.assertIn("copied", cs.link_file(src, self.tmp / "s2.json"))
        self.assertEqual((self.tmp / "s2.json").read_text(), '{"a": 1}')

    def test_add_under_launcher_writes_request(self):
        self.add(env={"CLAUDE_SWITCH_LAUNCHER": "4242", "CLAUDE_SWITCH_ACCOUNT": "main"})
        self.assertEqual(json.loads((self.sw / "requests" / "4242.json").read_text()),
                         {"target": "work", "session": ""})

    def test_remove_delete_dir_keeps_shared(self):
        self.add()
        work = self.home / ".claude-work"
        (work / ".credentials.json").write_text("work secret")
        (work / "sub").mkdir()
        make_link(self.main_dir / "projects", work / "sub" / "deep-link")  # nested link too
        before = tree_hash(self.main_dir)
        rc, out = self.main("remove", "work", "--delete-dir", "--yes")
        self.assertEqual(rc, 0, out)
        self.assertIn("unlink (shared", out)
        self.assertFalse(os.path.lexists(work))
        self.assertEqual(tree_hash(self.main_dir), before)
        self.assertEqual((self.main_dir / "projects" / "p" / "session.jsonl").read_text(), "history")
        self.assertEqual([a["name"] for a in cs.load()["accounts"]], ["main"])
        self.assertNotIn("claude-work()", self.bashrc.read_text())

    def test_delete_dir_never_follows(self):
        shared = self.tmp / "shared"
        (shared / "inner").mkdir(parents=True)
        (shared / "inner" / "keep.txt").write_text("keep")
        root = self.tmp / "victim"
        (root / "a" / "b").mkdir(parents=True)
        (root / "a" / "b" / "f.txt").write_text("x")
        make_link(shared, root / "a" / "j")
        make_link(shared / "inner", root / "j2")
        self.assertTrue(cs.is_link(root / "a" / "j"))
        if os.name == "nt":
            self.assertTrue(os.lstat(root / "j2").st_file_attributes & cs.stat.FILE_ATTRIBUTE_REPARSE_POINT)
        links, files, dirs = cs.scan_tree(root)
        self.assertEqual(sorted(map(os.path.basename, links)), ["j", "j2"])
        self.assertEqual([os.path.basename(f) for f in files], ["f.txt"])
        cs.delete_dir(root)
        self.assertFalse(root.exists())
        self.assertEqual((shared / "inner" / "keep.txt").read_text(), "keep")

    def test_remove_dry_run_and_no(self):
        self.add()
        work = self.home / ".claude-work"
        before, reg = tree_hash(work), cs.registry_path().read_text()
        rc, out = self.main("remove", "work", "--delete-dir", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("dry run: nothing changed", out)
        self.assertIn("unlink (shared", out)
        self.assertIn("delete: %s" % work, out)
        with mock.patch("builtins.input", side_effect=EOFError):
            rc, out = self.main("remove", "work", "--delete-dir")
        self.assertEqual(rc, 1)
        self.assertEqual((tree_hash(work), cs.registry_path().read_text()), (before, reg))

    def test_remove_keeps_dir_by_default(self):
        self.add()
        rc, out = self.main("remove", "work")
        self.assertEqual(rc, 0, out)
        self.assertTrue(cs.is_link(self.home / ".claude-work" / "projects"))
        self.assertIsNone(cs.find(cs.load(), "work"))

    def test_remove_refusals(self):
        with self.assertRaises(SystemExit) as e:
            self.main("remove", "main")
        self.assertIn("last account", str(e.exception))
        self.add()
        self.add("job")
        cases = ((("remove", "main"), None, "first account"),
                 (("remove", "work"), {"CLAUDE_SWITCH_ACCOUNT": "work"}, "account you're on"),
                 (("remove", "nope"), None, "unknown account"))
        for argv, env, msg in cases:
            with self.assertRaises(SystemExit) as e:
                self.main(*argv, env=env)
            self.assertIn(msg, str(e.exception))
        reg = cs.load()  # a dir overlapping another account's is never deleted
        cs.find(reg, "job")["dir"] = str(self.main_dir / "nested")
        cs.save(reg)
        (self.main_dir / "nested").mkdir()
        with self.assertRaises(SystemExit) as e:
            self.main("remove", "job", "--delete-dir", "--yes")
        self.assertIn("overlaps", str(e.exception))
        self.assertTrue((self.main_dir / "nested").is_dir())
        self.assertEqual([a["name"] for a in cs.load()["accounts"]], ["main", "work", "job"])

    def test_rename(self):
        self.add()
        rc, out = self.main("rename", "work", "job")
        self.assertEqual(rc, 0, out)
        a = cs.find(cs.load(), "job")
        self.assertEqual(a["dir"], str(self.home / ".claude-work"))
        self.assertTrue((self.home / ".claude-work").is_dir())
        bash = self.bashrc.read_text()
        self.assertIn("claude-job()", bash)
        self.assertNotIn("claude-work()", bash)
        for argv in (("rename", "job", "main"), ("rename", "job", "Bad"), ("rename", "nope", "x")):
            with self.assertRaises(SystemExit, msg=argv):
                self.main(*argv)

    def test_list(self):
        self.add()
        cs.touch("work")
        rc, out = self.main("list", env={"CLAUDE_SWITCH_ACCOUNT": "work"})
        lines = out.splitlines()
        self.assertEqual(rc, 0)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("main"))
        self.assertIn("last used never", lines[0])
        self.assertIn(str(self.main_dir), lines[0])
        self.assertIn(cs.find(cs.load(), "work")["colour"], lines[1])
        self.assertTrue(lines[1].endswith("(current)"))
        self.assertIn(" UTC", lines[1])
        self.assertNotIn("\x1b", out)  # not a tty: no ANSI


class MigrateTest(Base):
    def test_read_only_and_exclusions(self):
        h = self.home
        files = {".claude/projects/p/s.jsonl": "x", ".claude-alt/.credentials.json": "c",
                 ".claude-mac/.claude.json": "{}", ".claude-proj/projects/q/s.jsonl": "y",
                 ".claude-Bad/.credentials.json": "c", ".claude-old.stale-123/.credentials.json": "c",
                 ".claude-switch/accounts.json": "{}", ".claude-empty/notes.txt": "n",
                 ".claude-file": "not a dir", ".claude.json": "{}"}
        for rel, text in files.items():
            (h / rel).parent.mkdir(parents=True, exist_ok=True)
            (h / rel).write_text(text)
        before = tree_hash(h)
        rc, out = self.main("migrate")
        self.assertEqual(rc, 0, out)
        self.assertEqual(tree_hash(h), before)
        reg = cs.load()
        self.assertEqual([(a["name"], a["dir"]) for a in reg["accounts"]],
                         [(n, str(h / d)) for n, d in (("main", ".claude"), ("alt", ".claude-alt"),
                                                       ("mac", ".claude-mac"), ("proj", ".claude-proj"))])
        self.assertIn("'Bad' is not a valid account name", out)
        self.assertIn(".claude-empty: no .credentials.json", out)
        self.assertNotIn("stale", out)
        self.assertIn("claude-proj()", (self.tmp / "default" / ".bashrc").read_text())  # fallback target, mocked
        rc, out = self.main("migrate")
        self.assertIn("nothing new", out)
        self.assertEqual(tree_hash(h), before)

    def test_keeps_registered_main(self):
        self.register("main", "alt")
        (self.home / ".claude").mkdir()
        (self.home / ".claude-alt" / "projects").mkdir(parents=True)
        rc, out = self.main("migrate")
        self.assertEqual([a["name"] for a in cs.load()["accounts"]], ["main", "alt"])
        self.assertIn("'alt' is already", out)
        self.assertIn("nothing new", out)


class FindClaudeTest(Base):
    def test_skips_shim_dir_and_marked_wrappers(self):
        name = "claude.cmd" if os.name == "nt" else "claude"
        bin_dir, other, real = self.sw / "bin", self.tmp / "other", self.tmp / "real"
        for d, text in ((bin_dir, "x"), (other, "rem %s" % cs.SHIM_MARK), (real, "real")):
            d.mkdir(parents=True)
            (d / name).write_text(text)
            os.chmod(d / name, 0o755)
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join(map(str, (bin_dir, other, real))),
                                          "PATHEXT": ".EXE;.CMD"}):
            self.assertEqual(cs.find_claude(), [str(real / name)])


class LauncherTest(Base):
    def setUp(self):
        super().setUp()
        self.register("main", "alt")
        self.fake = self.tmp / "fake.py"
        self.fake.write_text(FAKE)

    def launch(self, *argv, log="log.jsonl", **fake_env):
        env = dict(os.environ, CLAUDE_SWITCH_CLAUDE=json.dumps([sys.executable, str(self.fake)]),
                   FAKE_LOG=str(self.tmp / log), FAKE_SCRIPT=str(SCRIPT), **fake_env)
        return subprocess.Popen([sys.executable, str(SCRIPT), "run"] + list(argv), env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)

    def finish(self, proc):
        out, err = proc.communicate(timeout=60)
        return proc.returncode, out, err

    def log(self, name="log.jsonl"):
        return [json.loads(x) for x in (self.tmp / name).read_text().splitlines()]

    def test_switch_resumes_on_target(self):
        rc, out, err = self.finish(self.launch("main", "--model", "x", FAKE_SWITCH_TO="alt", FAKE_SESSION=SID))
        self.assertEqual(rc, 0, err)
        log = self.log()
        self.assertEqual([(e["account"], e["args"]) for e in log],
                         [("main", ["--model", "x"]), ("alt", ["--resume", SID])])
        self.assertIsNone(log[0]["config"])  # default ~/.claude: CLAUDE_CONFIG_DIR unset
        self.assertEqual(log[1]["config"], cs.find(cs.load(), "alt")["dir"])
        self.assertEqual((log[0]["previous"], log[1]["previous"]), (None, "main"))
        self.assertEqual(log[0]["launcher"], log[1]["launcher"])
        self.assertIn("main -> alt", err)
        self.assertEqual(cs.most_recent(cs.load())["name"], "alt")
        self.assertEqual(self.requests(), [])

    def test_bad_session_continues(self):
        rc, _, err = self.finish(self.launch("main", FAKE_SWITCH_TO="alt", FAKE_SESSION="not-a-uuid"))
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.log()[1]["args"], ["--continue"])

    def test_resume_failure_falls_back(self):
        rc, _, err = self.finish(self.launch("main", FAKE_SWITCH_TO="alt", FAKE_SESSION=SID, FAKE_RESUME_FAIL="1"))
        self.assertEqual(rc, 0, err)
        self.assertEqual([(e["account"], e["args"]) for e in self.log()],
                         [("main", []), ("alt", ["--resume", SID]), ("alt", ["--continue"])])
        self.assertEqual(err.count("--resume failed"), 1)

    def test_exit_code_passthrough_and_recent(self):
        cs.touch("alt")
        rc, _, _ = self.finish(self.launch("-", FAKE_EXIT="3"))
        self.assertEqual(rc, 3)
        self.assertEqual([e["account"] for e in self.log()], ["alt"])
        rc, _, _ = self.finish(self.launch("--model", "x"))  # no name: most recent, args to claude
        self.assertEqual((rc, self.log()[-1]["account"], self.log()[-1]["args"]), (0, "alt", ["--model", "x"]))
        rc, _, err = self.finish(self.launch("gone", "hi"))  # stale claude-<name> wrapper
        self.assertEqual(rc, 2)
        self.assertIn("unknown account 'gone'. accounts: main, alt", err)
        self.assertEqual(len(self.log()), 2)  # claude not started

    def test_add_switches_into_new_account(self):
        rc, _, err = self.finish(self.launch("main", FAKE_ADD="work", FAKE_SESSION=SID))
        self.assertEqual(rc, 0, err)
        log = self.log()
        self.assertEqual([(e["account"], e["args"]) for e in log], [("main", []), ("work", ["--resume", SID])])
        self.assertEqual(log[1]["config"], str(self.home / ".claude-work"))
        self.assertTrue(cs.is_link(self.home / ".claude-work" / "projects"))
        self.assertIn("claude-work()", (self.tmp / "profiles" / ".bashrc").read_text())
        self.assertEqual(self.requests(), [])

    def test_two_launchers_dont_cross(self):
        a = self.launch("main", log="a.jsonl", FAKE_SWITCH_TO="alt", FAKE_SESSION=SID)
        b = self.launch("alt", log="b.jsonl", FAKE_SWITCH_TO="main", FAKE_SESSION=SID.replace("0b", "1c"))
        results = {}
        threads = [threading.Thread(target=lambda k=k, p=p: results.__setitem__(k, self.finish(p)))
                   for k, p in (("a", a), ("b", b))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual((results["a"][0], results["b"][0]), (0, 0), results)
        self.assertEqual([(e["account"], e["args"]) for e in self.log("a.jsonl")],
                         [("main", []), ("alt", ["--resume", SID])])
        self.assertEqual([(e["account"], e["args"]) for e in self.log("b.jsonl")],
                         [("alt", []), ("main", ["--resume", SID.replace("0b", "1c")])])
        self.assertEqual({e["launcher"] for e in self.log("a.jsonl")}, {str(a.pid)})
        self.assertEqual({e["launcher"] for e in self.log("b.jsonl")}, {str(b.pid)})


if __name__ == "__main__":
    unittest.main()
