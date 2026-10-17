# kanban-setup

*`SKILL.md` is the prompt Claude follows; this file is for you. Loop overview: [`kanban/README.md`](../README.md).*

Needs: `next` (installed with it).

## What it does

Creates a GitHub Projects (v2) board for a repo if it has none, then backfills issues from work already documented in the repo: planned work, already-done work (created and immediately closed, for history), or both.

## When to use

- A repo has no board yet (`next` tells you to run this).
- You want issue history backfilled from docs, TODOs, CHANGELOG or git log.

## How to invoke

```
/kanban-setup [current | retroactive | both]
```

Default `current`. Only you can run it (`disable-model-invocation: true`), because it creates real, visible issues.

## How it works

1. **Prereq:** `gh auth status` must list the `project` scope.
   - Otherwise offers `gh auth refresh -s project -s read:project` (you run it) or label mode.
   - Stops until you pick.
2. **Board (read-only until you say yes):** looks for `<repo> Board` per `next`'s [`BOARD.md`](../next/BOARD.md) and, if it exists, checks the Status field via `gh project field-list` for an "In Review" option (the default only has Todo/In Progress/Done).
   - Nothing is created in this step.
   - Label mode (four `status:*` labels instead of a board) is used when you ask for it, the `project` scope isn't granted, or the owner can't create projects.
3. **Scan:** README "Roadmap"/"TODO" sections, `TODO`/`FIXME` comments, `CHANGELOG.md`, `docs/` and plan-like docs; skips `skilleddocs/`, `node_modules`, `.venv` and vendored dirs.
4. **Candidates per mode:**
   - Both modes drop items that already have an issue (open or closed).
   - `current` = undone items.
   - `retroactive` = finished items from CHANGELOG / git log / resolved TODOs.
   - `both` = both, separated.
5. **Preview, then create:** shows the board actions and every issue (title, mode, target column), then waits.
   - The board actions are: create the board; `gh project link <n> --owner <owner> --repo <owner>/<repo>`; add In Review; or, in label mode, create the labels.
   - To add In Review it runs the `updateProjectV2Field` GraphQL mutation via `gh api graphql`, replaying every existing option plus the new one (`gh` can't add an option to an existing field). You can add it by hand in the UI instead.
   - On yes: board actions first.
   - Then `current` → create + `item-add` + `item-edit` to Todo.
   - `retroactive` → create, close, `item-add` + `item-edit` to Done (`item-add` alone leaves Status empty, so the `item-edit` step is required, not optional).
   - Label mode: each issue is created with `status:todo`, or `status:done` and closed.

## Design principles

- **Real issues, so preview first.** Issues it creates are public; every one is shown (title, mode, target column) before anything is created.
- **Idempotent board, nothing before the yes.** It looks for this repo's board, links a new one to the repo, and adds the In Review option only when missing; all of it is previewed and runs after your yes.
- **Backfill from what's documented.** Candidates come from the repo's own docs, TODOs, CHANGELOG and (retroactive) git log, deduped against existing issues.

## Use cases

- Starting the kanban loop on a repo with no board, when `next` says to run this.
- Turning a README roadmap or `TODO`/`FIXME` comments into issues.
- Giving a project a clean issue history from its CHANGELOG (`retroactive`, created and closed in Done).
- Adding the missing In Review column to an existing board.

## Tips

- Refresh the `project` scope before starting; it stops until you have.
- Default mode is `current`; pass `retroactive` or `both` for history.
- Prune the preview before you say yes: anything you leave in becomes a real issue.
- If you'd rather not run the GraphQL mutation for In Review, add the option by hand in the GitHub UI ([`IN-REVIEW-OPTION.md`](IN-REVIEW-OPTION.md)).

## Example

```
/kanban-setup both
```

1. `gh auth status` lists `project`, so it continues.
2. No board for this repo; nothing is created yet.
3. Scans the README roadmap, `TODO` comments, `CHANGELOG.md` and `git log`: 7 open TODOs (2 already have issues, skipped) and 12 CHANGELOG entries.
4. Previews the board actions (create and link "myrepo Board", add In Review) and 17 issues in two groups: 5 "current → Todo", 12 "retroactive → Done".
5. On your yes, creates and links the board and adds In Review, then creates the 5 and sets them to Todo; creates and closes the 12 and sets them to Done.

## Related

- [`next`](../next/) reads the board it creates.
- Needs `gh` with the `project` scope.

## Prereqs

- `gh`, authenticated, `origin` on GitHub (otherwise it stops and says so).
- The `project` OAuth scope is needed for a Projects v2 board: run `gh auth refresh -s project -s read:project` once (see [`kanban/README.md`](../README.md#prerequisite-the-project-oauth-scope)).
- It checks for the scope itself and stops if missing.
