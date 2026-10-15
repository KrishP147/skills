---
name: gap-scan
description: Survey one or more repos (code, commits, docs, tests, issues) and return a ranked, evidence-cited list of gaps, bugs, and extension ideas as issue-ready items. Read-only apart from its report. Use for "what's missing", "find gaps", "what should I work on in this repo".
argument-hint: "[repo path | owner/repo, ...] [--commits N]"
---

Read-only. The one write is the report under `skilleddocs/gaps/`. Issues, comments, labels, and board changes each need an explicit yes for that action.

No argument: current repo. Several: §1–3 per repo, one combined report. `--commits N` (default 20).

## 1. Sync

- Dirty tree → skip the pull and say so; survey as-is.
- Clean → `git pull --ff-only`; diverged → report it like dirty.
- Fork → `git fetch upstream`; report ahead/behind; also list upstream's open `good first issue`s.

## 2. Survey

- **Docs vs code**: every README/docs/roadmap claim the code contradicts (or code the docs miss), cited `doc:line` beside `code:line`.
- **Commits**: reverts, repeated fixes to one area (fragile spot), messages admitting shortcuts.
- **`TODO|FIXME|XXX`** in code, by `file:line`.
- **Tests**: find the command. Cheap (no network, GPU, paid calls, credentials) → run it, report failures. Otherwise "tests not run: <why>".
- **Open issues**: `gh issue list --state open --json number,title,labels`. A gap matching one is **already tracked: #n**, listed but not re-proposed.
- **UI apps only** (frontend, served site, dashboard), with the `run` skill or a screenshot tool: screenshot the main views and note layout, spacing, style, and dead-link problems, citing screenshot + component. Otherwise "visual pass: skipped (<not a UI app | no tool>)".

## 3. Rank

Value for effort, highest first; the trade-off in one clause. Size `S` (one session, one area) or `L` (multi-area or needs a design call → `divide` candidate). **Evidence or drop it**: every item cites `file:line`, a SHA, or `#n`.

## 4. Report

`skilleddocs/gaps/<local-date>.md`, uncommitted unless asked. Per item:

```markdown
### <title>
- Why: <what's missing/broken and why it matters>
- Evidence: <file:line | SHA | #n>
- Size: S | L
- Suggested labels: <bug, enhancement, ...>
- Status: new | already tracked: #<n>
```

Chat reply:

```
Scanned <repo> (synced clean | dirty, pull skipped). 12 candidates → 5 after filters.
Report: skilleddocs/gaps/<date>.md
1. [S] <title> — <why> (path/file.py:42)
2. [L] <title> — <why> (a1b2c3d)
Tests: <N passed/failed | not run: why>   Visual: <findings | skipped: why>
```

Then offer, don't run: `kanban-setup` (board from this list), `divide` (split an `L`), `grill-docs` (stress-test a big call).
