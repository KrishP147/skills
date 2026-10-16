---
name: grill-docs
description: Grill the user about a plan (same interview as grilling) and record it — Q→A transcript in skilleddocs/grills/, each decision appended to skilleddocs/decisions.md. Use for "grill me and document it", "grill with docs".
argument-hint: "plan, decision, or doc path [slug]"
---

Call the Skill tool with `"grilling"` and run that interview unchanged. Your addition: write it down **as each round settles**, so an abandoned session still leaves a record.

Paths (repo's `AGENTS.md`/`CLAUDE.md` may name another decisions doc; use it and say so in the header):
- transcript: `skilleddocs/grills/<local-date>-<slug>.md` (slug: the argument, else 2–4 topic words)
- register: `skilleddocs/decisions.md`

Untracked → exclude `skilleddocs/` per [TRACKING.md](../handoff-auto/TRACKING.md) (it also covers the `pip install .` hazard).

## Before round 1

```markdown
# Grill: <topic>

Date: <local date> · Subject: <doc path or one line> · Status: in progress

## Rounds
```

## After each round, before the next

Transcript, per question:

```markdown
### Q<n> — <title>
- Asked: <question + options, one line>
- Recommended: <your rec>
- Answer: <user's choice, verbatim if short; delegated → "(delegated) <rec>">
- Why: <user's reason, or "not stated">
```

Register, one row per settled question, continuing the `D<k>` numbering:

```markdown
| D<k> | <local date> | <decision> | <why> | grills/<file>#Q<n> |
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
