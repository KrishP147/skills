#!/usr/bin/env python3
"""Run several Claude Code accounts (one CLAUDE_CONFIG_DIR each) and move a
live conversation between them. Stdlib only.

  run [name|-] [claude args]   launcher loop; '-' or no name = most recent
  request [name] --session ID  ask the launcher this session runs under to switch
  setup [--account NAME=DIR ...] [--profile SHELL=PATH ...] [--yes]
                               register accounts, write shell wrappers
  add NAME [--dir DIR]         new account sharing the first one's items
  remove NAME [--delete-dir] [--yes] [--dry-run]
  rename OLD NEW | list | migrate

Registry: $CLAUDE_SWITCH_HOME (default ~/.claude-switch)/accounts.json.
Env for tests: CLAUDE_SWITCH_HOME, CLAUDE_SWITCH_CLAUDE (claude binary: a
path, or a JSON list of argv), CLAUDE_SWITCH_RESUME_FAIL_SECS.
"""
import argparse
import datetime
import difflib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

WINDOWS = os.name == "nt"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
COLOURS = ["cyan", "magenta", "yellow", "green", "blue", "red"]
ANSI = {"red": 31, "green": 32, "yellow": 33, "blue": 34, "magenta": 35, "cyan": 36}
BEGIN = "# >>> claude-switch >>>"
END = "# <<< claude-switch <<<"
SHIM_MARK = "claude-switch-shim"
POLL_SECS = 0.2
SHELLS = ("bash", "zsh", "fish", "powershell", "pwsh", "cmd")


# ---------------------------------------------------------------- registry

def switch_home():
    return Path(os.environ.get("CLAUDE_SWITCH_HOME") or (Path.home() / ".claude-switch"))


def ensure_home():
    """Create the registry dir. Old prior art used a plain FILE at this path:
    move it aside instead of crashing."""
    h = switch_home()
    if h.exists() and not h.is_dir():
        aside = h.with_name(h.name + ".stale-%d" % int(time.time()))
        os.replace(h, aside)
        print("claude-switch: moved old file %s to %s" % (h, aside), file=sys.stderr)
    (h / "requests").mkdir(parents=True, exist_ok=True)
    return h


def _retry(fn, tries=50):
    # Windows: os.replace / open fail while another process holds the file.
    for i in range(tries):
        try:
            return fn()
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.02)


def atomic_write(path, text, bom=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("%s.%d.tmp" % (path.name, os.getpid()))
    with open(tmp, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        f.write(text)
    _retry(lambda: os.replace(tmp, path))


def registry_path():
    return switch_home() / "accounts.json"


def load():
    p = registry_path()
    if not p.is_file():
        return {"accounts": []}
    data = _retry(lambda: json.loads(p.read_text(encoding="utf-8")))
    data.setdefault("accounts", [])
    return data


def save(reg):
    ensure_home()
    atomic_write(registry_path(), json.dumps(reg, indent=2) + "\n")


def find(reg, name):
    return next((a for a in reg["accounts"] if a["name"] == name), None)


def most_recent(reg, exclude=None):
    cands = [a for a in reg["accounts"] if a["name"] != exclude]
    if not cands:
        return None
    # max keeps the first of equal keys: never-used accounts fall back to registration order
    return max(cands, key=lambda a: a.get("last_used") or "")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def touch(name):
    reg = load()
    a = find(reg, name)
    if a:
        a["last_used"] = now_iso()
        save(reg)


def upsert(reg, name, d):
    if not NAME_RE.match(name):
        raise SystemExit("claude-switch: bad account name %r (use a-z, 0-9, -, _)" % name)
    d = str(Path(os.path.expanduser(d)).absolute())
    a = find(reg, name)
    if a:
        a["dir"] = d
        return a
    used = {x.get("colour") for x in reg["accounts"]}
    colour = next((c for c in COLOURS if c not in used), COLOURS[len(reg["accounts"]) % len(COLOURS)])
    a = {"name": name, "dir": d, "colour": colour, "theme": None, "last_used": None}
    reg["accounts"].append(a)
    return a


def is_default_dir(d):
    try:
        return Path(d).resolve() == (Path.home() / ".claude").resolve()
    except OSError:
        return False


def paint(acct, text):
    code = ANSI.get(acct.get("colour") or "")
    if not code or not sys.stderr.isatty():
        return text
    return "\x1b[1;%dm%s\x1b[0m" % (code, text)


# ---------------------------------------------------------------- request

def resolve_target(reg, name, current, previous):
    """Returns (account, None) or (None, message). D421: no name = this
    launcher's own previous account, else the most recent other than current."""
    names = ", ".join(a["name"] + (" (current)" if a["name"] == current else "") for a in reg["accounts"])
    if name:
        a = find(reg, name)
        if not a:
            return None, "unknown account '%s'. accounts: %s" % (name, names or "none")
        if name == current:
            return None, "already on '%s'; nothing to do" % name
        return a, None
    if previous and previous != current and find(reg, previous):
        return find(reg, previous), None
    a = most_recent(reg, exclude=current)
    if not a:
        return None, "no other account registered. accounts: %s" % (names or "none")
    return a, None


def setup_steps():
    return (
        "this session was not started by the claude-switch launcher, so it can't switch.\n"
        "set up once, then start Claude with `claude` or `claude-<name>` from a new shell:\n"
        '  "%s" "%s" setup --account main=~/.claude --account <name>=<config dir>'
        % (sys.executable, Path(__file__).resolve())
    )


def cmd_request(args):
    launcher = os.environ.get("CLAUDE_SWITCH_LAUNCHER")
    if not launcher:
        print(setup_steps())
        return 2
    reg = load()
    current = os.environ.get("CLAUDE_SWITCH_ACCOUNT")
    target, msg = resolve_target(reg, args.name, current, os.environ.get("CLAUDE_SWITCH_PREVIOUS"))
    if not target:
        print(msg)
        return 0 if args.name and args.name == current else 1
    ensure_home()
    atomic_write(switch_home() / "requests" / ("%s.json" % launcher),
                 json.dumps({"target": target["name"], "session": args.session or ""}))
    print("switching to '%s': this session ends now and resumes there." % target["name"])
    return 0


# ---------------------------------------------------------------- launcher

def find_claude():
    override = os.environ.get("CLAUDE_SWITCH_CLAUDE")
    if override:
        return json.loads(override) if override.lstrip().startswith("[") else [override]
    skip = {os.path.normcase(os.path.abspath(str(switch_home() / "bin")))}
    exts = os.environ.get("PATHEXT", ".EXE;.CMD;.BAT").split(";") if WINDOWS else [""]
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d or os.path.normcase(os.path.abspath(d)) in skip:
            continue
        for ext in exts:
            p = os.path.join(d, "claude" + ext.lower())
            if not os.path.isfile(p) or not os.access(p, os.X_OK):
                continue
            try:
                with open(p, "rb") as f:
                    if SHIM_MARK.encode() in f.read(4096):
                        continue  # our own wrapper: never recurse
            except OSError:
                continue
            return [p]
    raise SystemExit("claude-switch: no `claude` binary on PATH (outside %s)" % (switch_home() / "bin"))


class Terminal:
    """Saves the terminal state at start; restore() puts it back after a
    killed child left raw mode / the alt screen on."""
    RESET = "\x1b[?1049l\x1b[?2004l\x1b[?1000l\x1b[?1006l\x1b[?1004l\x1b[?25h\x1b[0m\r\n"

    def __init__(self):
        self.attrs = None
        self.modes = {}
        if WINDOWS:
            self._win_save()
        elif sys.stdin.isatty():
            import termios
            try:
                self.attrs = termios.tcgetattr(sys.stdin.fileno())
            except termios.error:
                pass

    def _win_save(self):
        import ctypes
        from ctypes import wintypes
        try:
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.GetStdHandle.restype = wintypes.HANDLE
            self.k = k
            for n in (-10, -11):  # STD_INPUT_HANDLE, STD_OUTPUT_HANDLE
                h = k.GetStdHandle(n)
                mode = wintypes.DWORD()
                if h and k.GetConsoleMode(wintypes.HANDLE(h), ctypes.byref(mode)):
                    self.modes[n] = (h, mode.value)
        except (OSError, AttributeError):
            self.modes = {}

    def restore(self):
        if WINDOWS:
            if not self.modes:
                if sys.stdin.isatty() and shutil.which("stty"):  # mintty / Git Bash pty
                    subprocess.run(["stty", "sane"], stderr=subprocess.DEVNULL)
                return
            from ctypes import wintypes
            if -11 in self.modes:  # VT on, so the resets are understood, not printed
                h, m = self.modes[-11]
                self.k.SetConsoleMode(wintypes.HANDLE(h), m | 0x0004)
                sys.stdout.write(self.RESET)
                sys.stdout.flush()
            for h, m in self.modes.values():
                self.k.SetConsoleMode(wintypes.HANDLE(h), m)
            return
        if self.attrs is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.attrs)
        if sys.stdout.isatty():
            sys.stdout.write(self.RESET)
            sys.stdout.flush()


def end_child(child):
    if child.poll() is not None:
        return
    if WINDOWS:
        # claude.exe leaves MCP server grandchildren: kill the whole tree
        subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()


def read_request(path):
    try:
        req = json.loads(_retry(lambda: path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        req = None
    try:
        os.remove(path)
    except OSError:
        pass
    return req if isinstance(req, dict) and req.get("target") else None


def child_env(acct, previous):
    env = dict(os.environ)
    if is_default_dir(acct["dir"]):
        env.pop("CLAUDE_CONFIG_DIR", None)  # default dir: keep ~/.claude.json where claude expects it
    else:
        env["CLAUDE_CONFIG_DIR"] = acct["dir"]
    env["CLAUDE_SWITCH_LAUNCHER"] = str(os.getpid())
    env["CLAUDE_SWITCH_PYTHON"] = sys.executable
    env["CLAUDE_SWITCH_ACCOUNT"] = acct["name"]
    env.pop("CLAUDE_SWITCH_PREVIOUS", None)
    if previous:
        env["CLAUDE_SWITCH_PREVIOUS"] = previous
    return env


def cmd_run(argv):
    reg = load()
    if not reg["accounts"]:
        print(setup_steps(), file=sys.stderr)
        return 2
    if argv and not argv[0].startswith("-"):  # wrappers pass '-' or a name first
        name, args = argv[0], list(argv[1:])
        if not find(reg, name):
            print("claude-switch: unknown account '%s'. accounts: %s"
                  % (name, ", ".join(a["name"] for a in reg["accounts"])), file=sys.stderr)
            return 2
    else:
        name, args = "-", list(argv[1:] if argv[:1] == ["-"] else argv)
    acct = most_recent(reg) if name == "-" else find(reg, name)
    claude = find_claude()
    req_path = ensure_home() / "requests" / ("%d.json" % os.getpid())
    if req_path.exists():
        os.remove(req_path)
    term = Terminal()
    fail_secs = float(os.environ.get("CLAUDE_SWITCH_RESUME_FAIL_SECS", "10"))
    previous = None
    resuming = False
    old = signal.signal(signal.SIGINT, lambda *_: None)  # a function, not SIG_IGN: exec resets it for the child
    try:
        while True:
            touch(acct["name"])
            started = time.monotonic()
            try:
                child = subprocess.Popen(claude + args, env=child_env(acct, previous))
            except OSError as e:
                print("claude-switch: can't start %s: %s" % (claude, e), file=sys.stderr)
                return 127
            req = None
            while child.poll() is None:
                if req_path.exists():
                    req = read_request(req_path)
                    if req:
                        end_child(child)
                        break
                time.sleep(POLL_SECS)
            if req is None and req_path.exists():  # wrote a request, then exited by itself
                req = read_request(req_path)
            rc = child.returncode
            if req is None:
                if resuming and rc != 0 and time.monotonic() - started < fail_secs:
                    print("claude-switch: --resume failed on '%s'; continuing its latest conversation instead"
                          % acct["name"], file=sys.stderr)
                    args, resuming = ["--continue"], False
                    continue
                return rc
            target = find(load(), req["target"])
            if not target:
                print("claude-switch: unknown account '%s'; exiting" % req["target"], file=sys.stderr)
                return 1
            term.restore()
            sid = str(req.get("session") or "")
            previous, acct = acct["name"], target
            args = ["--resume", sid] if UUID_RE.match(sid) else ["--continue"]
            resuming = args[0] == "--resume"
            print(paint(acct, ">> claude-switch: %s -> %s" % (previous, acct["name"])), file=sys.stderr)
    finally:
        signal.signal(signal.SIGINT, old)


# ---------------------------------------------------------------- setup

def documents_dir():
    if WINDOWS:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:  # CSIDL_PERSONAL
                return Path(buf.value)
        except (OSError, AttributeError):
            pass
    return Path.home() / "Documents"


def default_targets():
    h = Path.home()
    t = {}
    if (h / ".bashrc").exists() or shutil.which("bash"):
        t["bash"] = h / ".bashrc"
    if (h / ".zshrc").exists() or shutil.which("zsh"):
        t["zsh"] = h / ".zshrc"
    if shutil.which("fish") or (h / ".config" / "fish").is_dir():
        t["fish"] = h / ".config" / "fish" / "conf.d" / "claude-switch.fish"
    if WINDOWS:
        docs = documents_dir()
        t["powershell"] = docs / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1"
        t["pwsh"] = docs / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
        t["cmd"] = switch_home() / "bin"
    elif shutil.which("pwsh"):
        t["pwsh"] = h / ".config" / "powershell" / "Microsoft.PowerShell_profile.ps1"
    return t


def _sh_path(p):
    return Path(p).as_posix() if WINDOWS else str(p)


def wrappers(shell, names, py, script):
    """Lines of one shell's block (or, for cmd, {filename: text})."""
    entries = [("claude", "-")] + [("claude-" + n, n) for n in names]
    if shell in ("bash", "zsh"):
        q = lambda s: "'" + s.replace("'", "'\\''") + "'"
        return ["%s() { %s %s run %s \"$@\"; }" % (f, q(_sh_path(py)), q(_sh_path(script)), a) for f, a in entries]
    if shell == "fish":
        q = lambda s: "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"
        return ["function %s; command %s %s run %s $argv; end" % (f, q(_sh_path(py)), q(_sh_path(script)), a)
                for f, a in entries]
    if shell in ("powershell", "pwsh"):
        q = lambda s: "'" + s.replace("'", "''") + "'"
        return ["function %s { & %s %s run '%s' @args }" % (f, q(str(py)), q(str(script)), a)
                for f, a in entries]
    if shell == "cmd":
        return {f + ".cmd": "@echo off\r\nrem %s: generated by claude_switch.py setup\r\n\"%s\" \"%s\" run %s %%*\r\n"
                % (SHIM_MARK, py, script, a) for f, a in entries}
    raise ValueError(shell)


def replace_block(old, lines):
    """Insert or replace our marker block; everything else is left as is."""
    nl = "\r\n" if "\r\n" in old else "\n"
    block = nl.join([BEGIN, "# generated by claude_switch.py setup; rerun setup instead of editing"] + lines + [END]) + nl
    pat = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"[ \t]*(\r?\n)?", re.S)
    if pat.search(old):
        return pat.sub(lambda _: block, old, count=1)
    if old and not old.endswith(("\n", "\r")):
        old += nl
    return old + (nl if old else "") + block


def read_text(p):
    """(text, had_bom); missing file = ('', False)."""
    try:
        raw = Path(p).read_bytes()
    except FileNotFoundError:
        return "", False
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        return raw.decode("utf-8-sig"), bom
    except UnicodeDecodeError:
        raise SystemExit("claude-switch: %s is not UTF-8; save it as UTF-8 and rerun setup" % p)


def plan_setup(reg, targets, py, script):
    """[(path, old_text, new_text_or_None, bom)]; None = delete."""
    names = [a["name"] for a in reg["accounts"]]
    out = []
    old, bom = read_text(registry_path())
    new = json.dumps(reg, indent=2) + "\n"
    if old != new:
        out.append((registry_path(), old, new, False))
    for shell, path in targets.items():
        if shell == "cmd":
            files = wrappers("cmd", names, py, script)
            d = Path(path)
            existing = sorted(d.glob("claude*.cmd")) if d.is_dir() else []
            for p in existing:
                text, _ = read_text(p)
                if SHIM_MARK in text and p.name not in files:
                    out.append((p, text, None, False))
            for fname, text in files.items():
                cur, _ = read_text(d / fname)
                if cur != text:
                    out.append((d / fname, cur, text, False))
            continue
        cur, bom = read_text(path)
        new = replace_block(cur, wrappers(shell, names, py, script))
        if shell in ("powershell", "pwsh") and not Path(path).exists():
            bom = True  # PowerShell 5.1 reads BOM-less files as ANSI
        if cur != new:
            out.append((Path(path), cur, new, bom))
    return out


def cmd_setup(args):
    ensure_home()
    reg = load()
    for spec in args.account or []:
        name, sep, d = spec.partition("=")
        if not sep or not d:
            raise SystemExit("claude-switch: --account wants NAME=DIR, got %r" % spec)
        upsert(reg, name.strip(), d.strip())
    if not reg["accounts"]:
        upsert(reg, "main", str(Path.home() / ".claude"))  # D418
    if args.profile:
        targets = {}
        for spec in args.profile:
            shell, sep, p = spec.partition("=")
            if shell not in SHELLS or not p:
                raise SystemExit("claude-switch: --profile wants SHELL=PATH, SHELL one of %s" % ", ".join(SHELLS))
            targets[shell] = Path(os.path.expanduser(p)).absolute()
    else:
        targets = default_targets()
    # remembered, so add/remove/rename/migrate regenerate the same files
    reg["profiles"] = dict(reg.get("profiles") or {}, **{k: str(v) for k, v in targets.items()})
    plan = plan_setup(reg, targets, sys.executable, Path(__file__).resolve())
    for a in reg["accounts"]:
        if not Path(a["dir"]).is_dir():
            print("note: %s does not exist yet; claude creates it on first login as '%s'" % (a["dir"], a["name"]))
    if not plan:
        print("claude-switch: everything is up to date")
        return 0
    for path, old, new, _ in plan:
        sys.stdout.writelines(difflib.unified_diff(
            old.replace("\r\n", "\n").splitlines(True), (new or "").replace("\r\n", "\n").splitlines(True),
            str(path) if old else "/dev/null", str(path) if new is not None else "/dev/null"))
        if old and not old.endswith("\n"):
            sys.stdout.write("\n")
    if not args.yes:
        try:
            ans = input("Write these changes? [y/N] ")
        except EOFError:
            ans = ""
        if ans.strip().lower() not in ("y", "yes"):
            print("nothing written")
            return 1
    for path, _, new, bom in plan:
        if new is None:
            os.remove(path)
        else:
            atomic_write(path, new, bom=bom)
    print("written. open a new shell, then `claude` (most recent account) or `claude-<name>`.")
    if "cmd" in targets:
        print("cmd: put %s first on PATH so its claude.cmd shims are found" % targets["cmd"])
    return 0


def regen_shells(reg):
    """Save the registry, then rewrite our block in the shell files setup
    recorded (default_targets() when none). No prompt: only the marker
    block changes. Prints each changed path."""
    save(reg)
    targets = {k: Path(v) for k, v in (reg.get("profiles") or {}).items()}
    if not targets:
        targets = default_targets()
        reg["profiles"] = {k: str(v) for k, v in targets.items()}
        save(reg)
    try:
        plan = plan_setup(reg, targets, sys.executable, Path(__file__).resolve())
    except SystemExit as e:
        print("warning: shell files not updated (%s); fix it and rerun setup" % e)
        return
    for path, _, new, bom in plan:
        if new is None:
            os.remove(path)
        else:
            atomic_write(path, new, bom=bom)
        if path != registry_path():
            print("updated %s" % path)


# ---------------------------------------------------------------- accounts

SHARED_DIRS = ("skills", "agents", "commands", "plugins", "projects")
SHARED_FILES = ("settings.json", "CLAUDE.md")  # .credentials.json, .claude.json stay per account


def is_link(p):
    """Symlink or junction, never followed. Before Python 3.12,
    is_symlink() is False for a junction: check the reparse-point bit."""
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT) if WINDOWS else False


def _same(a, b):
    return os.path.normcase(os.path.realpath(str(a))) == os.path.normcase(os.path.realpath(str(b)))


def _norm(p):
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(p))))


def link_dir(src, dst):
    if WINDOWS:
        import _winapi
        _winapi.CreateJunction(str(src), str(dst))  # no admin or Developer Mode needed
    else:
        os.symlink(str(src), str(dst), target_is_directory=True)


def link_file(src, dst):
    """Symlink; Windows without Developer Mode: hardlink, else copy.
    Returns a warning, or None for a symlink."""
    try:
        os.symlink(str(src), str(dst))
        return None
    except OSError:
        if not WINDOWS:
            raise
    try:
        os.link(str(src), str(dst))
        return ("hardlinked (no symlink rights; turn on Developer Mode for symlinks): "
                "Claude rewrites settings.json atomically, which splits it off into a separate copy")
    except OSError:
        shutil.copy2(str(src), str(dst))
        return "copied (no symlink or hardlink possible): later edits are not shared"


def link_shared(src_dir, dst_dir):
    for name in SHARED_DIRS + SHARED_FILES:
        src, dst = Path(src_dir) / name, Path(dst_dir) / name
        if os.path.lexists(str(dst)):
            if is_link(dst) and _same(dst, src):
                print("already linked: %s" % dst)
            else:
                print("warning: %s already exists; left as is (not shared)" % dst)
            continue
        if name in SHARED_DIRS:
            if not src.exists():
                src.mkdir(parents=True)
                print("created empty %s to share" % src)
            link_dir(src, dst)
            print("linked %s -> %s" % (dst, src))
            continue
        if not src.is_file():
            print("note: %s missing; not shared" % src)
            continue
        warn = link_file(src, dst)
        print(("warning: %s %s" % (dst, warn)) if warn else "linked %s -> %s" % (dst, src))


def _account_or_exit(reg, name):
    a = find(reg, name)
    if not a:
        raise SystemExit("claude-switch: unknown account '%s'. accounts: %s"
                         % (name, ", ".join(x["name"] for x in reg["accounts"]) or "none"))
    return a


def _check_new_name(reg, name):
    if not NAME_RE.match(name):
        raise SystemExit("claude-switch: bad account name %r (use a-z, 0-9, -, _)" % name)
    if find(reg, name):
        raise SystemExit("claude-switch: account '%s' already exists" % name)


def cmd_add(args):
    reg = load()
    _check_new_name(reg, args.name)
    if not reg["accounts"]:
        raise SystemExit("claude-switch: no accounts yet; run setup or migrate first")
    d = Path(os.path.expanduser(args.dir) if args.dir else Path.home() / (".claude-" + args.name)).absolute()
    for a in reg["accounts"]:
        if _norm(a["dir"]) == _norm(d):
            raise SystemExit("claude-switch: %s is already account '%s'" % (d, a["name"]))
    first = reg["accounts"][0]
    d.mkdir(parents=True, exist_ok=True)
    link_shared(first["dir"], d)
    upsert(reg, args.name, str(d))
    regen_shells(reg)
    print("added '%s' (%s), sharing %s's items" % (args.name, d, first["name"]))
    launcher = os.environ.get("CLAUDE_SWITCH_LAUNCHER")
    if launcher:
        atomic_write(switch_home() / "requests" / ("%s.json" % launcher),
                     json.dumps({"target": args.name, "session": args.session or ""}))
        print("switching to '%s': this session ends now and resumes there; log in when Claude asks." % args.name)
    else:
        print("start it with claude-%s from a new shell; Claude asks you to log in." % args.name)
    return 0


def scan_tree(root):
    """(links, files, dirs) under root, never following a link; dirs
    parents first."""
    links, files, dirs = [], [], []
    stack = [str(root)]
    while stack:
        d = stack.pop()
        dirs.append(d)
        with os.scandir(d) as it:
            for e in it:
                if is_link(e.path):
                    links.append(e.path)
                elif e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                else:
                    files.append(e.path)
    return links, files, dirs


def unlink(p):
    """Remove a link or junction itself, never its target."""
    if WINDOWS and os.lstat(p).st_file_attributes & stat.FILE_ATTRIBUTE_DIRECTORY:
        os.rmdir(p)  # junction or directory symlink: removes only the reparse point
    else:
        os.unlink(p)


def _force_unlink(p):
    try:
        os.unlink(p)
    except PermissionError:
        os.chmod(p, stat.S_IWRITE)  # Windows read-only file
        os.unlink(p)


def delete_dir(root):
    """Unlink every link first, then delete what's left. Never rmtree."""
    if is_link(root):
        unlink(root)
        return
    for p in scan_tree(root)[0]:
        unlink(p)
    links, files, dirs = scan_tree(root)
    if links:  # appeared meanwhile: stop rather than risk a shared target
        raise SystemExit("claude-switch: new links under %s; nothing more deleted" % root)
    for p in files:
        _force_unlink(p)
    for d in reversed(dirs):
        os.rmdir(d)


def delete_refusal(reg, acct):
    d = _norm(acct["dir"])
    if d in (_norm(Path.home()), _norm(Path.home() / ".claude")) or d == os.path.dirname(d):
        return "%s is not a dir to delete" % acct["dir"]
    for other in [_norm(a["dir"]) for a in reg["accounts"] if a is not acct] + [_norm(switch_home())]:
        if other == d or other.startswith(d.rstrip(os.sep) + os.sep) or d.startswith(other.rstrip(os.sep) + os.sep):
            return "%s overlaps %s" % (acct["dir"], other)
    return None


def cmd_remove(args):
    reg = load()
    acct = _account_or_exit(reg, args.name)
    if args.name == os.environ.get("CLAUDE_SWITCH_ACCOUNT"):
        raise SystemExit("claude-switch: '%s' is the account you're on; switch away first" % args.name)
    if len(reg["accounts"]) == 1:
        raise SystemExit("claude-switch: '%s' is the last account; not removed" % args.name)
    if acct is reg["accounts"][0]:
        raise SystemExit("claude-switch: '%s' is the first account and the others link into its dir; "
                         "remove them first" % args.name)
    d = Path(acct["dir"])
    links, files, dirs = [], [], []
    print("plan for removing '%s':" % args.name)
    print("  unregister it and regenerate shell files")
    if not args.delete_dir:
        print("  keep %s (--delete-dir deletes it)" % d)
    elif not os.path.lexists(str(d)):
        print("  %s does not exist; nothing to delete" % d)
    else:
        why = delete_refusal(reg, acct)
        if why:
            raise SystemExit("claude-switch: won't delete: %s" % why)
        if is_link(d):
            links = [str(d)]
        else:
            links, files, dirs = scan_tree(d)
        for p in links:
            print("  unlink (shared; its target and content are kept): %s -> %s" % (p, os.path.realpath(p)))
        if dirs:
            print("  delete: %s (%d files, %d dirs, none shared)" % (d, len(files), len(dirs)))
    if args.dry_run:
        print("dry run: nothing changed")
        return 0
    if (links or dirs) and not args.yes:
        try:
            ans = input("Unlink and delete as above? [y/N] ")
        except EOFError:
            ans = ""
        if ans.strip().lower() not in ("y", "yes"):
            print("nothing changed")
            return 1
    reg["accounts"].remove(acct)
    regen_shells(reg)
    print("removed '%s'" % args.name)
    if links or dirs:
        delete_dir(d)
        print("deleted %s (%d links unlinked first)" % (d, len(links)))
    return 0


def cmd_rename(args):
    reg = load()
    acct = _account_or_exit(reg, args.old)
    _check_new_name(reg, args.new)
    acct["name"] = args.new
    regen_shells(reg)
    print("renamed '%s' to '%s'; dir %s not moved. new shells: claude-%s" % (args.old, args.new, acct["dir"], args.new))
    return 0


def cmd_list(args):
    reg = load()
    if not reg["accounts"]:
        print("no accounts; run setup or migrate")
        return 0
    current = os.environ.get("CLAUDE_SWITCH_ACCOUNT")
    tty = sys.stdout.isatty()
    width = max(len(a["name"]) for a in reg["accounts"])
    for a in reg["accounts"]:
        colour = a.get("colour") or "-"
        swatch = "\x1b[%dm  \x1b[0m " % (ANSI[colour] + 10) if tty and colour in ANSI else ""
        used = (a.get("last_used") or "")[:16].replace("T", " ")
        print("%s%-*s  %-7s  %s  last used %s%s" % (swatch, width, a["name"], colour, a["dir"],
                                                   used + " UTC" if used else "never",
                                                   "  (current)" if a["name"] == current else ""))
    return 0


def cmd_migrate(args):
    """Register ~/.claude and ~/.claude-<name> dirs. Only stats them: never
    writes inside an account dir."""
    reg = load()
    home = Path.home()
    known = {_norm(a["dir"]) for a in reg["accounts"]}
    found = []
    if (home / ".claude").is_dir() and _norm(home / ".claude") not in known:
        found.append(("main", home / ".claude"))
    for p in sorted(home.iterdir()):
        n = p.name
        if (not n.startswith(".claude-") or n == ".claude-switch" or ".stale-" in n
                or _norm(p) in known or _norm(p) == _norm(switch_home()) or not p.is_dir()):
            continue
        suffix = n[len(".claude-"):]
        if not NAME_RE.match(suffix):
            print("note: skipped %s: '%s' is not a valid account name" % (p, suffix))
            continue
        if not ((p / ".credentials.json").is_file() or (p / ".claude.json").is_file() or (p / "projects").is_dir()):
            print("note: skipped %s: no .credentials.json, .claude.json or projects/" % p)
            continue
        found.append((suffix, p))
    added = 0
    for name, p in found:
        if find(reg, name):
            print("note: skipped %s: '%s' is already %s" % (p, name, find(reg, name)["dir"]))
            continue
        upsert(reg, name, str(p))
        added += 1
        print("registered '%s' = %s" % (name, p))
    if not added:
        print("nothing new to register")
        return 0
    regen_shells(reg)
    return 0


# ---------------------------------------------------------------- main

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):  # cp1252 console + non-ASCII profile diff: no crash
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    if argv and argv[0] == "run":
        return cmd_run(argv[1:])
    p = argparse.ArgumentParser(prog="claude_switch.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="launcher loop: run [name|-] [claude args]")
    r = sub.add_parser("request", help="ask this session's launcher to switch")
    r.add_argument("name", nargs="?")
    r.add_argument("--session", default="")
    s = sub.add_parser("setup", help="register accounts and write shell wrappers")
    s.add_argument("--account", action="append", metavar="NAME=DIR")
    s.add_argument("--profile", action="append", metavar="SHELL=PATH",
                   help="write only these (%s; cmd takes the shim dir)" % ", ".join(SHELLS))
    s.add_argument("--yes", action="store_true", help="write without asking")
    ad = sub.add_parser("add", help="new account: config dir with shared items linked from the first")
    ad.add_argument("name")
    ad.add_argument("--dir", help="config dir (default ~/.claude-NAME)")
    ad.add_argument("--session", default="", help="session to resume on it when under the launcher")
    rm = sub.add_parser("remove", help="unregister an account; --delete-dir also deletes its dir")
    rm.add_argument("name")
    rm.add_argument("--delete-dir", action="store_true", help="unlink shared links first, then delete the rest")
    rm.add_argument("--yes", action="store_true", help="delete without asking")
    rm.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    rn = sub.add_parser("rename", help="rename an account (its dir is not moved)")
    rn.add_argument("old")
    rn.add_argument("new")
    sub.add_parser("list", help="accounts, colour, dir, last used")
    sub.add_parser("migrate", help="register ~/.claude and ~/.claude-* dirs; reads them only")
    a = p.parse_args(argv)
    return {"request": cmd_request, "setup": cmd_setup, "add": cmd_add, "remove": cmd_remove,
            "rename": cmd_rename, "list": cmd_list, "migrate": cmd_migrate}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
