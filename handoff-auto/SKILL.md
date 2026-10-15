---
name: handoff-auto
description: Write a handoff document for a fresh session, callable by the model. Use from skills or subagents that must end a session unattended.
argument-hint: "What will the next session be used for?"
---

Derived from Matt Pocock's `handoff` skill (MIT, see THIRD_PARTY_LICENSES.md); the frontmatter and the save location differ.

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save it in the repo under `skilleddocs/handoffs/<YYYY-MM-DD>-<slug>.md` (create the directory; local date, not UTC; slug = the argument or 2-4 words for the topic). If there is no repo or git working tree, fall back to the OS temporary directory. A repo's `AGENTS.md` / `CLAUDE.md` may prescribe a different folder or filename prefix; follow it.

Include a "suggested skills" section in the document, naming which skills the next agent should call the Skill tool for.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.

Finish by printing the handoff file's absolute path on its own line as the very last line of output — orchestrators parse it.
