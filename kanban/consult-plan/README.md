# consult-plan

*`SKILL.md` is the prompt Claude follows; this file is for you. Loop overview: [`kanban/README.md`](../README.md).*

## What it does

Grills a proposed change, deviation or new idea against the repo's existing plan (open issues, board, roadmap doc), then records the outcome where the repo already keeps decisions.

## When to use

- Pitching a new idea: "does this fit the plan?"
- Automatically, from [`update-progress`](../update-progress/), when a handoff lists deviations or innovations.

## How to invoke

`/consult-plan <the idea, deviation, or innovation>` — model-invocable.

## How it works

1. **Baseline** (whatever exists): open issues (`gh issue list --state open`), board state (`gh project item-list` or `status:*` labels), a roadmap doc (`ROADMAP.md`, `docs/roadmap.md`, …), plus `skilleddocs/decisions.md` and `skilleddocs/grills/`. Earlier decisions are cited as `D<k>`.
2. **Grill:** calls [`grilling`](../../grilling/) with that baseline, framed as fit / conflict / extension and what you want to happen.
3. **Record** once settled, both:
   - **Decision:** append to the repo's decisions doc. An existing `docs/decisions.md` or ADR folder wins; otherwise `skilleddocs/decisions.md` (header from [`grill-docs`](../../grill-docs/)).
   - **Issue:** comment on the relevant issue, or open a new one and put it on the board at Todo (Projects v2: `item-add` + `item-edit`; label mode: `status:todo`, created first if missing).

## Design principles

- **Ideas meet the plan before they enter it.** A deviation or new idea is tested against open issues, the board, the roadmap and earlier decisions, not added on enthusiasm.
- **Reuse the interview.** The questioning is `grilling`, with the plan as context; this skill adds the baseline and the record.
- **Record where the repo already does.** An existing `docs/decisions.md` or ADR folder wins over `skilleddocs/decisions.md`, and the outcome lands on an issue as well.

## Use cases

- Pitching an idea mid-project: "does this fit the plan?"
- A handoff's `## Board status` lists a deviation, and `update-progress` calls this to settle it.
- An orchestrated run where the `verifier` agent answers on your behalf (when authorized) and lists every Q and A.
- Deciding whether a new idea is its own issue or a comment on an existing one.

## Tips

- State the idea in one line as the argument; the baseline supplies the context.
- Earlier decisions are cited as `D<k>`, so a conflict with a past decision is visible in the questions.
- A settled idea that needs work becomes a new issue at Todo; one that only refines existing work becomes a comment.
- Want the full Q and A transcript kept too? Run [`grill-docs`](../../grill-docs/) on it instead; it also writes a transcript under `skilleddocs/grills/`.

## Example

```
/consult-plan add a plugin system instead of hard-coding exporters
```

Reads 12 open issues and `ROADMAP.md`, asks a round of questions (does it replace #31? scope for v1?), you settle it, and it appends an entry to `docs/decisions.md` (or `skilleddocs/decisions.md` if the repo has none) and comments on #31.

## Related

- Calls [`grilling`](../../grilling/); called by [`update-progress`](../update-progress/).
- Preloaded by the `verifier` agent, which may answer the questions on your behalf when authorized.

## Prereqs

`gh`, authenticated with the `project` OAuth scope: run `gh auth refresh -s project -s read:project` once (see [`kanban/README.md`](../README.md#prerequisite-the-project-oauth-scope)). [`grilling`](../../grilling/) installed.
