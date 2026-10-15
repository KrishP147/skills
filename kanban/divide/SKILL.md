---
name: divide
description: Split a GitHub issue or task into session-sized issues and put them on the board. Use when a task is too big for one session or remaining work must be split off.
argument-hint: "issue number or task description"
---

1. Read the target (`gh issue view <n>`, or the user's description).
2. Propose 2+ session-sized pieces, each with a "done when". Show the split; create nothing yet.
3. On yes: `gh issue create --title "<piece>" --body "Part of #<n>. <details>"` per piece, then add a task-list checkbox per child to the parent's body.
4. Put each child on the board at Todo ([BOARD.md](../next/BOARD.md)).
5. Roadmap doc links the parent → add `#n → #a, #b` beside it and commit `docs: divide #n into #a/#b`.
6. Parent now only tracks children → say so; offer to close it once they land.
