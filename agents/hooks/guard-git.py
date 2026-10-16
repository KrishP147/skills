#!/usr/bin/env python3
"""PreToolUse hook (Bash/PowerShell matcher): blocks pushes/merges/deletes
that would touch protected branches or GitHub. Stdlib only, Python 3.8+.

Reads PreToolUse hook JSON from stdin (tool_input.command, cwd). Exits 2 with
a one-line reason on stderr to block; exits 0 to allow. Non-JSON input or a
tool other than Bash/PowerShell -> exit 0. An internal error while analysing a
command that mentions push/merge/delete -> exit 2 (fail closed).

It is a guardrail, not a sandbox: it parses the shell command the agent is
about to run (quote-aware, recursing into `bash -c`, `pwsh -Command`, `eval`,
`iex`, `& { }`, `$(...)`, each nested shell in its own POSIX/PowerShell mode)
but cannot see into script files or pre-existing shell aliases. Code it can't
read (`eval $c`, `& $sb`) fails closed when the command mentions push/merge/delete.
Pair it with GitHub branch protection.

Protected branches: env GUARD_PROTECTED_BRANCHES (comma list), default
"main,master".

`--plugin`: set by the plugin-level hook (.claude-plugin/plugin.json), which
fires for every session, not just agents. Only enforces when stdin
`agent_type` is a guarded agent (implementer/manager, bare or
`<plugin>:`-namespaced); anything else, including the main session, exits 0.
"""
import base64
import json
import os
import re
import shlex
import subprocess
import sys
import time

MAX_DEPTH = 6
SUBST = "__GUARD_SUBST_%d__"
SUBST_RE = re.compile(r"__GUARD_SUBST_(\d+)__")
DYNAMIC = "__GUARD_DYNAMIC__"
UNKNOWN_BRANCH = "__GUARD_UNKNOWN_BRANCH__"  # current branch can't be read -> protected
RISKY_WORDS = re.compile(r"push|send-pack|merge|delete|gh\s+api|refs/heads", re.I)
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
REDIRECT_RE = re.compile(r"^\d*(>>?|<<<?|<<-?|<|>&|<&|&>>?|>\|)(.*)$")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "mksh", "ash"}
PWSH = {"pwsh", "powershell"}
KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "exec", "nohup", "command", "builtin"}
# Output idioms for "the current branch" - treated like HEAD in a refspec.
CURRENT_BRANCH_IDIOMS = (
    re.compile(r"^\s*git\s+branch\s+--show-current\s*$"),
    re.compile(r"^\s*git\s+rev-parse\s+--abbrev-ref\s+(HEAD|@)\s*$"),
    re.compile(r"^\s*git\s+symbolic-ref\s+(--short\s+HEAD|HEAD\s+--short)\s*$"),
)


# Keep in sync with the no-Python grep in .claude-plugin/plugin.json.
GUARDED_AGENTS = ("implementer", "manager")


def guarded_agent(agent_type):
    """True when a plugin-hook payload's agent_type is one guard-git guards."""
    if not isinstance(agent_type, str):
        return False
    return agent_type in GUARDED_AGENTS or any(agent_type.endswith(":" + a) for a in GUARDED_AGENTS)


class Block(Exception):
    pass


# git config keys whose value can silently redirect a push to another branch.
_REMOTE_PUSH_RE = re.compile(r"^remote\.[^.]+\.push$", re.I)
_REMOTE_MIRROR_RE = re.compile(r"^remote\.[^.]+\.mirror$", re.I)
_BRANCH_UPSTREAM_RE = re.compile(r"^branch\.[^.]+\.(merge|remote|pushremote)$", re.I)
_PUSH_DEFAULT_REDIRECTS = ("matching", "upstream", "tracking")
_TRUTHY = ("true", "yes", "on", "1", "")


def redirecting_config(key, value):
    """True if this git config key+value could push somewhere other than the
    branch named on the command line (so the refspec can't be trusted).
    `value` None means the value is unknown (from an env var) -> assume worst."""
    k = key.strip().lower()
    if k == "push.default":
        return value is None or value.strip().lower() in _PUSH_DEFAULT_REDIRECTS
    if _REMOTE_PUSH_RE.match(k) or _BRANCH_UPSTREAM_RE.match(k):
        return True
    if _REMOTE_MIRROR_RE.match(k):
        return value is None or value.strip().lower() in _TRUTHY
    return False


def protected_branches():
    raw = os.environ.get("GUARD_PROTECTED_BRANCHES", "main,master")
    return [b.strip() for b in raw.split(",") if b.strip()]


def git_current_branch(cwd):
    return _git_out(cwd, ["rev-parse", "--abbrev-ref", "HEAD"])


def git_alias(cwd, name):
    return _git_out(cwd, ["config", "--get", "alias." + name])


def _git_out(cwd, args):
    try:
        out = subprocess.run(["git"] + args, cwd=cwd or None, capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip() or None
    except Exception:
        pass
    return None


class Ctx:
    def __init__(self, protected, cwd=None, branch_lookup=git_current_branch, alias_lookup=git_alias,
                 powershell=False):
        self.protected = [p.lower() for p in protected]
        self.cwd = cwd
        self.branch_lookup = branch_lookup
        self.alias_lookup = alias_lookup
        self.powershell = powershell
        # current branch after an in-command `git checkout/switch <name>`; a
        # protected name (or UNKNOWN_BRANCH) makes a later bare push fail closed.
        self.branch_override = None
        # an in-command `git config`/`-c`/env set a push-redirecting key.
        self.push_config_tainted = False
        # the whole top-level command, for fail-closed checks on dynamic code
        self.top_cmd = ""

    def is_protected(self, name):
        return name.lower() in self.protected

    def block(self, reason):
        raise Block("Blocked: " + reason)

    def dynamic_exec(self, what):
        """`eval $c`, `iex $c`, `& $sb`: code we can't read. Fail closed when
        the command as a whole mentions push/merge/delete."""
        if RISKY_WORDS.search(self.top_cmd):
            self.block("%s runs code that can't be read, in a command mentioning "
                       "push/merge/delete; failing closed." % what)


# ---------------------------------------------------------------- splitting

HEREDOC_RE = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|\\?([^\s;&|<>()]+))")


def _heredoc_at(cmd, j):
    """If cmd[j:] starts a here-doc operator (`<<EOF`, `<<-'EOF'`, not `<<<`),
    return (delimiter, strip_tabs, index past the operator)."""
    if not cmd.startswith("<<", j) or cmd.startswith("<<<", j):
        return None
    m = HEREDOC_RE.match(cmd, j)
    if not m:
        return None
    delim = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
    return delim, m.group(1) == "-", m.end()


def _heredoc_body(cmd, j, delim, strip_tabs):
    """cmd[j] is the start of a body line; return (body, index past the
    delimiter line)."""
    lines, n = [], len(cmd)
    while j < n:
        k = cmd.find("\n", j)
        k = n if k == -1 else k
        line = cmd[j:k]
        j = k + 1
        if (line.lstrip("\t") if strip_tabs else line) == delim:
            break
        lines.append(line)
    return "\n".join(lines), min(j, n)


def _extract(cmd, i, closer):
    """cmd[i] is just past an opener; return (inner, index past closer)."""
    depth, q, j, n = 1, None, i, len(cmd)
    pending = []
    while j < n:
        c = cmd[j]
        if q is None and c == "\n" and pending:
            for delim, strip in pending:
                _, j = _heredoc_body(cmd, j + 1, delim, strip)
            pending = []
            continue
        if q is None and c == "<":
            hd = _heredoc_at(cmd, j)
            if hd:
                pending.append(hd[:2])
                j = hd[2]
                continue
        if q == "'":
            if c == "'":
                q = None
        elif c == "\\":
            j += 1
        elif q == '"':
            if c == '"':
                q = None
        elif c in "'\"":
            q = c
        elif closer == "`" and c == "`":
            return cmd[i:j], j + 1
        elif closer == ")" and c == "(":
            depth += 1
        elif closer == ")" and c == ")":
            depth -= 1
            if depth == 0:
                return cmd[i:j], j + 1
        j += 1
    return cmd[i:], n


def split_commands(cmd, ps=False):
    """Quote-aware split on newline ; & | && || ( ). Command and process
    substitutions are pulled out into `subs` and replaced by a placeholder.
    Unquoted `# ...` comments are dropped. Here-doc bodies are data, kept
    in `docs` keyed by segment index (a shell reading stdin runs them).
    Returns (segments, subs, docs). With `ps=True` the PowerShell escape rules
    apply: backtick (not backslash) is the escape/line-continuation char, and a
    bare backslash is a literal path separator, not an escape."""
    segs, subs, buf, docs, pending = [], [], [], {}, []
    q, i, n = None, 0, len(cmd)

    def flush():
        s = "".join(buf).strip()
        if s:
            segs.append(s)
        del buf[:]

    def subst(start, closer):
        inner, j = _extract(cmd, start, closer)
        subs.append(inner)
        buf.append(SUBST % (len(subs) - 1))
        return j

    while i < n:
        c = cmd[i]
        if q == "'":
            buf.append(c)
            if c == "'":
                q = None
            i += 1
            continue
        if ps and c == "`":  # PowerShell escape: `<newline> continues, `x -> x
            if i + 1 < n:
                if cmd[i + 1] == "\n":
                    i += 2
                    continue
                buf.append(cmd[i + 1])
                i += 2
                continue
            buf.append(c)
            i += 1
            continue
        if not ps and c == "\\" and i + 1 < n:
            if cmd[i + 1] == "\n":
                i += 2
                continue
            buf.append(cmd[i:i + 2])
            i += 2
            continue
        if c == "$" and cmd.startswith("$(", i):
            i = subst(i + 2, ")")
            continue
        if not ps and c == "`":
            i = subst(i + 1, "`")
            continue
        if q == '"':
            buf.append(c)
            if c == '"':
                q = None
            i += 1
            continue
        if c in "'\"":
            q = c
            buf.append(c)
            i += 1
            continue
        if c in "<>" and cmd.startswith("(", i + 1):
            i = subst(i + 2, ")")
            continue
        if c == "<":
            hd = _heredoc_at(cmd, i)
            if hd:
                pending.append(hd[:2])
                buf.append(" ")
                i = hd[2]
                continue
        if c == "\n" and pending:
            flush()
            for delim, strip in pending:
                body, i = _heredoc_body(cmd, i + 1, delim, strip)
                docs.setdefault(len(segs) - 1, []).append(body)
            pending = []
            continue
        if c == "#" and (not buf or buf[-1] in " \t"):
            while i < n and cmd[i] != "\n":
                i += 1
            continue
        if c == "&" and ((buf and buf[-1] in "<>") or cmd.startswith(">", i + 1)):
            buf.append(c)  # 2>&1, >&2, &>file
            i += 1
            continue
        if ps and _ps_call_op(cmd, i, buf):
            # PowerShell call operator `& x` / dot-source `. x`: keep it as the
            # head of its own segment; `& ("git") ...` -> the paren's value.
            flush()
            buf.append(c + " ")
            i += 1
            while i < n and cmd[i] in " \t":
                i += 1
            if i < n and cmd[i] == "(":
                inner, i = _extract(cmd, i + 1, ")")
                m = re.fullmatch(r"\s*(['\"]?)([^'\"\s;&|()`$+]+)\1\s*", inner)
                if m:  # `("git")`, `('git')`, `(git)`: a plain literal
                    buf.append(shlex.quote(m.group(2)) + " ")
                else:
                    subs.append(inner)
                    buf.append(SUBST % (len(subs) - 1) + " ")
            continue
        if c in "\n;&|()":
            flush()
            i += 1
            continue
        buf.append(c)
        i += 1
    flush()
    return segs, subs, docs


def _ps_call_op(cmd, i, buf):
    """cmd[i] is a PowerShell call operator: a lone `&` (not `&&`), or a `.`
    starting a command and followed by a space or `(`."""
    c = cmd[i]
    if c == "&":
        return not cmd.startswith("&", i + 1) and not (i > 0 and cmd[i - 1] == "&")
    return c == "." and not "".join(buf).strip() and cmd[i + 1:i + 2] in (" ", "\t", "(")


def tokenize(seg, ps=False):
    """shlex(posix) tokens with redirections dropped. None on parse failure.
    With `ps=True`, backslashes outside '...' are doubled so POSIX shlex keeps
    Windows paths (`C:\\x\\repo`) instead of eating the separators."""
    if not ps:  # bash drops the `\` of `\`` and `\$` inside "...", shlex keeps it
        out, q, i = [], None, 0
        while i < len(seg):
            c = seg[i]
            if c == "\\" and q != "'" and i + 1 < len(seg):
                out.append(seg[i + 1] if (q == '"' and seg[i + 1] in "`$") else seg[i:i + 2])
                i += 2
                continue
            if c == "'" and q != '"':
                q = None if q == "'" else "'"
            elif c == '"' and q != "'":
                q = None if q == '"' else '"'
            out.append(c)
            i += 1
        seg = "".join(out)
    else:  # double backslashes outside '...' (single-quoted text is literal)
        out, q = [], None
        for c in seg:
            if c == "'" and q != '"':
                q = None if q == "'" else "'"
            elif c == '"' and q != "'":
                q = None if q == '"' else '"'
            out.append("\\\\" if c == "\\" and q != "'" else c)
        seg = "".join(out)
    try:
        raw = shlex.split(seg, posix=True)
    except ValueError:
        return None
    toks, skip = [], False
    for t in raw:
        if skip:
            skip = False
            continue
        m = REDIRECT_RE.match(t)
        if m:
            skip = m.group(2) == ""
            continue
        toks.extend(brace_expand(t))
    return toks


BRACE_LIMIT = 64
SEQ_RE = re.compile(r"^(-?\d+|[A-Za-z])\.\.(-?\d+|[A-Za-z])(\.\.-?\d+)?$")


def _brace_alts(inner):
    """Alternatives of a `{...}` body, or None if bash would not expand it."""
    parts, depth, start = [], 0, 0
    for k, c in enumerate(inner):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(inner[start:k])
            start = k + 1
    if parts:
        return parts + [inner[start:]]
    m = SEQ_RE.match(inner)
    if not m:
        return None
    a, b = m.group(1), m.group(2)
    if a.lstrip("-").isdigit() and b.lstrip("-").isdigit():
        a, b = int(a), int(b)
        if abs(b - a) >= BRACE_LIMIT:
            return [DYNAMIC]
        step = 1 if b >= a else -1
        return [str(x) for x in range(a, b + step, step)]
    if len(a) == 1 and len(b) == 1 and not a.isdigit() and not b.isdigit():
        step = 1 if b >= a else -1
        return [chr(x) for x in range(ord(a), ord(b) + step, step)]
    return None


def brace_expand(tok):
    """Bash brace expansion (`ma{i,}n`, `{a..c}`) of one token. shlex has
    already dropped quotes, so quoted braces expand too (conservative). Too
    many results -> a single dynamic token."""
    i = 0
    while True:
        i = tok.find("{", i)
        if i == -1:
            return [tok]
        if i > 0 and tok[i - 1] == "$":
            i += 1
            continue
        depth, j = 0, i
        while j < len(tok):
            if tok[j] == "{":
                depth += 1
            elif tok[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        alts = _brace_alts(tok[i + 1:j]) if j < len(tok) else None
        if alts is None:
            i += 1
            continue
        out = []
        for alt in alts:
            out.extend(brace_expand(tok[:i] + alt + tok[j + 1:]))
            if len(out) > BRACE_LIMIT:
                return [tok + DYNAMIC]
        return out


def base(tok):
    b = re.split(r"[\\/]", tok)[-1].lower()
    return b[:-4] if b.endswith(".exe") else b


def is_dynamic(tok):
    return "$" in tok or DYNAMIC in tok or SUBST_RE.search(tok) is not None


# ---------------------------------------------------------------- analysis

def analyze(cmd, ctx, depth=0):
    """Raise Block if any command inside `cmd` is disallowed."""
    if depth > MAX_DEPTH:
        if RISKY_WORDS.search(cmd):
            ctx.block("command nested too deeply to analyse.")
        return
    ps = ctx.powershell
    segs, subs, docs = split_commands(cmd, ps=ps)
    for s in subs:
        analyze(s, ctx, depth + 1)
    stdin_modes = []
    for idx, seg in enumerate(segs):
        toks = tokenize(seg, ps=ps)
        if toks is None:
            fallback_check(seg, ctx)
            toks = seg.split()
        mode = run_segment(toks, ctx, subs, depth)
        ctx.powershell = ps  # a nested shell must not leak its mode
        if mode:
            stdin_modes.append(mode)
            for body in docs.get(idx, []):  # `bash <<EOF ... EOF`
                analyze_in(body, ctx, depth + 1, mode == "ps")
    for mode in stdin_modes:
        # `echo "git push origin main" | sh` (or `'...' | iex`): the piped text
        # is the script a stdin-reading shell runs.
        for seg in segs:
            toks = tokenize(seg, ps=ps) or seg.split()
            if toks and base(toks[0]) in ("echo", "printf", "write-output", "write-host"):
                analyze_in(" ".join(toks[1:]), ctx, depth + 1, mode == "ps")
            elif len(toks) == 1 and not toks[0].startswith("-"):
                analyze_in(toks[0], ctx, depth + 1, mode == "ps")


def analyze_in(cmd, ctx, depth, ps):
    """Analyse `cmd` as POSIX shell (`ps=False`) or PowerShell, restoring the
    caller's mode afterwards (`bash -c` inside a PowerShell call is POSIX)."""
    saved = ctx.powershell
    ctx.powershell = ps
    try:
        analyze(cmd, ctx, depth)
    finally:
        ctx.powershell = saved


def fallback_check(seg, ctx):
    """shlex failed (unbalanced quotes): be conservative."""
    if re.search(r"\bgh\b.*\bmerge\b", seg):
        ctx.block("unparseable gh command mentioning merge.")
    if not re.search(r"\b(push|send-pack)\b", seg):
        return
    if re.search(r"\{[^{}]*(,|\.\.)[^{}]*\}", seg):
        ctx.block("unparseable push command with a brace expansion.")
    words = re.findall(r"[\w./+-]+", seg)
    for w in words:
        if ctx.is_protected(strip_ref(w.lstrip("+").split(":")[-1])):
            ctx.block("unparseable push command naming a protected branch.")
    if re.search(r"(^|\s)(--force|--mirror|--delete|-[A-Za-z]*[fd][A-Za-z]*\b|\+)", seg):
        ctx.block("unparseable push command with a force/delete marker.")


CD_WORDS = {"cd", "chdir", "set-location", "sl", "pushd", "push-location"}
# PowerShell cmdlets that run a scriptblock argument
PS_BLOCK_RUNNERS = {"invoke-command", "icm", "start-job", "sajb", "start-threadjob", "foreach-object", "%",
                    "where-object", "?", "measure-command", "invoke-command", "register-engineevent"}


def scan_config_env(toks, ctx):
    """Leading `VAR=value` assignments can inject git config that redirects a
    push: GIT_CONFIG_PARAMETERS, or GIT_CONFIG_COUNT + GIT_CONFIG_KEY_n/VALUE_n.
    Taint the context if any such key is push-redirecting."""
    keys, vals = {}, {}
    for t in toks:
        if not ASSIGN_RE.match(t):
            break
        name, _, value = t.partition("=")
        up = name.upper()
        if up == "GIT_CONFIG_PARAMETERS":
            for item in shlex.split(value) if value else []:
                k, eq, v = item.partition("=")
                if eq and redirecting_config(k, v):
                    ctx.push_config_tainted = True
        elif up.startswith("GIT_CONFIG_KEY_"):
            keys[up[len("GIT_CONFIG_KEY_"):]] = value
        elif up.startswith("GIT_CONFIG_VALUE_"):
            vals[up[len("GIT_CONFIG_VALUE_"):]] = value
    for idx, k in keys.items():
        if redirecting_config(k, vals.get(idx)):
            ctx.push_config_tainted = True


def pwsh_path_arg(rest):
    """First positional (or -Path/-LiteralPath value) of a PowerShell cmdlet."""
    i = 0
    while i < len(rest):
        t = rest[i]
        lt = t.lower()
        if lt in ("-path", "-literalpath", "-lp") and i + 1 < len(rest):
            return rest[i + 1]
        if t.startswith("-"):
            i += 1
            continue
        return t
    return None


def start_process_cmd(rest):
    """Reconstruct the command a PowerShell `Start-Process git -ArgumentList
    'push','origin','main'` would run, as a string to re-analyse."""
    program, args = None, []
    i = 0
    while i < len(rest):
        t = rest[i]
        lt = t.lower()
        if (lt in ("-argumentlist", "-args") or (len(lt) > 4 and "-argumentlist".startswith(lt))):
            j = i + 1
            while j < len(rest) and not rest[j].startswith("-"):
                args.extend(x for x in rest[j].split(",") if x)
                j += 1
            i = j
            continue
        if lt in ("-filepath", "-path") and i + 1 < len(rest):
            program = rest[i + 1]
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        if program is None:
            program = t
        else:  # 2nd positional is -ArgumentList: `Start-Process git "push origin main"`
            args.extend(x for x in t.split(",") if x)
        i += 1
    return " ".join(([program] if program else []) + args)


def run_segment(toks, ctx, subs, depth):
    """Analyse one simple command. Returns True if it is a shell that reads
    its script from stdin: "posix" or "ps" (the script's language)."""
    scan_config_env(toks, ctx)
    toks = strip_prefixes(list(toks), ctx, depth)
    if not toks:
        return False
    if ctx.powershell:  # `{git push ...}` scriptblock braces glued to words
        if len(toks[0]) > 1 and toks[0].startswith("{"):
            toks[0] = toks[0][1:]
        if len(toks[-1]) > 1 and toks[-1].endswith("}") and "{" not in toks[-1]:
            toks[-1] = toks[-1][:-1]
    head = base(toks[0])
    rest = toks[1:]
    if ctx.powershell:
        for t in toks:  # `$env:GIT_CONFIG_PARAMETERS = '...'`
            if re.match(r"(?i)^\$env:GIT_CONFIG(?!_NOSYSTEM)", t):
                ctx.push_config_tainted = True
        if re.search(r"(?i)\.invoke(returnasis|withcontext)?$|\.invokescript$", toks[0]):
            ctx.dynamic_exec("a scriptblock .Invoke()")  # `$sb.Invoke()`
        brace = next((k for k in range(1, len(toks)) if toks[k].startswith("{")), None)
        if brace is not None and head not in ("&", ".", "invoke-command", "icm"):
            # `1 | % { git push ... }`, `Start-Job { ... }`, `try { ... }`
            body = " ".join(toks[brace:])[1:].strip()
            analyze(body[:-1] if body.endswith("}") else body, ctx, depth + 1)
        elif head in PS_BLOCK_RUNNERS and any(is_dynamic(t) for t in rest if not t.startswith("-")):
            ctx.dynamic_exec(head)  # `Start-Job $sb`, `% $sb`

    if head in CD_WORDS and rest:
        target = pwsh_path_arg(rest) if head != "cd" else rest[0]
        if target and not is_dynamic(target):
            ctx.cwd = os.path.join(ctx.cwd or os.getcwd(), target)
        return False
    if head in ("export", "declare", "typeset", "readonly", "local"):
        scan_config_env([t for t in rest if not t.startswith("-")], ctx)
        return False
    if head in ("eval", "iex", "invoke-expression"):
        args = [t for t in rest if t.lower() not in ("-command", "-c")]
        if not args:
            # reads the script from a pipe: `'git push ...' | iex`
            return "ps" if (ctx.powershell or head != "eval") else "posix"
        if any(is_dynamic(a) for a in args):
            ctx.dynamic_exec(head)  # `eval $c`, `iex $c`
        analyze(" ".join(args), ctx, depth + 1)  # eval joins its args with spaces
        return False
    if head == "&" or (head == "." and ctx.powershell):
        return call_op(head, rest, ctx, subs, depth)
    if head in (".", "source"):
        if rest and is_dynamic(rest[0]):
            ctx.dynamic_exec(head)
        analyze(" ".join(rest), ctx, depth + 1)  # dot-source: `. { git push ... }`
        return False
    if head in ("invoke-command", "icm"):  # -ScriptBlock { ... }
        invoke_command(rest, ctx, depth)
        return False
    if head in ("start-process", "saps", "start"):
        analyze(start_process_cmd(rest), ctx, depth + 1)
        return False
    if head in SHELLS:
        return shell_c(rest, ctx, depth)
    if head in PWSH:
        return pwsh_c(rest, ctx, depth)
    if head == "wsl":
        return wsl(rest, ctx, depth)
    if head == "find":
        # `find . -exec git push origin main \;`: each -exec/-ok command runs.
        i = 0
        while i < len(rest):
            if rest[i] in ("-exec", "-execdir", "-ok", "-okdir"):
                j = i + 1
                while j < len(rest) and rest[j] not in (";", "+"):
                    j += 1
                sub_toks = [t.replace("{}", DYNAMIC) for t in rest[i + 1:j]]
                run_segment(sub_toks, ctx, subs, depth + 1)
                i = j
            i += 1
        return False
    if head == "watch":
        i = 0
        while i < len(rest) and rest[i].startswith("-"):
            i += 2 if rest[i] in ("-n", "--interval", "-q", "--equexit") else 1
        analyze(" ".join(rest[i:]), ctx, depth + 1)  # watch runs its args via sh -c
        return False
    if head == "cmd":
        cmd_c(rest, ctx, depth)
        return False
    if head == "git":
        check_git(rest, ctx, subs, depth)
    elif head == "gh":
        check_gh(rest, ctx)
    elif is_dynamic(toks[0]):
        if any(t in ("push", "merge", "delete") for t in rest):
            # `$GIT push origin main`: unknown binary, assume the worst.
            check_git(rest, ctx, subs, depth)
            check_gh(rest, ctx)
        if not ctx.powershell and not ASSIGN_RE.match(toks[0]):
            ctx.dynamic_exec("a command named by a variable")  # `c='git push ...'; $c`
    return False


def call_op(head, rest, ctx, subs, depth):
    """PowerShell `& target args` / `. target args`."""
    if not rest:
        return False
    target = rest[0]
    if target.startswith("{"):  # `& { git push ... }`
        body = " ".join(rest)[1:].strip()
        analyze(body[:-1] if body.endswith("}") else body, ctx, depth + 1)
        return False
    if is_dynamic(target):  # `& $sb`, `& $exe --version`
        ctx.dynamic_exec(head + " " + target)
        return False
    return run_segment(rest, ctx, subs, depth + 1)


def invoke_command(rest, ctx, depth):
    """`Invoke-Command [-ScriptBlock] { ... }` / `icm $sb`."""
    for k, t in enumerate(rest):
        if t.startswith("{"):
            body = " ".join(rest[k:])[1:].strip()
            analyze(body[:-1] if body.endswith("}") else body, ctx, depth + 1)
            return
    i = 0
    while i < len(rest):
        lt = rest[i].lower()
        if lt in ("-filepath", "-file", "-fp"):
            return  # script file: out of reach
        if lt.startswith("-"):
            if lt in ("-scriptblock", "-sb") and i + 1 < len(rest) and is_dynamic(rest[i + 1]):
                ctx.dynamic_exec("Invoke-Command")
            i += 1 if lt in ("-asjob", "-nonewscope", "-hidecomputername", "-indisconnectedsession",
                             "-enablenetworkaccess", "-runasadministrator") else 2
            continue
        if is_dynamic(rest[i]):
            ctx.dynamic_exec("Invoke-Command")
        i += 1


def cmd_c(rest, ctx, depth):
    """`cmd [/d /q /s ...] /c|/k|/r <command>`; `^` is cmd's escape char."""
    for k, t in enumerate(rest):
        lt = t.lower()
        if lt in ("/c", "/k", "/r"):
            analyze(" ".join(rest[k + 1:]).replace("^", ""), ctx, depth + 1)
            return
        if not lt.startswith("/"):
            return


def wsl(rest, ctx, depth):
    """`wsl [-d X] [-u U] [--cd D] [-e|--exec] cmd ...` runs a Linux command."""
    i = 0
    while i < len(rest):
        t = rest[i]
        lt = t.lower()
        if lt in ("-e", "--exec"):
            i += 1
            break
        if lt == "--":
            i += 1
            break
        if lt in ("-d", "--distribution", "-u", "--user", "--cd", "--shell-type"):
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        break
    if rest[i:]:
        saved = ctx.powershell
        ctx.powershell = False
        try:  # the argv as-is, and as the Linux shell would re-read it joined
            run_segment(rest[i:], ctx, [], depth + 1)
            analyze(" ".join(rest[i:]), ctx, depth + 1)
        finally:
            ctx.powershell = saved
    return False


def strip_prefixes(toks, ctx, depth):
    """Drop `VAR=x`, keywords and wrappers (env, sudo, xargs, timeout, nice)."""
    while toks:
        t = toks[0]
        b = base(t)
        if ASSIGN_RE.match(t) or t in KEYWORDS:
            toks.pop(0)
        elif b == "env":
            toks.pop(0)
            scan_config_env([t for t in toks if not t.startswith("-")], ctx)
            while toks and (toks[0].startswith("-") or ASSIGN_RE.match(toks[0])):
                o = toks.pop(0)
                if o in ("-S", "--split-string") and toks:
                    toks = tokenize(toks.pop(0)) + toks
                elif o.startswith("--split-string="):
                    toks = tokenize(o.split("=", 1)[1]) + toks
                elif o in ("-u", "-C", "--unset", "--chdir") and toks:
                    toks.pop(0)
        elif b == "sudo":
            toks.pop(0)
            while toks and toks[0].startswith("-"):
                o = toks.pop(0)
                if o in ("-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U") and toks:
                    toks.pop(0)
        elif b in ("time", "setsid", "chronic"):
            toks.pop(0)
            while toks and toks[0].startswith("-"):
                o = toks.pop(0)
                if b == "time" and o in ("-f", "-o", "--format", "--output") and toks:
                    toks.pop(0)  # GNU /usr/bin/time
                if o == "--":
                    break
        elif b in ("nice", "timeout", "stdbuf", "ionice"):
            toks.pop(0)
            while toks and toks[0].startswith("-"):
                o = toks.pop(0)
                if o in ("-n", "-s", "-k", "--signal", "--kill-after", "-c", "-i", "-o", "-e") and toks:
                    toks.pop(0)
            if b == "timeout" and toks:
                toks.pop(0)  # duration
        elif b == "xargs":
            toks.pop(0)
            while toks and toks[0].startswith("-"):
                o = toks.pop(0)
                if o in ("-I", "-n", "-L", "-P", "-d", "-E", "-s", "-a") and toks:
                    toks.pop(0)
            toks.append(DYNAMIC)  # xargs appends arguments we cannot see
        else:
            break
    return toks


def shell_c(rest, ctx, depth):
    c_mode, i = False, 0
    while i < len(rest):
        t = rest[i]
        if t == "--":
            i += 1
            break
        if t in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            i += 2
            continue
        if t.startswith("--"):
            i += 1
            continue
        if len(t) > 1 and t[0] in "-+":
            if "c" in t[1:]:
                c_mode = True
            i += 1
            continue
        break
    operands = rest[i:]
    if c_mode and operands:
        analyze_in(operands[0], ctx, depth + 1, False)
        return False
    if not operands or operands[0] == "-" or "s" in "".join(t for t in rest[:i] if t.startswith("-")):
        return "posix"  # reads script from stdin
    return False  # script file: out of reach, documented limitation


def pwsh_c(rest, ctx, depth):
    arg_opts = {"-executionpolicy", "-ep", "-ex", "-workingdirectory", "-wd", "-outputformat", "-of",
                "-inputformat", "-if", "-windowstyle", "-w", "-configurationname", "-version", "-psconsolefile",
                "-settingsfile", "-custompipename"}
    i = 0
    while i < len(rest):
        t = rest[i].lower()
        if t in ("-e", "-ec", "-en", "-enc") or (len(t) > 3 and "-encodedcommand".startswith(t)):
            if i + 1 < len(rest):
                try:
                    script = base64.b64decode(rest[i + 1]).decode("utf-16-le")
                except Exception:
                    ctx.block("undecodable powershell -EncodedCommand.")
                analyze_in(script, ctx, depth + 1, True)
            return False
        if t in ("-c", "-command", "-cwa", "-commandwithargs") or (len(t) > 2 and "-command".startswith(t)):
            script = " ".join(rest[i + 1:])
            if script.strip() == "-":
                return "ps"
            analyze_in(script, ctx, depth + 1, True)
            return False
        if t in ("-f", "-file") or (len(t) > 2 and "-file".startswith(t)):
            return False
        if t in arg_opts:
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        break
    if rest[i:]:
        analyze_in(" ".join(rest[i:]), ctx, depth + 1, True)  # 5.1 defaults to -Command
    return False


# ---------------------------------------------------------------- git

GIT_ARG_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"}
GIT_KNOWN = {"push", "branch", "add", "commit", "status", "log", "diff", "show", "fetch", "pull", "checkout",
             "switch", "restore", "reset", "rebase", "merge", "stash", "tag", "remote", "config", "rev-parse",
             "worktree", "init", "clone", "mv", "rm", "grep", "blame", "cherry-pick", "revert", "clean",
             "describe", "ls-files", "symbolic-ref", "update-ref", "for-each-ref", "reflog", "submodule", "help",
             "send-pack", "http-push"}


def check_git(args, ctx, subs, depth, alias_depth=0):
    cwd = ctx.cwd
    i, inline_aliases = 0, {}
    while i < len(args) and args[i].startswith("-"):
        t = args[i]
        if t.startswith("--config-env="):  # --config-env=key=ENVVAR (value unseen)
            k = t[len("--config-env="):].split("=", 1)[0]
            if redirecting_config(k, None):
                ctx.push_config_tainted = True
            i += 1
            continue
        if t in GIT_ARG_OPTS and i + 1 < len(args):
            v = args[i + 1]
            if t == "-C" and not is_dynamic(v):
                cwd = os.path.join(cwd or os.getcwd(), v)
            if t == "-c" and "=" in v:
                k, val = v.split("=", 1)
                if k.lower().startswith("alias."):
                    inline_aliases[k[6:]] = val
                elif redirecting_config(k, val):
                    ctx.push_config_tainted = True
            if t == "--config-env":  # --config-env key=ENVVAR (value unseen)
                k = v.split("=", 1)[0]
                if redirecting_config(k, None):
                    ctx.push_config_tainted = True
            i += 2
        else:
            i += 1
    if i >= len(args):
        return
    sub, rest = args[i], args[i + 1:]

    if sub not in GIT_KNOWN and alias_depth < 3:
        alias = inline_aliases.get(sub) or (None if is_dynamic(sub) else ctx.alias_lookup(cwd, sub))
        if alias:
            if alias.startswith("!"):
                analyze(alias[1:] + " " + " ".join(shlex.quote(r) for r in rest), ctx, depth + 1)
            else:
                check_git((tokenize(alias) or alias.split()) + rest, ctx, subs, depth, alias_depth + 1)
            return
    if sub == "push":
        check_push(rest, ctx, subs, cwd)
    elif sub in ("send-pack", "http-push"):
        check_send_pack(rest, ctx, subs, cwd, sub)
    elif sub == "branch":
        check_branch_delete(rest, ctx)
        track_branch_rename(rest, ctx)
    elif sub in ("checkout", "switch"):
        track_checkout(sub, rest, ctx)
    elif sub == "symbolic-ref":
        track_symbolic_ref(rest, ctx)
    elif sub == "config":
        check_config(rest, ctx)


CHECKOUT_CREATE = {"-b", "-B", "-c", "-C", "--orphan"}
CONFIG_READ_FLAGS = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color",
                     "--get-colorbool", "-l", "--list", "-e", "--edit", "--default"}


def _set_branch(ctx, name):
    ctx.branch_override = UNKNOWN_BRANCH if (is_dynamic(name) or name == "-") else strip_ref(name)


def track_checkout(sub, args, ctx):
    """`git checkout/switch <name>` changes the current branch for a later bare
    push. A protected target, an unreadable one, or a detach -> fail closed.
    `-t/--track origin/main` creates and switches to `main`."""
    create, track, pos, paths = None, False, [], None
    i = 0
    while i < len(args):
        t = args[i]
        if t == "--":
            paths = args[i + 1:]
            break
        if t in ("--detach", "-d"):
            ctx.branch_override = UNKNOWN_BRANCH
            return
        if t in CHECKOUT_CREATE and i + 1 < len(args):
            create = args[i + 1]
            i += 2
            continue
        if t in ("-t", "--track") or t.startswith("--track="):
            track = True
        elif t == "-" or not t.startswith("-"):  # `git switch -` = previous branch
            pos.append(t)
        i += 1
    if paths:
        return  # `git checkout <tree> -- <paths>` restores files, no branch change
    if create is not None:
        _set_branch(ctx, create)
        return
    if not pos or (sub == "checkout" and len(pos) > 1):
        return  # nothing named, or `git checkout <tree> <paths>`
    name = pos[0]
    if track and "/" in name and not name.lower().startswith("refs/"):
        name = name.split("/", 1)[1]  # origin/main -> main
    elif track and name.lower().startswith("refs/remotes/"):
        name = name[len("refs/remotes/"):].split("/", 1)[-1]
    _set_branch(ctx, name)


def track_symbolic_ref(args, ctx):
    """`git symbolic-ref HEAD refs/heads/main` points HEAD at another branch."""
    pos, i, delete = [], 0, False
    while i < len(args):
        t = args[i]
        if t == "-m":
            i += 2
            continue
        if t in ("-d", "--delete"):
            delete = True
        elif not t.startswith("-"):
            pos.append(t)
        i += 1
    if not pos or pos[0] != "HEAD":
        return
    if delete:
        ctx.branch_override = UNKNOWN_BRANCH
    elif len(pos) >= 2:
        _set_branch(ctx, pos[1])


CONFIG_VALUE_OPTS = {"-f", "--file", "--blob", "--type", "--default", "--comment", "--value"}
CONFIG_SUBCOMMANDS_SAFE = {"get", "list", "unset", "remove-section", "edit", "get-color", "get-colorbool"}
_BRANCH_MERGE_RE = re.compile(r"^branch\..+\.merge$", re.I)
_INCLUDE_RE = re.compile(r"^include(if\..+)?\.path$", re.I)


def config_write_redirects(key, value, ctx):
    """True if persisting this key+value lets a later plain `git push` land
    somewhere other than the branch it names. `value` None = unreadable."""
    k = key.strip().lower()
    if _BRANCH_MERGE_RE.match(k):
        return value is None or ctx.is_protected(strip_ref(value))
    if _INCLUDE_RE.match(k):
        return True  # pulls in a config file we can't read
    if _BRANCH_UPSTREAM_RE.match(k):
        return False  # branch.*.remote/pushremote pick a remote, not a branch
    return redirecting_config(key, value)


def check_config(args, ctx):
    """`git config push.default matching` / `git config set remote.o.push ...`:
    the setting persists, so a later separate `git push` would be redirected.
    Block the write itself. Reads, unsets and harmless keys pass."""
    pos, i, rename = [], 0, False
    while i < len(args):
        t = args[i]
        if t in CONFIG_READ_FLAGS or t in ("--unset", "--unset-all", "--remove-section"):
            return  # a read or a removal, not a write
        if t == "--rename-section":
            rename = True
        if t in CONFIG_VALUE_OPTS:
            i += 2
            continue
        if not t.startswith("-"):
            pos.append(t)
        i += 1
    if pos and pos[0].lower() in CONFIG_SUBCOMMANDS_SAFE:
        return
    if pos and pos[0].lower() == "rename-section":
        rename, pos = True, pos[1:]
    elif pos and pos[0].lower() == "set":
        pos = pos[1:]
    if len(pos) < 2:
        return  # `git config <key>` reads
    key, value = pos[0], pos[1]
    if rename:
        if is_dynamic(value) or value.lower().startswith(("remote.", "branch.")):
            ctx.block("git config rename-section into a remote/branch section can carry "
                      "push settings; not allowed.")
        return
    if is_dynamic(key):
        ctx.block("git config write of an unreadable key '%s'; failing closed." % key)
    if config_write_redirects(key, None if is_dynamic(value) else value, ctx):
        ctx.block("git config %s %s persists a setting that can redirect a later push "
                  "(push.default/remote.*.push/mirror/branch.*.merge/include); not allowed." % (key, value))


def strip_ref(ref):
    """Branch name git would resolve `ref` to: collapses `//` and `/./`,
    drops `refs/heads/` and the DWIM `heads/` prefix."""
    prev = None
    while prev != ref:
        prev = ref
        ref = re.sub(r"/+", "/", ref).replace("/./", "/")
        ref = re.sub(r"^\./", "", ref)
    for p in ("refs/heads/", "heads/"):
        if ref.lower().startswith(p):
            return ref[len(p):]
    return ref


def is_current_branch_subst(tok, subs):
    m = SUBST_RE.fullmatch(tok)
    return bool(m) and any(p.match(subs[int(m.group(1))]) for p in CURRENT_BRANCH_IDIOMS)


def check_push(args, ctx, subs, cwd):
    if ctx.push_config_tainted:
        ctx.block("git push with a config override (push.default/remote.*.push/"
                  "mirror) that can redirect the push; not allowed.")
    positional, i, end_opts = [], 0, False
    while i < len(args):
        t = args[i]
        i += 1
        if end_opts or not t.startswith("-") or t == "-":
            positional.append(t)
            continue
        if t == "--":
            end_opts = True
            continue
        lt = t.lower()
        if lt.startswith("--force") or lt.startswith("--mirror") or lt.startswith("--delete"):
            ctx.block("git push %s is not allowed." % t.split("=")[0])
        if lt in ("--all", "--branches", "--prune"):
            ctx.block("git push %s touches every branch." % t)
        if t in ("--repo", "--push-option", "--receive-pack", "--exec", "-o"):
            i += 1
            continue
        if not t.startswith("--"):
            flags = t[1:]
            if "f" in flags:
                ctx.block("git push -f (force) is not allowed.")
            if "d" in flags:
                ctx.block("git push -d (delete) is not allowed.")
            if flags.endswith("o"):
                i += 1
    check_refspecs(positional[1:], ctx, subs, cwd)


def check_send_pack(args, ctx, subs, cwd, sub):
    """`git send-pack`/`http-push [opts] <remote> <ref>...`: plumbing push."""
    positional = []
    for t in args:
        lt = t.lower()
        if not t.startswith("-") or t == "-":
            positional.append(t)
        elif lt.startswith(("--force", "--mirror", "--all", "--stdin", "--delete")) or re.fullmatch(r"-[a-z]*[fd][a-z]*", t):
            ctx.block("git %s %s is not allowed." % (sub, t.split("=")[0]))
    if len(positional) < 2:
        ctx.block("git %s without explicit refs updates matching branches; name them." % sub)
    check_refspecs(positional[1:], ctx, subs, cwd)


def check_refspecs(refspecs, ctx, subs, cwd):
    needs_current = not refspecs
    for spec in refspecs:
        if spec.startswith("+"):
            ctx.block("force refspec '%s' is not allowed." % spec)
        if is_current_branch_subst(spec, subs):
            needs_current = True
            continue
        if is_dynamic(spec):
            ctx.block("push with a dynamic refspec '%s'; spell the branch name out." % spec)
        src, _, dst = spec.rpartition(":") if ":" in spec else ("", "", spec)
        if ":" in spec and src == "":
            ctx.block("delete refspec '%s' is not allowed." % spec)
        dst = strip_ref(dst)
        if "@{" in dst or dst == "-":
            ctx.block("refspec '%s' resolves to another branch; spell the branch name out." % spec)
        if "*" in dst:
            ctx.block("wildcard refspec '%s' is not allowed." % spec)
        if ctx.is_protected(dst):
            ctx.block("push to protected branch '%s' is not allowed." % dst)
        if dst in ("HEAD", "@"):
            needs_current = True
    if needs_current:
        if ctx.branch_override is not None:
            branch = ctx.branch_override
        else:
            branch = ctx.branch_lookup(cwd)
        if branch is UNKNOWN_BRANCH or branch == UNKNOWN_BRANCH:
            ctx.block("push of the current branch, which can't be determined; failing closed.")
        if not branch:
            # current branch unreadable (no repo, detached, bogus cwd) -> fail closed
            ctx.block("push of the current branch, which can't be determined; failing closed.")
        if ctx.is_protected(branch):
            ctx.block("push of current branch '%s' (protected) is not allowed." % branch)


def check_branch_delete(args, ctx):
    deleting = False
    names = []
    for t in args:
        if t == "--delete" or (t.startswith("-") and not t.startswith("--") and ("d" in t or "D" in t)):
            deleting = True
        elif not t.startswith("-"):
            names.append(strip_ref(t))
    if deleting and any(ctx.is_protected(n) for n in names):
        ctx.block("deleting a protected branch is not allowed.")


def track_branch_rename(args, ctx):
    """`git branch -m main` renames the current branch: a later bare push
    pushes the new name. `-m <old> <new>` may rename it too (old unknown)."""
    if not any(t in ("-m", "-M", "--move") or re.fullmatch(r"-[a-z]*[mM][a-z]*", t) for t in args):
        return
    pos = [t for t in args if not t.startswith("-")]
    if not pos:
        return
    new = pos[-1]
    if len(pos) == 1 or is_dynamic(new) or ctx.is_protected(strip_ref(new)):
        _set_branch(ctx, new)


# ---------------------------------------------------------------- gh

GH_API_ARG_OPTS = {"-X", "--method", "-H", "--header", "-f", "--raw-field", "-F", "--field", "--input", "-q",
                   "--jq", "-t", "--template", "--hostname", "-p", "--preview", "--cache"}
GRAPHQL_MUTATIONS = re.compile(r"mergePullRequest|enablePullRequestAutoMerge|mergeBranch|deleteRef|updateRef"
                               r"|updateRefs|deleteRepository|deleteBranchProtectionRule", re.I)


def check_gh(args, ctx):
    pos, i = [], 0
    while i < len(args) and len(pos) < 2:
        t = args[i]
        if t in ("-R", "--repo", "--hostname"):
            i += 2
            continue
        if not t.startswith("-"):
            pos.append(t)
        i += 1
    if pos[:2] == ["pr", "merge"]:
        ctx.block("gh pr merge is not allowed.")
    if pos[:2] == ["repo", "delete"]:
        ctx.block("gh repo delete is not allowed.")
    if pos[:1] == ["api"]:
        check_gh_api(args[args.index("api") + 1:], ctx)


def unreadable_ref(ref):
    """`..` segments and %-escapes may resolve server-side to any branch."""
    return "%" in ref or ".." in ref.split("/")


def _field_kv(spec, fields, typed=False):
    """`-F key=@file` reads the value from a file (or stdin): unreadable."""
    k, eq, v = spec.partition("=")
    if eq:
        fields[k.strip().lower()] = DYNAMIC if (typed and v.startswith("@")) else v


def check_gh_api(args, ctx):
    method, has_fields, endpoint, i = None, False, None, 0
    fields, input_file = {}, False
    while i < len(args):
        t = args[i]
        opt, eq, val = t.partition("=")
        if t.startswith("-") and opt in GH_API_ARG_OPTS:
            if not eq:
                val = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            if opt in ("-X", "--method"):
                method = val.upper()
            if opt in ("-f", "--raw-field", "-F", "--field"):
                has_fields = True
                _field_kv(val, fields, opt in ("-F", "--field"))
            if opt == "--input":
                has_fields = True
                input_file = True
        elif t.startswith("-X") and len(t) > 2:
            method = t[2:].upper()
        elif (t.startswith("-f") or t.startswith("-F")) and len(t) > 2 and "=" in t:
            has_fields = True  # attached form: -fbranch=main / -Fbranch=@f
            _field_kv(t[2:], fields, t.startswith("-F"))
        elif not t.startswith("-") and endpoint is None:
            endpoint = t
        i += 1
    if endpoint is None:
        return
    if method is None:
        method = "POST" if has_fields else "GET"
    write = method != "GET" or is_dynamic(method)
    ep = re.sub(r"^https?://[^/]+(/api/v3)?", "", endpoint).split("?")[0]
    prev = None
    while prev != ep:  # collapse `//` and `/./` so they can't hide a ref
        prev = ep
        ep = re.sub(r"/+", "/", ep).replace("/./", "/")
        ep = re.sub(r"^\./|/\.$", "", ep)
    ep = ep.strip("/")
    if re.search(r"(^|/)pulls/[^/]+/merge$", ep) or re.search(r"(^|/)merges$", ep):
        ctx.block("gh api merge endpoint is not allowed.")
    m = re.search(r"(^|/)git/refs/heads/(.+)$", ep)
    ref = strip_ref(m.group(2)) if m else None
    if m and write and (ctx.is_protected(ref) or is_dynamic(ref) or unreadable_ref(ref)):
        ctx.block("gh api %s on a protected branch ref is not allowed." % method)
    m = re.search(r"(^|/)branches/(.+)/protection(/|$)", ep)
    ref = strip_ref(m.group(2)) if m else None
    if m and write and (ctx.is_protected(ref) or is_dynamic(ref) or unreadable_ref(ref)):
        ctx.block("gh api %s on branch protection is not allowed." % method)
    if re.search(r"(^|/)repos/[^/]+/[^/]+/contents/", ep) and write:
        branch = fields.get("branch")
        if input_file:
            ctx.block("gh api %s to repo contents from --input (branch unreadable) "
                      "is not allowed." % method)
        if branch is None:
            ctx.block("gh api %s to repo contents with no branch= commits to the "
                      "default branch (protected); name a feature branch." % method)
        if is_dynamic(branch) or ctx.is_protected(strip_ref(branch)) or unreadable_ref(branch):
            ctx.block("gh api %s to repo contents on protected branch '%s' is not allowed."
                      % (method, branch))
    if re.fullmatch(r"repos/[^/]+/[^/]+", ep) and method == "DELETE":
        ctx.block("gh api DELETE on a repo is not allowed.")
    if ep == "graphql" and any(GRAPHQL_MUTATIONS.search(a) for a in args):
        ctx.block("gh api graphql merge/ref/repo mutation is not allowed.")


# ---------------------------------------------------------------- entry

def decide(command, ctx):
    """Return a block reason, or None to allow. Fails closed on internal
    errors when the command mentions push/merge/delete."""
    try:
        ctx.top_cmd = command
        analyze(command, ctx)
        return None
    except Block as b:
        return str(b)
    except Exception as e:  # noqa: BLE001 - fail closed on risky commands
        if RISKY_WORDS.search(command):
            return "Blocked: guard-git could not analyse this command (%s: %s); failing closed." % (
                type(e).__name__, e)
        return None


def main():
    if "--self-test" in sys.argv:
        run_self_test()
        return
    try:
        data = json.loads(sys.stdin.read())
        tool = data.get("tool_name")
        if tool not in ("Bash", "PowerShell"):
            sys.exit(0)
        if "--plugin" in sys.argv and not guarded_agent(data.get("agent_type")):
            sys.exit(0)  # plugin hook: main session and other agents may push
        command = (data.get("tool_input") or {}).get("command")
        cwd = data.get("cwd")
    except Exception:
        sys.exit(0)  # not hook JSON: nothing to guard
    if not isinstance(command, str) or not command:
        sys.exit(0)
    reason = decide(command, Ctx(protected_branches(), cwd, powershell=(tool == "PowerShell")))
    if reason:
        sys.stderr.write(reason + "\n")
        sys.exit(2)
    sys.exit(0)


# ---------------------------------------------------------------- self-test

B, A = True, False
CASES = [
    # (command, expect_block, current_branch)
    ("git push origin main", B, "feat"),
    ("git push origin feature/foo", A, "feat"),
    ("git push origin krish/x", A, "feat"),
    ("git push --force origin feature/foo", B, "feat"),
    ("git push -f origin feature/foo", B, "feat"),
    ("git push -uf origin feature/foo", B, "feat"),
    ("git push origin --force-with-lease feature/foo", B, "feat"),
    ("git push --force-with-lease=feature/foo:abc origin feature/foo", B, "feat"),
    ("git push --force-if-includes origin feature/foo", B, "feat"),
    ("git push origin --delete old-branch", B, "feat"),
    ("git push -d origin old-branch", B, "feat"),
    ("git push origin :old-branch", B, "feat"),
    ("git push --mirror origin", B, "feat"),
    ("git push --all origin", B, "feat"),
    ("git push origin +main", B, "feat"),
    ("git push origin +feature/foo", B, "feat"),
    ("git push origin HEAD:main", B, "feat"),
    ("git push origin x:refs/heads/main", B, "feat"),
    ("git push origin refs/heads/main", B, "feat"),
    ("git push origin HEAD:refs/heads/master", B, "feat"),
    ("git push origin 'refs/heads/*:refs/heads/*'", B, "feat"),
    ("git push origin MAIN", B, "feat"),
    ("git push", B, "main"),
    ("git push origin", B, "main"),
    ("git push -u origin HEAD", B, "main"),
    ("git push -u origin HEAD", A, "krish/x"),
    ("git push", A, "krish/x"),
    ("git push -u origin $(git branch --show-current)", B, "main"),
    ("git push -u origin $(git branch --show-current)", A, "krish/x"),
    ("git push origin $(echo main)", B, "feat"),
    ("git push origin $BRANCH", B, "feat"),
    ("git status\ngit push origin main", B, "feat"),
    ("git status & git push origin main", B, "feat"),
    ("git status | git push origin main", B, "feat"),
    ("git add -A && git push origin main", B, "feat"),
    ("false || git push origin main", B, "feat"),
    ("git status; git push origin main", B, "feat"),
    ("git status && git push origin feature/x", A, "feat"),
    ("git push origin krish/x 2>&1 | tail -5", A, "feat"),
    ("(git push origin main)", B, "feat"),
    ("git -C /tmp/repo push origin main", B, "feat"),
    ("git -c user.name=x push origin main", B, "feat"),
    ("git --git-dir=.git --work-tree . push origin main", B, "feat"),
    ("git --no-pager push origin main", B, "feat"),
    ("git -c alias.p=push p origin main", B, "feat"),
    ("git pp origin main", B, "feat"),  # alias pp=push injected below
    ("env X=1 git push origin main", B, "feat"),
    ("env -S 'git push origin main'", B, "feat"),
    ("command git push origin main", B, "feat"),
    ("GIT_TRACE=1 git push origin main", B, "feat"),
    ("/usr/bin/git push origin main", B, "feat"),
    ("git.exe push origin main", B, "feat"),
    ('"C:\\Program Files\\Git\\cmd\\git.exe" push origin main', B, "feat"),
    ("sudo -u me git push origin main", B, "feat"),
    ("timeout 30 git push origin main", B, "feat"),
    ("time git push origin main", B, "feat"),
    ("time -p git push origin main", B, "feat"),
    ("time -- git push origin main", B, "feat"),
    ("/usr/bin/time -f %e -o t.txt git push origin main", B, "feat"),
    ("setsid -f git push origin main", B, "feat"),
    ("nohup git push origin main &", B, "feat"),
    ("chronic git push origin main", B, "feat"),
    ("watch -n 5 git push origin main", B, "feat"),
    ("watch -d 'git push origin main'", B, "feat"),
    ("time -p git push origin krish/x", A, "feat"),
    ("watch -n 5 git status", A, "main"),
    ("find . -maxdepth 0 -exec git push origin main \\;", B, "feat"),
    ("find . -execdir git push origin main ';'", B, "feat"),
    ("find . -ok git push --force origin x \\;", B, "feat"),
    ("find . -name x -exec echo {} \\; -exec git push origin main +", B, "feat"),
    ("find refs -exec git push origin {} \\;", B, "feat"),
    ("find . -exec sh -c 'git push origin {}' \\;", B, "feat"),
    ("find . -name '*.py' -exec grep -n main {} +", A, "main"),
    ("find . -exec git push origin krish/x \\;", A, "feat"),
    ("g''it pu\\sh origin ma''in", B, "feat"),
    ("bash -c 'git push origin main'", B, "feat"),
    ("sh -c \"cd x && git push origin main\"", B, "feat"),
    ("bash -lc 'git push --force origin x'", B, "feat"),
    ("zsh -c 'bash -c \"git push origin main\"'", B, "feat"),
    ("pwsh -NoProfile -Command \"git push origin main\"", B, "feat"),
    ("powershell.exe -c git push origin main", B, "feat"),
    ("powershell -EncodedCommand " + base64.b64encode("git push origin main".encode("utf-16-le")).decode(), B, "feat"),
    ("cmd /c git push origin main", B, "feat"),
    ("eval 'git push origin main'", B, "feat"),
    ("echo $(git push origin main)", B, "feat"),
    ("x=`git push origin main`", B, "feat"),
    ("echo 'git push origin main' | sh", B, "feat"),
    ("echo main | xargs git push origin", B, "feat"),
    ("git push origin 'unterminated main", B, "feat"),
    ("git push origin \"unterminated -f", B, "feat"),
    ("git push origin x # main", A, "feat"),
    ("git push origin ma{i,}n", B, "feat"),
    ("git push origin {main,x}", B, "feat"),
    ("git push origin {x,+main}", B, "feat"),
    ("git push origin x:{main,y}", B, "feat"),
    ("git push {origin,main}", B, "feat"),
    ("git push origin 'ma{i,}n'", B, "feat"),  # quoted braces expand too: conservative
    ("git push origin ma{h..j}n", B, "feat"),
    ("git push origin x{1..999}", B, "feat"),  # too many to expand -> dynamic
    ("git push origin {krish/a,krish/b}", A, "feat"),
    ("git push origin krish/{docs}", A, "feat"),  # no comma: bash leaves it literal
    ("git push origin main^{}:krish/x", A, "feat"),
    ("git push origin 'ma{i,}n", B, "feat"),  # unparseable + brace
    ("git push origin HEAD:heads/main", B, "feat"),
    ("git push origin x:refs/heads//main", B, "feat"),
    ("git push origin x:refs/./heads/./main", B, "feat"),
    ("git push origin x:Refs/Heads/Main", B, "feat"),
    ("git push origin @{-1}", B, "feat"),
    ("git push origin HEAD@{0}:krish/x", A, "feat"),
    ("git push origin HEAD:heads/krish/x", A, "feat"),
    ("git push origin 'x:heads/main", B, "feat"),  # unparseable + DWIM
    ("git send-pack origin main", B, "feat"),
    ("git send-pack --force origin krish/x", B, "feat"),
    ("git send-pack --all origin", B, "feat"),
    ("git send-pack --mirror origin", B, "feat"),
    ("git send-pack --stdin origin", B, "feat"),
    ("git send-pack origin", B, "feat"),  # no refs = matching branches
    ("git send-pack origin +krish/x", B, "feat"),
    ("git send-pack origin HEAD:refs/heads/main", B, "feat"),
    ("git send-pack --receive-pack=x origin HEAD", B, "main"),
    ("git http-push https://h/r.git main", B, "feat"),
    ("git send-pack origin 'main", B, "feat"),  # unparseable
    ("git send-pack --thin origin krish/x", A, "feat"),
    ("git send-pack origin HEAD", A, "krish/x"),
    ("gh pr merge 123", B, "feat"),
    ("gh pr merge --squash --auto 5", B, "feat"),
    ("gh -R o/r pr merge 5", B, "feat"),
    ("gh repo delete owner/repo --yes", B, "feat"),
    ("gh api -X PUT repos/o/r/pulls/5/merge", B, "feat"),
    ("gh api repos/o/r/pulls/5/merge --method PUT", B, "feat"),
    ("gh api /repos/o/r/merges -f base=main -f head=x", B, "feat"),
    ("gh api -X DELETE repos/o/r/git/refs/heads/main", B, "feat"),
    ("gh api --method=PATCH repos/o/r/git/refs/heads/master -F sha=abc -F force=true", B, "feat"),
    ("gh api -XPATCH repos/o/r/git/refs/heads/main", B, "feat"),
    ("gh api -X DELETE repos/o/r/branches/main/protection", B, "feat"),
    ("gh api -X DELETE repos/o/r/git/refs/heads//main", B, "feat"),
    ("gh api -X PATCH repos/o/r/git/refs/heads/./master", B, "feat"),
    ("gh api -X DELETE repos/o/r/git/refs/heads/.//./main", B, "feat"),
    ("gh api -X DELETE repos//o/r/./git/refs/heads/main", B, "feat"),
    ("gh api -X DELETE repos/o/r/branches//main/protection", B, "feat"),
    ("gh api -X PUT repos/o/r/branches/./main/protection/", B, "feat"),
    ("gh api -X POST repos/o/r/branches/main/protection/required_signatures", B, "feat"),
    ("gh api -X PUT repos/o/r/pulls//5/merge", B, "feat"),
    ("gh api -X DELETE repos/o/r/git/refs/heads//krish/x", A, "feat"),
    ("gh api -X DELETE repos/o/r/git/refs/heads/krish/../main", B, "feat"),
    ("gh api -X PATCH repos/o/r/git/refs/heads/%6Dain", B, "feat"),
    ("gh api -X DELETE repos/o/r/branches/x/../main/protection", B, "feat"),
    ("gh api -X PUT repos/o/r/branches/krish/x/protection", A, "feat"),
    ("gh api repos/o/r/branches//main/protection", A, "feat"),
    ("gh api -X DELETE repos/o/r", B, "feat"),
    ("gh api graphql -f query='mutation{mergePullRequest(input:{pullRequestId:\"x\"}){clientMutationId}}'", B, "feat"),
    ("git branch -D main", B, "feat"),
    ("git branch --delete master", B, "feat"),
    ("git branch -df main", B, "feat"),
    ("git branch -D feature/foo", A, "feat"),
    # no false positives
    ("git commit -m \"fix main push\"", A, "feat"),
    ("git commit -m 'git push origin main --force'", A, "main"),
    ("git log main..HEAD", A, "feat"),
    ("git log --format='%h {x,y}'", A, "main"),
    ("mkdir -p src/{a,b}/main", A, "main"),
    ("git log --oneline origin/main", A, "main"),
    ("git diff main...HEAD", A, "feat"),
    ("git fetch origin main", A, "feat"),
    ("git checkout main && git pull", A, "feat"),
    ("git merge main", A, "feat"),
    ("git branch -a", A, "main"),
    ("git status", A, "main"),
    ("gh pr view 5", A, "feat"),
    ("gh pr create --base main --title 'merge main push' --body x", A, "feat"),
    ("gh api repos/o/r/pulls/5", A, "feat"),
    ("gh api repos/o/r/git/refs/heads/main", A, "feat"),
    ("gh api repos/o/r/pulls/5/merge", B, "feat"),  # GET is harmless but merge endpoints are blocked outright
    ("echo git push origin main", A, "feat"),  # argument to echo, never executed
    ("echo hello", A, "feat"),
    ("grep -rn 'push origin main' docs/", A, "feat"),
    ("python agents/hooks/guard-git.py --self-test", A, "main"),
    ("cat <<'EOF' > notes.md\ngit push origin main\nEOF", A, "feat"),
    ("git commit -m \"$(cat <<'EOF'\nfix: don't push to main (again)\n\ngit push origin main --force\nEOF\n)\"", A, "main"),
    ("git commit -F - <<'EOF'\nfix: don't push to main\nEOF\ngit push origin krish/x", A, "feat"),
    ("git commit -F - <<'EOF'\nfix: don't\nEOF\ngit push origin main", B, "feat"),
    ("bash <<'EOF'\ngit push origin main\nEOF", B, "feat"),
    ("bash -s <<EOF\n  git push --force origin x\nEOF", B, "feat"),
]


def run_self_test():
    passed = failed = 0
    for cmd, expect, branch in CASES:
        ctx = Ctx(["main", "master"], "/repo",
                  branch_lookup=lambda cwd, b=branch: b,
                  alias_lookup=lambda cwd, name: {"pp": "push"}.get(name))
        reason = decide(cmd, ctx)
        ok = (reason is not None) == expect
        passed += ok
        failed += not ok
        print("%s: %-60s block=%-5s branch=%-8s %s" % (
            "PASS" if ok else "FAIL", cmd.replace("\n", "\\n")[:60], reason is not None, branch, reason or ""))

    # fail-closed: an internal error on a risky command blocks, on a benign one allows
    def boom(cwd):
        raise RuntimeError("injected")
    for cmd, expect in (("git push", True), ("git status", False)):
        reason = decide(cmd, Ctx(["main"], None, branch_lookup=boom, alias_lookup=lambda c, n: None))
        ok = (reason is not None) == expect
        passed += ok
        failed += not ok
        print("%s: fail-closed %-47s block=%s" % ("PASS" if ok else "FAIL", cmd, reason is not None))

    # end-to-end through stdin: exit codes as Claude Code sees them
    env = dict(os.environ, GUARD_PROTECTED_BRANCHES="main,master")
    for payload, expect_rc in (
        ({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}, 2),
        ({"tool_name": "PowerShell", "tool_input": {"command": "git push origin main; git status"}}, 2),
        ({"tool_name": "Bash", "tool_input": {"command": "git push origin krish/x"}}, 0),
        ({"tool_name": "Read", "tool_input": {"file_path": "x"}}, 0),
        ("not json", 0),
    ):
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        rc = subprocess.run([sys.executable, os.path.abspath(__file__)], input=raw, text=True,
                            capture_output=True, env=env).returncode
        ok = rc == expect_rc
        passed += ok
        failed += not ok
        print("%s: stdin %-53s rc=%s" % ("PASS" if ok else "FAIL", raw[:53], rc))

    # --plugin: enforce only for implementer/manager (bare or namespaced)
    push_main = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}
    for agent_type, expect_rc in (
        (None, 0), ("", 0), ("verifier", 0), ("krish:verifier", 0), ("general-purpose", 0),
        ("implementer", 2), ("manager", 2), ("krish:implementer", 2), ("krish:manager", 2),
        ("xmanager", 0), ("manager:other", 0),
    ):
        payload = dict(push_main)
        if agent_type is not None:
            payload["agent_type"] = agent_type
        rc = subprocess.run([sys.executable, os.path.abspath(__file__), "--plugin"], input=json.dumps(payload),
                            text=True, capture_output=True, env=env).returncode
        ok = rc == expect_rc
        passed += ok
        failed += not ok
        print("%s: --plugin agent_type=%-30r rc=%s" % ("PASS" if ok else "FAIL", agent_type, rc))

    # --- issue #140: config overrides, checkout chains, PS wrappers, gh contents
    feat = lambda cwd: "feat"
    none_lookup = lambda cwd: None
    cd_lookup = lambda cwd: "feat" if cwd == "/repo" else None  # bogus cwd -> unreadable

    extra = [  # (command, expect_block, powershell, branch_lookup)
        # 1. git -c / --config-env / env config that can redirect the push
        ("git -c push.default=matching push origin", B, False, feat),
        ("git -c remote.origin.push=refs/heads/x:refs/heads/main push", B, False, feat),
        ("git -c remote.origin.mirror=true push origin", B, False, feat),
        ("git --config-env=push.default=MYVAR push origin", B, False, feat),
        ("git --config-env push.default=MYVAR push", B, False, feat),
        ("GIT_CONFIG_PARAMETERS=\"'push.default=matching'\" git push origin", B, False, feat),
        ("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=push.default GIT_CONFIG_VALUE_0=matching git push origin", B, False, feat),
        ("git config push.default matching && git push", B, False, feat),
        ("git config remote.origin.push refs/heads/x:refs/heads/main && git push origin krish/x", B, False, feat),
        ("git -c push.default=current push origin krish/x", A, False, feat),
        ("git -c push.default=simple push origin krish/x", A, False, feat),
        ("git -c user.name=x push origin krish/x", A, False, feat),
        ("git config core.editor vim && git push origin krish/x", A, False, feat),
        # 2. checkout/switch of a protected name earlier in the chain
        ("git checkout main && git push", B, False, feat),
        ("git switch main; git push origin HEAD", B, False, feat),
        ("git checkout -B master && git push origin", B, False, feat),
        ("git checkout $DYN && git push", B, False, feat),
        ("git switch --detach && git push", B, False, feat),
        ("git checkout - && git push", B, False, feat),
        ("git switch -c krish/y && git push -u origin HEAD", A, False, feat),
        ("git checkout main && git push origin krish/x", A, False, feat),
        ("git checkout main -- file.txt && git push origin krish/x", A, False, feat),
        # 3. current branch undeterminable for a bare/implicit push -> fail closed
        ("git push", B, False, none_lookup),
        ("git push origin", B, False, none_lookup),
        ("git push -u origin HEAD", B, False, none_lookup),
        ("git push origin krish/x", A, False, none_lookup),
        # 5. gh api repo contents (write to the default/protected branch)
        ("gh api -X PUT repos/o/r/contents/README.md -f branch=main -f message=x", B, False, feat),
        ("gh api -X PUT repos/o/r/contents/README.md -f message=x", B, False, feat),
        ("gh api --method PATCH repos/o/r/contents/x -F branch=master", B, False, feat),
        ("gh api -X PUT repos/o/r/contents/x -fbranch=main", B, False, feat),
        ("gh api -X PUT repos/o/r/contents/x --field=branch=main", B, False, feat),
        ("gh api -X PUT repos/o/r/contents/x --raw-field branch=main", B, False, feat),
        ("gh api -X PUT repos/o/r/contents/x --input body.json", B, False, feat),
        ("gh api repos/o/r/contents/x -f branch=main -f message=y", B, False, feat),  # fields -> POST
        ("gh api -X DELETE repos/o/r/contents/old.txt -f branch=main -f message=x", B, False, feat),
        ("gh api -X PUT repos/o/r/contents/x -f branch=$B -f message=y", B, False, feat),
        ("gh api -X PUT repos/o/r/contents/x -f branch=krish/../main", B, False, feat),
        ("gh api -X PUT repos/o/r/contents/x -f branch=krish/x -f message=y", A, False, feat),
        ("gh api repos/o/r/contents/README.md", A, False, feat),
        ("gh api repos/o/r/contents/x --jq .sha", A, False, feat),
        # 4. PowerShell iex / Invoke-Expression / Start-Process / scriptblocks
        ("Invoke-Expression 'git push origin main'", B, True, feat),
        ("iex 'git push origin main'", B, True, feat),
        ("'git push origin main' | iex", B, True, feat),
        ("iex -Command 'git push origin main'", B, True, feat),
        ("Start-Process git -ArgumentList 'push','origin','main'", B, True, feat),
        ("saps git -ArgumentList 'push','origin','main'", B, True, feat),
        ("Start-Process -FilePath git -ArgumentList push,origin,main", B, True, feat),
        ("& { git push origin main }", B, True, feat),
        (". { git push origin main }", B, True, feat),
        ("Invoke-Command -ScriptBlock { git push origin main }", B, True, feat),
        ("& git push origin main", B, True, feat),
        ("& 'git' push origin main", B, True, feat),
        ("Get-ChildItem", A, True, feat),
        ("git status", A, True, feat),
        # 3/PS. unquoted Windows backslash paths -> unreadable cwd -> fail closed
        ("cd C:\\Users\\x\\repo; git push", B, True, cd_lookup),
        ("Set-Location C:\\x\\repo; git push", B, True, cd_lookup),
        ("pushd workmain; git push", B, True, cd_lookup),
        ("git -C C:\\x\\repo push", B, True, cd_lookup),
        ("cd C:\\Users\\x\\repo; git push origin krish/x", A, True, cd_lookup),
        ("Set-Location workmain; git push origin krish/x", A, True, cd_lookup),
        # 6. false positive guard: PS backtick line continuation on a feature push
        ("git push origin krish/feat `\n-u", A, True, feat),
        ("git push origin krish/feat `\n--verbose", A, True, feat),
        # --- round 2
        # R1. eval joins its args with spaces
        ("eval git push origin main", B, False, feat),
        ("eval git push origin krish/x", A, False, feat),
        ("iex git push origin main", B, True, feat),
        ("Invoke-Expression git push --force origin x", B, True, feat),
        # R2. nested shells switch POSIX/PowerShell mode (and restore it)
        ("bash -c 'x=`git push origin main`'", B, True, feat),
        ("bash -c 'git push origin ma\\in'", B, True, feat),
        ("sh -c \"git push origin ma\\in\"", B, True, feat),
        ("'git push origin ma\\in' | bash", B, True, feat),
        ("bash -c 'echo hi'; git push origin ma`in", B, True, feat),
        ("bash -c 'echo hi'; cd C:\\x; git status", A, True, feat),
        ("pwsh -c 'echo hi'; git push origin ma\\in", B, False, feat),  # mode restored after pwsh
        ("pwsh -Command \"git push origin ma\\`in\"", B, False, feat),
        ("pwsh -Command \"git push origin krish/x\"", A, False, feat),
        ("bash -c \"pwsh -c 'git push origin ma\\`in'\"", B, False, feat),
        ("echo 'git push origin ma`in' | pwsh -Command -", B, False, feat),
        ("wsl bash -c 'git push origin ma\\in'", B, True, feat),
        ("wsl -d Ubuntu -e git push origin main", B, True, feat),
        ("cmd /d /c git push origin main", B, False, feat),
        ("cmd /c git push origin ma^in", B, False, feat),
        ("cmd /c dir", A, False, feat),
        # R3. eval/iex/&/./Invoke-Command of unreadable code: fail closed if risky
        ("c='git push origin main'; eval $c", B, False, feat),
        ("c='git push origin main'; $c", B, False, feat),
        ("eval $(ssh-agent) && git push origin krish/x", B, False, feat),
        ("$c='git push origin main'; iex $c", B, True, feat),
        ("$sb = { git push origin main }; & $sb", B, True, feat),
        ("$sb=[scriptblock]::Create('git push origin main'); & $sb", B, True, feat),
        ("[scriptblock]::Create('git push origin main').Invoke()", B, True, feat),
        ("$ExecutionContext.InvokeCommand.InvokeScript('git push origin main')", B, True, feat),
        ("$sb=[scriptblock]::Create('git push origin main'); Invoke-Command $sb", B, True, feat),
        ("Start-Job -ScriptBlock $sb; git push origin krish/x", B, True, feat),
        (". $sb; git push origin krish/x", B, True, feat),
        ("eval \"$(ssh-agent -s)\"", A, False, feat),
        ("eval $(ssh-agent)", A, False, feat),
        ("& $env:ComSpec /c dir", A, True, feat),
        ("& $exe --version", A, True, feat),
        ("$EDITOR notes.md", A, False, feat),
        ("ls | % { $_.Name }; git push origin krish/x", A, True, feat),
        # R4. icm, Start-Process positional ArgumentList, `& (expr)`, scriptblocks
        ("icm { git push origin main }", B, True, feat),
        ("icm -ComputerName h { git push origin main }", B, True, feat),
        ("Start-Process git \"push origin main\"", B, True, feat),
        ("Start-Process git push,origin,main", B, True, feat),
        ("Start-Process git \"push origin krish/x\"", A, True, feat),
        ("& (\"git\") push origin main", B, True, feat),
        ("& ('gi'+'t') push origin main", B, True, feat),
        ("& (Get-Command git) push origin main", B, True, feat),
        ("$r = & git push origin main", B, True, feat),
        ("&{git push origin main}", B, True, feat),
        ("if ($true) {git push origin main}", B, True, feat),
        ("1 | % { git push origin main }", B, True, feat),
        ("Start-Job { git push origin main }", B, True, feat),
        ("try { git push origin main } catch { }", B, True, feat),
        ("& (\"git\") status", A, True, feat),
        ("try { git status } catch { Write-Host $_ }", A, True, feat),
        ("git status && git push origin krish/x", A, True, feat),
        # R5. branch-changing commands before a bare push
        ("git checkout -t origin/main && git push", B, False, feat),
        ("git checkout --track origin/master && git push", B, False, feat),
        ("git switch --track=direct origin/main && git push", B, False, feat),
        ("git checkout main -- && git push", B, False, feat),
        ("git symbolic-ref HEAD refs/heads/main && git push", B, False, feat),
        ("git branch -m main && git push", B, False, feat),
        ("git branch -M krish/x main && git push", B, False, feat),
        ("git checkout -t origin/krish/x && git push", A, False, feat),
        ("git checkout -b krish/y -t origin/main && git push", A, False, feat),
        ("git symbolic-ref HEAD refs/heads/krish/x && git push", A, False, feat),
        ("git symbolic-ref --short HEAD", A, False, feat),
        ("git branch -m krish/y && git push", A, False, feat),
        # R6. persisted push-redirecting git config writes are blocked outright
        ("git config push.default matching", B, False, feat),
        ("git config --global push.default upstream", B, False, feat),
        ("git config --local --add remote.origin.push x:main", B, False, feat),
        ("git config --replace-all remote.origin.mirror true", B, False, feat),
        ("git config set push.default matching && git push origin krish/x", B, False, feat),
        ("git config set --append remote.origin.push refs/heads/x:refs/heads/main", B, False, feat),
        ("git config --file .git/config push.default tracking", B, False, feat),
        ("git config branch.krish/x.merge refs/heads/main", B, False, feat),
        ("git config branch.krish/x.merge $M", B, False, feat),
        ("git config include.path /tmp/x", B, False, feat),
        ("git config $K matching", B, False, feat),
        ("git config --rename-section remote.evil remote.origin", B, False, feat),
        ("export GIT_CONFIG_PARAMETERS=\"'push.default=matching'\"; git push origin", B, False, feat),
        ("env GIT_CONFIG_PARAMETERS=\"'push.default=matching'\" git push origin", B, False, feat),
        ("$env:GIT_CONFIG_PARAMETERS = \"'push.default=matching'\"; git push origin", B, True, feat),
        ("git config branch.krish/x.merge refs/heads/krish/x", A, False, feat),
        ("git config branch.krish/x.remote origin", A, False, feat),
        ("git config push.default simple", A, False, feat),
        ("git config remote.origin.mirror false", A, False, feat),
        ("git config --get push.default", A, False, feat),
        ("git config get push.default", A, False, feat),
        ("git config --list", A, False, feat),
        ("git config list", A, False, feat),
        ("git config --unset push.default", A, False, feat),
        ("git config set user.email a@b.c", A, False, feat),
        ("git -c push.default=matching status", A, False, feat),
        ("$env:GIT_CONFIG_NOSYSTEM = 1; git push origin krish/x", A, True, feat),
        # R7. gh api -F branch=@file: value read from a file -> unreadable
        ("gh api -X PUT repos/o/r/contents/x -F branch=@b.txt -f message=x", B, False, feat),
        ("gh api -X PUT repos/o/r/contents/x -Fbranch=@- -f message=x", B, False, feat),
        ("gh api -X PUT repos/o/r/contents/x --field branch=@b.txt", B, False, feat),
        ("gh api -X PUT repos/o/r/contents/x -f branch=@krish -f message=x", A, False, feat),  # -f is raw
        ("gh api -X PUT repos/o/r/contents/x -F branch=krish/x -f message=x", A, False, feat),
        # allow-side musts
        ("cd C:\\x; git status", A, True, feat),
        ("git log main..HEAD", A, True, feat),
        ("git commit -m 'C:\\path main push'", A, True, feat),
        ("Get-ChildItem C:\\Users\\x | Select-Object -First 5", A, True, feat),
    ]
    for cmd, expect, ps, lookup in extra:
        ctx = Ctx(["main", "master"], "/repo", branch_lookup=lookup,
                  alias_lookup=lambda cwd, name: None, powershell=ps)
        reason = decide(cmd, ctx)
        ok = (reason is not None) == expect
        passed += ok
        failed += not ok
        print("%s: %-62s block=%-5s %s" % (
            "PASS" if ok else "FAIL", cmd.replace("\n", "\\n")[:62], reason is not None, reason or ""))

    # timing: a ~2000-token command analyses well under 1s (no ReDoS / blow-up)
    big = "git push origin " + " ".join("krish/b%d" % k for k in range(2000))
    t0 = time.perf_counter()
    decide(big, Ctx(["main", "master"], "/repo", branch_lookup=feat, alias_lookup=lambda c, n: None))
    dt = time.perf_counter() - t0
    ok = dt < 1.0
    passed += ok
    failed += not ok
    print("%s: timing ~2000-token push analysed in %.3fs" % ("PASS" if ok else "FAIL", dt))

    print("\n%d passed, %d failed" % (passed, failed))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
