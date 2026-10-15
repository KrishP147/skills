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

## Related

- [`next`](../next/) reads the board it creates.
- Needs `gh` with the `project` scope.

## Example

```
/kanban-setup both
```

Creates "myrepo Board", finds 7 open TODOs and 12 CHANGELOG entries, previews 19 issues in two groups, and on your OK creates 7 in Todo and 12 closed in Done.
