# session-handoff

*`SKILL.md` is the prompt Claude follows; this file is for you. Loop overview: [`kanban/README.md`](../README.md).*

## What it does

Ends an implementation session tied to a GitHub issue: writes the handoff document (via `handoff-auto`), adds a `## Board status` section, and moves the issue's card to reflect reality.

## When to use

- Wrapping up a session that started from an issue / board card.
- The `implementer` agent calls it to finish.

## How to invoke

`/session-handoff <issue number or URL>` — model-invocable.

## How it works

1. Calls [`handoff-auto`](../../handoff-auto/) with the issue as argument; takes the path it prints.
2. Appends `## Board status` to that doc: issues/cards touched, complete / partial / blocked, deviations from the issue, new ideas found mid-session.
3. Moves the card (board lookup per [`next/BOARD.md`](../next/BOARD.md)): Projects v2 via `gh project item-edit` with IDs looked up from `gh project field-list` / `item-list` (GraphQL fallback when the list is stale); label fallback creates `status:in-review` first if missing, then swaps `status:in-progress` → `status:in-review` when complete, otherwise leaves it and comments if blocked.
4. Prints the handoff file path.

Follows any handoff filename/section rules in the repo's `CLAUDE.md`/`AGENTS.md`.

## Related

- Next step: [`update-progress`](../update-progress/) in a fresh session, with the printed path.
- Wraps [`handoff-auto`](../../handoff-auto/); preloaded by the `implementer` agent.

## Example

```
/session-handoff 31
```

Writes the handoff to `skilleddocs/handoffs/` with "Board status: #31 partial — export works, tests for large files missing; deviation: used streaming writer", moves #31's card to In Progress, prints the path.
