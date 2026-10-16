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

Approval (either one allows the single matched action):
  1. File-based, one-shot: drop a file into skilleddocs/spend-approvals/
     (relative to cwd; override the directory with
     SPEND_GATE_APPROVALS_DIR). The filename is just a label - contents are
     ignored. Names starting with "." (.gitkeep, .DS_Store) never count.
     The hook consumes (deletes) the first one it finds (sorted by name)
     and allows that single call; the log is skilleddocs/spend.md.
  2. SPEND_GATE_APPROVED=<label>, two ways to set it:
       - PowerShell only: start the command with
         `$env:SPEND_GATE_APPROVED='<label>'; <cmd>` (leading only, `;`
         required, non-empty value). Bash-style prefixes are not honoured.
       - Bash only: prefix the single command, e.g.
         `SPEND_GATE_APPROVED=yes runpodctl create pod ...` - this is a
         shell per-command env assignment, so it is read out of the command
         string itself (this hook does not execute the command) and only
         ever covers that one invocation.
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

DEFAULT_BASH_PATTERNS = [
    _RP + r"""(?:(?:pods?|serverless|sls|network-volume|nv)\s+)?(?:create|start)(?![\w-])""",
    _RP + r"""(?:network-volume|nv)\s+update\b[^\n]*--size\b""",
    _RP + r"""(?:serverless|sls)\s+update\b""",
    _RP + r"""(?:serverless|sls)\s+run\b""",
    _RP + r"""pods?\s+update\b[^\n]*--(?:volume-in-gb|container-disk-in-gb)\b""",
    _RP + r"""model\s+add\b""",
    r"""\bvultr-cli(?:\.exe|\.cmd)?["']?\s+instance\s+create\b""",
    r"""\baws(?:\.exe|\.cmd)?["']?\s+ec2\s+run-instances\b""",
    r"""\bgcloud(?:\.exe|\.cmd)?["']?\s+compute\s+instances\s+create\b""",
    r"""\baz(?:\.exe|\.cmd)?["']?\s+vm\s+create\b""",
    r"""\bmodal(?:\.exe|\.cmd)?["']?\s+deploy\b""",
]

# Deliberately not defaulted (ambiguous - has free tiers / non-billable uses):
# `fly deploy`. Add it yourself via SPEND_GUARD_PATTERNS or the patterns file
# if your fly.io usage is always billable.

DEFAULT_MCP_GLOBS = [
    "mcp__*runpod*__create-*",
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


def match_billable(tool_name, command, bash_patterns, mcp_globs):
    """Return a (reason, matched) tuple, or (None, None) if nothing matches.
    Never raises - any matching error fails open."""
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
            for glob in mcp_globs:
                if fnmatch.fnmatch(tool_name.lower(), glob.lower()):
                    return (
                        "tool '%s' matches billable MCP pattern '%s'" % (tool_name, glob),
                        glob,
                    )
        return None, None
    except Exception:
        return None, None


def inline_env_approved(command):
    """True if the Bash command string itself starts with a shell
    per-command SPEND_GATE_APPROVED=<value> assignment (possibly among
    other leading VAR=value assignments), e.g.
    `SPEND_GATE_APPROVED=yes runpodctl create pod ...`. This hook never
    executes the command, so it reads the assignment out of the string."""
    if not command:
        return False
    try:
        tokens = command.strip().split()
    except Exception:
        return False
    for tok in tokens:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            key, _, val = tok.partition("=")
            if key == "SPEND_GATE_APPROVED" and val:
                return True
            continue
        break  # first non-assignment token ends the env-prefix run
    return False


_PS_INLINE_RE = re.compile(
    r"""^\s*\$env:SPEND_GATE_APPROVED\s*=\s*(?:'[^']+'|"[^"$]+"|[^\s;'"$]+)\s*;""",
    re.IGNORECASE,
)


def powershell_inline_approved(command):
    """True if the PowerShell command string starts with
    `$env:SPEND_GATE_APPROVED='<label>';` (single, double or no quotes,
    non-empty literal value, `;` required). A `$` in an unquoted or
    double-quoted value is rejected: `$null`/`"$x"` may expand to empty.
    Only a leading assignment counts, never one mid-string. Bash-style `VAR=val cmd` is not valid PowerShell, so it
    is deliberately not honoured here."""
    if not command:
        return False
    try:
        return bool(_PS_INLINE_RE.match(command))
    except Exception:
        return False


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
        "(2) prefix the Bash command with SPEND_GATE_APPROVED=<label> "
        "(covers just that command), or start a PowerShell command with "
        "$env:SPEND_GATE_APPROVED='<label>'; <cmd>. MCP tool calls: use the file. "
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

    reason, _matched = match_billable(tool_name, command, bash_patterns, mcp_globs)
    if tool_name and fnmatch.fnmatch(tool_name.lower(), POD_ACTION_GLOB):
        # Verb-dependent: only start/resume blocks; anything else allows.
        reason = pod_action_billable(tool_name, tool_input)
    if tool_name and fnmatch.fnmatch(tool_name.lower(), NETVOL_UPDATE_GLOB):
        # Only a body containing "size" blocks; rename-only allows.
        reason = netvol_update_billable(tool_name, tool_input)
    if tool_name and fnmatch.fnmatch(tool_name.lower(), POD_UPDATE_GLOB):
        # Only a body with a storage-size key blocks; name/image allows.
        reason = pod_update_billable(tool_name, tool_input)
    if reason is None:
        return None  # not billable (or unrecognized) - allow

    if command:
        if tool_name == "PowerShell":
            if powershell_inline_approved(command):
                return None
        elif inline_env_approved(command):
            return None
    if env_approved(env):
        return None

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
    import time
    t0 = time.time()
    long_cmd = "runpodctl " + " ".join(["--a-b c"] * 400 + ["-x"] * 400) + " pod list"
    record("400+400 flag run allows fast (no backtracking blowup)",
           check("Bash", {"command": long_cmd}, None, env=iso) is None
           and time.time() - t0 < 2.0)
    record("pod update volumeInGb allowed with approval",
           check(up, {"body": {"volumeInGb": 5}}, None,
                 env=dict(iso, SPEND_GATE_APPROVED="yes")) is None)

    print("\n%d passed, %d failed" % (passed, failed))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
