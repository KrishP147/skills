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

## Related

- Calls [`grilling`](../../grilling/); called by [`update-progress`](../update-progress/).
- Preloaded by the `verifier` agent, which may answer the questions on your behalf when authorized.

## Example

```
/consult-plan add a plugin system instead of hard-coding exporters
```

Reads 12 open issues and `ROADMAP.md`, asks a round of questions (does it replace #31? scope for v1?), you settle it, and it appends an entry to `docs/decisions.md` (or `skilleddocs/decisions.md` if the repo has none) and comments on #31.
