# meta-orchestrator

*`SKILL.md` is the prompt Claude follows; `SETUP.md` (first-run interview + every option) and `ROTATION.md` (handoff / resume) are loaded only when needed. This file is for you.*

## What it does

Works through a repo's backlog unattended. Claude becomes the **orchestrator**: it never implements, it loops `planner` → `manager` (or `implementer`) → merge gate → `verifier`, holds the merge gate itself (tests + CI green or no merge), logs every event to a ledger, and hands off to a fresh orchestrator session after a budget of merges. Almost every behaviour is a setting you pick on the first run.

## When to use

- "Go through the open issues and don't stop", "work through the board with subagents", "act as the orchestrator".
- "Resume" a previous orchestrator run.
- For one task, use [`pair`](../pair/) instead.

## How to invoke

```
/meta-orchestrator <repo path> [resume | reconfigure] [key=value ...]
```

- First run: setup interview (below), then the loop.
- `resume`: no questions; continues from `orchestrator-handoff.md`.
- `reconfigure`: re-run the interview on an existing run.
- `key=value` skips that question, e.g. `merge=ask execution=flat reports=end`.

## How it works

0. **Setup** ([`SETUP.md`](SETUP.md)). Read-only recon (contributing guide, `skilleddocs/`, branches, PRs, CI, merge style). Resolves defaults in layers: built-ins → your saved `~/.claude/orchestrator-defaults.md` → the repo's `AGENTS.md`/`CLAUDE.md` → arguments. Shows the resulting contract and asks **"Use these, or customize?"**. Customize walks four short rounds (multiple choice, recommended option first):

   | Round | You choose |
   |---|---|
   | Run shape | which issues, when to stop (queue empty / N merges / time box), `pair` vs `flat`, how many issues in parallel |
   | Control | merge `auto` / `ask` each time / `pr-only`, merge style, whether agents may answer planning questions for you, which changes always pause for you (new deps, migrations, deletions, API or CI changes; billable always) |
   | Documentation | what gets written (ledger always; decisions register, per-issue handoffs, manager reports, CHANGELOG lines), whether docs are committed, report cadence (each handoff / every N merges / end / on request), Markdown or docx, ledger detail |
   | Models and pacing | implementer model, review model, handoff budget, push notifications |

   Writes **`skilleddocs/orchestrator/scope.md`** (a yaml block of every key), commits it, and offers to save your choices as personal defaults so the next repo starts from them.
1. **Agents.** `planner` → kickoff brief; `manager` (`execution: pair`) or `implementer` (`execution: flat`); `verifier`. Each step is a fresh Agent call. Agents run code review inline (nested fan-out stalls). An **INTERIM** report is not a result.
2. **Loop:** `planner → manager | implementer → merge gate → verifier → repeat`; parallel issues each get their own worktree.
3. **Merge gate (orchestrator only).** Tests/CI green for the head SHA; diff skimmed for scope creep, secrets, drift and anything on your pause list; push, then merge per your `merge` setting; worktree torn down links-first; ledger entry.
4. **Autonomy.** One retry per failure, then split or park, never loop. The `guard-git.py` hook blocks agents from pushing default or merging.
5. **Ledger.** Append-only `skilleddocs/orchestrator/ledger.md`, local timestamps, committed per entry (unless you chose uncommitted docs).
6. **Rotation** ([`ROTATION.md`](ROTATION.md)). After `handoff_budget` merges or a smart-zone warning: writes `orchestrator-handoff.md`, logs it, optionally runs a progress report, stops. `resume` picks up from there.
7. **Done** when every in-scope issue is closed or parked with a reason (or `stop` is reached), default is green, every merge has a verify entry.

## Design principles

- **The orchestrator never implements.** Its context stays free for decisions; a strong model there is worth more than anywhere else.
- **State lives in files, not context.** `scope.md` + ledger + git mean any fresh session can take over, so rotating is cheap and degrading is avoidable.
- **Ask once, up front.** Every preference is settled in setup and saved; the loop itself only stops for destructive or scope-changing calls.
- **Gates are binary.** Green tests and CI for the exact SHA, or no merge.

## Use cases

- Clearing a labelled backlog overnight with `merge=auto`.
- Running cautiously on a shared repo with `merge=pr-only`, so every change waits as a PR for you.
- Long runs split across days via `resume`, with a progress report at each handoff.

## Tips

- Run it once, customize, and save defaults; later repos then need one "use these" click.
- `merge=ask` is a good first run on a repo you care about; switch to `auto` once you trust the gate.
- Pair with branch protection on GitHub; the guard hook is a guardrail, not a sandbox.

## Example

```
/meta-orchestrator ~/code/myrepo merge=ask
```

Shows the contract (merge already set to `ask`), you pick "Use these", it writes `skilleddocs/orchestrator/scope.md`, then loops: planner picks #17, a manager implements and reviews it, the orchestrator shows you the green PR and merges on your yes, the verifier updates the board and surfaces #18. After 10 merges it writes `orchestrator-handoff.md` and tells you to run `/meta-orchestrator ~/code/myrepo resume` in a fresh session.

## Related

- Spawns [`planner`, `manager`, `implementer`, `verifier`](../agents/README.md).
- Uses [`pair`](../pair/)'s worktree pattern; kanban skills via the agents ([`next`](../kanban/next/), [`divide`](../kanban/divide/), [`update-progress`](../kanban/update-progress/), [`consult-plan`](../kanban/consult-plan/)).
- [`progress-report`](../progress-report/) reads its ledger.
- Optional [`hooks/smartzone.py`](../hooks/smartzone.py) triggers an early rotation.

## Prereqs

`gh` (authenticated); the four agents installed (`scripts/install-skills.*`); a board, `status:*` labels, or a roadmap doc for `next` to read. Push notifications need the PushNotification tool.
