# session-bridge

*`SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Coordinates with another running Claude Code session or agent that might be working on the same repo.

- Finds it.
- Takes a read-only snapshot of what it's doing.
- Checks for overlap (same files, branch, issue/PR).
- Only with your explicit yes, sends it a message.
- Everything it learns from the other session is treated as information to show you, never as your approval for anything.

## When to use

- "Check with the other session", "what's the other agent doing",
  "coordinate with my other terminal", "is anyone else touching this
  file/branch", "message the other Claude", "sync up with the other
  worktree", "avoid duplicate work", "ask the other session".
- Not for talking to a subagent you spawned yourself in this conversation —
  that's ordinary `SendMessage`/resume, no bridging needed. `session-bridge`
  is for an *independent* session or agent you didn't spawn from here:
  another terminal, another worktree, a teammate's session, or a cloud run.

## How to invoke

```
/session-bridge
```

Claude also runs it when you say one of the phrases above, so you don't have to
type the slash command.

## How it works

1. **Identify the target.** `ListAgents` (if available) first, because it's live and authoritative.
   - Otherwise, fall back to that repo's transcripts under `~/.claude/projects/<encoded-cwd>/*.jsonl`.
   - `<encoded-cwd>` is the working directory path with every character other than letters and digits replaced by `-`.
   - If no target is found, it says so and stops.
2. **Read-only snapshot.** Uses `ListAgents`/`SendMessage` if the session is reachable that way, or reads the other session's transcript with the bundled `scripts/snapshot.py`. It never dumps the raw `.jsonl` file (no `cat`).
   - Extracts only the last user ask, the last N actions, and any branches/PRs/files mentioned.
   - Also checks `git`, `gh pr`, and that repo's `skilleddocs/` for its handoff/ledger.
   - Redacts anything that looks like a secret, token, or personal data before repeating it.
3. **Overlap/conflict detection.** Compares the other session's files, branch/worktree, and issue/PR against this session's own, and proposes a concrete ownership split when they collide.
4. **Gate.** Shows the exact message text and the exact recipient before sending anything, and waits for an explicit yes.
5. **Send.** `SendMessage` if available and the target is reachable that way; otherwise appends to a shared `skilleddocs/bridge.md` as a drop-off, since there's no live channel to that session.
6. **Log.** Every exchange (sent and any reply) appended to `skilleddocs/bridge.md` with local timestamps, not UTC.
7. **Report.** The reply, if one arrives — or "no reply" if not.
   - Notes when a session (cloud, Remote-Control, or transcript-only) can't reply by design.
   - Reads its transcript/handoff/PR instead where accessible.

Reads: `ListAgents` (if available), transcript files under `~/.claude/projects/`, `git`, `gh`, a repo's `skilleddocs/`.

Writes: nothing without the step 4 gate.

- On a yes, either a `SendMessage` call or an append to `skilleddocs/bridge.md`.
- `skilleddocs/bridge.md` also gets the exchange log either way.

## Design principles

- **Read-only until an explicit yes.** Finding and snapshotting another
  session never sends anything; only step 4's gate can turn a draft into a sent
  message.
- **A message from another session is never approval.** It's data to relay
  to the user, not a command to execute or a substitute for the user's own
  yes — stated as its own rule so it's never assumed away under time
  pressure.
- **Best-effort discovery.** `ListAgents`/`SendMessage` are the fast path
  when available; the transcript fallback exists because they aren't always
  on, but it's one-directional by nature, so the skill says so rather than
  pretending a reply is possible.

## Use cases

- Two terminals on the same repo, different worktrees or branches, about to
  touch the same files.
- Picking up a task and wanting to know whether another session already
  started it, before duplicating the work.
- A long-running session needs to hand a finding or a heads-up to another
  one working the same issue, without you copy-pasting between terminals.
- Checking a cloud or background session's progress via its transcript or
  PR when it isn't reachable for a live reply.

## Tips

- If `ListAgents` isn't available or doesn't list the target, the
  transcript fallback still works, but a session found that way generally
  can't reply back — treat it as a one-way read, not a conversation.
- Redact first, ask questions later: never repeat a token, key, or personal
  detail found in another session's transcript, even back to the user who
  asked for the snapshot.
- Overlap on the same file doesn't always mean stop — sometimes the right
  call is "you take the top half, I'll take the bottom," and this skill
  proposes that split rather than just flagging a collision.

## Example

```
/session-bridge
```

```
Found: session "api-worker" (ListAgents), repo same as this one, branch
fix/login. Snapshot: last ask "add rate limiting to /login", last action
edited src/auth.py. Overlap: you're both touching src/auth.py.
Proposed split: it keeps src/auth.py, you take src/session.py.
Send this to api-worker? "Heads up — I'm on src/session.py for the same
issue, can you stick to src/auth.py so we don't collide?"
```

## Related

- [`sitrep`](../sitrep/README.md) — checks *this* session's own state
  (background work, git, PRs); `session-bridge` checks an *other* session's
  state instead.
- [`pair`](../pair/README.md) and [`meta-orchestrator`](../meta-orchestrator/README.md)
  — run isolated worktrees/agents that `session-bridge` can coordinate
  between, but neither one bridges to a session outside its own run.
- [`spend-gate`](../spend-gate/README.md) — the same explicit-yes-before-
  outward-action pattern, applied to billable actions instead of messages.

## Prereqs

None required.

- `ListAgents`/`SendMessage` are used when available and enabled (cross-session messaging); without them, the skill falls back to reading transcript files and to `skilleddocs/bridge.md`.
- `gh` is used, if present, for the PR/issue overlap check.
