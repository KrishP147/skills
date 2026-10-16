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
2. Records branch, base SHA (`git merge-base <default> HEAD`), head SHA and, if the tree is dirty, `git status --short`, and adds a "suggested skills" section.
3. References existing artifacts by path/URL instead of duplicating them.
4. Redacts secrets and personal data.
5. Tailors to the argument if one was given.
6. Prints the file's absolute path (native OS form) on its own line, last.

## Design principles

- **Machine-readable ending.** The absolute path is always the very last line, so a calling skill or orchestrator can parse it without guessing.
- **Same document as `handoff`.** Only the frontmatter, save location, tracking sentence, a git-state line (branch, base SHA, head SHA) and the final path line differ from the original, so a manual and an unattended handoff read the same.
- **Shared tracking rule.** Commit or not comes from [`TRACKING.md`](TRACKING.md), the single source for every file under `skilleddocs/`.

## Use cases

- `session-handoff` ending an implementation session from an issue.
- An `implementer` or `manager` agent wrapping up, or running low on turns or context.
- Any skill that must close a session with nobody at the keyboard.

## Tips

- Call `/handoff` yourself for manual handoffs; this variant exists so skills and agents can call it.
- Pass the next session's focus (an issue number or a sentence) as the argument to tailor the doc.
- If you parse its output, read only the last line: that is the file path.
- On a fork the file is never committed: it stays untracked and `skilleddocs/` is added to the git exclude file.

## Example

An implementer finishing issue #42 runs `session-handoff`, which calls the Skill tool with `handoff-auto` and the argument `#42`. In a repo that already tracks `skilleddocs/` (not a fork), it:

1. Writes `skilleddocs/handoffs/2026-10-15-csv-export.md`: what was done (commits referenced by SHA, not copied), what is left, the exact next step, and a "suggested skills" section (`update-progress`). An API token seen in a log is redacted.
2. Commits it, per [`TRACKING.md`](TRACKING.md).
3. Ends its output with the absolute path on its own line:

```
/home/you/code/myrepo/skilleddocs/handoffs/2026-10-15-csv-export.md
```

`session-handoff` then appends its `## Board status` section to that same file.

## Related

- [`handoff`](../handoff/) — user-only original.
- [`session-handoff`](../kanban/session-handoff/) — calls this, then adds board status.
- Agents `implementer` and `manager` preload it (see [`agents/README.md`](../agents/README.md)).

## Prereqs

None. Uses `gh` for the fork check in [`TRACKING.md`](TRACKING.md) when available; without it, an `upstream` remote counts as a fork.
