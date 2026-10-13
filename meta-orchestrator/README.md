# meta-orchestrator

*`SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Works through a repo's backlog unattended. Claude becomes the **orchestrator**: it never implements, it loops `planner` → `manager` (or `implementer`) → merge gate → `verifier`, holds the merge gate itself (tests + CI green or no merge), logs every event to a ledger, and hands off to a fresh orchestrator session after a budget of merges.

## When to use

- "Go through the open issues and don't stop", "work through the board with subagents", "act as the orchestrator".
- "Resume" a previous orchestrator run.
- For one task, use [`pair`](../pair/) instead.

## How to invoke

```
/meta-orchestrator <repo path or name> [resume] [+ scope notes, e.g. 'skip gated issues', 'execution: flat']
```

Model-invocable. `resume` skips the setup questions and continues from `orchestrator-handoff.md`.

## How it works

0. **Confirm, then ask once.** Reads the repo's contributing guide / `CLAUDE.md` / `AGENTS.md`; checks the named skills and the four agents exist (repo-local skills win; falls back to `general-purpose` if agents are missing). Read-only recon (branches, issues, PRs, CI). Asks every unclear thing in one batch (stray branches, interview authorization, exclusions, merge style, report location, execution mode, handoff budget). Reads `skilleddocs/` (decisions, grills, handoffs) as the design record. Writes the answers to **`skilleddocs/orchestrator/scope.md`** in the repo, committed — the run's contract.
1. **Agents.** `planner` (opus) → kickoff brief; `manager` (opus, `execution: pair`, default) or `implementer` (sonnet, `execution: flat`); `verifier` (opus); `general-purpose` on **haiku** for chores (board moves, filing a pre-written issue, CI log triage, recon, doc count fixes), never for judgment or the merge gate. Each step is a fresh Agent call; the handoff doc or saved manager report is the only bridge to the verifier. Agents are told to run code review inline (nested fan-out stalls). A manager report titled **INTERIM** is not a result; the orchestrator waits for the final one.
2. **Loop:** `planner → manager | implementer → merge gate → verifier → repeat`. Worktrees (`../_worktrees/<repo>-<slug>`) optional; deps linked from the main checkout as in `pair`.
3. **Merge gate (orchestrator only).** Pull; run tests or read CI for the head SHA; skim the diff for scope creep, secrets, personal data, doc drift; push the branch, merge in the repo's style, delete branch, fast-forward default; tear down any worktree links-first (never a recursive delete through a linked `node_modules`/`.venv`), then `git worktree remove`; append a ledger entry.
4. **Autonomy rules.** Interview skills answered by the verifier only if you authorized it, logged as "decided for you". With `decisions: assume` in scope (for fast/MVP runs), agents make design calls themselves and record each as an open **assumed** decision (`A-n`: what, why, what would change it, undo cost); only you confirm or replace it. Divide when work is multi-session. One retry per failure, then file/split and move on — never loop. The `guard-git.py` hook blocks agents from pushing default / merging.
5. **Ledger.** Append-only `skilleddocs/orchestrator/ledger.md` in the repo, committed after every entry: `### NNN · <local timestamp> · <kind>` with issue/PR, what, verified-by, decided-for-you, manual step. Timestamps in your local time zone.
6. **Handoff cycle.** After `handoff_budget` merges (default 10) or a smart-zone warning, finishes the current loop, writes `<reports>/orchestrator-handoff.md` (scope, last ledger entry, loop state, open worktrees/branches, resume command), logs a `handoff` entry, and stops. `resume` reads `scope.md`, the handoff and the ledger tail, re-runs recon, continues.
7. **Done** when every in-scope issue is closed or parked with a reason, default is green, every merge has a verify entry.

Files: `scope.md`, `ledger.md`, `orchestrator-handoff.md` under `skilleddocs/orchestrator/` in the repo; manager reports under `skilleddocs/orchestrator/reports/`.

## Related

- Spawns [`planner`, `manager`, `implementer`, `verifier`](../agents/README.md).
- Uses [`pair`](../pair/)'s manager pattern; kanban skills via the agents ([`next`](../kanban/next/), [`divide`](../kanban/divide/), [`update-progress`](../kanban/update-progress/), [`consult-plan`](../kanban/consult-plan/)).
- [`progress-report`](../progress-report/) reads its ledger.
- Optional [`hooks/smartzone.py`](../hooks/) triggers an early handoff.

## Example

```
/meta-orchestrator ~/code/myrepo skip issues labelled needs-design
```

Asks one batch of questions, writes `reports/scope.md`, then loops: planner picks #17, a manager implements and reviews it, the orchestrator merges on green CI, the verifier updates the board and surfaces #18. After 10 merges it writes `reports/orchestrator-handoff.md` and tells you to run `/meta-orchestrator ~/code/myrepo resume` in a fresh session.
