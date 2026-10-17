#!/usr/bin/env python3
"""Reminders tied to your Claude accounts (switch skill) or to a time.
Stdlib only.

  add reset  [--account A] [TEXT...]   when A's 5-hour (session) limit resets
  add weekly [--account A] [TEXT...]   when A's weekly limit resets
  add under PCT [--account A] [TEXT...]  when A's usage is under PCT% (in-session only)
  add in DURATION TEXT...              e.g. 2h, 90m, 1h30m, 1d
  add at WHEN TEXT...                  e.g. 15:00, 3pm, 3:30pm, "tomorrow 9am", "2026-10-18 09:00"
  list | cancel ID
  hook                                 UserPromptSubmit: print due reminders once

Account kinds read the switch registry and usage cache in $CLAUDE_SWITCH_HOME
(default ~/.claude-switch); the account defaults to the one this session runs
on. Store: reminders.json next to that registry, else ~/.claude-remind/.
Timed reminders also get a one-shot OS notification: a Windows scheduled
task (toast, else `msg`) or an `at` job on macOS/Linux.
Env: CLAUDE_REMIND_TASK_PREFIX (scheduled task / notification name prefix).
"""
import argparse
import base64
import contextlib
import datetime
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

WINDOWS = os.name == "nt"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
KINDS = ("reset", "weekly", "under", "in", "at")
WINDOW = {"reset": ("five_hour", "session"), "weekly": ("seven_day", "weekly")}
TITLE = "Claude reminder"
KEEP_DONE_SECS = 86400


def now():
    return time.time()


# ---------------------------------------------------------------- store

def switch_home():
    return Path(os.environ.get("CLAUDE_SWITCH_HOME") or (Path.home() / ".claude-switch"))


def home():
    """Next to the switch registry when switch is set up, else ~/.claude-remind."""
    sw = switch_home()
    return sw if (sw / "accounts.json").is_file() else Path.home() / ".claude-remind"


def store_path():
    return home() / "reminders.json"


def _retry(fn, tries=50):
    # Windows: os.replace fails while another process holds the file
    for i in range(tries):
        try:
            return fn()
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.02)


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("%s.%d.tmp" % (path.name, os.getpid()))
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    _retry(lambda: os.replace(tmp, path))


def read_store(strict=False):
    """{"next": int, "reminders": [...]}. A corrupt file reads as empty; with
    strict it is moved aside first (so a write never overwrites it unseen)."""
    p = store_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("reminders"), list) \
                and all(isinstance(r, dict) and isinstance(r.get("id"), int) for r in data["reminders"]):
            data.setdefault("next", max([r["id"] for r in data["reminders"]] + [0]) + 1)
            return data
        raise ValueError("unexpected shape")
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        if strict:
            aside = p.with_name("reminders.corrupt-%d.json" % int(now()))
            _retry(lambda: os.replace(p, aside))
            print("remind: %s was unreadable (%s); moved to %s" % (p, e, aside), file=sys.stderr)
    return {"next": 1, "reminders": []}


def write_store(data, t):
    data["reminders"] = [r for r in data["reminders"] if not r.get("done") or t - r["done"] < KEEP_DONE_SECS]
    atomic_write(store_path(), json.dumps(data, indent=2) + "\n")


@contextlib.contextmanager
def locked():
    """Cross-process lock around read-modify-write: hooks of parallel
    sessions must not deliver a reminder twice or drop a new one."""
    lock = home() / "reminders.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(150):
        try:
            os.mkdir(lock)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 10:  # left by a killed process
                    os.rmdir(lock)
                    continue
            except OSError:
                pass
            time.sleep(0.02)
    else:
        raise RuntimeError("reminders are locked by another process (%s)" % lock)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            os.rmdir(lock)


def install_copy():
    """Copy this script next to the store: switch's hook and the README's
    hook snippet run that copy, so updating the skill doesn't break them."""
    src = Path(__file__).resolve()
    dst = home() / "remind.py"
    try:
        if src == dst.resolve() or dst.read_bytes() == src.read_bytes():
            return
    except OSError:
        pass
    data = src.read_bytes()
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name("remind.py.%d.tmp" % os.getpid())
    tmp.write_bytes(data)
    _retry(lambda: os.replace(tmp, dst))


# ---------------------------------------------------------------- switch

_SWITCH = []


def switch_module():
    """The switch script: its registry dir copy, else the installed skill
    next to this one. None without switch."""
    if not _SWITCH:
        mod = None
        for p in (switch_home() / "claude_switch.py",
                  Path(__file__).resolve().parents[2] / "switch" / "scripts" / "claude_switch.py"):
            if p.is_file():
                spec = importlib.util.spec_from_file_location("claude_switch_for_remind", p)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                break
        _SWITCH.append(mod)
    return _SWITCH[0]


def account_or_exit(name):
    cs = switch_module()
    if cs is None or not (switch_home() / "accounts.json").is_file():
        raise SystemExit("remind: account reminders need the switch skill set up (no %s)"
                         % (switch_home() / "accounts.json"))
    reg = cs.load()
    if name is None:
        acct = cs.current_account(reg)
        if not acct:
            raise SystemExit("remind: not sure which account this is; name one with --account (%s)"
                             % ", ".join(a["name"] for a in reg["accounts"]))
        return cs, acct["name"]
    if not cs.find(reg, name):
        raise SystemExit("remind: no account '%s' (have: %s)"
                         % (name, ", ".join(a["name"] for a in reg["accounts"]) or "none"))
    return cs, name


def usage_cache(cs, name):
    p = cs.usage_path(name)
    return cs._read_json(p) if p.is_file() else None


# ---------------------------------------------------------------- time

def fmt(epoch, t=None):
    d = datetime.datetime.fromtimestamp(epoch)
    today = datetime.datetime.fromtimestamp(now() if t is None else t).date()
    if d.date() == today:
        return d.strftime("%H:%M")
    if d.date() == today + datetime.timedelta(days=1):
        return d.strftime("tomorrow %H:%M")
    return d.strftime("%Y-%m-%d %H:%M")


DUR_RE = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m(?:in)?)?$")
CLOCK_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$")


def parse_in(s, t):
    m = DUR_RE.match(s.strip().lower().replace(" ", ""))
    if not m or not any(m.groups()):
        raise SystemExit("remind: bad duration %r (e.g. 2h, 90m, 1h30m, 1d)" % s)
    secs = int(m.group(1) or 0) * 86400 + int(m.group(2) or 0) * 3600 + int(m.group(3) or 0) * 60
    if secs <= 0:
        raise SystemExit("remind: duration must be more than 0")
    return t + secs


def parse_at(s, t):
    """Local time: HH:MM / 3pm / 3:30pm (today, or tomorrow once past),
    'tomorrow <time>', or 'YYYY-MM-DD <time>'."""
    s = s.strip().lower()
    base = datetime.datetime.fromtimestamp(t)
    day, rolls = base.date(), True
    m = re.match(r"^(tomorrow|\d{4}-\d{2}-\d{2})[ t]+(.+)$", s)
    if m:
        rolls = False
        if m.group(1) == "tomorrow":
            day = day + datetime.timedelta(days=1)
        else:
            try:
                day = datetime.date.fromisoformat(m.group(1))
            except ValueError:
                raise SystemExit("remind: bad date %r" % m.group(1))
        s = m.group(2).strip()
    c = CLOCK_RE.match(s)
    hh, mm = (int(c.group(1)), int(c.group(2) or 0)) if c else (99, 99)
    if c and c.group(3):
        hh = -1 if not 1 <= hh <= 12 else hh % 12 + (12 if c.group(3) == "pm" else 0)
    if not (c and 0 <= hh <= 23 and 0 <= mm <= 59):
        raise SystemExit("remind: bad time %r (e.g. 15:00, 3pm, 'tomorrow 9am', '2026-10-18 09:00')" % s)
    when = datetime.datetime.combine(day, datetime.time(hh, mm)).timestamp()
    if when <= t and rolls:
        when = datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time(hh, mm)).timestamp()
    if when <= t:
        raise SystemExit("remind: %s is in the past" % fmt(when, t))
    return when


# ---------------------------------------------------------------- reminders

def describe(r):
    k = r["kind"]
    if k in WINDOW:
        s = "%s's %s limit reset" % (r["account"], WINDOW[k][1])
    elif k == "under":
        s = "%s is under %g%%" % (r["account"], r["pct"])
    else:
        return r["text"]
    return "%s: %s" % (s, r["text"]) if r.get("text") else s


def make(kind, args, t):
    """A new reminder dict, or SystemExit saying why not (never a guess)."""
    words = list(args.words)
    if kind in ("in", "at"):
        if len(words) < 2:
            raise SystemExit("remind: usage: add %s %s TEXT..." % (kind, "DURATION" if kind == "in" else "WHEN"))
        when = (parse_in if kind == "in" else parse_at)(words[0], t)
        return {"kind": "at", "at": when, "text": " ".join(words[1:])}
    if kind == "under":
        try:
            pct = float(words.pop(0).rstrip("%")) if words else None
        except ValueError:
            pct = None
        if pct is None or not 0 < pct <= 100:
            raise SystemExit("remind: usage: add under PCT [--account A] [TEXT...] (PCT 1-100)")
    cs, name = account_or_exit(args.account)
    data = usage_cache(cs, name)
    text = " ".join(words)
    if data is None:
        raise SystemExit("remind: no usage cached for '%s' yet; switch's statusline records it "
                         "once that account has used Claude" % name)
    if kind == "under":
        cur = cs.effective_usage(data, t)[0]
        if cur < pct:
            raise SystemExit("remind: %s is already under %g%% (%d%%)" % (name, pct, int(cur)))
        return {"kind": "under", "account": name, "pct": pct, "text": text}
    key, label = WINDOW[kind]
    w = data.get(key) if isinstance(data.get(key), dict) else {}
    resets = w.get("resets_at")
    if not cs._num(resets):
        raise SystemExit("remind: no %s reset time cached for '%s'" % (label, name))
    if resets <= t:
        raise SystemExit("remind: %s's cached %s window already reset at %s; no newer one seen yet"
                         % (name, label, fmt(resets, t)))
    return {"kind": kind, "account": name, "at": float(resets), "text": text}


def is_due(r, t, cs=None):
    if r.get("done"):
        return False
    if r["kind"] == "under":
        if cs is None:
            return False
        data = usage_cache(cs, r["account"])
        return data is not None and cs.effective_usage(data, t)[0] < r["pct"]
    return isinstance(r.get("at"), (int, float)) and r["at"] <= t


def deliver(t=None):
    """Due reminders as one message, each marked done so it shows once;
    None when nothing is due. The cheap path (nothing due) takes no lock
    and writes nothing."""
    t = now() if t is None else t
    pending = [r for r in read_store()["reminders"] if not r.get("done")]
    cs = None
    if any(r["kind"] == "under" for r in pending):
        try:
            cs = switch_module()
        except Exception as e:  # a broken switch copy must not hold back timed reminders
            print("remind: switch: %s" % e, file=sys.stderr)
    if not any(is_due(r, t, cs) for r in pending):
        return None
    with locked():
        data = read_store()  # re-read: another session may have delivered them
        due = [r for r in data["reminders"] if is_due(r, t, cs)]
        for r in due:
            r["done"] = t
        if due:
            write_store(data, t)
    lines = []
    for r in due:
        when = " (due %s)" % fmt(r["at"], t) if r.get("at") and t - r["at"] > 120 else ""
        lines.append("Reminder %d%s: %s" % (r["id"], when, describe(r)))
    return "\n".join(lines) or None


# ---------------------------------------------------------------- OS notification

def task_name(rid):
    return "%s%d" % (os.environ.get("CLAUDE_REMIND_TASK_PREFIX") or "claude-remind-", rid)


def _ps_str(s):
    return "'%s'" % s.replace("'", "''")


def toast_script(body):
    """PowerShell 5.1: a toast under PowerShell's own AppId (no app
    registration needed), else `msg *`."""
    xml = ('<toast><visual><binding template="ToastGeneric"><text>%s</text><text>%s</text>'
           '</binding></visual></toast>') % (escape(TITLE), escape(body))
    return "\n".join([
        "try {",
        "  $null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]",
        "  $null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]",
        "  $x = New-Object Windows.Data.Xml.Dom.XmlDocument",
        "  $x.LoadXml(%s)" % _ps_str(xml),
        "  $app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'",
        "  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show("
        "[Windows.UI.Notifications.ToastNotification]::new($x))",
        "} catch {",
        "  & msg.exe '*' %s" % _ps_str("%s: %s" % (TITLE, body)),
        "}",
    ])


def task_xml(r):
    start = datetime.datetime.fromtimestamp(int(r["at"]))
    ps = (os.environ.get("SystemRoot") or r"C:\Windows") + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
    enc = base64.b64encode(toast_script(describe(r)).encode("utf-16-le")).decode("ascii")
    args = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand " + enc
    iso = "%Y-%m-%dT%H:%M:%S"
    # StartBoundary in ISO local time: no locale-dependent schtasks /SD dates. Missed (asleep)
    # runs start when available for a day; the task then deletes itself.
    return """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>%s</Description></RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>%s</StartBoundary>
      <EndBoundary>%s</EndBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <DeleteExpiredTaskAfter>PT0S</DeleteExpiredTaskAfter>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>%s</Command><Arguments>%s</Arguments></Exec></Actions>
</Task>
""" % (escape("%s %d" % (TITLE, r["id"])), start.strftime(iso),
       (start + datetime.timedelta(days=1)).strftime(iso), escape(ps), escape(args))


def notify_command(r, plat):
    """Shell line an `at` job runs to notify, or None when there is no notifier."""
    body = describe(r)
    if plat == "darwin":
        q = lambda s: '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
        return "osascript -e %s" % shlex.quote("display notification %s with title %s" % (q(body), q(TITLE)))
    if shutil.which("notify-send"):
        env = "".join("%s=%s " % (k, shlex.quote(os.environ[k]))
                      for k in ("DISPLAY", "DBUS_SESSION_BUS_ADDRESS") if os.environ.get(k))
        return "%snotify-send %s %s" % (env, shlex.quote(TITLE), shlex.quote(body))
    return None


def _run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, errors="replace", **kw)


def schedule(r, plat=None):
    """Book the OS notification for a timed reminder. (handle or None, note)."""
    plat = plat or sys.platform
    if plat == "win32":
        name = task_name(r["id"])
        fd, xml = tempfile.mkstemp(suffix=".xml", prefix="remind-")
        os.close(fd)
        try:
            Path(xml).write_text(task_xml(r), encoding="utf-16")
            p = _run(["schtasks", "/Create", "/TN", name, "/XML", xml, "/F"])
        except OSError as e:
            return None, "no toast (%s); in-session only" % e
        finally:
            with contextlib.suppress(OSError):
                os.remove(xml)
        if p.returncode:
            return None, "no toast (schtasks: %s); in-session only" % (p.stderr or p.stdout).strip()
        return {"task": name}, "toast at %s (scheduled task %s)" % (fmt(r["at"]), name)
    if not shutil.which("at"):
        return None, "no `at` command here: in-session only"
    cmd = notify_command(r, plat)
    if not cmd:
        return None, "no notify-send here: in-session only"
    stamp = datetime.datetime.fromtimestamp(int(r["at"])).strftime("%Y%m%d%H%M.%S")
    try:
        p = _run(["at", "-t", stamp], input=cmd + "\n")
    except OSError as e:
        return None, "no notification (%s); in-session only" % e
    m = re.search(r"job\s+(\d+)", p.stderr + p.stdout)
    if p.returncode or not m:
        return None, "no notification (at: %s); in-session only" % (p.stderr or p.stdout).strip()
    return {"at_job": m.group(1)}, "notification at %s (at job %s)" % (fmt(r["at"]), m.group(1))


def unschedule(handle):
    """Remove a booked notification; one already gone (fired and deleted) is fine."""
    if not handle:
        return None
    try:
        if "task" in handle:
            p = _run(["schtasks", "/Delete", "/TN", handle["task"], "/F"])
        else:
            p = _run(["atrm", handle["at_job"]])
    except OSError as e:
        return "could not remove the notification (%s)" % e
    return None if p.returncode == 0 else "notification was already gone"


# ---------------------------------------------------------------- commands

def cmd_add(args):
    t = now()
    r = make(args.kind, args, t)
    with locked():
        data = read_store(strict=True)
        r = dict({"id": data["next"], "created": t}, **r)
        data["next"] += 1
        data["reminders"].append(r)
        write_store(data, t)
    if r["kind"] == "under":
        note = "in-session only (no fixed time)"
    else:
        handle, note = schedule(r)
        if handle:
            with locked():
                data = read_store()
                for x in data["reminders"]:
                    if x["id"] == r["id"]:
                        x["notify"] = handle
                write_store(data, t)
    install_copy()
    when = "" if r["kind"] == "under" else " at %s" % fmt(r["at"], t)
    print("reminder %d%s: %s" % (r["id"], when, describe(r)))
    print("  %s" % note)
    print("  in-session: %s" % hook_status())
    return 0


def hook_status():
    sw = switch_home() / "claude_switch.py"
    if (switch_home() / "accounts.json").is_file() and sw.is_file():
        try:
            if "remind.py" in sw.read_text(encoding="utf-8", errors="replace"):
                return "next prompt after it's due, any account (switch's hook)"
        except OSError:
            pass
        return "switch's hook predates remind: rerun switch setup once to refresh it"
    return "add this UserPromptSubmit hook command once (README): %s" % hook_line()


def hook_line():
    """Absolute interpreter (Windows `python3` may be the Store stub) and the
    stable copy, forward slashes so Git Bash and PowerShell both run it."""
    parts = [str(p).replace("\\", "/") for p in (sys.executable, home() / "remind.py")]
    return " ".join('"%s"' % p if " " in p else p for p in parts) + " hook"


def cmd_list(args):
    t = now()
    pending = [r for r in read_store()["reminders"] if not r.get("done")]
    if not pending:
        print("no reminders")
        return 0
    for r in pending:
        when = "when it happens" if r["kind"] == "under" else fmt(r["at"], t)
        how = "in-session only" if not r.get("notify") else "+ notification"
        print("%3d  %-16s %s  (%s)" % (r["id"], when, describe(r), how))
    return 0


def cmd_cancel(args):
    with locked():
        data = read_store(strict=True)
        r = next((x for x in data["reminders"] if x["id"] == args.id), None)
        if r is None:
            raise SystemExit("remind: no reminder %d (see: list)" % args.id)
        data["reminders"].remove(r)
        write_store(data, now())
    note = unschedule(r.get("notify"))  # a fired task lingers until it expires: remove it too
    if r.get("done"):
        note = None
    print("cancelled %d: %s%s" % (r["id"], describe(r), "; " + note if note else ""))
    return 0


def cmd_hook():
    """Standalone UserPromptSubmit hook (switch's hook calls deliver() itself).
    Never fails the prompt."""
    try:
        sys.stdin.buffer.read()
        msg = deliver()
        if msg:
            print(json.dumps({"systemMessage": msg}))
    except Exception as e:  # a broken hook must never block the user's prompt
        print("remind hook: %s" % e, file=sys.stderr)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):  # cp1252 console + non-ASCII text: no crash
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    if argv[:1] == ["hook"]:
        return cmd_hook()
    p = argparse.ArgumentParser(prog="remind.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="new reminder: reset|weekly|under|in|at")
    a.add_argument("kind", choices=KINDS)
    a.add_argument("--account", help="switch account (default: this session's)")
    a.add_argument("words", nargs="*", help="PCT / DURATION / WHEN, then the text")
    sub.add_parser("list", help="pending reminders")
    c = sub.add_parser("cancel", help="delete a reminder and its notification")
    c.add_argument("id", type=int)
    sub.add_parser("hook", help="UserPromptSubmit hook: due reminders as a systemMessage")
    args = p.parse_args(argv)
    if args.cmd == "add" and args.account and not NAME_RE.match(args.account):
        raise SystemExit("remind: bad account name %r" % args.account)
    return {"add": cmd_add, "list": cmd_list, "cancel": cmd_cancel}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
