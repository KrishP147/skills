# grill-docs

*Original. Wraps Matt Pocock's `grilling` (MIT). `SKILL.md` is the prompt Claude follows; this file is for you.*

Needs: `consult-plan`, `handoff-auto`, `next` (installed with it).

## What it does

Runs the `grilling` interview on a plan or decision and leaves a paper trail in the repo: the full question → recommendation → answer transcript, and one row per settled decision in an append-only register. Everything else about the interview is unchanged.

## When to use

- You want a grilling session that a teammate, a later session, or an orchestrator can read.
- A plan doc exists and its open questions need settling on the record.
- Before running `meta-orchestrator`, so its planner and verifier can cite decision ids.

## How to invoke

`/grill-docs <plan, decision, or doc path> [slug]`, or "grill me on X and document it". Model-invocable.

## How it works

1. Creates `skilleddocs/grills/<YYYY-MM-DD>-<slug>.md` (or `grills/` beside a tracked register when `skilleddocs/` is untracked) with a header (`Status: in progress`) before the first round.
2. Asks rounds exactly as `grilling` does (numbered questions, one recommendation each, then waits).
3. After each answered round, appends:
   - a `### Q<n>` block (topic / asked / recommended / answer / why) to the transcript
   - one `| D<k> | date | decision | why | source |` row to the decisions doc (created with a header if missing)
   - `Q<n>` counts across the whole session.
   - The heading is just `### Q<n>`, so the register's source link (`grills/<file>#q<n>`) works on GitHub, where anchors are lowercase.
   - Delegated answers ("go with your recs") are recorded as `(delegated)`.
4. When no open questions are left and you confirm: sets `Status: settled`, adds `## Summary` and `## Open`, prints both paths. Nothing is committed unless you ask.

Writes `skilleddocs/grills/<date>-<slug>.md` and the decisions doc:

- The decisions doc is the one `AGENTS.md` / `CLAUDE.md` names, else an existing `docs/decisions.md`, else an ADR folder (`docs/adr/`, `doc/adr/`, `docs/decisions/`), else `skilleddocs/decisions.md` (the same rule `consult-plan` uses).
- The transcript header's `Register:` field says which.
- In an ADR folder, a new ADR that reverses or narrows an old one also marks the old one `Superseded by NNNN` / `Amended by NNNN`.

## Design principles

- **Write as you go.** Each answer is recorded before the next question, so an abandoned session still leaves a usable record (`Status: abandoned after Q<n>`); rerunning with the same slug resumes it.
- **The register is the interface.** Planners, verifiers and `consult-plan` read the register (the decisions doc above), so every answer becomes a row, delegated ones included.
- **Append-only.** A decision is reversed with a new row; old rows stay as written.

## Use cases

- Settling a plan doc's open questions on the record before implementation starts.
- Giving a later session or a teammate the "why" behind each decision, not just the outcome.
- Seeding `D<k>` decision ids for a `meta-orchestrator` run to cite.

## Tips

- To set the transcript filename, put a kebab-case slug after a doc path or a quoted subject (`/grill-docs "our caching plan" cache-plan`). Otherwise Claude picks 2 to 4 topic words. A hyphenated last word in a plain sentence (`e-books`) stays part of the subject, not the slug.
- Register tracked (say `docs/decisions.md`) but `skilleddocs/` not: the transcript goes in `docs/grills/` instead, so the rows' Source links work once you commit both.
- "Go with your recs" is fine: delegated answers are recorded as `(delegated) <rec>`, so the register stays complete.
- Files are left uncommitted unless you ask; commit them yourself if the repo tracks `skilleddocs/`.
- If your repo's `AGENTS.md` or `CLAUDE.md` names a decisions doc, that file is used; otherwise an existing `docs/decisions.md` or ADR folder; the transcript header's `Register:` field says which.

## Example

```
/grill-docs docs/backend-extension-plan.md backend-plan
```

Produces `skilleddocs/grills/2026-09-23-backend-plan.md` with 14 Q→A blocks and appends D1–D14 to `skilleddocs/decisions.md`.

## Related

- [`grilling`](../grilling/) — the interview itself, no files.
- [`consult-plan`](../kanban/consult-plan/) — grills a *deviation* against the existing plan and appends to the same register.
- [`meta-orchestrator`](../meta-orchestrator/) — reads the register and transcripts as the design record.

## Prereqs

None beyond [`grilling`](../grilling/) installed alongside it.
