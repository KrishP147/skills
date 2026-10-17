# grilling

*By Matt Pocock (MIT), included verbatim. `SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Interviews you, one round at a time, until a plan or decision has no unexamined branches left. Every question comes with Claude's recommended answer, so you can just say "yes" to most.

## When to use

- You have a plan, design or decision and want it stress-tested before acting.
- You say "grill me", "grill this plan", "poke holes in this".
- Other skills call it: `consult-plan` uses it to test an idea against a repo's plan.

## How to invoke

- `/grilling <the plan or idea>`, or just ask to be grilled; Claude auto-invokes it (model-invocable).
- `/grill-me` is a user-only alias.

## How it works

1. Maps the topic as a **design tree**: each decision branches into the decisions that depend on it.
2. Asks the whole **frontier** (every question answerable now, with prerequisites settled) in one numbered round: `❓ Q1 …` then `➡️ recommended answer`.
3. Waits for your answers, recomputes the frontier, asks the next round. Questions that depend on an open question wait for a later round.
4. Looks up facts itself (dispatching a sub-agent for filesystem/tool lookups) instead of asking you; only decisions go to you.
5. Ends when the frontier is empty, and does nothing with the result until you confirm shared understanding.

Reads/writes no files by itself.

## Design principles

- **Design tree, asked by frontier.** A question is only asked once everything it depends on is settled, so you never answer a hypothetical that a later answer would undo.
- **Facts are Claude's job, decisions are yours.** Anything the environment can answer gets looked up; only real choices reach you.
- **Recommend, don't just ask.** Each question carries a recommended answer worded so "yes" accepts it, which keeps rounds fast.

## Use cases

- Stress-testing a design before writing code (a migration, a new service boundary, an API change).
- Turning a vague idea into a list of settled decisions.
- Testing a proposed change against a repo's existing plan, via `consult-plan`.

## Tips

- Answer by number ("1 yes, 2 no: keep sessions, 3 yes"); anything you skip stays on the frontier.
- A fact lookup only holds back the questions that depend on it; the rest of the round is asked anyway.
- Nothing is written down. Use [`grill-docs`](../grill-docs/) when the answers need a record.
- It acts on nothing until you confirm a shared understanding, so say so explicitly when you're done.

## Example

```
/grilling move auth from sessions to JWTs
```

- Round 1 asks ~4 numbered questions (token lifetime, refresh strategy, revocation, migration of live sessions), each with a recommendation.
- You answer; round 2 follows up on revocation storage because you chose short-lived tokens.
- Stops when nothing is left open.

## Related

- [`grill-me`](../grill-me/) — alias.
- [`consult-plan`](../kanban/consult-plan/) — calls this with the repo's plan as context.
- `verifier` agent — may answer its questions on your behalf when authorized (see [`agents/README.md`](../agents/README.md)).

## Prereqs

None.
