#!/usr/bin/env python3
"""claude-switch statusline. Claude Code runs it with the session JSON on
stdin (setup puts it in the shared settings.json as `statusLine`). Prints

  <account in its colour>  session 42% · 2h13m left  week 18% · 4d6h left

(`-` for a window Claude hasn't reported), caches the last seen usage in
$CLAUDE_SWITCH_HOME/usage/<account>.json for the usage guard, then runs the
statusLine you had before setup with the same stdin and puts its output on
the same line. Never fails: bad input prints what it can and exits 0.
Stdlib only.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_switch as cs  # noqa: E402

ORIGINAL_TIMEOUT = 5
LABELS = (("five_hour", "session"), ("seven_day", "week"))


def time_left(secs):
    secs = int(secs)
    if secs < 60:
        return "<1m"
    d, h, m = secs // 86400, secs % 86400 // 3600, secs % 3600 // 60
    if d:
        return "%dd%dh" % (d, h)
    if h:
        return "%dh%02dm" % (h, m)
    return "%dm" % m


def window(label, w, now):
    pct = w.get("used_percentage") if isinstance(w, dict) else None
    if not cs._num(pct):
        return "%s -" % label
    out = "%s %d%%" % (label, round(pct))
    r = w.get("resets_at")
    if cs._num(r) and r > now:
        out += " · %s left" % time_left(r - now)
    return out


def git_bash():
    """Git Bash on Windows (never WSL's System32 bash), else None."""
    p = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if p and os.path.isfile(p):
        return p
    git = shutil.which("git")
    cands = []
    if git:
        root = Path(git).resolve().parent.parent
        cands += [root / "bin" / "bash.exe", root.parent / "bin" / "bash.exe"]
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if os.environ.get(env):
            cands.append(Path(os.environ[env]) / ("Programs" if env == "LOCALAPPDATA" else "") / "Git" / "bin" / "bash.exe")
    for c in cands:
        if c.is_file():
            return str(c)
    b = shutil.which("bash")
    if b and "system32" not in b.lower() and "windowsapps" not in b.lower():
        return b
    return None


def shell_argv(cmd):
    """The shell Claude Code itself would use for a statusLine command."""
    if cs.WINDOWS:
        bash = git_bash()
        return [bash, "-c", cmd] if bash else ["powershell", "-NoProfile", "-Command", cmd]
    return [shutil.which("bash") or "/bin/sh", "-c", cmd]


def run_original(sl, raw):
    cmd = sl.get("command") if isinstance(sl, dict) else None
    if not isinstance(cmd, str) or not cmd.strip() or cs.is_our_statusline(sl):
        return ""
    try:
        r = subprocess.run(shell_argv(cmd), input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=ORIGINAL_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.decode("utf-8", "replace").rstrip("\r\n")


def render(data, reg, raw, now):
    acct = cs.current_account(reg)
    rl = data.get("rate_limits")
    rl = rl if isinstance(rl, dict) else {}
    if acct:
        try:
            cs.record_usage(acct["name"], rl, now)
        except OSError:
            pass
    parts = [cs.paint(acct, acct["name"], force=True)] if acct else []
    parts += [window(label, rl.get(key), now) for key, label in LABELS]
    line = "  ".join(parts)
    theirs = run_original((reg.get("settings") or {}).get("statusline_original"), raw)
    if theirs:
        first, _, rest = theirs.partition("\n")
        line += "  " + first + ("\n" + rest if rest else "")
    return line


def main():
    out = ""
    try:
        raw = sys.stdin.buffer.read()
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        try:
            reg = cs.load()
        except (OSError, ValueError):
            reg = {"accounts": []}
        out = render(data, reg, raw, time.time())
    except Exception as e:  # a statusline must never crash Claude's footer
        out = out or "claude-switch: %s" % e.__class__.__name__
    sys.stdout.buffer.write((out + "\n").encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
