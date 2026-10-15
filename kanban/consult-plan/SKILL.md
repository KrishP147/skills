---
name: consult-plan
description: Grill a proposed change, deviation, or new idea against a repo's existing plan (issues, board, roadmap, decisions), then record the outcome. Use to pitch an idea; update-progress calls it for handoff deviations.
argument-hint: "the idea, deviation, or innovation"
---

1. **Baseline**, whatever exists: open issues, board state, roadmap doc, `skilleddocs/decisions.md` and `skilleddocs/grills/` (cite decisions as `D<k>`).
2. **Grill**: call the Skill tool with `"grilling"`, baseline as context. The question tree: does the idea fit, conflict with, or extend the plan, and what does the user want to happen?
3. **Record** once settled:
   - Append to the repo's decisions doc (an existing `docs/decisions.md` or ADR folder wins; else `skilleddocs/decisions.md`, header from `grill-docs`).
   - Comment on the relevant issue, or open one and put it on the board at Todo ([BOARD.md](../next/BOARD.md)).
