# session-handoff

*`SKILL.md` is the prompt Claude follows; this file is for you. Loop overview: [`kanban/README.md`](../README.md).*

Needs: `handoff-auto`, `kanban-setup`, `next` (installed with it).

## What it does

Ends an implementation session tied to a GitHub issue: writes the handoff document (via `handoff-auto`), adds a `## Board status` section, and moves the issue's card to reflect reality.

## When to use

- Wrapping up a session that started from an issue / board card.
- The `implementer` agent calls it to finish.

## How to invoke

`/session-handoff <issue number or URL>`. Claude can also run it itself.

## How it works

1. Calls [`handoff-auto`](../../handoff-auto/) with the issue as argument; takes the path it prints.
2. Appends `## Board status` to that doc: issues/cards touched, complete / partial / blocked, deviations from the issue, new ideas found mid-session.
3. Moves the card (board lookup per [`next/BOARD.md`](../next/BOARD.md)).
   - Projects v2 via `gh project item-edit` with IDs looked up from `gh project field-list` / `item-list` (GraphQL fallback when the list is stale).
   - Label fallback creates `status:in-review` first if missing, then swaps `status:in-progress` → `status:in-review` when complete, otherwise leaves it and comments if blocked.
   - A Projects board with no In Review option: the card stays In Progress, the handoff says so, and it points at [`IN-REVIEW-OPTION.md`](../kanban-setup/IN-REVIEW-OPTION.md).
   - Run by a guarded agent (`implementer`/`manager`, read-only `gh`), it skips the move and comment and lists them in the handoff for the caller.
4. Prints the handoff file path.

- Follows any handoff filename/section rules in the repo's `CLAUDE.md`/`AGENTS.md`.
- Commits the handoff only per [`handoff-auto/TRACKING.md`](../../handoff-auto/TRACKING.md): never on a fork, and in commit mode only when the current branch is the default.
- On a task branch it stays uncommitted on disk (`update-progress` commits it on the default branch), so it can't leak into the task's PR.

## Design principles

- **Record reality, not hope.** Only a complete session (the issue's done-when is met; deviations are listed, the done-when is not rewritten) moves the card to In Review; partial or blocked work stays In Progress, and a blocked one gets an issue comment saying why.
- **Wrap, don't duplicate.** The document itself comes from `handoff-auto`; this skill only adds board status and the card move.
- **Path last.** The handoff path is the final line, so the `implementer` agent's caller can read it.

## Use cases

- Ending a manual session that started from `/next` and an issue.
- The `implementer` agent's last step, so a manager or orchestrator gets a handoff whose path it can read.
- Stopping partway through a task: the board shows it is still In Progress, and the handoff says what is left.

## Tips

- Pass the issue number (or URL) so the handoff and the card move target the right issue.
- Next, open a fresh session and run [`update-progress`](../update-progress/) with the printed path; that is what verifies and closes the issue.
- Deviations listed under `## Board status` are what `update-progress` later sends to `consult-plan`, so name them plainly in the session.
- A board error doesn't block: the handoff is still written and the error is noted.

## Example

```
/session-handoff 31
```

1. `handoff-auto` writes `skilleddocs/handoffs/2026-10-15-csv-export.md` and prints its path.
2. Appended to it:

```markdown
## Board status

- #31 Add CSV export: partial. Export works; tests for files over 1 GB missing.
- Deviation: used a streaming writer instead of building the file in memory.
- New idea: an `--gzip` option (not in the issue).
```

3. Partial, so the card stays In Progress (no comment, since it isn't blocked).
4. Prints the handoff's absolute path as the last line.

## Related

- Next step: [`update-progress`](../update-progress/) in a fresh session, with the printed path.
- Wraps [`handoff-auto`](../../handoff-auto/); preloaded by the `implementer` agent.

## Prereqs

- `gh`, authenticated with the `project` OAuth scope: run `gh auth refresh -s project -s read:project` once (see [`kanban/README.md`](../README.md#prerequisite-the-project-oauth-scope)).
- [`handoff-auto`](../../handoff-auto/) installed.
