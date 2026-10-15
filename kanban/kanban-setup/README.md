# kanban-setup

*`SKILL.md` is the prompt Claude follows; this file is for you. Loop overview: [`kanban/README.md`](../README.md).*

## What it does

Creates a GitHub Projects (v2) board for a repo if it has none, then backfills issues from work already documented in the repo: planned work, already-done work (created and immediately closed, for history), or both.

## When to use

- A repo has no board yet (`next` tells you to run this).
- You want issue history backfilled from docs, TODOs, CHANGELOG or git log.

## How to invoke

```
/kanban-setup [current | retroactive | both]
```

Default `current`. User-invoked only (`disable-model-invocation: true`) because it creates real, visible issues.

## How it works

1. **Prereq:** `gh auth status` must list the `project` scope; otherwise tells you to run `gh auth refresh -s project -s read:project` and stops.
2. **Board (idempotent):** looks for `<repo> Board` per `next`'s [`BOARD.md`](../next/BOARD.md); creates it with `gh project create` if missing; checks the Status field via `gh project field-list` for an "In Review" option (the default only has Todo/In Progress/Done). Missing it: `gh` can't add an option to an existing field, so this runs the `updateProjectV2Field` GraphQL mutation via `gh api graphql` (replaying every existing option plus the new one), or tells you to add it by hand in the UI if that's not wanted. Label mode: creates the four `status:*` labels up front.
3. **Scan:** README "Roadmap"/"TODO" sections, `TODO`/`FIXME` comments, `CHANGELOG.md`, `docs/` and plan-like docs.
4. **Candidates per mode:** `current` = undone items (deduped against existing issues); `retroactive` = finished items from CHANGELOG / git log / resolved TODOs; `both` = both, separated.
5. **Preview, then create:** shows every issue (title, mode, target column) and waits. Then `current` → create + `item-add` + `item-edit` to Todo; `retroactive` → create, close, `item-add` + `item-edit` to Done (`item-add` alone leaves Status empty, so the `item-edit` step is required, not optional).

## Design principles

- **Real issues, so preview first.** Issues it creates are public; every one is shown (title, mode, target column) before anything is created.
- **Idempotent board.** It looks for this repo's board before creating one, and adds the In Review option only when missing.
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
2. No board for this repo, so it creates "myrepo Board"; the Status field lacks In Review, so it adds it.
3. Scans the README roadmap, `TODO` comments, `CHANGELOG.md` and `git log`: 7 open TODOs (2 already have issues, skipped) and 12 CHANGELOG entries.
4. Previews 17 issues in two groups: 5 "current → Todo", 12 "retroactive → Done".
5. On your yes, creates the 5 and sets them to Todo; creates and closes the 12 and sets them to Done.

## Related

- [`next`](../next/) reads the board it creates.
- Needs `gh` with the `project` scope.

## Prereqs

`gh`, authenticated with the `project` OAuth scope: run `gh auth refresh -s project -s read:project` once (see [`kanban/README.md`](../README.md#prerequisite-the-project-oauth-scope)). It checks for the scope itself and stops if missing.
