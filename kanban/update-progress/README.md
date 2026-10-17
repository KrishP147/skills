# update-progress

*`SKILL.md` is the prompt Claude follows; this file is for you. Loop overview: [`kanban/README.md`](../README.md).*

## What it does

Takes a handoff document, **verifies** its claims (git log, tests, code review), then updates the repo's docs, the board and the issue to match what actually happened.

## When to use

In a fresh session after [`session-handoff`](../session-handoff/). The `verifier` agent runs it end to end.

## How to invoke

`/update-progress [path to handoff doc]`

- Omit the path to use the newest file by mtime in `skilleddocs/handoffs/` across all worktrees (then the OS temp dir).
- Model-invocable.

## How it works

1. **Locate the handoff**: the given path, or the newest by mtime.
   - Looks in the handoff folder (`AGENTS.md`/`CLAUDE.md`'s, else `skilleddocs/handoffs/`) of every `git worktree list` entry, current first.
   - Other worktrees' untracked files only.
   - Skips one whose issues already carry a "verified, merged" comment.
   - Tied mtimes are listed and you are asked.
   - Then temp dir.
2. **Verify claims:** `git log` over the handoff's base SHA..head (else `git merge-base <default> <branch>`).
   - Fetches first and counts head as merged when it is on `origin/<default>` or the branch has a merged PR containing it (squash and rebase merges count; a deleted PR branch is read via the PR's `pull/<n>/head` ref; an erroring check never counts as merged).
   - Runs the repo's test suite on the handoff's code: the default checkout (fast-forwarded) if head is merged, else the worktree with the branch checked out, else a temporary `git worktree add` of head.
   - Doesn't trust "tests pass".
3. **Code review** via the `code-review` skill if product code changed.
4. **Update docs that exist** (only once the work is merged into the default branch):
   - Roadmap checkboxes, status doc rows + dated entry, decisions doc (only if a decision was recorded), else README status section / `CHANGELOG.md` / `docs/`.
   - Moves a "current phase" marker to where merges are landing.
   - Fixes README feature lists that miss merged capabilities.
   - Never invents doc structure.
5. **Update the board:** comments on the issue.
   - Closes it and moves the card to Done if complete, verified and merged.
   - Complete and verified but unmerged → In Review with a "verified, awaiting merge" comment.
   - Otherwise sets the card/label to where it stands.
   - Label mode: creates `status:done` first if missing; complete, verified and merged → `status:in-review` (or a never-moved `status:in-progress`) becomes `status:done`; partial/blocked keeps its label.
6. **Escalate deviations:** if the handoff's `## Board status` lists deviations/innovations, calls [`consult-plan`](../consult-plan/).
7. **Commits the doc edits and the handoff** on the default branch.
   - The handoff is moved into the default checkout first if it sits in the task's worktree, so it can't block that branch's next merge.
   - Handoff only if it was left uncommitted and the repo is in commit mode per [`TRACKING.md`](../../handoff-auto/TRACKING.md).
   - A protected default branch (a PR required by classic protection or a ruleset; an unclear answer, e.g. no admin rights on the classic endpoint, means it asks) gets a `docs/` branch instead (or the repo's own branch prefix).
   - Pushes, and opens that PR, only on your yes.
8. Ends by calling (or telling you to call) [`next`](../next/).

## Design principles

- **Every claim is unverified until checked.** "Tests pass" in a handoff means nothing until `git log` and a real test run agree.
- **Fresh session.** Verification runs in a new context, not the one that did the work.
- **Update only what exists.** It ticks boxes and adds rows in the docs the repo already has; it never invents doc structure.
- **Drift is fixed here.** A merged capability missing from the README or status summary gets added, and a "current phase" marker follows where merges land.

## Use cases

- Closing the loop after `/session-handoff`: verify, update docs, move the card to Done.
- Checking a handoff someone (or an agent) else wrote before you trust it.
- Inside the `verifier` agent at the end of each task in a `meta-orchestrator` run.
- Routing a session's deviations to `consult-plan` instead of letting them silently change the plan.

## Tips

- Run it in a fresh session.
- With no argument it picks the newest file by mtime in the handoff folder of any worktree, so pass the path if several sessions ended recently.
- Only complete, verified and merged work goes to Done and closes the issue.
- Verified but unmerged waits in In Review.
- Anything else is set to where it really stands.
- Code review only runs when product code changed; the `verifier` agent skips it with `review-done=yes`.
- It ends with `next`, so the following task is already on screen.

## Example

```
/update-progress
```

1. Picks the newest handoff, `skilleddocs/handoffs/2026-10-15-csv-export.md`, for #31.
2. `git log` from the handoff's base SHA shows 3 commits, already merged into `main`; runs `npm test` there (green), matching the handoff.
3. Product code changed, so it runs `code-review` on those commits.
4. Ticks #31 in `ROADMAP.md` and adds a `CHANGELOG.md` entry, both already present in the repo; the README's feature list lacked CSV export, so it adds it.
5. Comments a summary on #31, moves the card to Done and closes the issue.
6. `## Board status` lists a "streaming writer" deviation, so it calls `consult-plan` on it.
7. Runs `next`, which suggests #28.

## Related

- Input from [`session-handoff`](../session-handoff/); calls `code-review`, [`consult-plan`](../consult-plan/), [`next`](../next/).
- Preloaded by the `verifier` agent (which can skip step 3 with `review-done=yes`).

## Prereqs

- `gh`, authenticated with the `project` OAuth scope: run `gh auth refresh -s project -s read:project` once (see [`kanban/README.md`](../README.md#prerequisite-the-project-oauth-scope)).
- `consult-plan` and `next` installed.
- A `code-review` skill for the review step.
