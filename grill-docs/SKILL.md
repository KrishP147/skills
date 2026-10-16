---
name: grill-docs
description: Grill the user about a plan (same interview as grilling) and record it — Q→A transcript in skilleddocs/grills/, each decision appended to skilleddocs/decisions.md. Use for "grill me and document it", "grill with docs".
argument-hint: "plan, decision, or doc path [slug]"
---

Call the Skill tool with `"grilling"` and run that interview unchanged. Your addition: write it down **as each round settles**, so an abandoned session still leaves a record.

Paths:
- transcript: `skilleddocs/grills/<local-date>-<slug>.md` (slug: the argument's last word when it is kebab-case with a hyphen, like `auth-plan`, and words remain before it; else 2–4 topic words from the subject)
- register (the decisions doc): the one the repo's `AGENTS.md`/`CLAUDE.md` names; else an existing `docs/decisions.md` or ADR folder; else `skilleddocs/decisions.md`. Same rule as `consult-plan`. An ADR folder gets one new ADR per decision in its own format, carrying the same Source. Always name the chosen path in the header's `Register:` field.

Untracked → exclude `skilleddocs/` per [TRACKING.md](../handoff-auto/TRACKING.md) (it also covers the `pip install .` hazard).

## Before round 1

```markdown
# Grill: <topic>

Date: <local date> · Subject: <doc path or one line> · Register: <decisions doc path> · Status: in progress

## Rounds
```

## After each round, before the next

Transcript, per question. `Q<n>` counts across the whole session: continue the numbering across rounds, unique within the file. The heading is exactly `### Q<n>` so its anchor is the lowercase `#q<n>` (a title in the heading would change the anchor); the title goes on the first line:

```markdown
### Q<n>
- Topic: <title>
- Asked: <question + options, one line>
- Recommended: <your rec>
- Answer: <user's choice, verbatim if short; delegated → "(delegated) <rec>">
- Why: <user's reason, else the recommendation's rationale marked "(rec)">
```

Register, one row per settled question, continuing the `D<k>` numbering. Source is the transcript path, relative to the register, plus the lowercase anchor (`grills/2026-10-16-sync-plan.md#q3` from `skilleddocs/decisions.md`). Called from a `wayfinder` ticket, name the ticket in Source too (`ticket <link>; grills/<file>#q<n>`):

```markdown
| D<k> | <local date> | <decision> | <why> | grills/<file>#q<n> |
```

New register header:

```markdown
# Decisions

Append-only register of decisions from grilling sessions, consult-plan reviews, and orchestrator runs. Reverse a decision with a new row; old rows stay as written.

| # | Date | Decision | Why | Source |
|---|------|----------|-----|--------|
```

Every answer is a decision, delegated ones too: planners, verifiers and consult-plan read only the register.

## Close

Frontier empty and the user confirms → `Status: settled`, add `## Summary` (3–8 bullets) and `## Open` (or "none"). Ended early → `Status: abandoned at Q<n>`. Print both paths; say they're uncommitted unless the user asks to commit.
