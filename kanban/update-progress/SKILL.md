---
name: update-progress
description: Verify a session's handoff document and update the repo's docs and kanban board from it. Run in a fresh session after session-handoff.
argument-hint: "handoff doc path (default: newest by mtime in the handoff folder)"
---

Treat every claim in the handoff as unverified until you've checked it.

1. **Locate** the handoff: given path, else the newest by mtime among `*.md` in the handoff folder (AGENTS.md/CLAUDE.md's, else `skilleddocs/handoffs/`) in every `git worktree list` entry (current worktree first; an uncommitted handoff lives in the task's worktree). Skip one whose issues all carry a "verified, merged" comment (already processed); one closed by a PR's `Closes #n` without it still runs, for the docs. Tied mtimes → list them and ask. None → newest handoff-looking file in the OS temp dir.
2. **Verify**: `git log` over the handoff's base SHA..head, else `git merge-base <default> <branch>`..branch (`<default>` per the `handoff-auto` skill's `TRACKING.md`). **Merged** = `git merge-base --is-ancestor <head> <default>` succeeds. Run the repo's test command on the code the handoff describes: merged → the `<default>` checkout; else the worktree with `<branch>` checked out at head, else a temp `git worktree add --detach <tmp> <head>` (install deps there first; remove it after). Record the real result and where it ran.
3. **Review**: product code changed → call the Skill tool with `"code-review"` on the session's commits.
4. **Docs**, only when merged and only what the repo already has: tick roadmap checkboxes, add status/CHANGELOG entries, add a decisions row if the handoff records a decision.
   - The "current phase" marker follows where merges land. Merges in a later phase → move the marker; mark the earlier phase "done except gated (#…)".
   - Every capability merged this phase appears in the README / status summary. A missing one is drift; fix it here.
5. **Board** ([BOARD.md](../next/BOARD.md); its Target repo section first: `-R` on every `gh` call, on a fork ask before writing): comment a summary on each issue. Complete, verified and merged → Done, close the issue, comment "verified, merged". Complete and verified, not merged → In Review, comment "verified, awaiting merge" (the PR's `Closes #n` or a later run closes it). Otherwise set the status to where it really stands.
6. **Deviations** in `## Board status` → call the Skill tool with `"consult-plan"`.
7. **Commit the handoff** if it is uncommitted and the `handoff-auto` skill's `TRACKING.md` says commit mode: after verifying, move it into the `<default>` checkout's handoff folder if it sits in another worktree, commit it on `<default>` there, then delete the worktree copy (left behind, it blocks that branch's next merge). Untracked mode → leave it.
8. Finish with the `next` skill.
