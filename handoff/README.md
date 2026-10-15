# handoff

*By Matt Pocock (MIT); one sentence modified so the file saves under `skilleddocs/handoffs/`, one added for whether to commit it. `SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Compacts the current conversation into a handoff document so a fresh session can continue the work without the old context.

## When to use

- Context is getting long and quality is dropping.
- You're stopping for the day and want to resume cleanly.
- You want to hand the task to another agent/session.

## How to invoke

`/handoff [what the next session will be used for]`. User-invoked only (`disable-model-invocation: true`). For a model-callable version use [`handoff-auto`](../handoff-auto/).

## How it works

1. Summarises the conversation into a document saved in the repo under **`skilleddocs/handoffs/<date>-<slug>.md`** (OS temp dir only when there is no repo). Committed only if the repo already tracks `skilleddocs/` or opts in, never on a fork; otherwise left untracked and git-excluded ([`TRACKING.md`](../handoff-auto/TRACKING.md)).
2. Adds a "suggested skills" section naming skills the next session should load.
3. References existing artifacts (specs, plans, ADRs, issues, commits, diffs) by path/URL instead of copying them.
4. Redacts secrets and personal data.
5. If you passed an argument, tailors the doc to that next-session focus.

Output: one handoff file under `skilleddocs/handoffs/`.

## Related

- [`handoff-auto`](../handoff-auto/) — same, model-invocable, prints the path last.
- [`session-handoff`](../kanban/session-handoff/) — kanban-aware wrapper (uses `handoff-auto`).

## Example

```
/handoff finish the CSV export and write its tests
```

Writes a Markdown file under `skilleddocs/handoffs/` with state, open questions, file references, and "suggested skills". Start a fresh session and point it at that file.
