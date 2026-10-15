---
name: session-handoff
description: End an implementation session that started from a GitHub issue — writes the handoff, records progress against the issue, moves the card.
argument-hint: "issue number or URL"
---

1. Call the Skill tool with `"handoff-auto"`, passing the argument. Keep the path it prints.
2. Append `## Board status` to that document: issues touched; complete / partial / blocked; deviations from the issue; new ideas not in the issue.
3. Move the card ([BOARD.md](../next/BOARD.md)): complete → In Review; partial or blocked → stays In Progress, plus an issue comment saying why if blocked.
4. Print the handoff path as the last line.

A repo's `CLAUDE.md`/`AGENTS.md` may prescribe filename or required sections; follow it. Commit the handoff or not per [TRACKING.md](../../handoff-auto/TRACKING.md).
