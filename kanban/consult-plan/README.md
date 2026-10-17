# consult-plan

*`SKILL.md` is the prompt Claude follows; this file is for you. Loop overview: [`kanban/README.md`](../README.md).*

Needs: `next` (installed with it).

## What it does

Grills a proposed change, deviation or new idea against the repo's existing plan (open issues, board, roadmap doc), then records the outcome where the repo already keeps decisions.

## When to use

- Pitching a new idea: "does this fit the plan?"
- Automatically, from [`update-progress`](../update-progress/), when a handoff lists deviations or innovations.

## How to invoke

`/consult-plan <the idea, deviation, or innovation>`. Claude can also run it itself.

## How it works

1. **Baseline** (whatever exists):
   - Open issues (`gh issue list --state open`).
   - Board state (`gh project item-list` or `status:*` labels).
   - A roadmap doc (`ROADMAP.md`, `docs/roadmap.md`, …).
   - The decisions doc (found by the same rule as step 3).
   - The grill transcripts (`skilleddocs/grills/`, or `grills/` beside a tracked register).
   - Earlier decisions are cited as `D<k>`.
2. **Grill:** calls [`grilling`](../../grilling/) with that baseline. The questions are framed as fit, conflict or extension, plus what you want to happen.
3. **Record** once settled, both:
   - **Decision:** append to the repo's decisions doc.
     - The one `AGENTS.md` / `CLAUDE.md` names, else an existing `docs/decisions.md` or ADR folder, else `skilleddocs/decisions.md` (header and rows as in [`grill-docs`](../../grill-docs/)).
     - Source column: `consult-plan <date>` plus the issue or PR link if any.
   - **Issue** (accepted or changed ideas):
     - A comment on the relevant issue when it refines existing work.
     - A new issue when it needs its own work, put on the board at Todo (Projects v2: `item-add` + `item-edit`; label mode: `status:todo`, created first if missing).
     - A **rejected** idea gets the decision row only, plus a comment if a related issue exists; no new issue.

## Design principles

- **Ideas meet the plan before they enter it.** A deviation or new idea is tested against open issues, the board, the roadmap and earlier decisions, not added on enthusiasm.
- **Reuse the interview.** The questioning is `grilling`, with the plan as context; this skill adds the baseline and the record.
- **Record where the repo already does.** A decisions doc named in `AGENTS.md` / `CLAUDE.md` wins, then an existing `docs/decisions.md` or ADR folder, then `skilleddocs/decisions.md`; an accepted outcome lands on an issue as well.

## Use cases

- Pitching an idea mid-project: "does this fit the plan?"
- A handoff's `## Board status` lists a deviation, and `update-progress` calls this to settle it.
- An orchestrated run where the `verifier` agent answers on your behalf (when authorized) and lists every Q and A.
- Deciding whether a new idea is its own issue or a comment on an existing one.

## Tips

- State the idea in one line as the argument; the baseline supplies the context.
- Earlier decisions are cited as `D<k>`, so a conflict with a past decision is visible in the questions.
- A settled idea that needs work becomes a new issue at Todo; one that only refines existing work becomes a comment; a rejected one is a decision row only.
- Want the full Q and A transcript kept too? Run [`grill-docs`](../../grill-docs/) on it instead; it also writes a transcript under `skilleddocs/grills/`.

## Example

```
/consult-plan add a plugin system instead of hard-coding exporters
```

- Reads 12 open issues and `ROADMAP.md`.
- Asks a round of questions (does it replace #31? scope for v1?).
- You settle it.
- It appends an entry to `docs/decisions.md` (or `skilleddocs/decisions.md` if the repo has none) and comments on #31.

## Related

- Calls [`grilling`](../../grilling/); called by [`update-progress`](../update-progress/).
- Preloaded by the `verifier` agent, which may answer the questions on your behalf when authorized.

## Prereqs

- `gh`, authenticated, and `origin` on GitHub.
- On a fork it asks which repo to write to. If the fork has issues turned off (GitHub's default), it reads issues from the parent.
- Projects v2 boards also need the `project` OAuth scope: run `gh auth refresh -s project -s read:project` once (see [`kanban/README.md`](../README.md#prerequisite-the-project-oauth-scope)); label mode doesn't.
- [`grilling`](../../grilling/) installed.
