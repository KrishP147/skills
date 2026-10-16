#!/usr/bin/env python3
"""PreToolUse hook: blocks known billable commands/MCP tool calls unless an
approval already exists. Stdlib only, Python 3.8+.

Reads PreToolUse hook JSON from stdin (tool_name, tool_input.command for
Bash and PowerShell, cwd). Exits 2 with a one-line reason on stderr to block; exits 0 to
allow. Never raises into a block of unrelated work - any error while
matching or loading config fails OPEN (allow), since the cost of a hook bug
blocking unrelated commands is worse than the cost of missing one billable
pattern; this hook is a safety net for the spend-gate skill's own steps, not
the only line of defense.

Billable patterns (extend, don't replace, with your own):
  - env SPEND_GUARD_PATTERNS: entries separated by ";" (regexes may contain
    commas, so ";" is the separator, not ",").
  - file .claude/spend-guard-patterns.txt (relative to the tool call's cwd):
    one entry per line.
Entry format for both: optional "bash:" or "mcp:" prefix, default "bash:".
  bash:<regex>   - re.search'd, case-insensitive, against the Bash command
  mcp:<glob>     - fnmatch'd, case-insensitive, against tool_name
Blank lines and lines starting with # are ignored.

Indirect forms (indirect_billable): the patterns are also run on rewrites
of the command, so a billable call hidden behind indirection still blocks:
aliases, functions and variables defined in the same command (bash
`alias`/`f(){..}`/`X=..`, PowerShell `Set-Alias`/`function`/`$X=..`)
substituted into their call sites; `Start-Process`/`saps`/`start` params
reassembled; quote/backtick/brace noise stripped; base64 (`-EncodedCommand`,
`base64 -d`) decoded. Also blocked: REST/GraphQL writes to provider APIs
(Runpod REST/GraphQL/serverless, Vultr, EC2 `Action=RunInstances`, GCE,
Azure VMs) and SDK one-liners (`python -c "import runpod;
runpod.create_pod(..)"`, boto3 `run_instances`, ...). Fallback: in a command
that mentions a billable program, a call target or verb argument held in a
variable whose value can't be read (`$X create pod`, `runpodctl $VERB`,
`eval "$C"`, `xargs runpodctl`) blocks. False positives are cheap here,
false negatives are not. Inline approval never covers these forms.

Approval (either one allows the single matched action):
  1. File-based, one-shot: drop a file into skilleddocs/spend-approvals/
     (relative to cwd; override the directory with
     SPEND_GATE_APPROVALS_DIR). The filename is just a label - contents are
     ignored. Names starting with "." (.gitkeep, .DS_Store) never count.
     The hook consumes (deletes) the first one it finds (sorted by name)
     and allows that single call; the log is skilleddocs/spend.md. A call
     with two or more billable commands is refused, file left in place.
  2. SPEND_GATE_APPROVED=<label>, two ways to set it:
       - PowerShell only: start the command with
         `$env:SPEND_GATE_APPROVED='<label>'; <cmd>` (leading only, `;`
         required, non-empty value). Bash-style prefixes are not honoured.
       - Bash only: prefix the single command, e.g.
         `SPEND_GATE_APPROVED=yes runpodctl create pod ...` (or after a
         bare `env`) - this is a shell per-command env assignment, so it is
         read out of the command string itself (this hook does not execute
         the command) and only ever covers that one invocation.
       Both inline forms count only when the rest is ONE simple command
       (no ;, &&, ||, |, &, newline, subshell, $(...) or backticks) whose
       program is the call's only billable match: `true && <create>`,
       `<create>; <create>`, `bash -c '<create>'` are not approved.
       - Process env: only if set when Claude Code was launched (`export`
         inside a Bash tool call never reaches this hook). Approves every
         matching call for the session - avoid; use the approval file for
         MCP tool calls.

Tripwire, not a security boundary: an agent that can write files can write
its own approval. It catches a skipped gate, not a hostile agent.
"""
import fnmatch
import json
import os
import re
import sys

# runpodctl prefix: binary (optionally .exe/.cmd/quoted) plus any global
# flags before the noun (`--profile x`, `--output=json`, `-o json`, `--`). A
# space-separated flag value may not be a noun/verb word, so it cannot
# swallow the real noun. Each token has exactly one parse (no overlapping
# dash runs, values never start with "-"), so a long non-matching flag run
# fails in linear time instead of backtracking exponentially.
_RP_NOUN = r"""(?:pods?|serverless|sls|network-volume|nv|model|template|registry|hub|create|start)(?![\w-])"""
_RP = (r"""\brunpodctl(?:\.exe|\.cmd)?["']?\s+(?:(?:--?\w[\w-]*(?:=\S*|\s+(?!-)(?!"""
       + _RP_NOUN
       + r""")(?:"[^"]*"|'[^']*'|[^\s"'-]\S*))?|--)\s+)*""")



def _flags(stops):
    """Global flags (with values, `--f=v`) as in _RP; a space-separated value
    may not be one of `stops` (service/track words), so it can't swallow them."""
    return (r"""(?:(?:--?\w[\w-]*(?:=\S*|\s+(?!-)(?!(?:""" + stops + r""")(?![\w-]))"""
            r"""(?:"[^"]*"|'[^']*'|[^\s"'-]\S*))?|--)\s+)*""")


def _cli(binary, stops):
    """aws/gcloud/az binary plus global flags before the service (#202)."""
    return r"""\b""" + binary + r"""(?:\.exe|\.cmd)?["']?\s+""" + _flags(stops)


_GC_STOPS = "compute|alpha|beta|preview"
_AWS = _cli("aws", "ec2")
_GCLOUD = _cli("gcloud", _GC_STOPS) + r"""(?:(?:alpha|beta|preview)\s+""" + _flags(_GC_STOPS) + ")?"
_AZ = _cli("az", "vm")

DEFAULT_BASH_PATTERNS = [
    _RP + r"""(?:(?:pods?|serverless|sls|network-volume|nv)\s+)?(?:create|start)(?![\w-])""",
    _RP + r"""(?:network-volume|nv)\s+update\b[^\n]*--size\b""",
    _RP + r"""(?:serverless|sls)\s+update\b""",
    _RP + r"""(?:serverless|sls)\s+run\b""",
    _RP + r"""pods?\s+update\b[^\n]*--(?:volume-in-gb|container-disk-in-gb)\b""",
    _RP + r"""model\s+add\b""",
    r"""\bvultr-cli(?:\.exe|\.cmd)?["']?\s+instance\s+create\b""",
    _AWS + r"""ec2\s+(?:run-instances|request-spot-instances|request-spot-fleet"""
    r"""|start-instances)\b""",
    _GCLOUD + r"""compute\s+instances\s+(?:create|start|bulk\s+create)\b""",
    _AZ + r"""vm\s+(?:create|start)\b""",
    r"""\bmodal(?:\.exe|\.cmd)?["']?\s+(?:deploy|run)\b""",
]

# Deliberately not defaulted (ambiguous - has free tiers / non-billable uses):
# `fly deploy`. Add it yourself via SPEND_GUARD_PATTERNS or the patterns file
# if your fly.io usage is always billable.

# Runpod MCP create-* tools that only write free config/credential records,
# exempt from the default create-* glob below: create-template (pod/endpoint
# config), create-secret (stored secret), create-registry (container
# registry auth), create-delegation (access delegation). Still blocked:
# create-pod, create-endpoint, create-cluster (compute bills) and
# create-network-volume, create-global-volume (storage bills). The
# exemption applies only to the default glob; a user mcp: glob naming one
# of these still blocks it. Other providers' create-* are unaffected.
RUNPOD_FREE_CREATE_TOOLS = (
    "create-template", "create-secret", "create-registry", "create-delegation",
)
RUNPOD_CREATE_GLOB = "mcp__*runpod*__create-*"

DEFAULT_MCP_GLOBS = [
    RUNPOD_CREATE_GLOB,
    "mcp__*runpod*__deploy-*",
    "mcp__*runpod*__run-endpoint",
    "mcp__*runpod*__runsync-endpoint",
    "mcp__*runpod*__retry-job",
    "mcp__*runpod*__update-endpoint",
    "mcp__*runpod*__set-endpoint-gpus",
]

# pod-action carries the verb in its input: only starting/resuming a pod
# bills, so it is a small special case rather than a plain glob.
POD_ACTION_GLOB = "mcp__*runpod*__pod-action"
POD_BILLABLE_ACTIONS = ("start", "resume")

# update-network-volume body {name?, size?}: a resize bills more storage, a
# rename does not. Blocks whenever body has a "size" key (even equal to the
# current size: the hook cannot know it). update-global-volume is NOT gated:
# it only takes a name, nothing billable to change.
NETVOL_UPDATE_GLOB = "mcp__*runpod*__update-network-volume"

# update-pod body: only storage keys bill. The live v2 UpdatePodRequest
# sizes storage via "disk" (container disk GB) and "mounts.persistent.size",
# and "templateId" applies a template's disk; "volumeInGb"/
# "containerDiskInGb" are the v1 names, kept in case an older server is
# wired up. name/image/env/ports and network/global mounts do not bill.
POD_UPDATE_GLOB = "mcp__*runpod*__update-pod"
POD_UPDATE_BILLABLE_KEYS = ("disk", "templateId", "volumeInGb", "containerDiskInGb")

PATTERNS_FILE_REL = os.path.join(".claude", "spend-guard-patterns.txt")
APPROVALS_DIR_REL = os.path.join("skilleddocs", "spend-approvals")


def parse_pattern_lines(lines):
    """Split lines into (bash_regexes, mcp_globs). Bad regexes are skipped,
    not fatal - see module docstring on failing open."""
    bash_patterns = []
    mcp_globs = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("mcp:"):
            mcp_globs.append(line[len("mcp:"):].strip())
        elif line.startswith("bash:"):
            pat = line[len("bash:"):].strip()
            if _valid_regex(pat):
                bash_patterns.append(pat)
        else:
            if _valid_regex(line):
                bash_patterns.append(line)
    return bash_patterns, mcp_globs


def _valid_regex(pat):
    try:
        re.compile(pat)
        return True
    except re.error:
        return False


def load_extra_patterns(cwd, env=None):
    """Extra (bash_regexes, mcp_globs) from SPEND_GUARD_PATTERNS and the
    per-repo patterns file. Any error here fails open (returns what was
    parsed so far, or empty lists)."""
    env = os.environ if env is None else env
    bash_patterns = []
    mcp_globs = []
    try:
        env_val = env.get("SPEND_GUARD_PATTERNS")
        if env_val:
            b, m = parse_pattern_lines(env_val.split(";"))
            bash_patterns.extend(b)
            mcp_globs.extend(m)
    except Exception:
        pass
    try:
        if cwd:
            path = os.path.join(cwd, PATTERNS_FILE_REL)
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    b, m = parse_pattern_lines(f.readlines())
                bash_patterns.extend(b)
                mcp_globs.extend(m)
    except Exception:
        pass
    return bash_patterns, mcp_globs


def match_billable(tool_name, command, bash_patterns, mcp_globs, n_default_mcp=0):
    """Return a (reason, matched) tuple, or (None, None) if nothing matches.
    The first n_default_mcp globs are the defaults (RUNPOD_FREE_CREATE_TOOLS
    exemption applies to those only). Never raises - errors fail open."""
    try:
        if tool_name in ("Bash", "PowerShell"):
            if not command:
                return None, None
            for pat in bash_patterns:
                if re.search(pat, command, re.IGNORECASE):
                    return (
                        "command matches billable pattern '%s'" % pat,
                        pat,
                    )
            return None, None
        if tool_name:
            for i, glob in enumerate(mcp_globs):
                if (i < n_default_mcp and glob == RUNPOD_CREATE_GLOB
                        and _runpod_free_create(tool_name)):
                    continue  # default glob only; see RUNPOD_FREE_CREATE_TOOLS
                if fnmatch.fnmatch(tool_name.lower(), glob.lower()):
                    return (
                        "tool '%s' matches billable MCP pattern '%s'" % (tool_name, glob),
                        glob,
                    )
        return None, None
    except Exception:
        return None, None


def _runpod_free_create(tool_name):
    """True if tool_name is a runpod MCP tool whose name after the last
    "__" is one of RUNPOD_FREE_CREATE_TOOLS."""
    return (fnmatch.fnmatch(tool_name.lower(), RUNPOD_CREATE_GLOB)
            and tool_name.lower().rsplit("__", 1)[-1] in RUNPOD_FREE_CREATE_TOOLS)


def billable_spans(command, bash_patterns):
    """Billable matches in command as merged (start, end) spans: overlapping
    matches of different patterns (a user pattern repeating a default) count
    once; two separate billable commands are two spans. Errors skip that
    pattern (the caller treats too few spans as "not approvable")."""
    spans = []
    for pat in bash_patterns:
        try:
            for m in re.finditer(pat, command, re.IGNORECASE):
                spans.append((m.start(), max(m.end(), m.start() + 1)))
        except Exception:
            continue
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _simple_command_tokens(command, start, shell):
    """Split command[start:] into whitespace-separated (start, end) token
    spans, quote-aware. Return None unless it is ONE simple command: any
    unquoted separator, pipe, background `&`, newline, subshell/group or
    substitution (`;` `|` `&` `(` `)` newline, backtick; PowerShell also `{`
    `}`), `$(` inside double quotes, or an unbalanced quote fails closed.
    Redirections stay allowed, including `2>&1`, `&>` and `>&`."""
    toks = []
    tok_start = None
    quote = None
    i = start
    n = len(command)
    meta = ";|()\n\r`" + ("{}" if shell == "ps" else "")
    while i < n:
        c = command[i]
        if quote == "'":
            if c == "'":
                quote = None
            i += 1
            continue
        if quote == '"':
            if c == '"':
                quote = None
            elif c == "`":
                return None
            elif c == "$" and command[i + 1:i + 2] == "(":
                return None
            elif c == "\\" and shell == "bash":
                i += 1
            i += 1
            continue
        if c in " \t":
            if tok_start is not None:
                toks.append((tok_start, i))
                tok_start = None
            i += 1
            continue
        if c in meta:
            return None
        if c == "#" and tok_start is None:
            # comment to end of line; a later line would be a new command
            if "\n" in command[i:] or "\r" in command[i:]:
                return None
            break
        if shell == "bash" and c == "$" and command[i + 1:i + 2] in ("'", '"'):
            return None  # $'...' / $"..." quote rules differ; fail closed
        if c == "&":
            prev = command[i - 1] if i > start else ""
            nxt = command[i + 1:i + 2]
            ps_call = shell == "ps" and not toks and tok_start is None
            if not (prev in "<>" and prev) and nxt != ">" and not ps_call:
                return None
        if tok_start is None:
            tok_start = i
        if c in "'\"":
            quote = c
        elif c == "\\" and shell == "bash":
            if command[i + 1:i + 2] in ("\n", "\r"):
                return None
            i += 1
        i += 1
    if quote is not None:
        return None
    if tok_start is not None:
        toks.append((tok_start, n))
    return toks


def _one_span_in_head(spans, head):
    """True if there is exactly one billable span and it starts inside the
    head token (the program actually run), so the approval cannot land on a
    no-op or on text passed to `bash -c`, `xargs`, `echo` and the like."""
    return len(spans) == 1 and head[0] <= spans[0][0] < head[1]


_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)


def inline_env_approved(command, spans=None):
    """True if the Bash command is ONE simple command carrying a per-command
    SPEND_GATE_APPROVED=<value> assignment in its leading assignment run
    (optionally after a bare `env`), and the only billable match is that
    command's program, e.g. `SPEND_GATE_APPROVED=yes runpodctl create pod`
    or `env SPEND_GATE_APPROVED=yes runpodctl create pod` (same scope: one
    process). Anything compound (`&&`, `;`, `|`, `$(...)`, subshell,
    `bash -c '...'`, two billable commands, `export X=y; ...`) is not
    approved. The value must be a non-empty literal (no `$`). This hook
    never executes the command, so it reads the assignment from the
    string."""
    if not command:
        return False
    try:
        if spans is None:
            spans = billable_spans(command, DEFAULT_BASH_PATTERNS)
        toks = _simple_command_tokens(command, 0, "bash")
        if not toks:
            return False
        approved = False
        seen_env = False
        for a, b in toks:
            raw = command[a:b]
            m = _ASSIGN_RE.match(raw)
            if m:
                key, val = m.group(1), m.group(2)
                if key == "SPEND_GATE_APPROVED":
                    approved = (bool(val.strip("'\"")) and "$" not in val)
                continue
            if not seen_env and (raw == "env" or raw.endswith("/env")):
                seen_env = True
                continue
            return approved and _one_span_in_head(spans, (a, b))
        return False
    except Exception:
        return False


_PS_INLINE_RE = re.compile(
    r"""^\s*\$env:SPEND_GATE_APPROVED\s*=\s*(?:'[^']+'|"[^"$`]+"|[^\s;'"$`]+)\s*;""",
    re.IGNORECASE,
)


def powershell_inline_approved(command, spans=None):
    """True if the PowerShell command starts with
    `$env:SPEND_GATE_APPROVED='<label>';` (single, double or no quotes,
    non-empty literal value, `;` required) and what follows is ONE simple
    command (optionally `& <path>`) whose program is the only billable
    match: a second `;`, a pipe, `&&`/`||`, `(...)`/`$(...)`/`{...}`, a
    newline or a second billable command is not approved. A `$` in an
    unquoted or double-quoted value is rejected: `$null`/`"$x"` may expand
    to empty. Only a leading assignment counts, never one mid-string.
    Bash-style `VAR=val cmd` is not valid PowerShell, so it is deliberately
    not honoured here."""
    if not command:
        return False
    try:
        m = _PS_INLINE_RE.match(command)
        if not m:
            return False
        if spans is None:
            spans = billable_spans(command, DEFAULT_BASH_PATTERNS)
        toks = _simple_command_tokens(command, m.end(), "ps")
        if not toks:
            return False
        head = toks[0]
        if command[head[0]:head[1]] == "&":
            if len(toks) < 2:
                return False
            head = toks[1]
        return _one_span_in_head(spans, head)
    except Exception:
        return False


# --- issue #160: indirection, Start-Process, REST and SDK billers ---------
#
# The default patterns read the command text literally. indirect_billable()
# also checks rewritten "variants" of the command, plus a few rules of its
# own, so a billable call hidden behind an alias, function, variable,
# Start-Process, encoding, REST call or SDK one-liner still blocks:
#   1. definitions read from the command itself (bash `X=v`, `alias r=v`,
#      `f(){ ...; }`, `function f {...}`; PowerShell `$X = v`, `Set-Alias`,
#      `function f {...}`) are substituted back into their call sites and
#      the patterns re-run on the result;
#   2. Start-Process/saps/start params are reassembled into `<file> <args>`;
#   3. quote, comma, paren and backtick noise is stripped (`'run''podctl'`,
#      `{runpodctl,create,pod}`, `` r`unpodctl ``), `$'\x72...'` decoded and
#      base64 (`-EncodedCommand`, `base64 -d`) decoded;
#   4. REST/GraphQL writes to provider APIs and SDK one-liners block;
#   5. fallback: a call target (or the first args of a billable CLI) that is
#      a variable with no readable definition blocks when the command
#      mentions a billable program. False positives are cheap here, false
#      negatives are not.
# Every rule is a regex scan or a single linear pass; the number of variants
# and definitions is capped so a long command stays well under a second.

_PROG_RE = r"(?:runpodctl|vultr-cli|aws|gcloud|az|modal)"
_PROG_WORD_RE = re.compile(
    r"(?<![\w.$@-])(" + _PROG_RE + r")(?:\.exe|\.cmd)?(?![\w.-])", re.I)
_MENTION_RE = re.compile(
    r"(?<![\w.-])" + _PROG_RE + r"(?:\.exe|\.cmd)?(?![\w.-])"
    r"|\brunpod\b|\bboto3\b|runpod\.(?:io|ai)\b|api\.vultr\.com"
    r"|amazonaws\.com|compute\.googleapis\.com|management\.azure\.com", re.I)

_MAX_DEFS = 64
_MAX_VARIANT_GROWTH = 8

# bash NAME=value (quoted parts, $(...), backticks, plain chars, repeated)
_BASH_ASSIGN_RE = re.compile(
    r"""(?:^|(?<=[\s;&|(){}`]))([A-Za-z_]\w*)=((?:'[^']*'|"(?:[^"\\]|\\.)*"|\$\([^)]*\)|`[^`]*`|\$(?!\()|[^\s;&|()`'"$])*)""")
# PowerShell $X = value / $env:X = value (to end of statement)
_PS_ASSIGN_RE = re.compile(
    r"""\$\{?(?:(?:env|global|script|local|private|using):)?([A-Za-z_]\w*)\}?[ \t]*=(?!=)[ \t]*([^;\n\r]*)""",
    re.I)
_FUNC_DEF_RE = re.compile(
    r"""(?:(?<![\w-])(?:function|filter)\s+([\w.:-]+)\s*(?:\([^)]*\))?|(?<![\w$@.:\\/-])([A-Za-z_][\w.:-]*)\s*\(\s*\))\s*([{(])""",
    re.I)
_PS_FUNC_PROVIDER_RE = re.compile(r"""(?<![\w-])function:([\w.-]+)\}?""", re.I)
_BASH_ALIAS_RE = re.compile(r"""(?<![\w-])alias\s+([^;\n\r|&]*)""")
_ALIAS_TOKEN_RE = re.compile(r"""([\w.:-]+)=('[^']*'|"[^"]*"|\S*)""")
_PS_ALIAS_RE = re.compile(r"""(?<![\w-])(?:Set-Alias|New-Alias|sal|nal)\s+([^;\n\r|]*)""", re.I)
_PS_ALIAS_PROVIDER_RE = re.compile(r"""(?<![\w-])alias:([\w.-]+)\}?([^;\n\r|]*)""", re.I)
_TOKEN_RE = re.compile(r"""'[^']*'|"[^"]*"|[^\s,]+""")

_VAR_REF_RE = re.compile(
    r"""\$\{([^}\s{$]{0,200})\}|\$(?:(?:env|global|script|local|private|using):)?([A-Za-z_]\w*)|(?<=\s)@([A-Za-z_]\w*)|%([A-Za-z_]\w*)%""",
    re.I)
_FORWARD_RE = re.compile(r"""["']?(?:\$@|\$\*|\$\{@\}|\$\{\*\}|@args|\$args|\$input)["']?""", re.I)
_POSARG_RE = re.compile(r"""\$\{?([1-9])\}?|\$args\[(\d)\]""", re.I)


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


def _brace_end(s, i):
    """Index of the bracket closing s[i] ({ or (), or len(s)."""
    open_c = s[i]
    close_c = "}" if open_c == "{" else ")"
    depth = 0
    for m in re.finditer(re.escape(open_c) + "|" + re.escape(close_c), s[i:]):
        depth += 1 if m.group(0) == open_c else -1
        if depth == 0:
            return i + m.start()
    return len(s)


def _parse_defs(command):
    """Return (vars, funcs, def_spans). vars: lower name -> set of values;
    funcs: lower name -> list of bodies (aliases are bodies too); def_spans:
    (start, end) of function/alias definitions, blanked before call-site
    expansion so a definition is not mistaken for a call."""
    vars_ = {}
    funcs = {}
    spans = []

    def add_var(name, val):
        if len(vars_) < _MAX_DEFS or name.lower() in vars_:
            vars_.setdefault(name.lower(), set()).add(val)

    def add_func(name, body, span):
        if len(funcs) < _MAX_DEFS or name.lower() in funcs:
            funcs.setdefault(name.lower(), []).append(body)
            spans.append(span)

    for m in _BASH_ASSIGN_RE.finditer(command):
        add_var(m.group(1), _unquote(m.group(2)))
    for m in _PS_ASSIGN_RE.finditer(command):
        add_var(m.group(1), _unquote(m.group(2)))
    for m in _FUNC_DEF_RE.finditer(command):
        name = m.group(1) or m.group(2)
        if name.lower() in ("if", "while", "for", "foreach", "until", "switch",
                            "elif", "select", "case"):
            continue
        end = _brace_end(command, m.start(3))
        add_func(name, command[m.end(3):end], (m.start(), end + 1))
    for m in _PS_FUNC_PROVIDER_RE.finditer(command):
        rest = command[m.end():]
        stop = re.search(r"[;\n\r]", rest)
        brace = rest.find("{")
        if brace != -1 and (stop is None or brace < stop.start()):
            end = _brace_end(rest, brace)
            add_func(m.group(1), rest[brace + 1:end], (m.start(), m.end() + end + 1))
        else:
            seg = rest[:stop.start()] if stop else rest
            add_func(m.group(1), seg, (m.start(), m.end() + len(seg)))
    for m in _BASH_ALIAS_RE.finditer(command):
        for t in _ALIAS_TOKEN_RE.finditer(m.group(1)):
            add_func(t.group(1), _unquote(t.group(2)) + ' "$@"', (m.start(), m.end()))
    for m in _PS_ALIAS_RE.finditer(command):
        name = value = None
        toks = _TOKEN_RE.findall(m.group(1))
        i = 0
        pos = []
        while i < len(toks):
            t = toks[i]
            tl = t.lower()
            if tl.startswith("-n"):
                name = toks[i + 1] if i + 1 < len(toks) else None
                i += 2
                continue
            if tl.startswith("-v"):
                value = toks[i + 1] if i + 1 < len(toks) else None
                i += 2
                continue
            if tl.startswith(("-s", "-o", "-d")):
                i += 2
                continue
            if tl.startswith("-"):
                i += 1
                continue
            pos.append(t)
            i += 1
        if name is None and pos:
            name = pos.pop(0)
        if value is None and pos:
            value = pos.pop(0)
        if name and value:
            add_func(_unquote(name), _unquote(value) + " @args", (m.start(), m.end()))
    for m in _PS_ALIAS_PROVIDER_RE.finditer(command):
        toks = [t for t in _TOKEN_RE.findall(m.group(2)) if not t.startswith("-")]
        if toks:
            add_func(m.group(1), _unquote(toks[0]) + " @args", (m.start(), m.end()))
    return vars_, funcs, spans


def _subst_vars(text, vars_):
    """Replace $X / ${X} / $env:X / @X with X's value when X has exactly one
    readable definition; others are left in place (unresolved)."""
    def rep(m):
        raw = m.group(1)
        if raw is not None:
            name = raw.split(":", 1)[-1] if ":" in raw else raw
            if not re.match(r"^[A-Za-z_]\w*$", name):
                return m.group(0)
        else:
            name = m.group(2) or m.group(3) or m.group(4)
        vals = vars_.get(name.lower())
        if vals and len(vals) == 1:
            return next(iter(vals))
        return m.group(0)
    out = text
    limit = len(text) * _MAX_VARIANT_GROWTH + 4096
    for _ in range(3):
        new = _VAR_REF_RE.sub(rep, out)
        if new == out or len(new) > limit:
            break
        out = new
    return out


def _posarg(pm, argv):
    idx = int(pm.group(1)) if pm.group(1) else int(pm.group(2)) + 1
    return argv[idx - 1] if idx <= len(argv) else ""


def _expand_calls(text, funcs, prog_only):
    """Replace each call of a defined function/alias with its body (args
    spliced into $@/$*/$1../@args/$args), or with only the billable program
    its body names when prog_only."""
    names = sorted(funcs, key=len, reverse=True)
    if not names:
        return text
    call_re = re.compile(
        r"(?<![\w$@.:/\\-])(" + "|".join(re.escape(n) for n in names)
        + r")(?![\w.:/\\-])([^;&|\n\r)}]*)", re.I)

    def rep(m):
        args = m.group(2)
        bodies = funcs.get(m.group(1).lower()) or []
        if prog_only:
            for body in bodies:
                p = _PROG_WORD_RE.search(body)
                if p:
                    return p.group(0) + args
            return m.group(0)
        parts = []
        argv = args.split()
        for body in bodies:
            b = _FORWARD_RE.sub(lambda _m: " " + args + " ", body)
            b = _POSARG_RE.sub(lambda pm: _posarg(pm, argv), b)
            parts.append(b)
        return " ; ".join(parts) if parts else m.group(0)

    out = text
    limit = len(text) * _MAX_VARIANT_GROWTH + 4096
    for _ in range(3):
        new = call_re.sub(rep, out)
        if new == out or len(new) > limit:
            break
        out = new
        if prog_only:
            break
    return out


def _blank_spans(text, spans):
    if not spans:
        return text
    chars = list(text)
    for a, b in spans:
        for i in range(max(a, 0), min(b, len(chars))):
            chars[i] = " "
        if 0 <= a < len(chars):
            chars[a] = ";"
    return "".join(chars)


_START_PROC_RE = re.compile(r"(?<![\w-])(?:Start-Process|saps|start)(?![\w-])([^;\n\r|]*)", re.I)


def _start_process_variant(text):
    """`Start-Process [-FilePath] f [-ArgumentList] a,b ...` -> `f a b`, one
    line per occurrence, so the default patterns can read it."""
    out = []
    for m in _START_PROC_RE.finditer(text):
        toks = _TOKEN_RE.findall(m.group(1))
        fp = None
        args = []
        in_args = False
        i = 0
        while i < len(toks):
            t = toks[i]
            tl = t.lower()
            if tl.startswith("-") and len(tl) > 1 and tl[1].isalpha():
                in_args = False
                if tl.startswith("-f"):
                    if i + 1 < len(toks):
                        fp = toks[i + 1]
                    i += 2
                    continue
                if tl.startswith("-a"):
                    in_args = True  # following tokens are arguments
                    i += 1
                    continue
                if tl.startswith(("-wa", "-n", "-p", "-u", "-l")):
                    i += 1
                    continue  # switch
                if tl.startswith(("-w", "-v", "-r", "-c", "-e")):
                    i += 2
                    continue  # param with a value
                i += 1
                continue
            if fp is None and not in_args:
                fp = t
            else:
                args.append(t)
            i += 1
        if fp:
            out.append(" ".join(_unquote(t) for t in [fp] + args))
    return "\n".join(out)


_B64_GATE_RE = re.compile(r"base64|FromBase64String|(?<![\w-])-(?:e|ec|en|enc\w*)(?![\w-])", re.I)
_B64_TOKEN_RE = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


def _b64_variant(text):
    """Decoded base64 tokens (UTF-16LE for -EncodedCommand, else UTF-8),
    only when the command decodes base64 at all."""
    if not _B64_GATE_RE.search(text):
        return ""
    import base64
    out = []
    for m in list(_B64_TOKEN_RE.finditer(text))[:200]:
        tok = m.group(0)
        try:
            raw = base64.b64decode(tok + "=" * (-len(tok) % 4), validate=True)
        except Exception:
            continue
        # UTF-16LE (-EncodedCommand) only when every high byte is zero
        wide = len(raw) >= 2 and len(raw) % 2 == 0 and not raw[1::2].strip(b"\x00")
        for enc in (("utf-16-le",) if wide else ("utf-8",)):
            try:
                s = raw.decode(enc)
            except Exception:
                continue
            if s and sum(c.isprintable() or c in "\r\n\t" for c in s) >= 0.9 * len(s):
                out.append(s)
                break
    return "\n".join(out)


_ANSI_C_RE = re.compile(r"\$'((?:[^'\\]|\\.)*)'")
_CONCAT_RE = re.compile(r"""['"]\s*\+\s*['"]""")


def _normalize(text):
    """Strip quoting/grouping noise: `'run''podctl'`, `"run"podctl`,
    `('run'+'podctl')`, `{runpodctl,create,pod}`, PowerShell backtick
    escapes, `$'\\x72unpodctl'`, and arg forwarders."""
    def ansi(m):
        try:
            import codecs
            return codecs.decode(m.group(1), "unicode_escape")
        except Exception:
            return m.group(1)
    t = _ANSI_C_RE.sub(ansi, text)
    t = _CONCAT_RE.sub("", t)
    t = _FORWARD_RE.sub(" ", t)
    t = re.sub(r"\)\.(?:Source|Path|Definition|Name)\b", ")", t, flags=re.I)  # (gcm x).Source
    t = re.sub(r"""\$\(\s*\)|``|['"`]""", "", t)
    t = re.sub(r"[(){},@\[\]]", " ", t)
    return t


def _norms(v):
    """_normalize(v), plus a copy without backslashes (bash `r\\unpodctl`;
    kept apart so a Windows path keeps its word boundary in the first)."""
    n = _normalize(v)
    return [n, n.replace("\\", "")] if "\\" in n else [n]


# --- REST / GraphQL ---------------------------------------------------------
# Write = an explicit POST/PUT/PATCH anywhere, or a body flag (curl -d,
# --data*, --json, -F, -T; wget --post-*; PowerShell -Body/-InFile; python
# data=/json=). Case-sensitive for the short curl flags (-f is --fail).
_WRITE_RE = re.compile(
    r"""(?i:(?<![\w-])(?:-X)?(?:POST|PUT|PATCH)(?![\w-]))"""
    r"""|(?<![\w-])-[a-zA-Z]{0,3}[dFT](?=[\s=@'"{]|$)"""
    r"""|(?i:(?<![\w-])(?:--data[\w-]*|--json|--form[\w-]*|--upload-file|--post-data|--post-file|--body-data|--body-file|-Body|-InFile|-Form)(?![\w-]))"""
    r"""|(?<![\w.])(?:data|json)\s*=(?!=)""")

# (label, host regex capturing the path, path regex that does NOT bill)
_REST_HOSTS = [
    ("Runpod REST", r"rest\.runpod\.io(/[^\s'\"`\\]*)?",
     r"^/v\d+/(?:templates|containerregistryauths?|registries|secrets|user|billing)\b|/stop\b"),
    ("Runpod serverless", r"api\.runpod\.ai(/[^\s'\"`\\]*)?",
     r"/(?:cancel|purge-queue|status|health|stream)\b|/graphql\b"),
    ("Vultr", r"api\.vultr\.com(/[^\s'\"`\\]*)?",
     r"^/v\d+/(?:ssh-keys|firewalls|startup-scripts|domains|users|account|iso)\b|/halt\b"),
    ("Google Compute", r"compute\.googleapis\.com(/[^\s'\"`\\]*)?",
     r"^(?!.*/instances\b)|/(?:stop|suspend|reset)\b|/delete\b"),
    ("Azure", r"management\.azure\.com(/[^\s'\"`\\]*)?",
     r"^(?!.*Microsoft\.Compute/virtualMachines)|/(?:powerOff|deallocate)\b"),
]
_REST_HOSTS = [(lab, re.compile(h, re.I), re.compile(f, re.I)) for lab, h, f in _REST_HOSTS]
_AWS_QUERY_RE = re.compile(
    r"Action=(?:RunInstances|RequestSpotInstances|RequestSpotFleet|CreateFleet|StartInstances)\b", re.I)
_GRAPHQL_HOST_RE = re.compile(r"runpod\.(?:io|ai)(?::\d+)?/graphql", re.I)
_GQL_BILL_NAMES_RE = re.compile(
    r"podFindAndDeployOnDemand|podRentInterruptable|podResume|podBidResume|saveEndpoint"
    r"|deployCpuPod|createNetworkVolume|updateNetworkVolume|podEditJob", re.I)
_GQL_MUTATION_RE = re.compile(r"\bmutation\b", re.I)
_GQL_BILL_WORD_RE = re.compile(r"deploy|rent|resume|create|save|update|edit|bid|start|launch", re.I)
# mutations that only write free config records (D375): a template is not compute
_GQL_FREE_FIELDS = {"savetemplate"}
# a readable GraphQL operation: `query {`, `mutation Name(...) {`, or the
# anonymous `{"query": "{ ... }"}` shorthand (not a `mutation.json` filename)
_GQL_ANY_OP_RE = re.compile(
    r"""\b(?:query|mutation)\s*(?:[A-Za-z_]\w*\s*)?(?:\([^)]*\)\s*)?\{|["']query\\?["']\s*:\s*\\?["']\s*\{""",
    re.I)


_GQL_FIELD_RE = re.compile(r"\b([A-Za-z_]\w*)\s*[({]")


def _rest_hits(text, gql_readable):
    """Distinct REST/GraphQL billing calls found in one variant's text. A
    GraphQL mutation bills when a field or operation name under `mutation`
    reads deploy/rent/resume/create/save/update/edit/bid/start/launch (or is
    a known billable one); a write whose body holds no readable `query` or
    `mutation` in any variant (gql_readable False: `-d @file`, `-InFile`)
    is treated as billable too."""
    hits = set()
    write = bool(_WRITE_RE.search(text))
    if _GRAPHQL_HOST_RE.search(text):
        bill = bool(_GQL_BILL_NAMES_RE.search(text))
        for k, mut in enumerate(_GQL_MUTATION_RE.finditer(text)):
            if k >= 20:
                bill = True  # absurd number of mutations: fail closed
                break
            window = text[mut.end():mut.end() + 2000]
            if any(_GQL_BILL_WORD_RE.search(f) and f.lower() not in _GQL_FREE_FIELDS
                   for f in _GQL_FIELD_RE.findall(window)):
                bill = True
                break
        if bill or (write and not gql_readable):
            hits.add("Runpod GraphQL billable mutation (or unreadable body)")
    if write:
        for label, host_re, free_re in _REST_HOSTS:
            for m in host_re.finditer(text):
                if not free_re.search(m.group(1) or ""):
                    hits.add("%s write to %s" % (label, m.group(0)[:80]))
    if _AWS_QUERY_RE.search(text):
        hits.add("AWS EC2 query API launch")
    return hits


# --- SDK one-liners ---------------------------------------------------------
_SDK_GATE_RE = re.compile(
    r"(?<![\w.-])(?:i?python[\d.]*w?|py|pypy3?|node|nodejs|bun|deno|npx)(?:\.exe)?(?![\w.-])"
    r"|\bimport\b|\brequire\s*\(", re.I)
_SDK_RULES = [
    # #178: JS SDK `runpod-sdk` -> `.endpoint(id).run/runSync/runAsync(` runs a billed job
    ("Runpod JS SDK", re.compile(r"runpod-sdk"), re.compile(
        r"\.\s*(?:run|runSync|runAsync)\s*\(")),
    ("Runpod SDK", re.compile(r"\brunpod\b"), re.compile(
        r"\b(?:create_pod|create_endpoint|resume_pod|create_network_volume|create_cluster"
        r"|update_endpoint\w*|run_sync|run_async)\s*\("
        # `from runpod... import create_pod as c` (call hidden behind a rename)
        r"|\bimport\b[^;\n]{0,300}\b(?:create_pod|create_endpoint|resume_pod"
        r"|create_network_volume|create_cluster)\b"
        r"|\bEndpoint\b[\s\S]{0,400}?\.\s*run\w*\s*\(")),
    ("boto3 EC2", re.compile(r"\bboto3\b"), re.compile(
        r"\b(?:run_instances|request_spot_instances|request_spot_fleet|create_fleet"
        r"|create_instances|start_instances)\s*\(")),
    ("Google Compute SDK", re.compile(r"compute_v1|googleapiclient|google\.cloud\.compute"),
     re.compile(r"\.\s*(?:insert|start|resume)\s*\(")),
    ("Azure Compute SDK", re.compile(r"azure\.mgmt\.compute|ComputeManagementClient"),
     re.compile(r"virtual_machines\s*\.\s*begin_(?:create_or_update|start)\s*\(")),
    ("Modal SDK", re.compile(r"\bmodal\b"), re.compile(
        r"\b(?:deploy|deploy_app|deploy_stub)\s*\(|\.\s*(?:deploy|remote|spawn)\s*\(")),
]


def _sdk_hits(text):
    """(labels, number of billable SDK calls) in one variant's text; only
    when a Python interpreter or an `import` is present."""
    if not _SDK_GATE_RE.search(text):
        return set(), 0
    labels = set()
    n = 0
    for label, mod_re, call_re in _SDK_RULES:
        if mod_re.search(text):
            k = len(call_re.findall(text))
            if k:
                labels.add(label)
                n += k
    return labels, n


# --- fallback: unreadable call targets ---------------------------------------
_PS_OPS = (r"-(?:eq|ne|gt|ge|lt|le|like|notlike|match|notmatch|contains|notcontains"
           r"|in|notin|and|or|not|xor|is|isnot|as|replace|split|join|band|bor|f)\b")
# PowerShell automatic variables ($_, $true, ...) are never call targets
_VAR_TOKEN = (r"""\$(?!\()(?!(?:_|psitem|true|false|null|this|matches|lastexitcode|error|input|\?)(?![\w:]))"""
              r"""(?:\{[^}\s{$]{0,200}\}|[\w:!#?@*]+)""")
# a variable as the command run: start of a statement / after a wrapper,
# optional `X=y` prefixes and `&`/`.` call operator, then $var, then an arg
# or end of statement (not `=`, `|`, `.member`, a PowerShell operator)
_CALL_VAR_RE = re.compile(
    r"""(?:^|[;&|({}\n\r`]|\$\(|(?<![\w-])(?:then|do|else|exec|command|builtin|sudo|nohup|time"""
    r"""|xargs|env|source|Start-Process|saps|start|Invoke-Command|icm|-c|/c|-Command|-FilePath|-ScriptBlock)(?![\w-])"""
    r"""|(?<![\w$.])\.)[ \t]*(?:[A-Za-z_]\w*=[^\s;&|]*[ \t]+)*(?:[&.][ \t]*)?["']?"""
    + _VAR_TOKEN
    + r"""["']?(?=[ \t]*(?:$|[;&)}\n\r])|[ \t]+(?![|=]|[-+*/%]=|in\b|""" + _PS_OPS + r"""))""",
    re.I)
# eval/iex of text holding a variable, scriptblock from a variable
_EVAL_VAR_RE = re.compile(
    r"""(?<![\w-])(?:eval|iex|Invoke-Expression)(?![\w-])[^;\n\r|$]{0,1000}\$(?!\()"""
    r"""|::Create\s*\(\s*\$|\.Invoke\s*\(""", re.I)
# first args of a billable CLI that are dynamic: (prog, prefixes that may
# precede the dynamic arg)
_DYN_ARG_PREFIXES = {
    "runpodctl": [(), ("pod",), ("pods",), ("serverless",), ("sls",),
                  ("network-volume",), ("nv",), ("model",)],
    "vultr-cli": [(), ("instance",)],
    "aws": [(), ("ec2",)],
    "gcloud": [(), ("compute",), ("compute", "instances")],
    "az": [(), ("vm",)],
    "modal": [()],
}
_XARGS_TAIL_RE = re.compile(r"(?<![\w-])(?:xargs|parallel)(?![\w-])[^;&|\n\r]*$")


def _dynamic_arg_hit(text):
    """True if a billable CLI's verb position holds a variable, $(...),
    @splat or (...) whose value can't be read: `runpodctl $X`,
    `aws ec2 $ACTION`, `runpodctl @a`, `xargs -I{} runpodctl {} pod`; or
    `xargs runpodctl [pod]`, whose verb arrives on stdin."""
    for n, m in enumerate(_PROG_WORD_RE.finditer(text)):
        if n >= 200:
            return True  # absurd number of mentions: fail closed
        prog = m.group(1).lower()
        prefixes = _DYN_ARG_PREFIXES.get(prog, [])
        stop = re.search(r"[;&|\n\r]", text[m.end():m.end() + 2000])
        seg = text[m.end():m.end() + (stop.start() if stop else 2000)]
        toks = seg.split()
        pos = []
        i = 0
        while i < len(toks) and len(pos) < 4:
            t = toks[i].strip("'\"")
            if not t:
                i += 1
                continue
            if t in (":::", "::::", ":::+") or re.match(r"\d*[<>]", t):
                break  # GNU parallel args / a redirect (`<<< 'pod create'`, `< f`): stdin, not args
            if t.startswith("-"):
                nxt = toks[i + 1].strip("'\"") if i + 1 < len(toks) else ""
                if "=" not in t and nxt[:1] in ("$", "@"):
                    i += 2  # a variable flag value, e.g. --profile $P
                    continue
                i += 1
                continue
            pos.append(t)
            i += 1
        for k, t in enumerate(pos):
            if t[:1] in ("$", "@", "(", "`", "{"):
                if tuple(p.lower() for p in pos[:k]) in prefixes:
                    return True
                break
        if (tuple(p.lower() for p in pos) in prefixes
                and _XARGS_TAIL_RE.search(text[max(0, m.start() - 300):m.start()])):
            return True
    return False


def _unresolved_hit(text):
    return bool(_CALL_VAR_RE.search(text) or _EVAL_VAR_RE.search(text)
                or _dynamic_arg_hit(text))


def indirect_billable(command, bash_patterns):
    """Return (reason, count, indirect). reason: why the command bills via a
    form the literal patterns miss, or None. count: billable actions seen
    (max over rewritten variants of pattern matches + REST + SDK calls, +1
    for an unreadable call). indirect: True when anything beyond the literal
    patterns on the raw text matched, so an inline approval (which reads the
    raw command) must not cover it."""
    vars_, funcs, def_spans = _parse_defs(command)
    subst = _subst_vars(command, vars_)
    base = [command, subst]
    if funcs:
        blanked = _blank_spans(command, def_spans)
        for prog_only in (False, True):
            base.append(_subst_vars(_expand_calls(blanked, funcs, prog_only), vars_))
    extra = [_start_process_variant(subst), _b64_variant(command)]
    base.extend(e for e in extra if e)
    variants = []
    seen = set()
    for v in base + [n for b in base for n in _norms(b)]:
        if v and v not in seen:
            seen.add(v)
            variants.append(v)

    raw_n = len(billable_spans(command, bash_patterns))
    gql_readable = any(_GQL_ANY_OP_RE.search(v) for v in variants)
    pat_n = raw_n
    rest_labels = set()
    sdk_labels = set()
    side_n = 0
    for v in variants:
        if v is not command:
            pat_n = max(pat_n, len(billable_spans(v, bash_patterns)))
        r = _rest_hits(v, gql_readable)
        labels, k = _sdk_hits(v)
        rest_labels |= r
        sdk_labels |= labels
        side_n = max(side_n, len(r) + k)
    reasons = []
    if pat_n > raw_n:
        reasons.append("command reaches a billable pattern through an alias, function, "
                       "variable, Start-Process, quoting or encoding")
    reasons.extend(sorted(rest_labels))
    reasons.extend(sorted(sdk_labels))
    count = pat_n + side_n
    # Unreadable call targets count only in variants with known definitions
    # substituted and function/alias definitions blanked: the raw
    # `X=runpodctl; $X get pod` or `f(){ runpodctl "$@"; }` is not one.
    resolved = base[2:] if funcs else [subst] + [e for e in extra if e]
    resolved = resolved + [n for r in resolved for n in _norms(r)]
    if (_MENTION_RE.search("\n".join(variants))
            and any(_unresolved_hit(v) for v in resolved)):
        reasons.append("command mentions a billable program and runs a variable, "
                       "eval or argument whose value can't be read")
        count += 1
    if not reasons:
        return None, raw_n, False
    return "; ".join(reasons), max(count, 1), True


def pod_action_billable(tool_name, tool_input):
    """Return a block reason if this is a runpod pod-action that starts or
    resumes a pod, else None. Action is tool_input["body"]["action"], with
    tool_input["action"] as fallback. Unknown/missing shape fails open."""
    try:
        if not tool_name or not fnmatch.fnmatch(tool_name.lower(), POD_ACTION_GLOB):
            return None
        ti = tool_input or {}
        body = ti.get("body")
        action = body.get("action") if isinstance(body, dict) else None
        if action is None:
            action = ti.get("action")
        if isinstance(action, str) and action.strip().lower() in POD_BILLABLE_ACTIONS:
            return "tool '%s' action '%s' starts a billable pod" % (
                tool_name, action.strip().lower())
    except Exception:
        pass
    return None


def netvol_update_billable(tool_name, tool_input):
    """Return a block reason if this is a runpod update-network-volume whose
    body is a dict containing "size" (resize), else None. Fails open."""
    try:
        if not tool_name or not fnmatch.fnmatch(tool_name.lower(), NETVOL_UPDATE_GLOB):
            return None
        body = (tool_input or {}).get("body")
        if isinstance(body, dict) and "size" in body:
            return "tool '%s' sets a size (volume resize bills)" % tool_name
    except Exception:
        pass
    return None


def pod_update_billable(tool_name, tool_input):
    """Return a block reason if this is a runpod update-pod whose body is a
    dict containing a POD_UPDATE_BILLABLE_KEYS key or a "mounts" object with
    a "persistent" entry (storage resize bills), else None. Fails open."""
    try:
        if not tool_name or not fnmatch.fnmatch(tool_name.lower(), POD_UPDATE_GLOB):
            return None
        body = (tool_input or {}).get("body")
        if not isinstance(body, dict):
            return None
        mounts = body.get("mounts")
        if any(k in body for k in POD_UPDATE_BILLABLE_KEYS) or (
                isinstance(mounts, dict) and "persistent" in mounts):
            return "tool '%s' sets pod storage size (resize bills)" % tool_name
    except Exception:
        pass
    return None


def env_approved(env):
    return bool(env.get("SPEND_GATE_APPROVED"))


def consume_file_approval(approvals_dir):
    """If approvals_dir has a regular file whose name does not start with
    ".", delete the first one (sorted) and return True. Dotfiles
    (.gitkeep, .DS_Store) are ignored and never deleted: a committed
    .gitkeep must not auto-approve after every checkout. Never raises."""
    try:
        if not os.path.isdir(approvals_dir):
            return False
        names = sorted(
            n for n in os.listdir(approvals_dir)
            if not n.startswith(".")
            and os.path.isfile(os.path.join(approvals_dir, n))
        )
        if not names:
            return False
        os.remove(os.path.join(approvals_dir, names[0]))
        return True
    except Exception:
        return False


def approval_hint():
    return (
        "Approve with ONE of: (1) drop a file into "
        "skilleddocs/spend-approvals/ (one-shot, consumed on use); "
        "(2) prefix the Bash command with SPEND_GATE_APPROVED=<label>, or "
        "start a PowerShell command with $env:SPEND_GATE_APPROVED='<label>'; "
        "<cmd> (inline: one simple command only, no ;/&&/|/subshell, one "
        "billable command). MCP tool calls: use the file. "
        "See the spend-gate skill: estimate, check balance, get an "
        "explicit yes for this action, log it, before approving."
    )


def check(tool_name, tool_input, cwd, env=None):
    """Return a block reason string, or None to allow. Pure function so the
    self-test can drive it directly without touching real env/files except
    where a test is specifically about env or file approval."""
    env = os.environ if env is None else env
    command = None
    if tool_name in ("Bash", "PowerShell"):
        command = (tool_input or {}).get("command")

    try:
        extra_bash, extra_mcp = load_extra_patterns(cwd, env)
    except Exception:
        extra_bash, extra_mcp = [], []

    bash_patterns = DEFAULT_BASH_PATTERNS + extra_bash
    mcp_globs = DEFAULT_MCP_GLOBS + extra_mcp

    reason, _matched = match_billable(tool_name, command, bash_patterns, mcp_globs,
                                      n_default_mcp=len(DEFAULT_MCP_GLOBS))
    if tool_name and fnmatch.fnmatch(tool_name.lower(), POD_ACTION_GLOB):
        # Verb-dependent: only start/resume blocks; anything else allows.
        reason = pod_action_billable(tool_name, tool_input)
    if tool_name and fnmatch.fnmatch(tool_name.lower(), NETVOL_UPDATE_GLOB):
        # Only a body containing "size" blocks; rename-only allows.
        reason = netvol_update_billable(tool_name, tool_input)
    if tool_name and fnmatch.fnmatch(tool_name.lower(), POD_UPDATE_GLOB):
        # Only a body with a storage-size key blocks; name/image allows.
        reason = pod_update_billable(tool_name, tool_input)
    ind_count = 0
    indirect = False
    if tool_name in ("Bash", "PowerShell") and command:
        try:
            ind_reason, ind_count, indirect = indirect_billable(command, bash_patterns)
        except Exception:
            ind_reason, ind_count, indirect = None, 0, False  # fail open
        if reason is None:
            reason = ind_reason
    if reason is None:
        return None  # not billable (or unrecognized) - allow

    spans = billable_spans(command, bash_patterns) if command else []
    # Inline approval reads the raw command, so it never covers a call that
    # only bills through an alias/variable/REST/SDK form (#160).
    if command and not indirect:
        if tool_name == "PowerShell":
            if powershell_inline_approved(command, spans):
                return None
        elif inline_env_approved(command, spans):
            return None
    if env_approved(env):
        return None

    n_actions = max(len(spans), ind_count)
    if n_actions > 1:
        # One approval file is one action: never let it cover two billable
        # commands chained in one call (and don't consume it).
        return ("Blocked: %s, and %d billable commands in one call; one "
                "approval covers one action, so run them as separate calls. %s"
                % (reason, n_actions, approval_hint()))

    approvals_dir = env.get("SPEND_GATE_APPROVALS_DIR") or os.path.join(
        cwd or ".", APPROVALS_DIR_REL
    )
    if consume_file_approval(approvals_dir):
        return None

    return "Blocked: %s. %s" % (reason, approval_hint())


def main():
    if "--self-test" in sys.argv:
        run_self_test()
        return

    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
        tool_name = data.get("tool_name")
        tool_input = data.get("tool_input") or {}
        cwd = data.get("cwd")
        reason = check(tool_name, tool_input, cwd)
        if reason:
            sys.stderr.write(reason + "\n")
            sys.exit(2)
        sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        # Malformed stdin, missing fields, etc. - fail open rather than
        # block unrelated work on a hook bug.
        sys.exit(0)


# Perf self-tests catch blowups (exponential/ReDoS take minutes at 2000 tokens),
# not load jitter: best of 3 runs against a generous bound.
PERF_LIMIT = 3.0


def _best_time(fn, runs=3):
    import time
    best = None
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        dt = time.perf_counter() - t0
        best = dt if best is None else min(best, dt)
        if best < PERF_LIMIT / 6:
            break  # clearly fast: skip the extra runs
    return best


def run_self_test():
    import tempfile

    passed = 0
    failed = 0
    # Never read the real env or touch a real approvals dir: every check()
    # below gets an explicit env pointing at an empty temp dir.
    empty_dir = tempfile.mkdtemp(prefix="spend-guard-selftest-")
    iso = {"SPEND_GATE_APPROVALS_DIR": empty_dir}

    def record(label, ok, extra=""):
        nonlocal passed, failed
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print("%s: %-55s %s" % (status, label, extra))

    # 1. non-billable Bash command is allowed
    reason = check("Bash", {"command": "echo hello"}, None, env=iso)
    record("non-billable Bash command allowed", reason is None)

    # 2. each default bash pattern blocks
    default_cases = [
        "runpodctl create pod --gpuType RTX4090",
        "runpodctl pod create --gpu-id RTX4090",
        "runpodctl serverless create --template-id t1",
        "runpodctl network-volume create --size 10",
        "runpodctl.exe pod create --gpu-id RTX4090",
        "vultr-cli instance create --region ewr",
        "aws ec2 run-instances --image-id ami-123",
        "gcloud compute instances create my-vm",
        "az vm create --name my-vm",
        "modal deploy app.py",
        # D375 (#174): starting stopped instances and modal run bill too
        "aws ec2 start-instances --instance-ids i-123",
        "gcloud compute instances start my-vm",
        "modal run app.py",
    ]
    for cmd in default_cases:
        reason = check("Bash", {"command": cmd}, None, env=iso)
        record("default pattern blocks: %s" % cmd, reason is not None)

    # 2a. runpodctl v2 noun-verb, start, resize, serverless update
    rp_block = [
        "runpodctl start pod x", "runpodctl pod start x", "runpodctl pods start x",
        "runpodctl pod create --image y", "runpodctl serverless create --name z",
        "runpodctl network-volume create --size 10", "runpodctl nv create",
        "runpodctl network-volume update id --size 200",
        "runpodctl nv update id --name a --size 2",
        "runpodctl serverless update id --workers-max 3",
        "runpodctl.exe pod start x", "'C:/x/runpodctl.exe' pod start x",
        "/usr/local/bin/runpodctl pod start x",
        r'& "C:\Program Files\runpod\runpodctl.exe" pod start x',
    ]
    for cmd in rp_block:
        tool = "PowerShell" if cmd.startswith("&") else "Bash"
        record("runpodctl blocks: %s" % cmd,
               check(tool, {"command": cmd}, None, env=iso) is not None)
    rp_allow = [
        "runpodctl pod list", "runpodctl pod logs x", "runpodctl pod stop x",
        "runpodctl pod get x", "runpodctl get pod",
        "runpodctl template create --name t", "runpodctl registry create",
        "runpodctl network-volume update id --name x",
        "myrunpodctl pod start x", "runpodctl pod delete x",
    ]
    for cmd in rp_allow:
        record("runpodctl allowed: %s" % cmd,
               check("Bash", {"command": cmd}, None, env=iso) is None)

    # 2b. Windows .exe/.cmd, quoted and path forms block
    win_cases = [
        ("Bash", "runpodctl.exe create pod x"),
        ("Bash", "'C:/x/runpodctl.exe' create pod x"),
        ("Bash", "/usr/local/bin/runpodctl create pod x"),
        ("PowerShell", r'& "C:\Program Files\runpod\runpodctl.exe" create pod x'),
        ("Bash", "vultr-cli.exe instance create --region ewr"),
        ("Bash", "'C:/x/vultr-cli.exe' instance create --region ewr"),
        ("PowerShell", r'& "C:\tools\vultr-cli.exe" instance create --region ewr'),
        ("Bash", "aws.exe ec2 run-instances --image-id ami-1"),
        ("Bash", "'C:/x/aws.exe' ec2 run-instances --image-id ami-1"),
        ("PowerShell", r'& "C:\Program Files\Amazon\aws.exe" ec2 run-instances --image-id ami-1'),
        ("Bash", "gcloud.exe compute instances create my-vm"),
        ("Bash", "gcloud.cmd compute instances create my-vm"),
        ("Bash", "'C:/x/gcloud.cmd' compute instances create my-vm"),
        ("PowerShell", r'& "C:\sdk\bin\gcloud.cmd" compute instances create my-vm'),
        ("Bash", "az.exe vm create --name my-vm"),
        ("Bash", "az.cmd vm create --name my-vm"),
        ("Bash", "'C:/x/az.cmd' vm create --name my-vm"),
        ("PowerShell", r'& "C:\az\wbin\az.cmd" vm create --name my-vm'),
        ("Bash", "modal.exe deploy app.py"),
        ("Bash", "'C:/x/modal.exe' deploy app.py"),
        ("PowerShell", r'& "C:\py\Scripts\modal.exe" deploy app.py'),
    ]
    for tool, cmd in win_cases:
        reason = check(tool, {"command": cmd}, None, env=iso)
        record("win form blocks: %s %s" % (tool, cmd), reason is not None)

    # 2c. near-miss forms stay allowed
    for cmd in ["runpodctl.exe get pod", "myrunpodctl create pod x"]:
        reason = check("Bash", {"command": cmd}, None, env=iso)
        record("near-miss allowed: %s" % cmd, reason is None)

    # 3. unrelated tool name with no command is allowed
    reason = check("Read", {"file_path": "x.txt"}, None, env=iso)
    record("non-Bash, non-MCP tool allowed", reason is None)

    # 4. MCP glob blocks
    reason = check("mcp__runpod__create-pod", {}, None, env=iso)
    record("MCP glob blocks create-pod", reason is not None)
    reason = check("mcp__runpod__list-pods", {}, None, env=iso)
    record("MCP tool not matching a glob is allowed", reason is None)

    # 4a. free runpod create-* tools allowed; billable create-* still block
    for pre in ("mcp__runpod__", "mcp__plugin_runpod_runpod__"):
        for t in RUNPOD_FREE_CREATE_TOOLS:
            record("MCP free %s%s allowed" % (pre, t),
                   check(pre + t, {}, None, env=iso) is None)
        for t in ("create-pod", "create-endpoint", "create-cluster",
                  "create-network-volume", "create-global-volume"):
            record("MCP billable %s%s blocks" % (pre, t),
                   check(pre + t, {}, None, env=iso) is not None)
    record("MCP CREATE-TEMPLATE (case) allowed",
           check("mcp__RunPod__CREATE-TEMPLATE", {}, None, env=iso) is None)
    record("MCP create-template-x (unknown suffix) blocks",
           check("mcp__runpod__create-template-x", {}, None, env=iso) is not None)
    record("MCP other provider create-template still matched by user glob",
           check("mcp__digitalocean__create-template", {}, None,
                 env=dict(iso, SPEND_GUARD_PATTERNS="mcp:mcp__*__create-*")) is not None)
    record("MCP user glob can re-gate runpod create-template",
           check("mcp__runpod__create-template", {}, None,
                 env=dict(iso, SPEND_GUARD_PATTERNS="mcp:mcp__*runpod*__create-template"))
           is not None)
    record("MCP user glob identical to default text still blocks create-secret",
           check("mcp__runpod__create-secret", {}, None,
                 env=dict(iso, SPEND_GUARD_PATTERNS="mcp:mcp__*runpod*__create-*"))
           is not None)

    # 5. file-based approval allows, and is consumed (one-shot)
    with tempfile.TemporaryDirectory() as tmp:
        approvals_dir = os.path.join(tmp, "approvals")
        os.makedirs(approvals_dir)
        with open(os.path.join(approvals_dir, "runpod-pod-test"), "w") as f:
            f.write("approved for test\n")
        env = {"SPEND_GATE_APPROVALS_DIR": approvals_dir}
        reason = check("Bash", {"command": "runpodctl create pod x"}, None, env=env)
        record("approval file allows the billable command", reason is None)
        reason2 = check("Bash", {"command": "runpodctl create pod x"}, None, env=env)
        record(
            "approval file is consumed (second call blocks again)",
            reason2 is not None,
        )

    # 5a. dotfiles (.gitkeep, .DS_Store) are not approvals and are kept
    with tempfile.TemporaryDirectory() as tmp:
        for dot in (".gitkeep", ".DS_Store"):
            open(os.path.join(tmp, dot), "w").close()
        os.makedirs(os.path.join(tmp, "subdir"))
        env = {"SPEND_GATE_APPROVALS_DIR": tmp}
        record("approval dir with only dotfiles/subdir blocks",
               check("Bash", {"command": "runpodctl create pod x"}, None, env=env)
               is not None)
        record("dotfiles not deleted by a blocked call",
               os.path.exists(os.path.join(tmp, ".gitkeep"))
               and os.path.exists(os.path.join(tmp, ".DS_Store")))
        open(os.path.join(tmp, "approved-1"), "w").close()
        record("real approval file beside .gitkeep allows",
               check("Bash", {"command": "runpodctl create pod x"}, None, env=env)
               is None)
        record("real file consumed, .gitkeep kept",
               not os.path.exists(os.path.join(tmp, "approved-1"))
               and os.path.exists(os.path.join(tmp, ".gitkeep")))
        record("MCP call with only .gitkeep blocks",
               check("mcp__runpod__create-pod", {}, None, env=env) is not None)

    # 6. env approval allows - inline (Bash), process env (MCP)
    reason = check(
        "Bash", {"command": "SPEND_GATE_APPROVED=yes runpodctl create pod x"}, None, env=iso
    )
    record("inline SPEND_GATE_APPROVED prefix allows Bash command", reason is None)

    reason = check(
        "mcp__runpod__create-pod", {}, None, env=dict(iso, SPEND_GATE_APPROVED="yes")
    )
    record("process-env SPEND_GATE_APPROVED allows MCP call", reason is None)

    # 7. custom pattern via env var blocks
    env = dict(iso, SPEND_GUARD_PATTERNS=r"bash:\bdoctl\s+droplets\s+create\b")
    reason = check(
        "Bash", {"command": "doctl droplets create --region nyc1"}, None, env=env
    )
    record("custom pattern via SPEND_GUARD_PATTERNS blocks", reason is not None)

    # 8. custom pattern via patterns file blocks
    with tempfile.TemporaryDirectory() as tmp:
        claude_dir = os.path.join(tmp, ".claude")
        os.makedirs(claude_dir)
        with open(os.path.join(claude_dir, "spend-guard-patterns.txt"), "w") as f:
            f.write("# comment line\nmcp:mcp__*digitalocean*__create-*\n")
        reason = check("mcp__digitalocean__create-droplet", {}, tmp, env=iso)
        record("custom MCP glob via patterns file blocks", reason is not None)

    # 9. malformed stdin fails open (never raises, never blocks) - run the
    # actual script as a subprocess so this exercises main()'s try/except,
    # not just the pure check() function.
    import subprocess

    proc = subprocess.run(
        [sys.executable, os.path.abspath(__file__)],
        input="{not valid json",
        capture_output=True,
        text=True,
        timeout=10,
    )
    record(
        "malformed stdin fails open (exit 0, no traceback)",
        proc.returncode == 0 and "Traceback" not in proc.stderr,
    )

    # 10. billable command with no tool_input.command fails open (missing
    # field, not malformed JSON, but the same "don't crash into a block")
    proc = subprocess.run(
        [sys.executable, os.path.abspath(__file__)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {}}),
        capture_output=True,
        text=True,
        timeout=10,
    )
    record("Bash tool_input missing 'command' fails open", proc.returncode == 0)

    # 11. PowerShell tool (same regexes as Bash)
    ps_cmd = "runpodctl create pod --gpuType RTX4090"
    record("PowerShell billable blocks",
           check("PowerShell", {"command": ps_cmd}, None, env=iso) is not None)
    record("PowerShell non-billable allowed",
           check("PowerShell", {"command": "Get-ChildItem"}, None, env=iso) is None)
    for form in ("'x'", '"x"', "x", " 'x' "):
        cmd = "$env:SPEND_GATE_APPROVED=%s; %s" % (form, ps_cmd)
        record("PowerShell $env approval allows: %s" % form,
               check("PowerShell", {"command": cmd}, None, env=iso) is None)
    record("PowerShell approval not leading still blocks",
           check("PowerShell", {"command": ps_cmd + "; $env:SPEND_GATE_APPROVED='x'"},
                 None, env=iso) is not None)
    record("PowerShell empty approval value blocks",
           check("PowerShell", {"command": "$env:SPEND_GATE_APPROVED=''; " + ps_cmd},
                 None, env=iso) is not None)
    for form in ("$null", "$false", '"$x"'):
        record("PowerShell variable approval value blocks: %s" % form,
               check("PowerShell", {"command": "$env:SPEND_GATE_APPROVED=%s; %s"
                                    % (form, ps_cmd)}, None, env=iso) is not None)
    record("PowerShell approval case-insensitive allows",
           check("PowerShell", {"command": "  $ENV:spend_gate_approved = 'x' ; " + ps_cmd},
                 None, env=iso) is None)
    record("PowerShell comment before approval blocks",
           check("PowerShell", {"command": "<# c #> $env:SPEND_GATE_APPROVED='x'; " + ps_cmd},
                 None, env=iso) is not None)
    record("PowerShell without ; blocks",
           check("PowerShell", {"command": "$env:SPEND_GATE_APPROVED='x' " + ps_cmd},
                 None, env=iso) is not None)
    record("Bash-style prefix not approval in PowerShell",
           check("PowerShell", {"command": "SPEND_GATE_APPROVED=yes " + ps_cmd},
                 None, env=iso) is not None)
    record("PowerShell $env form not approval in Bash",
           check("Bash", {"command": "$env:SPEND_GATE_APPROVED='x'; " + ps_cmd},
                 None, env=iso) is not None)

    # 12. new runpod MCP globs
    for tool in ("run-endpoint", "runsync-endpoint", "retry-job",
                 "update-endpoint", "set-endpoint-gpus"):
        record("MCP runpod %s blocks" % tool,
               check("mcp__runpod__%s" % tool, {}, None, env=iso) is not None)
    record("MCP runpod get-job-status allowed",
           check("mcp__runpod__get-job-status", {}, None, env=iso) is None)

    # 13. pod-action: only start/resume bills
    pa = "mcp__plugin_runpod_runpod__pod-action"
    record("pod-action start blocks",
           check(pa, {"id": "p", "body": {"action": "start"}}, None, env=iso) is not None)
    record("pod-action resume blocks",
           check(pa, {"id": "p", "body": {"action": "resume"}}, None, env=iso) is not None)
    record("pod-action top-level action start blocks",
           check(pa, {"id": "p", "action": "start"}, None, env=iso) is not None)
    for act in ("stop", "restart", "terminate"):
        record("pod-action %s allowed" % act,
               check(pa, {"id": "p", "body": {"action": act}}, None, env=iso) is None)
    record("pod-action missing body allowed",
           check(pa, {"id": "p"}, None, env=iso) is None)
    record("pod-action odd shape allowed",
           check(pa, {"body": "start"}, None, env=iso) is None)
    record("pod-action start allowed with process-env approval",
           check(pa, {"body": {"action": "start"}}, None,
                 env=dict(iso, SPEND_GATE_APPROVED="yes")) is None)

    # 14. update-network-volume: only a body with "size" bills
    nv = "mcp__plugin_runpod_runpod__update-network-volume"
    record("netvol update size blocks",
           check(nv, {"id": "v", "body": {"size": 200}}, None, env=iso) is not None)
    record("netvol update name+size blocks",
           check(nv, {"id": "v", "body": {"name": "a", "size": 10}}, None, env=iso) is not None)
    record("netvol update name-only allowed",
           check(nv, {"id": "v", "body": {"name": "a"}}, None, env=iso) is None)
    record("netvol update missing body allowed",
           check(nv, {"id": "v"}, None, env=iso) is None)
    record("netvol update string body allowed",
           check(nv, {"id": "v", "body": "size"}, None, env=iso) is None)
    record("netvol update size allowed with process-env approval",
           check(nv, {"body": {"size": 5}}, None,
                 env=dict(iso, SPEND_GATE_APPROVED="yes")) is None)
    record("global-volume update name allowed",
           check("mcp__plugin_runpod_runpod__update-global-volume",
                 {"body": {"name": "a"}}, None, env=iso) is None)

    # 15. issue #130: serverless run, sls alias, pod update storage, model add,
    # global flags before noun, update-pod MCP
    new_block = [
        "runpodctl serverless run ep1 --input '{}'", "runpodctl sls run ep1 --input x",
        "runpodctl sls create --name z", "runpodctl sls update ep --workers-max 2",
        "runpodctl pod update p1 --volume-in-gb 50",
        "runpodctl pods update p1 --name a --container-disk-in-gb 80",
        "runpodctl model add --name m", "runpodctl --profile x pod create --image y",
        "runpodctl --output=json pod create", "runpodctl -o json serverless run ep",
        "runpodctl --verbose create pod x", "runpodctl.exe -o json sls run ep",
        "runpodctl --profile a --output=json nv create",
    ]
    for cmd in new_block:
        record("#130 blocks: %s" % cmd,
               check("Bash", {"command": cmd}, None, env=iso) is not None)
    new_allow = [
        "runpodctl pod update p1 --name y", "runpodctl serverless status ep j",
        "runpodctl serverless health ep", "runpodctl serverless logs ep",
        "runpodctl hub search vllm", "runpodctl model list", "runpodctl model remove m",
        "runpodctl --output=json pod list", "myrunpodctl sls run ep",
        "runpodctl pod list --output json create", "runpodctl --profile x pod stop p",
        "runpodctl -o json template create --name t",
    ]
    for cmd in new_allow:
        record("#130 allowed: %s" % cmd,
               check("Bash", {"command": cmd}, None, env=iso) is None)
    up = "mcp__plugin_runpod_runpod__update-pod"
    record("pod update volumeInGb blocks",
           check(up, {"id": "p", "body": {"volumeInGb": 50}}, None, env=iso) is not None)
    record("pod update containerDiskInGb blocks",
           check(up, {"id": "p", "body": {"name": "a", "containerDiskInGb": 9}},
                 None, env=iso) is not None)
    record("pod update name/imageName allowed",
           check(up, {"id": "p", "body": {"name": "a", "imageName": "i"}},
                 None, env=iso) is None)
    record("pod update missing/string body allowed",
           check(up, {"id": "p"}, None, env=iso) is None
           and check(up, {"body": "volumeInGb"}, None, env=iso) is None)
    record("pod update v2 disk blocks",
           check(up, {"id": "p", "body": {"disk": 80}}, None, env=iso) is not None)
    record("pod update v2 mounts.persistent blocks",
           check(up, {"id": "p", "body": {"mounts": {"persistent":
                 {"size": 50, "path": "/workspace"}}}}, None, env=iso) is not None)
    record("pod update templateId blocks (applies template disk)",
           check(up, {"id": "p", "body": {"templateId": "t"}}, None, env=iso) is not None)
    record("pod update network mount path / env / ports allowed",
           check(up, {"id": "p", "body": {"mounts": {"network": [{"volumeId": "v",
                 "path": "/d"}]}, "env": {"A": "1"}, "ports": ["22/tcp"],
                 "image": "i", "locked": True}}, None, env=iso) is None)
    # #130 verifier: regex edge forms + backtracking bound
    for cmd in ["runpodctl --profile serverless-prod pod create",
                "runpodctl --x=-1 pod create", 'runpodctl --profile "my prof" pod create',
                "runpodctl -- pod create", "runpodctl -o json	sls run ep",
                "runpodctl --profile=pod pod create"]:
        record("#130v blocks: %s" % cmd,
               check("Bash", {"command": cmd}, None, env=iso) is not None)
    for cmd in ["runpodctl update", "runpodctl --profile start-x pod list",
                "runpodctl help pod create", "runpodctl ---a pod create"]:
        record("#130v allowed: %s" % cmd,
               check("Bash", {"command": cmd}, None, env=iso) is None)
    long_cmd = "runpodctl " + " ".join(["--a-b c"] * 400 + ["-x"] * 400) + " pod list"
    record("400+400 flag run allows fast (no backtracking blowup)",
           check("Bash", {"command": long_cmd}, None, env=iso) is None
           and _best_time(lambda: check("Bash", {"command": long_cmd}, None, env=iso)) < PERF_LIMIT)
    record("pod update volumeInGb allowed with approval",
           check(up, {"body": {"volumeInGb": 5}}, None,
                 env=dict(iso, SPEND_GATE_APPROVED="yes")) is None)

    # 16. issue #141: inline approval covers only the one simple command it
    # prefixes, and only when that command's program is the one billable match
    C = "runpodctl create pod x"
    A = "SPEND_GATE_APPROVED=yes "
    bash_allow = [
        A + C,
        A + "runpodctl pod create --gpu-id 'RTX 4090' --name 'a;b|c&&d'",
        "FOO=1 " + A + "BAR=2 " + C,
        "SPEND_GATE_APPROVED='ok label' " + C,
        'SPEND_GATE_APPROVED="ok" ' + C,
        "env " + A + C,
        "/usr/bin/env " + A + C,
        "env FOO=1 " + A + C,
        A + "/usr/local/bin/runpodctl pod start x",
        A + "'C:/x/runpodctl.exe' pod create x",
        A + C + " > out.json 2>&1",
        A + C + " &> log.txt",
        A + C + " # one-line comment",
        A + "runpodctl --profile x pod create --image y",
        A + "modal deploy app.py",
        A + "runpodctl serverless run ep --input \"{\\\"a\\\": 1}\"",
    ]
    for cmd in bash_allow:
        record("#141 Bash inline allows: %s" % cmd,
               check("Bash", {"command": cmd}, None, env=iso) is None)
    bash_block = [
        A + "true && " + C, A + "true; " + C, A + "true || " + C,
        A + "true | " + C, A + "true & " + C, A + "true\n" + C, A + "true\r\n" + C,
        A + C + " && " + C, A + C + "; " + C, A + C + " || " + C,
        A + C + " | " + C, A + C + " & " + C, A + C + "\n" + C,
        A + C + " &",
        A + "echo $(" + C + ")", A + "echo `" + C + "`",
        A + 'echo "$(' + C + ')"', A + 'echo "`' + C + '`"',
        A + "(" + C + ")", "(" + A + C + ")", A + "{ " + C + "; }",
        A + "bash -c '" + C + "'", A + "bash -c '" + C + "; " + C + "'",
        A + "sh -c \"" + C + "\"", A + "xargs " + C, A + "nohup " + C,
        A + "sudo " + C, A + "echo " + C, A + "true " + C,
        A + "cat <(" + C + ")",
        "export " + A.strip() + "; " + C, "export " + A.strip() + " && " + C,
        "export " + A + C,
        "env -i " + A + C, "env " + A + "env " + C,
        "SPEND_GATE_APPROVED= " + C, "SPEND_GATE_APPROVED='' " + C,
        "SPEND_GATE_APPROVED=$X " + C, 'SPEND_GATE_APPROVED="$X" ' + C,
        "SPEND_GATE_APPROVED=$(echo y) " + C,
        "true " + A + C, "cd x && " + A + C,
        A + C + " --name $'a\\'' ; " + C + " ''",
        A + "#'\n" + C + " #'",
        A + C + " --name 'unbalanced",
        A + C + " --env 'X=runpodctl create pod'",
        A + "runpodctl create pod x \\\n; " + C,
        A + C + " # c\n" + C,
    ]
    for cmd in bash_block:
        record("#141 Bash inline blocks: %r" % cmd,
               check("Bash", {"command": cmd}, None, env=iso) is not None)
    record("#141 inline approval applies to Bash only (not MCP)",
           check("mcp__runpod__create-pod", {"command": A + C}, None, env=iso)
           is not None)
    record("#141 custom pattern overlapping default still one span (allows)",
           check("Bash", {"command": A + C}, None,
                 env=dict(iso, SPEND_GUARD_PATTERNS=r"bash:create\s+pod")) is None)
    dpat = dict(iso, SPEND_GUARD_PATTERNS=r"bash:\bdoctl\s+droplets\s+create\b")
    record("#141 custom pattern: inline allows its own single command",
           check("Bash", {"command": A + "doctl droplets create d"}, None, env=dpat)
           is None)
    record("#141 custom pattern as a second command blocks",
           check("Bash", {"command": A + C + " --tag x; doctl droplets create d"},
                 None, env=dpat) is not None)

    P = "$env:SPEND_GATE_APPROVED='x'; "
    ps_allow = [
        P + C, P + " " + C, '$env:SPEND_GATE_APPROVED="x"; ' + C,
        P + r'& "C:\Program Files\runpod\runpodctl.exe" pod create x',
        P + r"&'C:\x\runpodctl.exe' pod create x",
        P + C + " --name 'a;b|c' 2>&1",
        P + C + " # trailing comment",
        P + "modal deploy app.py",
    ]
    for cmd in ps_allow:
        record("#141 PS inline allows: %s" % cmd,
               check("PowerShell", {"command": cmd}, None, env=iso) is None)
    ps_block = [
        P + C + "; " + C, P + "Write-Host hi; " + C, P + C + "; Write-Host hi",
        P + C + " | " + C, P + "Get-Date | " + C, P + C + " && " + C,
        P + "$true || " + C, P + C + "\n" + C, P + C + "\r\n" + C,
        P + "Write-Host $(" + C + ")", P + 'Write-Host "$(' + C + ')"',
        P + "@(" + C + ")", P + "(" + C + ")", P + "& { " + C + " }",
        P + "Invoke-Expression '" + C + "'", P + "iex '" + C + "'",
        P + "bash -c '" + C + "'", P + "& & " + C, P + C + " `\n; " + C,
        P + C + ' --name "a`"; ' + C + '"',
        P + C + " & " + C,
        "$env:SPEND_GATE_APPROVED='x'; $env:SPEND_GATE_APPROVED='y'; " + C,
        "Write-Host a; " + P + C,
        P + C + " # c\n" + C,
    ]
    for cmd in ps_block:
        record("#141 PS inline blocks: %r" % cmd,
               check("PowerShell", {"command": cmd}, None, env=iso) is not None)

    # 16a. one approval file never covers two billable commands in one call
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "approved-1"), "w").close()
        env = {"SPEND_GATE_APPROVALS_DIR": tmp}
        for tool, cmd in (("Bash", C + " && " + C), ("PowerShell", C + "; " + C),
                          ("Bash", A + C + "; " + C)):
            record("#141 file approval refuses two creates: %s %r" % (tool, cmd),
                   check(tool, {"command": cmd}, None, env=env) is not None)
        record("#141 refused multi-create leaves the approval file",
               os.path.exists(os.path.join(tmp, "approved-1")))
        record("#141 file approval still covers cd x && one create",
               check("Bash", {"command": "cd x && " + C}, None, env=env) is None
               and not os.path.exists(os.path.join(tmp, "approved-1")))

    # 16b. perf: 2000-flag command lines check() well under 1 s
    for tool, cmd in (
            ("Bash", A + "runpodctl " + " ".join(["--a-b c"] * 2000) + " pod create"),
            ("Bash", A + "runpodctl " + " ".join(["-x"] * 2000) + " pod create"),
            ("Bash", "runpodctl " + " ".join(["--k='v w'"] * 2000) + " pod list"),
            ("Bash", "runpodctl " + " ".join(['--a "x'] * 2000) + " pod create"),
            ("PowerShell", P + "runpodctl " + " ".join(["--a-b c"] * 2000) + " pod create"),
            ("Bash", A + C + " " + " ".join(["-a b ;"] * 1000))):
        dt = _best_time(lambda: check(tool, {"command": cmd}, None, env=iso))
        record("#141 perf %s %d chars < %.0fs (best of 3: %.3fs)" % (tool, len(cmd), PERF_LIMIT, dt),
               dt < PERF_LIMIT)

    # 17. issue #160: indirection, Start-Process, REST/GraphQL, SDK one-liners.
    # Each form: (tool, blocks, near-miss that stays allowed).
    P_ = P  # PowerShell inline-approval prefix from section 16
    S, P = "Bash", "PowerShell"
    forms = [
        (S, "alias r=runpodctl; r create pod", "alias r=runpodctl; r get pod"),
        (S, "alias r='runpodctl pod'; r create", "alias r='runpodctl pod'; r list"),
        (S, "X=runpodctl; $X create pod", "X=runpodctl; $X get pod"),
        (S, "X=runpodctl; ${X} create pod", "X=runpodctl; ${X} get pod"),
        (S, 'X=runpodctl; "$X" create pod', 'X=runpodctl; "$X" get pod'),
        (S, "A=runpod; B=ctl; $A$B create pod", "A=runpod; B=ctl; $A$B pod list"),
        (S, 'f(){ runpodctl "$@"; }; f create pod', 'f(){ runpodctl "$@"; }; f get pod'),
        (S, 'function f { runpodctl "$@"; }; f create pod',
         'function f { runpodctl "$@"; }; f get pod'),
        (S, "f(){ runpodctl $1 pod; }; f create", "f(){ runpodctl $1 pod; }; f list"),
        (S, 'f(){ aws ec2 "$@"; }; f run-instances --image-id x',
         'f(){ aws ec2 "$@"; }; f describe-instances'),
        (P, "Set-Alias r runpodctl; r create pod", "Set-Alias r runpodctl; r get pod"),
        (P, "New-Alias -Name r -Value runpodctl; r create pod",
         "New-Alias -Name r -Value runpodctl; r get pod"),
        (P, "$X='runpodctl'; & $X create pod", "$X='runpodctl'; & $X get pod"),
        (P, "$env:RP='runpodctl'; & $env:RP create pod", "$env:RP='runpodctl'; & $env:RP pod list"),
        (P, "$c = Get-Command runpodctl; & $c create pod", "$c = Get-Command runpodctl; & $c get pod"),
        (P, "function f { runpodctl @args }; f create pod", "function f { runpodctl @args }; f get pod"),
        (P, "$a = 'create','pod'; runpodctl @a", "$a = 'get','pod'; runpodctl @a"),
        # unreadable call target / args, in a command naming a billable program
        (S, "$X create pod; runpodctl get pod", "$X create pod"),
        (P, "& $c create pod; runpodctl get pod", "& $c create pod"),
        (S, "eval \"$CMD\"; which runpodctl", "eval \"$CMD\""),
        (S, "runpodctl $VERB pod", "runpodctl pod list --name $N"),
        (S, "aws ec2 $ACTION --image-id x", "aws --profile $P s3 ls"),
        (S, "echo create pod | xargs runpodctl",
         "runpodctl pod list | xargs -n1 runpodctl pod stop"),
        # Start-Process and wrappers
        (P, "Start-Process runpodctl -ArgumentList 'create pod'",
         "Start-Process runpodctl -ArgumentList 'get pod'"),
        (P, "Start-Process -FilePath runpodctl -ArgumentList 'create','pod'",
         "Start-Process -FilePath runpodctl -ArgumentList 'pod','list'"),
        (P, "Start-Process -ArgumentList 'ec2 run-instances' -FilePath aws",
         "Start-Process -ArgumentList 'ec2 describe-instances' -FilePath aws"),
        (P, "saps runpodctl 'create pod'", "saps runpodctl 'pod list'"),
        (P, "start vultr-cli -ArgumentList 'instance create'", "start vultr-cli -ArgumentList 'instance list'"),
        (P, "cmd /c \"runpodctl create pod\"", "cmd /c \"runpodctl get pod\""),
        (S, "bash -c 'runpodctl create pod'", "bash -c 'runpodctl get pod'"),
        (P, "pwsh -c \"runpodctl create pod\"", "pwsh -c \"runpodctl get pod\""),
        # quoting / encoding noise
        (S, "'run''podctl' create pod", "'run''podctl' get pod"),
        (S, "r\\unpodctl create pod", "r\\unpodctl get pod"),
        (S, "{runpodctl,create,pod}", "{runpodctl,get,pod}"),
        (P, "& ('run'+'podctl') create pod", "& ('run'+'podctl') get pod"),
        (P, "r`unpodctl create pod", "r`unpodctl get pod"),
        (P, "powershell -EncodedCommand "
            "cgB1AG4AcABvAGQAYwB0AGwAIABjAHIAZQBhAHQAZQAgAHAAbwBkAA==",
         "powershell -EncodedCommand cgB1AG4AcABvAGQAYwB0AGwAIABnAGUAdAAgAHAAbwBkAA=="),
        # REST / GraphQL writes
        (S, "curl -X POST https://rest.runpod.io/v1/pods -d '{\"interruptible\":true}'",
         "curl https://rest.runpod.io/v1/pods"),
        (S, "curl https://rest.runpod.io/v1/pods --json '{}'",
         "curl -X DELETE https://rest.runpod.io/v1/pods/p1"),
        (S, "curl -X POST https://rest.runpod.io/v1/pods/p1/start",
         "curl -X POST https://rest.runpod.io/v1/pods/p1/stop"),
        (S, "curl -X POST https://rest.runpod.io/v1/endpoints -d '{}'",
         "curl -X POST https://rest.runpod.io/v1/templates -d '{}'"),
        (S, "curl -XPOST https://rest.runpod.io/v1/pods/p1/start",
         "curl -XPOST https://rest.runpod.io/v1/pods/p1/stop"),
        (S, "wget --post-data '{}' https://rest.runpod.io/v1/networkvolumes",
         "wget https://rest.runpod.io/v1/networkvolumes"),
        (P, "Invoke-RestMethod -Uri https://rest.runpod.io/v1/pods -Method Post -Body $b",
         "Invoke-RestMethod -Uri https://rest.runpod.io/v1/pods"),
        (P, "irm https://rest.runpod.io/v1/endpoints -Body '{}'", "irm https://rest.runpod.io/v1/endpoints"),
        (P, "iwr https://rest.runpod.io/v1/pods -Method Patch -InFile b.json",
         "iwr https://rest.runpod.io/v1/pods -Method Get"),
        (S, "curl -X POST https://api.runpod.io/graphql -d '{\"query\":\"mutation "
            "{ podFindAndDeployOnDemand(input:{}) { id } }\"}'",
         "curl -X POST https://api.runpod.io/graphql -d '{\"query\":\"query "
         "{ myself { pods { id } } }\"}'"),
        (S, "curl https://api.runpod.io/graphql -d '{\"query\":\"mutation "
            "{ podRentInterruptable(input:{bidPerGpu:0.2}) { id } }\"}'",
         "curl https://api.runpod.io/graphql -d '{\"query\":\"mutation "
         "{ podTerminate(input:{podId:\\\"p\\\"}) }\"}'"),
        (S, "curl -X POST https://api.runpod.io/graphql -d '{\"query\":\"mutation "
            "{ podResume(input:{podId:\\\"p\\\"}) { id } }\"}'",
         "curl -X POST https://api.runpod.io/graphql -d '{\"query\":\"{ myself { id } }\"}'"),
        (S, "curl -X POST https://api.runpod.io/graphql -d @mutation.json",
         "curl https://api.runpod.io/graphql?query=x"),
        (P, "irm https://api.runpod.io/graphql -Method Post -Body '{\"query\":\"mutation "
            "{ saveEndpoint(input:{}) { id } }\"}'",
         "irm https://api.runpod.io/graphql -Method Post -Body '{\"query\":\"query "
         "{ gpuTypes { id } }\"}'"),
        # D375 (#174): saveTemplate writes a free config record; saveEndpoint still bills
        (S, "curl -X POST https://api.runpod.io/graphql -d '{\"query\":\"mutation "
            "{ saveTemplate(input:{}) { id } saveEndpoint(input:{}) { id } }\"}'",
         "curl -X POST https://api.runpod.io/graphql -d '{\"query\":\"mutation "
         "{ saveTemplate(input:{name:\\\"t\\\"}) { id } }\"}'"),
        (S, "aws ec2 start-instances --instance-ids i-1", "aws ec2 stop-instances --instance-ids i-1"),
        (S, "gcloud compute instances start vm1", "gcloud compute instances list"),
        (S, "modal run app.py", "modal app list"),
        (S, "curl -X POST https://api.runpod.ai/v2/ep/runsync -d '{\"input\":{}}'",
         "curl https://api.runpod.ai/v2/ep/status/j1"),
        (S, "curl -X POST https://api.vultr.com/v2/instances -d '{}'",
         "curl https://api.vultr.com/v2/instances"),
        (S, "curl 'https://ec2.amazonaws.com/?Action=RunInstances&ImageId=a'",
         "curl 'https://ec2.amazonaws.com/?Action=DescribeInstances'"),
        # SDK one-liners
        (S, "python -c \"import runpod; runpod.create_pod('a','b','c')\"",
         "python -c \"import runpod; runpod.get_pods()\""),
        (S, "python3 -c \"import runpod; runpod.resume_pod('p', 1)\"",
         "python3 -c \"import runpod; runpod.stop_pod('p')\""),
        (S, "py -c \"import runpod; runpod.create_endpoint(name='x', template_id='t')\"",
         "py -c \"import runpod; runpod.get_endpoints()\""),
        (S, "python -c \"import runpod; runpod.Endpoint('e').run_sync({})\"",
         "python -c \"import runpod; runpod.Endpoint('e').health()\""),
        (S, "python - <<EOF\nimport runpod\nrunpod.create_pod(name='x', image_name='i', "
            "gpu_type_id='g', cloud_type='COMMUNITY')\nEOF",
         "python - <<EOF\nimport runpod\nprint(runpod.get_gpus())\nEOF"),
        (S, "python -c \"import boto3; boto3.client('ec2').run_instances(MinCount=1)\"",
         "python -c \"import boto3; boto3.client('ec2').describe_instances()\""),
        (S, "python -c \"import boto3; boto3.client('ec2').request_spot_instances()\"",
         "grep -rn 'request_spot_instances(' src/"),
        # #178: Node/Bun/Deno runpod-sdk one-liners (endpoint run/runSync/runAsync bill)
        (S, "node -e \"const s=require('runpod-sdk').default('k'); s.endpoint('e').run({input:{}})\"",
         "node -e \"const s=require('runpod-sdk').default('k'); s.endpoint('e').status('j')\""),
        (S, "node --eval \"import('runpod-sdk').then(m=>m.default('k').endpoint('e').runSync({}))\"",
         "node --eval \"import('runpod-sdk').then(m=>m.default('k').endpoint('e').health())\""),
        (S, "node -p \"require('runpod-sdk').default('k').endpoint('e').runAsync({})\"",
         "node -p \"require('runpod-sdk')\""),
        (S, "cat > r.mjs <<'EOF'\nimport runpodSdk from 'runpod-sdk'\n"
            "await runpodSdk('k').endpoint('e').runSync({input:{}})\nEOF\nnode r.mjs",
         "cat > r.mjs <<'EOF'\nimport runpodSdk from 'runpod-sdk'\n"
         "console.log(await runpodSdk('k').endpoint('e').health())\nEOF\nnode r.mjs"),
        (S, "node --input-type=module <<'EOF'\nimport r from 'runpod-sdk'\nr('k').endpoint('e').run({})\nEOF",
         "node --input-type=module <<'EOF'\nimport r from 'runpod-sdk'\nconsole.log(typeof r)\nEOF"),
        (S, "npx -y -p runpod-sdk node -e \"require('runpod-sdk').default('k').endpoint('e').run({})\"",
         "npx -y -p runpod-sdk node -e \"require('runpod-sdk').default('k').endpoint('e').status('j')\""),
        (S, "bun -e \"(await import('runpod-sdk')).default('k').endpoint('e').runSync({})\"",
         "bun -e \"(await import('runpod-sdk')).default('k').endpoint('e').health()\""),
        (S, "deno eval \"import('npm:runpod-sdk').then(m=>m.default('k').endpoint('e').run({}))\"",
         "deno eval \"import('npm:runpod-sdk').then(m=>console.log(typeof m))\""),
        (P, "node -e \"require('runpod-sdk').default('k').endpoint('e').runSync({})\"",
         "node -e \"console.log('runpod-sdk')\""),
        # spot / interruptible
        (S, "runpodctl create pod --communityCloud --bid 0.2", "runpodctl get pod --communityCloud"),
        (S, "aws ec2 request-spot-instances --spot-price 0.1", "aws ec2 describe-spot-price-history"),
    ]
    for tool, bad_cmd, ok_cmd in forms:
        record("#160 blocks: %s %r" % (tool, bad_cmd),
               check(tool, {"command": bad_cmd}, None, env=iso) is not None)
        record("#160 near-miss allowed: %s %r" % (tool, ok_cmd),
               check(tool, {"command": ok_cmd}, None, env=iso) is None)
    # misses found by adversarial runs while building #160
    for tool, cmd in (
            (S, "echo cnVucG9kY3RsIGNyZWF0ZSBwb2Q= | base64 -d | sh"),
            (S, "parallel runpodctl ::: create"),
            (P, "& (Get-Command runpodctl).Source create pod"),
            (S, "curl -X POST https://api.runpod.io/graphql --data-binary @mutation.json"),
            (S, "python -c \"from runpod.api.ctl_commands import create_pod as c; c('a')\""),
            (S, "X=ls; X=runpodctl; $X create pod"),
            (S, "for c in runpodctl; do $c create pod; done"),
            (S, "${RP:-runpodctl} create pod"),
            (S, "g(){ runpodctl \"$@\"; }; f(){ g \"$@\"; }; f create pod"),
            (P, "$sb = { runpodctl @args }; & $sb create pod"),
            (P, "Set-Item -Path function:f -Value { runpodctl @args }; f create pod")):
        record("#160 regression blocks: %s %r" % (tool, cmd),
               check(tool, {"command": cmd}, None, env=iso) is not None)
    other_allow = [
        (P, "runpodctl get pod -o json | ConvertFrom-Json | % { $_.id }"),
        (P, "foreach ($p in (runpodctl get pod -o json | ConvertFrom-Json)) { $p.id }"),
        (S, "curl -fsSL https://get.runpod.io/install.sh | bash"),
        (S, "cd $PROJ && runpodctl pod list"),
        (P, "$x = 1; if ($x -eq 1) { runpodctl pod list }"),
    ]
    for tool, cmd in other_allow:
        record("#160 allowed: %s %r" % (tool, cmd),
               check(tool, {"command": cmd}, None, env=iso) is None)

    # 17a. indirection never opens an inline approval; a literal one still works
    for tool, cmd in (
            (S, A + "X=runpodctl $X create pod"), (S, A + "runpodctl $VERB pod"),
            (S, A + "curl -X POST https://rest.runpod.io/v1/pods -d '{}'"),
            (S, A + "python -c \"import runpod; runpod.create_pod('a','b','c')\""),
            (S, A + "xargs runpodctl"),
            (P, P_ + "Start-Process runpodctl -ArgumentList 'create pod'"),
            (P, P_ + "& $X create pod; runpodctl get pod"),
            (P, P_ + "runpodctl create pod --name ('run'+'podctl create pod')")):
        record("#160 inline approval does not cover: %r" % cmd,
               check(tool, {"command": cmd}, None, env=iso) is not None)
    for tool, cmd in ((S, A + "runpodctl create pod --communityCloud"),
                      (P, P_ + "runpodctl create pod --communityCloud"),
                      (P, P_ + r"& 'C:\x\runpodctl.exe' pod create x")):
        record("#160 literal inline approval still allows: %r" % cmd,
               check(tool, {"command": cmd}, None, env=iso) is None)

    # 17b. approval file: one hidden action allowed, two refused
    with tempfile.TemporaryDirectory() as tmp:
        env = {"SPEND_GATE_APPROVALS_DIR": tmp}
        open(os.path.join(tmp, "approved-1"), "w").close()
        record("#160 file approval refuses two hidden creates",
               check(S, {"command": "X=runpodctl; $X create pod; $X create pod"},
                     None, env=env) is not None
               and os.path.exists(os.path.join(tmp, "approved-1")))
        record("#160 file approval covers one alias create",
               check(S, {"command": "alias r=runpodctl; r create pod"}, None, env=env)
               is None and not os.path.exists(os.path.join(tmp, "approved-1")))

    # 17d. #202: global flags before the service, gcloud tracks, xargs stdin, new defaults
    for cmd in ("aws --region us-east-1 ec2 run-instances --image-id x",
                "aws --profile p ec2 start-instances --instance-ids i-1",
                "aws --region=us-east-1 --output json ec2 run-instances",
                "aws --debug ec2 run-instances",
                "aws --no-verify-ssl --region x ec2 request-spot-instances",
                "gcloud --project p compute instances create vm1",
                "gcloud --project=p compute instances create vm1",
                "gcloud alpha compute instances create vm1",
                "gcloud beta compute instances create vm1",
                "gcloud beta --project p compute instances start vm1",
                "gcloud --verbosity debug alpha compute instances create vm1",
                "gcloud compute instances bulk create --count 2",
                "az --subscription s vm create -n v",
                "az --subscription=s vm create -n v",
                "az vm start -n v -g g",
                "az --debug vm start -n v",
                "xargs runpodctl <<< 'pod create'",
                "xargs runpodctl < args.txt",
                "xargs runpodctl pod < args.txt",
                "cat args.txt | xargs runpodctl",
                "xargs -a args.txt runpodctl"):
        record("#202 blocks: %r" % cmd, check(S, {"command": cmd}, None, env=iso) is not None)
    for cmd in ("aws --region x ec2 describe-instances",
                "aws --profile p s3 ls",
                "aws --region x ec2 stop-instances --instance-ids i-1",
                "gcloud --project p compute instances list",
                "gcloud alpha compute instances describe vm1",
                "gcloud config set project p",
                "az --subscription s vm list",
                "az vm stop -n v -g g",
                "az account show",
                "xargs runpodctl pod list < ids.txt",
                "runpodctl pod list | xargs -n1 runpodctl pod stop"):
        record("#202 allows: %r" % cmd, check(S, {"command": cmd}, None, env=iso) is None)

    # 17c. perf: long lines through every rewrite stay well under 1 s
    n = 2000
    for label, tool, cmd in (
            ("assigns", S, "; ".join("X%d=runpodctl" % i for i in range(n)) + "; $X1 get pod"),
            ("aliases", S, "alias " + " ".join("a%d=runpodctl" % i for i in range(n)) + "; a1 get"),
            ("funcs", S, " ".join('f%d(){ runpodctl "$@"; };' % i for i in range(n)) + " f1 get"),
            ("braces", S, "f(){ " + "{ " * n + 'runpodctl "$@"' + " }" * n + "; }; f get pod"),
            ("refs", S, "X=runpodctl; " + " ".join(["${X}"] * n)),
            ("ps-assign", P, "; ".join("$x%d = 'runpodctl pod list'" % i for i in range(n))),
            ("startproc", P, "Start-Process runpodctl " + " ".join(["-ArgumentList 'a'"] * n)),
            ("graphql", S, "curl -X POST https://api.runpod.io/graphql -d '"
             + " ".join(["mutation { podStop(input:{}) }"] * n) + "'"),
            ("eval", S, " ".join(["eval x"] * n) + " runpodctl"),
            ("b64", S, "echo " + " ".join(["cnVucG9kY3RsIGdldCBwb2Q="] * n) + " | base64 -d"),
            ("dollar-brace", S, "runpodctl " + "${" * n),
            ("cli-flags", S, "gcloud " + "--f v " * n + "beta " + "--g=w " * n + "compute instances list"),
            ("spaces", S, "alias r=runpodctl;" + " " * 20000 + "$X")):
        dt = _best_time(lambda: check(tool, {"command": cmd}, None, env=iso))
        record("#160 perf %s %d chars < %.0fs (best of 3: %.3fs)" % (label, len(cmd), PERF_LIMIT, dt),
               dt < PERF_LIMIT)

    print("\n%d passed, %d failed" % (passed, failed))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
