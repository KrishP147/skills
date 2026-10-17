---
name: switch
description: Move this conversation to another Claude account (the previous one, or one by name).
argument-hint: "[account name]"
disable-model-invocation: true
allowed-tools: Bash("${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" request:*)
---

Run exactly this one command with the Bash tool, nothing else, no text before it:

```
"${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" request $ARGUMENTS --session "${CLAUDE_SESSION_ID}"
```

Then repeat its output in one line and stop:

- `switching to '<name>'` → the launcher ends this session and resumes it on that account. Add nothing.
- Anything else (unknown name with the account list, already on that account, not started by the launcher with setup steps, python not found) → nothing was switched; show the output as is. Python not found means the session wasn't started by the launcher: point at the setup step in this skill's README.
