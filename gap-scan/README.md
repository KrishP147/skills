# gap-scan

*`SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Surveys one or more repos — code, recent commits, docs, open issues, and
(for a UI app) a visual pass — and hands back a ranked list of gaps, bugs,
and extension ideas.

- Every item cites its evidence (a `file:line`, a commit SHA, or an issue
  number); an item with nothing to point at gets dropped rather than listed.
- Read-only: it writes one report file and nothing else.

## When to use

- "What's missing", "find gaps", "what should I work on in this repo",
  "scan for bugs/extensions", "survey this repo".
- Starting cold on a repo you (or someone else) haven't touched in a while
  and want a prioritized starting point instead of reading everything by
  hand.
- Not for picking the next task off an existing board — that's
  [`kanban/next`](../kanban/next/) reading the board this skill's output can
  seed. Not for watching an open PR to merge — that's
  [`pr-watch`](../pr-watch/).

## How to invoke

```
/gap-scan [repo path or owner/repo, ...] [--commits N]
```

No argument surveys the current repo. Model-invocable, so the trigger
phrases above work without the slash command.

## How it works

1. **Sync.** Per repo:
   - If dirty (tracked changes, or untracked files outside `skilleddocs/`,
     so its own report doesn't count), skip the pull and say so.
   - No upstream or no remote: skip the pull and say so.
   - Otherwise `git pull --ff-only` (a diverged history is reported the same
     as dirty, never force-merged).
   - A fork also fetches `upstream`, reports how far ahead/behind it is, and
     pulls upstream's own `good first issue`-labeled issues.
2. **Survey.**
   - README and docs (flagging doc/code drift).
   - The last ~20 commits (default; `--commits` overrides).
   - A `TODO`/`FIXME`/`XXX` grep over code.
   - The repo's detected test command (run if it looks cheap, otherwise
     skipped with a reason).
   - Every open issue — so a gap that's already tracked is marked as such
     instead of proposed again.
   - If `gh` can't reach the issues (non-GitHub remote, no auth), the summary
     says `Issues: not checked (why)` and items read `new (issues unchecked)`.
3. **Optional visual pass.** Only for a web/UI app, using the `run` skill or
   a screenshot capability if this session has one; skipped (with a reason)
   for libraries, CLIs, and backend-only services, or when no such tool is
   available.
4. **Rank and tag.** Every surviving candidate gets a value/effort
   trade-off, an `S`/`L` size tag, and mandatory evidence — no evidence, no
   listing. A secret is cited by `file:line` or SHA, never by its value.
5. **Write.** One file, `skilleddocs/gaps/<local-date>.md` — the only write
   this skill makes. Never committed unless asked; `skilleddocs/` is excluded
   per [`TRACKING.md`](../handoff-auto/TRACKING.md).
6. **Report.** A short chat summary plus the top items inline; full detail
   in the file.
7. **Gate.** Creating issues, commenting, or touching a board needs an
   explicit yes for that specific action; a vague reply means do nothing.
   Offers `kanban-setup` (user-only: you type `/kanban-setup`), `divide`, or
   `grill-docs` as next steps instead of taking them itself.

Reads: `git`, `gh`, the repo's files and test command, optionally the `run`
skill. Writes: `skilleddocs/gaps/<local-date>.md` only.

## Design principles

- **Evidence or it doesn't exist.** A ranked list that can't be traced back
  to a line, a commit, or an issue is just opinion; this skill would rather
  under-report than pad the list.
- **Don't re-litigate the board.** Cross-checking open issues before
  ranking means the output adds to a backlog instead of duplicating it.
- **Report, then stop.** Surveying and proposing is the whole job; turning
  a proposal into an issue or a PR is a separate, explicitly gated step
  (or another skill's, via the hand-offs at the end of the report).

## Use cases

- Picking up a repo cold and wanting a prioritized "start here" instead of
  reading every file yourself.
- Before a planning session, to get a fresh, evidence-backed list to sanity
  check against what's already on the board.
- On a fork, to see both home-grown gaps and upstream's own
  `good first issue` backlog in one pass.
- Periodic health check on a repo you maintain but haven't looked at in a
  while — doc drift and TODOs tend to accumulate quietly.

## Tips

- Run it before `kanban-setup` on a repo with no board yet — its output is
  ready to backfill from.
- An `L`-tagged item is a signal to run `divide` on it before anyone starts,
  not to tackle it in one sitting.
- If the test command looks expensive or needs credentials, the report says
  "not run" and why instead of guessing at the result — check that line
  before trusting a "tests: clean" read of the repo.
- The visual pass only fires for actual UI apps; a "skipped" line for a
  library or CLI is expected, not a missing feature.

## Example

```
/gap-scan
```

Illustrative: repo state as of 2026-09-26; findings may since be fixed.

Run read-only against a skills-and-agents repo (a collection of small
Markdown-defined Claude Code skills, a lint script, and a small static
site). Sync: clean, pulled nothing new. Survey found:

- No `TODO`/`FIXME` markers in any script or hook — the handful of
  matches were skills' own docs *describing* that convention, not
  unresolved markers, so nothing was listed for those.
- The lint script warns (non-fatal) that 15 skill `README.md` files are
  missing four required sections. That gap already has an open issue
  covering exactly this, so it's listed as **already tracked**, not
  proposed again.
- Two hook scripts that gate destructive or billable commands each ship a
  `--self-test` mode, but CI runs lint, the site build, and the unit-test
  suites only, never those self-tests. A regression in either guard would
  merge green. Cheap to fix, high stakes: the top new item.
- The static site's per-skill detail page is a template that still says
  "coming soon". A real extension, but bigger: it needs a decision on what
  each page shows.

Chat summary:

```
Scanned <repo> (synced clean).
6 candidates -> 3 after evidence + already-tracked filter.
Report: skilleddocs/gaps/2026-09-26.md

1. [S] Run the hooks' --self-test in CI - both guards have one, CI never
   calls it (evidence: .github/workflows/ci.yml:23-31,
   agents/hooks/guard-git.py:120, hooks/spend-guard.py:245)
2. [L] Real per-skill detail pages - template is a placeholder
   (evidence: site/src/detail.html:17)
3. [S] README section backfill - already tracked: #22

Issues: 14 open, 1 matched.
Tests: 9 passed (python unittest suite).
Visual: skipped (the site is a sub-project; not in scope this pass).
```

No issues were created — that needs an explicit yes (the gate in `SKILL.md`).

## Related

- [`kanban-setup`](../kanban/kanban-setup/) — backfill a board/issues from
  this skill's report, offered but never run automatically.
- [`divide`](../kanban/divide/) — split an `L`-tagged item into
  session-sized issues before work starts on it.
- [`grill-docs`](../grill-docs/) — stress-test a candidate gap before
  committing to it, with a paper trail.
- [`kanban/next`](../kanban/next/) — the read side of an existing board;
  `gap-scan` is for when there's nothing to read yet, or you want a fresh
  pass regardless of what's on it.
- [`pr-watch`](../pr-watch/) — the equivalent read-then-gate loop for open
  PRs instead of a repo's overall state.

## Prereqs

- `git`, `gh`.
- The `run` skill (or an in-session screenshot capability) is optional and
  only used for the visual/UX pass on web/UI apps — skipped with a note when
  absent.
