#!/usr/bin/env python3
"""PreToolUse hook (Bash/PowerShell matcher): blocks pushes/merges/deletes
that would touch protected branches or GitHub. Stdlib only, Python 3.8+.

Reads PreToolUse hook JSON from stdin (tool_input.command, cwd). Exits 2 with
a one-line reason on stderr to block; exits 0 to allow. Non-JSON input or a
tool other than Bash/PowerShell -> exit 0. An internal error while analysing a
command that mentions push/merge/delete -> exit 2 (fail closed).

It is a guardrail, not a sandbox: it parses the shell command the agent is
about to run (quote-aware, recursing into `bash -c`, `pwsh -Command`, `eval`,
`$(...)`) but cannot see into script files or pre-existing shell aliases.
Pair it with GitHub branch protection.

Protected branches: env GUARD_PROTECTED_BRANCHES (comma list), default
"main,master".
"""
import base64
import json
import os
import re
import shlex
import subprocess
import sys

MAX_DEPTH = 6
SUBST = "__GUARD_SUBST_%d__"
SUBST_RE = re.compile(r"__GUARD_SUBST_(\d+)__")
DYNAMIC = "__GUARD_DYNAMIC__"
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


class Block(Exception):
    pass


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
    def __init__(self, protected, cwd=None, branch_lookup=git_current_branch, alias_lookup=git_alias):
        self.protected = [p.lower() for p in protected]
        self.cwd = cwd
        self.branch_lookup = branch_lookup
        self.alias_lookup = alias_lookup

    def is_protected(self, name):
        return name.lower() in self.protected

    def block(self, reason):
        raise Block("Blocked: " + reason)


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


def split_commands(cmd):
    """Quote-aware split on newline ; & | && || ( ). Command and process
    substitutions are pulled out into `subs` and replaced by a placeholder.
    Unquoted `# ...` comments are dropped. Here-doc bodies are data, kept
    in `docs` keyed by segment index (a shell reading stdin runs them).
    Returns (segments, subs, docs)."""
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
        if c == "\\" and i + 1 < n:
            if cmd[i + 1] == "\n":
                i += 2
                continue
            buf.append(cmd[i:i + 2])
            i += 2
            continue
        if c == "$" and cmd.startswith("$(", i):
            i = subst(i + 2, ")")
            continue
        if c == "`":
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
        if c in "\n;&|()":
            flush()
            i += 1
            continue
        buf.append(c)
        i += 1
    flush()
    return segs, subs, docs


def tokenize(seg):
    """shlex(posix) tokens with redirections dropped. None on parse failure."""
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
    segs, subs, docs = split_commands(cmd)
    for s in subs:
        analyze(s, ctx, depth + 1)
    stdin_shell = False
    for idx, seg in enumerate(segs):
        toks = tokenize(seg)
        if toks is None:
            fallback_check(seg, ctx)
            toks = seg.split()
        if run_segment(toks, ctx, subs, depth):
            stdin_shell = True
            for body in docs.get(idx, []):  # `bash <<EOF ... EOF`
                analyze(body, ctx, depth + 1)
    if stdin_shell:
        # `echo "git push origin main" | sh`: the echoed text is the script.
        for seg in segs:
            toks = tokenize(seg) or seg.split()
            if toks and base(toks[0]) in ("echo", "printf"):
                analyze(" ".join(toks[1:]), ctx, depth + 1)


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


def run_segment(toks, ctx, subs, depth):
    """Analyse one simple command. Returns True if it is a shell that reads
    its script from stdin."""
    toks = strip_prefixes(list(toks), ctx, depth)
    if not toks:
        return False
    head = base(toks[0])
    rest = toks[1:]

    if head == "cd" and rest and not is_dynamic(rest[0]):
        ctx.cwd = os.path.join(ctx.cwd or os.getcwd(), rest[0])
        return False
    if head == "eval":
        analyze(" ".join(rest), ctx, depth + 1)
        return False
    if head in SHELLS:
        return shell_c(rest, ctx, depth)
    if head in PWSH:
        return pwsh_c(rest, ctx, depth)
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
    if head == "cmd" and rest and rest[0].lower() in ("/c", "/k"):
        analyze(" ".join(rest[1:]), ctx, depth + 1)
        return False
    if head == "git":
        check_git(rest, ctx, subs, depth)
    elif head == "gh":
        check_gh(rest, ctx)
    elif is_dynamic(toks[0]) and any(t in ("push", "merge", "delete") for t in rest):
        # `$GIT push origin main`: unknown binary, assume the worst.
        check_git(rest, ctx, subs, depth)
        check_gh(rest, ctx)
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
        analyze(operands[0], ctx, depth + 1)
        return False
    if not operands or operands[0] == "-" or "s" in "".join(t for t in rest[:i] if t.startswith("-")):
        return True  # reads script from stdin
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
                analyze(script, ctx, depth + 1)
            return False
        if t in ("-c", "-command", "-cwa", "-commandwithargs") or (len(t) > 2 and "-command".startswith(t)):
            script = " ".join(rest[i + 1:])
            if script.strip() == "-":
                return True
            analyze(script, ctx, depth + 1)
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
        analyze(" ".join(rest[i:]), ctx, depth + 1)  # 5.1 defaults to -Command
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
        if t in GIT_ARG_OPTS and i + 1 < len(args):
            v = args[i + 1]
            if t == "-C" and not is_dynamic(v):
                cwd = os.path.join(cwd or os.getcwd(), v)
            if t == "-c" and v.lower().startswith("alias.") and "=" in v:
                k, val = v.split("=", 1)
                inline_aliases[k[6:]] = val
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
        branch = ctx.branch_lookup(cwd)
        if branch and ctx.is_protected(branch):
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


def check_gh_api(args, ctx):
    method, has_fields, endpoint, i = None, False, None, 0
    while i < len(args):
        t = args[i]
        opt, eq, val = t.partition("=")
        if t.startswith("-") and opt in GH_API_ARG_OPTS:
            if not eq:
                val = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            if opt in ("-X", "--method"):
                method = val.upper()
            if opt in ("-f", "--raw-field", "-F", "--field", "--input"):
                has_fields = True
        elif t.startswith("-X") and len(t) > 2:
            method = t[2:].upper()
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
    if m and write and (ctx.is_protected(ref) or is_dynamic(ref)):
        ctx.block("gh api %s on a protected branch ref is not allowed." % method)
    m = re.search(r"(^|/)branches/(.+)/protection(/|$)", ep)
    ref = strip_ref(m.group(2)) if m else None
    if m and write and (ctx.is_protected(ref) or is_dynamic(ref)):
        ctx.block("gh api %s on branch protection is not allowed." % method)
    if re.fullmatch(r"repos/[^/]+/[^/]+", ep) and method == "DELETE":
        ctx.block("gh api DELETE on a repo is not allowed.")
    if ep == "graphql" and any(GRAPHQL_MUTATIONS.search(a) for a in args):
        ctx.block("gh api graphql merge/ref/repo mutation is not allowed.")


# ---------------------------------------------------------------- entry

def decide(command, ctx):
    """Return a block reason, or None to allow. Fails closed on internal
    errors when the command mentions push/merge/delete."""
    try:
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
        if data.get("tool_name") not in ("Bash", "PowerShell"):
            sys.exit(0)
        command = (data.get("tool_input") or {}).get("command")
        cwd = data.get("cwd")
    except Exception:
        sys.exit(0)  # not hook JSON: nothing to guard
    if not isinstance(command, str) or not command:
        sys.exit(0)
    reason = decide(command, Ctx(protected_branches(), cwd))
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

    print("\n%d passed, %d failed" % (passed, failed))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
