---
name: consult-plan
description: Grill a proposed change, deviation, or new idea against a repo's existing plan (issues, board, roadmap, decisions), then record the outcome. Use to pitch an idea; update-progress calls it for handoff deviations.
argument-hint: "the idea, deviation, or innovation"
---

0. **Target repo** per [BOARD.md](../next/BOARD.md#target-repo): resolve `origin` (this skill needs it on GitHub), `-R <owner>/<repo>` on every `gh` call, and on a fork ask which repo to write to before any write.
1. **Baseline**, whatever exists: open issues, board state, roadmap doc, `skilleddocs/decisions.md` and `skilleddocs/grills/` (cite decisions as `D<k>`).
2. **Grill**: call the Skill tool with `"grilling"`, baseline as context. The question tree: does the idea fit, conflict with, or extend the plan, and what does the user want to happen?
3. **Record** once settled:
   - Append one row per decision to the repo's decisions doc: the one `AGENTS.md`/`CLAUDE.md` names; else an existing `docs/decisions.md` or ADR folder; else `skilleddocs/decisions.md` (same rule as `grill-docs`, which also gives the header and row format; an ADR folder gets one new ADR per decision). Source: `consult-plan <local date>`, plus the issue or PR link when there is one. Untracked → exclude `skilleddocs/` per the `handoff-auto` skill's `TRACKING.md` (it also covers the `pip install .` hazard).
   - Idea **accepted** or changed: comment on the relevant issue (the `D<k>` ids and a one-line outcome), or open one and put it on the board at Todo ([BOARD.md](../next/BOARD.md)).
   - Idea **rejected**: the decision row is the record. Comment only if a related issue exists; never open an issue for a rejected idea.
