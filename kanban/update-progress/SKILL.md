---
name: update-progress
description: Verify a session's handoff document and update the repo's docs and kanban board from it. Run in a fresh session after session-handoff.
argument-hint: "handoff doc path (default: newest by mtime in skilleddocs/handoffs/)"
---

Treat every claim in the handoff as unverified until you've checked it.

1. **Locate** the handoff: given path, else the newest by mtime among `skilleddocs/handoffs/*.md` in every `git worktree list` entry (current worktree first; an uncommitted handoff lives in the task's worktree). Tied mtimes → list them and ask. None → newest handoff-looking file in the OS temp dir.
2. **Verify**: `git log` over the handoff's base SHA..head, else `git merge-base <default> <branch>`..branch (`<default>` per the `handoff-auto` skill's `TRACKING.md`); run the repo's test command. Record the real result.
3. **Review**: product code changed → call the Skill tool with `"code-review"` on the session's commits.
4. **Docs**, only what the repo already has: tick roadmap checkboxes, add status/CHANGELOG entries, add a decisions row if the handoff records a decision.
   - The "current phase" marker follows where merges land. Merges in a later phase → move the marker; mark the earlier phase "done except gated (#…)".
   - Every capability merged this phase appears in the README / status summary. A missing one is drift; fix it here.
5. **Board** ([BOARD.md](../next/BOARD.md)): comment a summary on each issue. Complete and verified → Done, close the issue. Otherwise set the status to where it really stands.
6. **Deviations** in `## Board status` → call the Skill tool with `"consult-plan"`.
7. **Commit the handoff** if it is uncommitted and the `handoff-auto` skill's `TRACKING.md` says commit mode: commit it on `<default>` (where this runs), after verifying. Untracked mode → leave it.
8. Finish with the `next` skill.
