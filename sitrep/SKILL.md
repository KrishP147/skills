---
name: sitrep
description: Live status of this session in ≤10 lines — what's running, git state, PRs + CI, asked vs done, what needs the user, and a SAFE/NOT SAFE close verdict. Use for "how's it going", "status update", "what's running", "can I close this".
---

Read-only snapshot of right now; no file writes (progress-report covers history). The one exception is §4, through `handoff-auto`.

## 1. Gather

- **Running**: every background `Bash`/`PowerShell`, `Monitor`, and background `Agent` launched this session without a completion notification yet. Per task: age + last line of its output file. `ListAgents` → note peers that look stalled.
- **Git**, per `git worktree list` entry: `git status --porcelain`; no upstream → "never pushed"; else `git log @{u}.. --oneline`.
- **PRs**: `gh pr list --author @me --json number,title,url,isDraft,statusCheckRollup` → passing / failing / pending.
- **Asked vs done**: each distinct ask in this conversation → done / in progress / not started.
- **Needs you**: keys, approvals, manual steps, unanswered questions. "none" if none.

## 2. Verdict

**SAFE** only when nothing runs and nothing is dirty or unpushed (or it's covered by a committed, pushed handoff). Else **NOT SAFE** + each reason.

## 3. Output (≤10 lines, no preamble, drop empty lines)

```
Running: 2 background (12m, "tests passing") | 1 agent pending
Git: 3 worktrees, 1 dirty, 1 unpushed (feat/x, 2 commits)
PRs: #12 passing | #14 CI failing
Asked → done: 4/5 (in progress: <what>)
Needs you: <item>
Verdict: NOT SAFE — stop feat/x's shell and push first
```

## 4. On "close" / "stop them"

1. List exactly what will stop (task ids, agents) and anything that would be committed or pushed.
2. Act on an explicit yes only; anything vaguer → repeat the list.
3. `TaskStop` each (no tool → tell the user how).
4. Commit or push only if the yes named that too.
5. Mid-flight work → `handoff-auto`, print its path.
