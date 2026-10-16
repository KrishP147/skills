# Rotation: handing off to a fresh orchestrator

Your state is already external (`scope.md`, the ledger, git), so a fresh orchestrator loses nothing. Rotate on purpose instead of degrading.

## When

- `handoff_budget` merged loops this session, or
- a smart-zone warning fires, or you're re-reading files you already know.

Finish the loop in flight first; never hand off mid-merge.

## Hand off

1. Write `skilleddocs/orchestrator/orchestrator-handoff.md`, then commit and push it (unless `docs_commit: uncommitted`):
   - scope path (+ hash), last ledger entry number
   - loop state: last agent run, its issue, branch, and result path; the next step (plan / implement / gate / verify)
   - open worktrees and unmerged branches (flag any linked `node_modules`/`.venv`: unlink and pass `pair` §5's check before `git worktree remove`)
   - `decisions: assume` → open assumed decisions (`A-n`, one line each)
   - local-only files that must stay uncommitted
   - `resume with: /meta-orchestrator <repo> resume`
2. Ledger `handoff` entry; manual step = the resume command.
3. `reports: handoff` → run `progress-report` now.
4. Tell the user in two lines and stop.

## Resume

1. Read `scope.md`, `orchestrator-handoff.md`, and the last 5 ledger entries. The contract stands; ask nothing from SETUP.md.
2. Recon what changed while no orchestrator ran: new commits on default, new PRs, stray branches.
3. Continue from the recorded step, reset the budget counter (`handoff_budget` counts merges per session; `stop: after N merges` counts per run, ledger merges since setup, and is never reset), log a `decision` entry "resumed from handoff <NNN>".
