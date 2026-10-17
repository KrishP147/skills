# divide

*`SKILL.md` is the prompt Claude follows; this file is for you. Loop overview: [`kanban/README.md`](../README.md).*

## What it does

Splits an issue (or a described task) that's too big for one session into two or more session-sized issues (about the ~75K-token smart zone, one PR).

- Links them from the parent.
- Puts them on the board.

## When to use

- A task is clearly multi-session.
- Context is running low mid-task and the rest must be split off (the `smartzone.py` hook suggests this).
- The `planner` agent uses it to *propose* splits (it never creates them).

## How to invoke

`/divide <issue number or task description>`. Claude can also run it itself.

## How it works

1. Reads the target (`gh issue view <n>` or your description).
2. Target already fits one session? Says so and stops.
   - Otherwise proposes 2+ pieces (or uses your split) and **shows it before creating anything**.
   - If you revise the split, it shows it again.
3. On confirmation: `gh issue create` per piece ("Part of #n").
   - Adds a task-list checkbox per child to the parent's body. If the parent already uses sub-issues, it attaches each child as one instead.
   - Work an existing child covers is never re-split.
   - A free-text target has no parent issue, so "Part of", the checkboxes and the roadmap link are skipped.
4. Adds each child to the board.
   - Projects v2 → `gh project item-add` then `gh project item-edit` to set Status=Todo (`item-add` alone leaves Status empty).
   - Label fallback → `status:todo` (created first if missing).
5. If a roadmap doc links the parent, adds `#n → #a, #b` inline and commits only the roadmap file as `docs: divide #n into #a/#b/#c…` on the current branch.
   - On the default branch it branches first, reports the branch and SHA, asks whether to push and open a PR (never without your yes), then switches back.
6. If the parent is now only a tracker, says so and offers to close it once children land.

## Design principles

- **Session-sized pieces.** Each child gets a "done when", so one session can finish it and `session-handoff` can call it complete.
- **Propose first, create on yes.** The split is shown before any issue exists; the `planner` agent only ever proposes.
- **Keep the trail.** Children say "Part of #n", the parent gets a checkbox per child, and a roadmap that links the parent links the children too.

## Use cases

- An issue that is clearly several sessions of work.
- Context running low mid-task: split off what's left as its own issue.
- The `planner` agent flagging an oversized issue during a `meta-orchestrator` run (proposal only; you create).

## Tips

- Bring your own split ("divide 28 into the token model and the migration") if you already know the seams.
- Push back on the proposal before saying yes; nothing exists until you do.
- Once the parent only tracks children, accept the offer to close it after they land rather than leaving it in Todo.
- In a repo whose roadmap doc links the parent, it commits the roadmap edit (`docs: divide #n into #a/#b/#c…`, on a branch, not pushed).

## Example

```
/divide 28
```

Claude reads #28 "Rework auth flow" and proposes:

```
1. Auth token model: done when tokens are issued and validated, with tests.
2. Migrate sessions: done when live sessions convert to tokens on next request.
3. Remove old middleware: done when the session middleware is deleted and CI is green.
Create these 3 issues?
```

You say yes.

- It creates #40, #41 and #42 (each "Part of #28. …").
- It adds three task-list checkboxes to #28's body.
- It puts each child on the board at Todo.
- It adds `#28 → #40, #41, #42` beside #28 in `ROADMAP.md` and commits `docs: divide #28 into #40/#41/#42`.
- #28 now only tracks its children, so it offers to close it once they land.

## Related

- Preloaded by the `planner` agent (proposal only).
- [`consult-plan`](../consult-plan/) adds its new issues to the board the same way.

## Prereqs

- `gh`, authenticated, `origin` on GitHub (otherwise it stops and says so).
- On a fork it asks which repo to write to (fork issues off: it reads the parent).
- Projects v2 boards need the `project` OAuth scope: run `gh auth refresh -s project -s read:project` once (see [`kanban/README.md`](../README.md#prerequisite-the-project-oauth-scope)).
