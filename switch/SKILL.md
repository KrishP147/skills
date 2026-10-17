---
name: switch
description: Move this conversation to another Claude account (the previous one, or one by name), or add, remove, rename and list accounts.
argument-hint: "[account name] [yes] | add <name> | remove <name> [--delete-dir] | rename <old> <new> | list | theme <name> [theme] | rc-ok <name> on|off"
disable-model-invocation: true
allowed-tools:
  - Bash("${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" request:*)
  - Bash("${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" add:*)
  - Bash("${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" remove:*)
  - Bash("${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" rename:*)
  - Bash("${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" list:*)
  - Bash("${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" theme:*)
  - Bash("${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" rc-ok:*)
---

Pick the branch by the first word of `$ARGUMENTS` and run only its commands with the Bash tool, exactly as written, no text before the first one.

**`add <name> [--dir DIR]`**:

```
"${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" $ARGUMENTS --session "${CLAUDE_SESSION_ID}"
```

Show its output as is. `switching to '<name>'` means the launcher ends this session and reopens it on the new account, which asks for a login; add nothing.

**`rename <old> <new>`**, **`list`**, **`theme <name> [theme]`** or **`rc-ok <name> on|off`**:

```
"${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" $ARGUMENTS
```

Show its output as is.

**`remove <name> [--delete-dir]`**: two steps, never one.

1. Show the plan, then ask "Remove as above? (yes/no)" and stop until the user answers:

   ```
   "${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" $ARGUMENTS --dry-run
   ```

   A refusal (the account you're on, the last or first account, an overlapping dir) ends it here.
2. Only on the user's explicit yes in their next message:

   ```
   "${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" $ARGUMENTS --yes
   ```

   Anything but yes: say nothing was changed and stop.

**Anything else** (empty or an account name, either optionally followed by `yes`): run this and show its output as is.

```
"${CLAUDE_SWITCH_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/claude_switch.py" request $ARGUMENTS --session "${CLAUDE_SESSION_ID}"
```

- Ends with `switching to '<name>'` → the launcher ends this session and resumes it on that account. Add nothing.
- Ends with `rerun with yes` → nothing switched: something is live (three or more accounts only; with two accounts `/switch` never asks). Ask "Switch anyway? (yes/no)" and stop. Only on the user's explicit yes in their next message, run the same command with `yes` right after `$ARGUMENTS`; anything else: say nothing was switched.
- Anything else (unknown name with the account list, already on that account, not started by the launcher with setup steps, python not found) → nothing was switched; show the output as is. Python not found means the session wasn't started by the launcher: point at the setup step in this skill's README.
