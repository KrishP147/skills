# hooks/ — optional per-repo hooks

Not installed by `install-skills`; copy what you want into a repo's
`.claude/hooks/` and wire it in that repo's `.claude/settings.json`.
(The agents' own `guard-git.py` lives in [`../agents/hooks/`](../agents/hooks/)
and *is* installed, into `~/.claude/agents/hooks/`, or wired by the plugin.)
None of these ship with the plugin either.

Each `hooks/*.py` gets a page on the [skills site](https://www.krishpunjabi.com/skills/),
built from its ``## `<file>.py` — tagline`` section below (the tagline is the
summary; the build fails if a hook has no section). See [`../site/README.md`](../site/README.md).

## `smartzone.py` — "your context has left the smart zone" warning

`UserPromptSubmit` hook. Prints a one-line warning into the conversation when
the live context passes ~75k tokens, so both you and Claude see it and can
wrap up: `/divide` the rest, then `/session-handoff` (or, for an orchestrator,
the rotation step (`ROTATION.md`) in `meta-orchestrator`). Heuristic only;
`/context` is the precise check.

How it works: on every prompt you submit, Claude Code passes the hook JSON
on stdin; the script reads `transcript_path` and only the tail of that file
(never the whole transcript). It takes the last main-chain assistant entry
(not a sidechain) with `message.usage` and sums `input_tokens +
cache_creation_input_tokens + cache_read_input_tokens`. `/compact` appends a
`compact_boundary` line and never truncates the file, so usage from before the
last boundary is ignored; if there is no usage after it (or at all), it falls
back to the bytes after the last boundary (whole file if none) at ~20 bytes
per token. If the result is at least the threshold it prints the warning
(stdout is injected into the conversation). Below it, or on any error
(missing file, malformed lines, bad env), it prints nothing and never blocks.

Threshold: env var `SMARTZONE_TOKENS` (integer tokens), default `75000` (the
old 1.5 MB size check at ~20 bytes per token). A bad value falls back to the
default. Set it in the hook `command` or your shell env.

Related: [`divide`](../kanban/divide/), [`session-handoff`](../kanban/session-handoff/),
[`meta-orchestrator`](../meta-orchestrator/) (rotates early on this warning).

Example output once a long session crosses the threshold:

```
[smart-zone] Session transcript context is ~82k tokens - context has likely left the smart zone (~100-120k tokens; this is a heuristic, verify with /context). Wrap up: run /divide on the remaining work, then /session-handoff, and continue in a fresh session.
```

Install per repo:

```bash
mkdir -p .claude/hooks
cp <skills repo>/hooks/smartzone.py .claude/hooks/
```

`.claude/settings.json` (merge into an existing `hooks` block if there is one):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"$CLAUDE_PROJECT_DIR/.claude/hooks/smartzone.py\" || exit 0"
          }
        ]
      }
    ]
  }
}
```

Claude Code asks you to approve the hook once per repo.

Install at user level (covers sessions started in your home directory too).
In a home-dir session `$CLAUDE_PROJECT_DIR` is `~`, so a per-repo
`.claude/hooks/` copy is never loaded there. Copy the script to
`~/.claude/hooks/` and register it in `~/.claude/settings.json` with an
absolute path:

```bash
mkdir -p ~/.claude/hooks
cp <skills repo>/hooks/smartzone.py ~/.claude/hooks/
```

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"/home/you/.claude/hooks/smartzone.py\" || exit 0"
          }
        ]
      }
    ]
  }
}
```

Use your real absolute path (on Windows e.g. `C:/Users/you/.claude/hooks/smartzone.py`).

Self-test (fixtures in temp dirs, no network):

```bash
python hooks/smartzone.py --self-test
```

## `spend-guard.py` — block billable commands without an approval

`PreToolUse` hook for `Bash`, `PowerShell` and MCP tool calls. Enforces the
[`spend-gate`](../spend-gate/) skill's gate at the tool-call level: blocks a
command or MCP call that matches a known billable pattern unless an
approval already exists, so a billable action can't slip through even if
the gate steps get skipped in the prompt.

How it works: reads the hook JSON on stdin (`tool_name`,
`tool_input.command` for `Bash` and `PowerShell`, `cwd`). A `Bash` or `PowerShell` command is checked against
a list of regexes; any other tool name is checked against a list of
`fnmatch` globs (for MCP tool names like `mcp__runpod__create-pod`).
Default billable patterns: `runpodctl create`, `vultr-cli instance create`,
`aws ec2 run-instances`, `gcloud compute instances create`, `az vm create`,
`modal deploy` (also as `.exe`/`.cmd`, quoted, or full-path forms), and MCP tools matching `mcp__*runpod*__create-*` /
`mcp__*runpod*__deploy-*` / `__run-endpoint` / `__runsync-endpoint` /
`__retry-job` / `__update-endpoint` / `__set-endpoint-gpus`, plus
`__pod-action` only when its action is `start` or `resume` (read from
`tool_input.body.action`, else `tool_input.action`; `stop`, `restart`,
`terminate` and an unrecognised shape are allowed). Trade-off: more approval
prompts, since every job submit and endpoint update now needs approval. Deliberately **not** defaulted: `fly deploy` and
similar commands with a real free tier — add them yourself if your usage is
always billable. No match → exits 0 (allow) immediately. Any error while
reading config or matching (bad regex, unreadable file, malformed stdin)
**fails open** — allows the call rather than blocking unrelated work on a
hook bug; this hook is a net under `spend-gate`, not the only gate.

Approval scheme (either allows the one matched action):

1. **File-based, one-shot.** Drop any file into
   `skilleddocs/spend-approvals/` (path relative to the tool call's `cwd`;
   override the directory with `SPEND_GATE_APPROVALS_DIR`). The filename is
   just a label — contents are ignored. The hook deletes the first file it
   finds (sorted by name) and allows that single call; the next matching
   call is blocked again until another approval file appears.
2. **`SPEND_GATE_APPROVED=<label>`.** For `Bash`, prefix the one command —
   `SPEND_GATE_APPROVED=yes runpodctl create pod ...` — this is a shell
   per-command env assignment, read out of the command string itself (the
   hook never executes the command), so it only ever covers that one
   invocation. For `PowerShell`, start the command with
   `$env:SPEND_GATE_APPROVED='<label>'; <cmd>` (leading only, `;` required,
   non-empty value; a Bash-style prefix is not honoured). For an MCP tool call use the approval file: `export` inside a
   Bash tool call never reaches the hook's environment. The hook does also
   honour `SPEND_GATE_APPROVED` in the environment Claude Code was launched
   with, but that approves every matching call for the whole session, so
   avoid it.

This is a tripwire, not a security boundary: an agent that can write files
can write its own approval. It catches a skipped gate. It can't stop an
agent that ignores the skill.

Patterns are extendable, without editing the script:

- **Env var** `SPEND_GUARD_PATTERNS` — entries separated by `;` (regexes can
  contain commas). Each entry is `bash:<regex>` or `mcp:<glob>`; no prefix
  defaults to `bash:`.
- **File** `.claude/spend-guard-patterns.txt` (relative to the tool call's
  `cwd`) — same `bash:`/`mcp:` format, one entry per line; blank lines and
  `#` comments are ignored.

```
# .claude/spend-guard-patterns.txt
bash:\bdoctl\s+droplets\s+create\b
mcp:mcp__*digitalocean*__create-*
```

Example output when Claude runs a billable command with no approval in place:
the hook exits 2 and prints this one line on stderr.

```transcript
⏺ Bash(runpodctl create pod --gpuType RTX4090)
  ⎿ Blocked: command matches billable pattern '\brunpodctl(?:\.exe|\.cmd)?["']?\s+create\b'. Approve with ONE of: (1) drop a file into skilleddocs/spend-approvals/ (one-shot, consumed on use); (2) prefix the Bash command with SPEND_GATE_APPROVED=<label> (covers just that command), or start a PowerShell command with $env:SPEND_GATE_APPROVED='<label>'; <cmd>. MCP tool calls: use the file. See the spend-gate skill: estimate, check balance, get an explicit yes for this action, log it, before approving.
```

After an explicit yes, `SPEND_GATE_APPROVED=yes runpodctl create pod --gpuType RTX4090`
passes (exit 0, nothing printed); the next unprefixed call is blocked again.

Install into a repo:

```bash
mkdir -p .claude/hooks
cp <skills repo>/hooks/spend-guard.py .claude/hooks/
```

`.claude/settings.json` (merge into an existing `hooks` block if there is
one):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|PowerShell|mcp__.*",
        "hooks": [
          {
            "type": "command",
            "command": "python \"$CLAUDE_PROJECT_DIR/.claude/hooks/spend-guard.py\""
          }
        ]
      }
    ]
  }
}
```

Self-test (no billable API/CLI is ever called — every case is in-process
with piped JSON): `python hooks/spend-guard.py --self-test`.

Related: [`spend-gate`](../spend-gate/) (the skill this hook backs up).
