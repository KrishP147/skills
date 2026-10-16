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
Default billable patterns: `runpodctl` `create`/`start` (legacy `create pod`/`start pod` and v2 `pod|serverless|network-volume|nv create|start`; `template`/`registry create` are free and stay ungated), `runpodctl network-volume|nv update ... --size` (resize; rename-only is allowed), `runpodctl serverless|sls update`, `runpodctl serverless|sls run` (job submit), `runpodctl pod|pods update ... --volume-in-gb|--container-disk-in-gb` (storage resize; other updates allowed), `runpodctl model add` (uploads to model storage), the `sls` alias for `create`/`update`/`run`, global flags before the noun (`--profile x pod create`, `-o json serverless run`), `vultr-cli instance create`,
`aws ec2 run-instances|request-spot-instances|request-spot-fleet`, `gcloud compute instances create`, `az vm create`,
`modal deploy` (also as `.exe`/`.cmd`, quoted, or full-path forms), and MCP tools matching `mcp__*runpod*__create-*` (except the free `create-template`, `create-secret`, `create-registry` and `create-delegation`, which only write config or credential records; a `mcp:` glob of your own still gates them) /
`mcp__*runpod*__deploy-*` / `__run-endpoint` / `__runsync-endpoint` /
`__retry-job` / `__update-endpoint` / `__set-endpoint-gpus`, plus
`__pod-action` only when its action is `start` or `resume` (read from
`tool_input.body.action`, else `tool_input.action`; `stop`, `restart`,
`terminate` and an unrecognised shape are allowed). `__update-network-volume` only when `tool_input.body` is an object with a `size` key (resize bills; name-only allowed; blocks even if the size equals the current one, since the hook can't know it). `__update-pod` only when `tool_input.body` is an object with a `disk`, `templateId` (applies a template's disk), `mounts.persistent` (always carries `size`, so a path-only edit blocks too), or v1 `volumeInGb`/`containerDiskInGb` key (name/image/env/ports and network/global mounts allowed). There is no `runpodctl hub deploy`: Hub deploys go through `serverless create --hub-id`, already gated. `update-global-volume` is not gated: it only takes a name, nothing billable. Trade-off: more approval
prompts, since every job submit and endpoint update now needs approval. Deliberately **not** defaulted: `fly deploy` and
similar commands with a real free tier — add them yourself if your usage is
always billable. No match → exits 0 (allow) immediately. Any error while
reading config or matching (bad regex, unreadable file, malformed stdin)
**fails open** — allows the call rather than blocking unrelated work on a
hook bug; this hook is a net under `spend-gate`, not the only gate.

Indirect forms. The patterns are also run on rewrites of the command, and a
few rules cover billers that are not a CLI. All of these block:

- **Aliases, functions, variables** defined in the same command, substituted
  into their call sites: `alias r=runpodctl; r create pod`,
  `X=runpodctl; $X create pod` (also `${X}`, `"$X"`, `A=runpod; B=ctl; $A$B`),
  `f(){ runpodctl "$@"; }; f create pod`, `function f { ... }`, PowerShell
  `Set-Alias r runpodctl`, `$X='runpodctl'; & $X create pod`,
  `function f { runpodctl @args }`, `$a='create','pod'; runpodctl @a`. The
  near miss (`X=runpodctl; $X get pod`) is allowed.
- **Start-Process / saps / start**: `-FilePath` and `-ArgumentList` (any
  order, positional or comma lists) are reassembled into `<file> <args>`.
  `cmd /c`, `bash -c`, `pwsh -c` were already covered.
- **Quoting and encoding noise**: `'run''podctl'`, `r\unpodctl`,
  `{runpodctl,create,pod}`, `('run'+'podctl')`, PowerShell backticks,
  `$'\x72...'`, `(Get-Command runpodctl).Source`, base64 from
  `-EncodedCommand` or `base64 -d`.
- **REST/GraphQL writes** (`curl`, `wget`, `Invoke-RestMethod`/`irm`,
  `Invoke-WebRequest`/`iwr`, python `requests`, ...). A write is an explicit
  `POST`/`PUT`/`PATCH` or a body flag (`-d`, `--data*`, `--json`, `-F`, `-T`,
  `--post-data`, `-Body`, `-InFile`). Blocked: writes to `rest.runpod.io`
  except `templates`, `containerregistryauth`, `secrets`, `user`, `billing`
  and `/stop`; `api.runpod.ai/v2/<id>/run|runsync|...` except
  `cancel`/`purge-queue`/`status`/`health`/`stream`; Runpod GraphQL
  (`api.runpod.io/graphql`) mutations whose field reads
  deploy/rent/resume/create/save/update/edit/bid/start/launch
  (`podFindAndDeployOnDemand`, `podRentInterruptable`, `podResume`,
  `saveEndpoint`, ...) or a write whose body can't be read (`-d @file`);
  `api.vultr.com` writes (except ssh-keys, firewalls, startup-scripts,
  domains, users, account, iso, `/halt`); EC2 `Action=RunInstances` (and
  spot/fleet/start); GCE `.../instances` writes; Azure
  `Microsoft.Compute/virtualMachines` writes. GETs, DELETEs, `/stop` and a
  query-only GraphQL body (`query { myself { pods { id } } }`) are allowed.
- **SDK one-liners** (needs `python`/`py` or an `import` in the command, so
  `python -c` and `python - <<EOF` heredocs): Runpod `create_pod`,
  `create_endpoint`, `resume_pod`, `create_network_volume`, `run_sync`,
  `Endpoint(..).run(..)`, importing one of those by name; boto3
  `run_instances`/`request_spot_instances`/`create_instances`/...; GCE
  `insert`; Azure `begin_create_or_update`; Modal `deploy`/`remote`/`spawn`.
- **Fallback**: when the command mentions a billable program (or `runpod`,
  `boto3`, a provider API host), a call target or verb argument whose value
  can't be read blocks: `$X create pod` / `& $c create pod` with no
  definition in the command, `eval "$C"`, `iex $c`, `runpodctl $VERB`,
  `aws ec2 $ACTION`, `xargs runpodctl`. With no mention at all
  (`$X create pod` alone) the hook can't tell and allows.

Spot and interruptible flags (`--communityCloud`, `--bid`,
`podRentInterruptable`, `"interruptible": true`) don't change any of this:
the create still blocks. A call blocked only through one of these forms is
not covered by an inline `SPEND_GATE_APPROVED` (that reads the raw command);
use the approval file. Every rewrite is a regex scan or a single linear
pass, capped, so a 2000-flag line stays well under a second.

Approval scheme (either allows the one matched action):

1. **File-based, one-shot.** Drop a file into
   `skilleddocs/spend-approvals/` (path relative to the tool call's `cwd`;
   override the directory with `SPEND_GATE_APPROVALS_DIR`). The filename is
   just a label — contents are ignored, and names starting with `.`
   (`.gitkeep`, `.DS_Store`) never count. The hook deletes the first file it
   finds (sorted by name) and allows that single call; the next matching
   call is blocked again until another approval file appears. The file is
   gone after use, so it is no record: the log is `skilleddocs/spend.md`. A
   call holding two or more billable commands (`<create> && <create>`) is
   refused and the file kept: run them as separate calls.
2. **`SPEND_GATE_APPROVED=<label>`.** For `Bash`, prefix the one command —
   `SPEND_GATE_APPROVED=yes runpodctl create pod ...` — this is a shell
   per-command env assignment, read out of the command string itself (the
   hook never executes the command), so it only ever covers that one
   invocation. For `PowerShell`, start the command with
   `$env:SPEND_GATE_APPROVED='<label>'; <cmd>` (leading only, `;` required,
   non-empty literal value, no `$` variables; a Bash-style prefix is not
   honoured). Both inline forms count only when the rest of the call is
   one simple command whose program is the call's only billable match:
   `true && <create>`, `<create>; <create>`, a pipe, `&`, a newline, a
   subshell, `$(...)`, backticks or a wrapper (`bash -c '<create>'`,
   `xargs`, `sudo`) is not approved, and `export SPEND_GATE_APPROVED=...`
   never is. `env SPEND_GATE_APPROVED=yes <create>` is the same single
   command and counts. Redirections (`> out 2>&1`) are fine. For an MCP tool call use the approval file: `export` inside a
   Bash tool call never reaches the hook's environment. The hook does also
   honour `SPEND_GATE_APPROVED` in the environment Claude Code was launched
   with, but that approves every matching call for the whole session, so
   avoid it.

This is a tripwire, not a security boundary: an agent that can write files
can write its own approval. It catches a skipped gate. It can't stop an
agent that ignores the skill.

Patterns are searched anywhere in the command string, so a command that only
mentions a billable command also trips: `grep -rn 'runpodctl pod create'`,
`echo 'modal deploy app.py' >> README.md`, a `git commit -m` message naming
one. This is accepted tripwire behaviour: rephrase (e.g. put the text in a
file and use `git commit -F`) or approve it.

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
  ⎿ Blocked: command matches billable pattern '\brunpodctl(?:\.exe|\.cmd)?["']?\s+(?:(?:pods?|serverless|network-volume|nv)\s+)?(?:create|start)\b'. Approve with ONE of: (1) drop a file into skilleddocs/spend-approvals/ (one-shot, consumed on use); (2) prefix the Bash command with SPEND_GATE_APPROVED=<label>, or start a PowerShell command with $env:SPEND_GATE_APPROVED='<label>'; <cmd> (inline: one simple command only, no ;/&&/|/subshell, one billable command). MCP tool calls: use the file. See the spend-gate skill: estimate, check balance, get an explicit yes for this action, log it, before approving.
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
