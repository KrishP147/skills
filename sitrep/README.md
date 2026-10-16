# sitrep

*`SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Answers "how's it going" in **10 lines or fewer**: what's running right now,
git state (worktrees, dirty/unpushed work), open PRs and their CI, an
asked-vs-done checklist for this conversation, anything that needs you, and
a verdict on whether it's safe to close the session. It's a live, spoken
answer, not a document.

## When to use

- "How's it going", "status update", "what's running", "anything for me",
  "can I close this".
- Named `sitrep` rather than `/status` because `/status` is already a
  built-in Claude Code command.
- Not for a written record of a long run — that's
  [`progress-report`](../progress-report/), which is scoped to everything
  since the last report and produces a file. `sitrep` never writes a report
  and only answers for right now.

## How to invoke

```
/sitrep
```

Model-invocable, so any of the trigger phrases above work without typing the
slash command.

## How it works

1. **What's running.** Collects background task IDs from the transcript
   (`Bash`/`PowerShell` with `run_in_background`, `Monitor` loops,
   background `Agent` launches) minus those whose completion notification
   already arrived; reports each one's age and its last output line (read
   from the task's output file, or `TaskOutput`, now deprecated). Checks `ListAgents` (if available) for
   other addressable agents.
2. **Git.** For each repo this session ran git in (not only the current
   one): `git worktree list`; per worktree, `git status --porcelain` and
   `git status --porcelain --ignored -- skilleddocs` (handoffs in an excluded
   `skilleddocs/`), and unpushed commits (`git log <default>..`, or `@{u}..`
   with an upstream). A branch with 0 commits and a clean tree has nothing to
   push; "never pushed" is only for commits with no upstream.
3. **PRs + CI.** `gh pr list --author @me` with checks status.
4. **Asked vs. done.** A short checklist built from this conversation's user
   messages — not the whole backlog.
5. **Needs-you items.** Missing keys/approvals/manual steps/unanswered
   questions, or "none".
6. **Verdict.** SAFE to close only if nothing's running, nothing's
   dirty/unpushed (or it's intentional and already handed off), and any
   mid-flight work has a handoff: committed and pushed, or saved on disk per
   [`TRACKING.md`](../handoff-auto/TRACKING.md) (untracked; the only option
   on forks). An untracked handoff covers only the work it describes, and
   is NOT SAFE when its worktree is a non-main one or was made by
   pair/meta-orchestrator (it would be removed with the worktree), or when
   unsure. Otherwise NOT SAFE, with the specific reasons.
7. **On "close" / "yes, stop them":** lists exactly what will be stopped and
   what (if anything) would be committed/pushed, and waits for an explicit
   yes before doing either. On yes, stops background tasks with `TaskStop`
   (if available); calls `handoff-auto` to write the handoff if anything was
   mid-flight, and prints its path.

Reads: background-task tools (if available), `git`, `gh`, this conversation.
Writes: nothing, except a handoff document via `handoff-auto` when closing
mid-flight work, saved under `skilleddocs/handoffs/`.

## Design principles

- **Live and conversational, not a document.** `progress-report` already
  covers the ledger-scoped, written case; `sitrep` fills the gap of "just
  tell me, right now, in chat."
- **Read-only by default.** Reconnaissance only reads state; the one path
  that changes anything (stopping background work, writing a handoff) is
  gated behind an explicit yes.
- **Short on purpose.** A status check that takes longer to read than the
  work itself defeats the point — hence the 10-line cap and "drop empty
  lines rather than padding them."

## Use cases

- Mid-session, checking whether a background agent or long shell command has
  finished.
- Before stepping away, to see whether anything is unpushed or uncommitted
  across several worktrees.
- Before closing a session or terminal, to get a SAFE/NOT SAFE verdict
  instead of guessing.
- After a flurry of asks, to see which ones are still outstanding.

## Tips

- If `ListAgents` isn't enabled, or a background task's output file path
  isn't in the transcript, `sitrep` still works from the transcript alone and
  says the last-output check was skipped. (`TaskOutput` is deprecated in
  favor of `Read` on the output file.) `TaskList` is the session to-do list, not background work; it
  only feeds the asked-vs-done line.
- "Can I close this?" and "close this" are different asks: the former is a
  read-only verdict (§2); only the latter (or an explicit "yes, stop them")
  triggers the gated stop-and-handoff flow in §4.
- Ask again after fixing a NOT SAFE reason — it's cheap and re-checks
  everything, not just the item you fixed.

## Example

```
/sitrep
```

```
Running: 1 background (8m, "3 tests failing") | 0 agents pending
Git: 2 worktrees, 1 dirty, 1 unpushed (fix/date-parse, 3 commits)
PRs: #21 checks passing
Asked -> done: 3/4 (in progress: fixing date parser)
Needs you: none
Verdict: NOT SAFE - background test run still failing, fix/date-parse unpushed
```

Untracked handoff in a worktree slated for removal:

```
Running: none
Git: 2 worktrees, clean, all pushed (handoff in ../wt-issue-9 is excluded)
PRs: none
Asked -> done: 2/2
Needs you: none
Verdict: NOT SAFE - untracked handoff in worktree slated for removal: move ../wt-issue-9/skilleddocs/handoffs/2026-10-15-x.md or keep worktree
```

## Related

- [`progress-report`](../progress-report/) — the written, ledger-scoped
  counterpart; use it for "what's been done" over a whole run, not "right
  now".
- [`handoff-auto`](../handoff-auto/) — writes the handoff document `sitrep`
  points at when it closes mid-flight work.
- [`session-handoff`](../kanban/session-handoff/) — same handoff, plus board
  bookkeeping, for a full end-of-session wrap-up rather than a quick check.

## Prereqs

`gh` for the PR/CI check. `TaskOutput` (deprecated), `TaskStop`, `TaskList` and
`ListAgents` are optional — used when available,
skipped with a note otherwise.
