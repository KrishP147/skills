# handoff-auto

*Derived from Matt Pocock's `handoff` (MIT). `SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Same handoff document as [`handoff`](../handoff/), but Claude (or a skill/subagent) can call it without you typing a command. Prints the document's absolute path as the very last line so orchestrators can parse it.

## When to use

- A skill or subagent must end a session unattended (e.g. `session-handoff`, the `implementer` and `manager` agents).
- You rarely call it directly; use `/handoff` for manual handoffs.

## How to invoke

Model-invocable: another skill calls the Skill tool with `handoff-auto` (optional argument = next-session focus). You can also type `/handoff-auto [focus]`.

## How it works

1. Summarises the conversation into a document under the repo's **`skilleddocs/handoffs/`** (OS temp dir only when there is no repo). Committed or left untracked per [`TRACKING.md`](TRACKING.md): commit only if the repo already tracks `skilleddocs/` or opts in, never on a fork.
2. Adds a "suggested skills" section.
3. References existing artifacts by path/URL instead of duplicating them.
4. Redacts secrets and personal data.
5. Tailors to the argument if one was given.
6. Prints the file's absolute path on its own line, last.

## Related

- [`handoff`](../handoff/) — user-only original.
- [`session-handoff`](../kanban/session-handoff/) — calls this, then adds board status.
- Agents `implementer` and `manager` preload it (see [`agents/README.md`](../agents/README.md)).

## Example

`session-handoff` calls `handoff-auto` with `#42`; it writes a handoff file under `skilleddocs/handoffs/` and ends its output with that absolute path, which `session-handoff` then extends.
