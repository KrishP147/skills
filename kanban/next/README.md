# next

*`SKILL.md` is the prompt Claude follows; this file is for you. Loop overview: [`kanban/README.md`](../README.md).*

Works on its own.

## What it does

Shows the next 1–3 tasks to work on, pulled from the repo's GitHub kanban board, with a size and a suggested model for each.

- Read-only (Edit/Write disallowed).

## When to use

- Starting a work session: "what should I work on next?"
- End of `update-progress` and `verifier` runs, to surface the following task.

## How to invoke

`/next`, or just ask what's next. Claude can also run it itself.

## How it works

1. **Find the board** (the same lookup the other kanban skills use): `gh project list --owner <owner>`, filtered to the title `<repo> Board` or boards linking this repo's issues.
   - One match → use it; several → asks you.
   - None → `status:todo` / `status:in-progress` / `status:in-review` / `status:done` labels. Whichever skill applies one first creates it (`gh label create status:<name> --color <hex> --force`); each label has a fixed color, so repeat calls change nothing.
   - None → a roadmap doc (`ROADMAP.md`, `docs/roadmap.md`) whose execution order links issues.
   - Nothing → tells you to run `/kanban-setup`.
2. **Failing CI comes first:** workflow names come from `gh workflow list --json name -q '.[].name'`.
   - It checks the most recent *completed* run on the default branch, which counts as red only if its conclusion is `failure`.
   - An old, since-fixed failure doesn't count.
   - `cancelled`/`timed_out` aren't treated as red.
   - Checked per workflow when there are several.
3. **Candidates:**
   - In Review items first, tagged "awaiting verification" (Projects: the In Review column; labels: `status:in-review`).
   - Then Projects Todo/Ready items (it double-checks with `gh issue list` if `gh project item-list`, which can lag, returns empty), `status:todo` issues, or open issues in roadmap order.
   - Issues labelled `wayfinder:*` are skipped (they belong to `/wayfinder`).
   - Within each group (In Review, then Todo), sorted by `priority:*` label (`p0` before `p1`, `high` before `low`), else roadmap order, else oldest first.
   - A repo's `CLAUDE.md`/`AGENTS.md` rules override all of this.
4. **Present:** top 1–3 with title, number, size (`size:*` label or "unestimated"), suggested model (a fast one for well-specified work, a strong one for ambiguous or `needs-design` work).
   - "go" picks the top one.
   - Picking doesn't claim the card; `pair` or `meta-orchestrator` moves it to In Progress when it creates the branch, so a Todo card may have been picked but never started.

## Design principles

- **Read-only.** Edit and Write are disallowed; it only looks. Picking a task doesn't claim the card: whoever creates the branch moves it.
- **A red default branch comes first.** A failing latest run on the default branch outranks every card.
- **One board lookup for every skill.** How to find the board and move a card lives in [`BOARD.md`](BOARD.md), which the other kanban skills and agents point at.

## Use cases

- Opening a work session and choosing what to do.
- After `update-progress` or a `verifier` run, to surface the following task.
- Inside the `planner` agent, as the first step of briefing an orchestrated run.
- A repo with no Projects board: it falls back to `status:*` labels, then a roadmap doc.

## Tips

- Say "go" to take the top suggestion.
- A Todo card may have been picked before but never started; only a created branch moves it to In Progress.
- Add `size:*` and priority labels to issues if you want sizes and ordering rather than "unestimated" and oldest first.
- Your repo's `CLAUDE.md` or `AGENTS.md` can override the ordering rules.
- "Board is empty" is double-checked against `gh issue list`, since `gh project item-list` can lag.

## Example

```
/next
```

The board `myrepo Board` is found by title. The latest completed CI run on `main` passed, so nothing jumps the queue. Two Todo items come back, ordered by priority label:

```
1. #31 Add CSV export (size:M, fast model: narrow, well-specified)
2. #28 Rework auth flow (unestimated, strong model: needs-design)
Say "go" for #31, or pick one.
```

Had the latest `main` run failed, the failing workflow would be listed first as priority #1. You say "go"; the card stays in Todo until a branch is created for #31.

## Related

- [`kanban-setup`](../kanban-setup/) creates the board it reads.
- Called by [`update-progress`](../update-progress/); preloaded by the `planner` and `verifier` agents.
- Board lookup reused by `session-handoff`, `update-progress`, `kanban-setup`.

## Prereqs

- `gh`, authenticated, `origin` on GitHub (otherwise it stops and says so).
- Projects v2 boards need the `project` OAuth scope: run `gh auth refresh -s project -s read:project` once (see [`kanban/README.md`](../README.md#prerequisite-the-project-oauth-scope)).
