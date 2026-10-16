# Rotation: handing off to a fresh orchestrator

Your state is already external (`scope.md`, the ledger, git), so a fresh orchestrator loses nothing. Rotate on purpose instead of degrading.

## When

- `handoff_budget` merged loops this session, or
- a smart-zone warning fires, or you're re-reading files you already know.

Finish the loop in flight first; never hand off mid-merge. `parallel > 1`: start no new issue in any lane, let every in-flight lane finish its loop (merge and verify) or park its issue, then hand off.

## Hand off

1. Write `skilleddocs/orchestrator/orchestrator-handoff.md`, then commit and push it (unless `docs_commit: uncommitted`):
   - scope path + its hash (`git log -1 --format=%h -- <scope>`; uncommitted: `git hash-object <scope>`), and the number step 2's `handoff` entry will take (last entry + 1)
   - loop state, one line per lane (`parallel: 1` = one line): lane, issue, branch, worktree, step (plan / implement / gate / verify), last result path
   - open worktrees and unmerged branches (flag any linked `node_modules`/`.venv`; tear down only with `pair` §5's steps: move or merge every record in its doc folders into main, unlink, check, then `git worktree remove`)
   - `decisions: assume` → open assumed decisions (`A-n`, one line each)
   - local-only files that must stay uncommitted
   - `resume with: /meta-orchestrator <repo> resume`
2. Ledger `handoff` entry; manual step = the resume command.
3. `reports: handoff` → run `progress-report` now.
4. Tell the user in two lines and stop.

## Resume

1. Read `scope.md`, `orchestrator-handoff.md`, and the last 5 ledger entries. The contract stands; ask nothing from SETUP.md.
2. Recon what changed while no orchestrator ran: new commits on default, new PRs, stray branches.
3. Continue each lane from its recorded step, reset the budget counter (`handoff_budget` counts merges per session; `stop: after N merges` counts per run, ledger merges since setup, and is never reset), log a `decision` entry "resumed from handoff <NNN>".
