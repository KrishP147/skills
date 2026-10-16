---
name: pair
description: Run one task (issue number or free text) in an isolated git worktree via a manager subagent that owns its implementer and retries; you push and open the PR at the end. Use for "implement issue N", "pair on this", or one task on any repo, forks included.
argument-hint: "<issue # | task text> [--no-worktree] [--push] [--model opus|sonnet]"
---

You run **one task** through a `manager` subagent. Neither you nor the agents implement in your context; you are the only one who touches the remote.

Flags: `--no-worktree` (new branch in the current checkout), `--push` (push + PR without asking), `--model` (implementer model; default: the manager's call).

## 1. Resolve

- **Target repo** per the `next` skill's `BOARD.md`, Target repo section (path in §2): `-R <o/r>` on every `gh` call. Number → `gh issue view <n> -R <o/r>` (on a fork, the parent's issue is fine to read). Text → write a 3–6 item acceptance checklist.
- Repo facts: default branch, branch prefix (user's `CLAUDE.md`, else `feat`), test command, `CONTRIBUTING.md` / `AGENTS.md`.
- **Fork** (`upstream` remote): reading is fine, so `git fetch upstream`, fast-forward default to `upstream/<default>`, then confirm every file or symbol the issue names still exists. Put anything missing in the brief.

## 2. Isolate

`origin` a relative path (`git remote get-url origin` has no `scheme://`, `host:`, leading `/` or drive letter, e.g. `../origin.git`): git resolves it from each worktree's own root, so fetch and push fail inside a worktree. Make it absolute first, from the main checkout: `git -C "<main>" remote set-url origin "$(cd "<main>" && cd "<url>" && pwd)"`. Same target, and remotes are shared by every worktree, so this one change covers them all; tell the user the old and new URL.

```
slug = issue-<n>-<kebab-title>   (or ≤6 kebab words of the task)
git worktree add ../_worktrees/<repo>-<slug> -b <prefix>/<slug> <default>
```

`--no-worktree`: `git switch -c <prefix>/<slug> <default>`. Existing worktree or branch → reuse it and say so.

Deps (`node_modules`, `.venv`): link each from the main checkout, paths quoted (shown for `.venv`). Windows: link only when both paths are absolute; an empty one puts the junction at the drive root (`C:\.venv`).
- Windows, Git Bash (`cygpath` builds the paths; without `MSYS_NO_PATHCONV` MSYS rewrites `/J` into a path):
  ```
  w=$(cygpath -wa "<wt>"); m=$(cygpath -wa "<main>")
  if [[ $w == [A-Za-z]:\\?* && $m == [A-Za-z]:\\?* ]]; then MSYS_NO_PATHCONV=1 cmd /c mklink /J "$w\.venv" "$m\.venv"; else echo "STOP: path not absolute: '$w' '$m'"; fi
  ```
- Windows, PowerShell: `if ("<wt>" -match '^[A-Za-z]:\\.' -and "<main>" -match '^[A-Za-z]:\\.') { cmd /c mklink /J "<wt>\.venv" "<main>\.venv" } else { "STOP: path not absolute" }`.
- mac/linux: `ln -s "<main>/.venv" "<wt>/.venv"`.

Issue number on a board, worktree/branch not reused → (fork: only after the target-repo answer) move it to In Progress and comment "Started on branch `<branch>`" (the `next` skill's `BOARD.md`: `~/.claude/skills/next/` or, as the plugin, `kanban/next/`). Board errors never block the task.

## 3. Delegate

One blocking call, `subagent_type="manager"` (or `"krish:manager"` when installed as the plugin; never `fork`: it ignores the model and can't nest):

```
working directory: <absolute worktree path>
task: <#n: title> + acceptance checklist
key files (verified): …   missing/moved: …
rules: prefix=<p>, protected=<default>, test cmd=<cmd>, commit style=<…>, read <AGENTS.md>
implementer model: <--model or "your call">
max_rounds: 3
never push, merge, or open a PR.
```

Leave the worktree alone while it runs.

## 4. On return

1. **INTERIM** report → not a result; wait for the next handback.
2. Show the report verbatim.
3. Thin report or risky change → rerun the tests yourself. One-line fixes: commit them.
4. Unfinished (`skilleddocs/HANDOFF.md`, or the SHA that last held it) → say what's left; offer another round from it.
5. Before any push: `git -C <worktree> diff --name-only <default>...HEAD` lists no `skilleddocs/HANDOFF.md`, nothing in the handoff folder (AGENTS.md/CLAUDE.md's, else `skilleddocs/handoffs/`) in commit mode, and nothing under `skilleddocs/` or that folder when untracked ([TRACKING.md](../handoff-auto/TRACKING.md)). A hit → remove it in a commit.
6. `--push` or the user says go:
   ```
   git -C <worktree> push -u origin <branch>
   gh pr create -R <o/r> --head <origin-owner>:<branch> --title "<title>" --body "<summary>\n\nCloses #<n>"
   ```
   `<o/r>` = the PR's base: on a fork, ask fork or parent first; the parent only on an explicit yes naming it. Never merge.
7. Review comments later → step 3 again, comments as the task, same worktree.

## 5. Print and teardown

Print: branch, worktree, PR URL or "not pushed", test result, rounds, HANDOFF.md path if any.

Teardown only after the PR merges. `git worktree remove` and any recursive delete (`rm -rf`, `Remove-Item -Recurse`) follow a link and empty the main checkout's copy: never run them while a link exists.

1. Move the worktree's dated handoffs into the same folder in the main checkout (`<hf>` = AGENTS.md/CLAUDE.md's handoff folder, else `skilleddocs/handoffs`). Left behind, one blocks `git worktree remove`, or is deleted with the worktree when git-excluded, and the verifier on `<default>` never sees it. In main, `update-progress` finds it and commits it per [TRACKING.md](../handoff-auto/TRACKING.md). `mv -n` keeps a same-named file in main and leaves the worktree copy; step 3 stops on any copy left (git would delete a git-excluded one silently).
   - Git Bash or mac/linux: `mkdir -p "<main>/<hf>"; for f in "<wt>/<hf>"/*.md; do [ -e "$f" ] && mv -n "$f" "<main>/<hf>/"; done`
   - PowerShell: `New-Item -ItemType Directory -Force "<main>\<hf>" | Out-Null; Get-ChildItem "<wt>\<hf>\*.md" -ErrorAction SilentlyContinue | Move-Item -Destination "<main>\<hf>\"` (fails, not overwrites, on a name clash).
2. Unlink each dep (removes the link only): Git Bash or mac/linux `rm "<wt>/.venv"` (no `-r`); PowerShell `cmd /c rmdir "<wt>\.venv"` (not `Remove-Item`).
3. Hard check; remove only when it passes (`-L` catches a dangling link):
   - Git Bash or mac/linux: `if [ -e "<wt>/.venv" ] || [ -L "<wt>/.venv" ] || [ -e "<wt>/node_modules" ] || [ -L "<wt>/node_modules" ] || ls "<wt>/<hf>"/*.md >/dev/null 2>&1; then echo "STOP: dep link or handoff in <wt>"; else git worktree remove "<wt>"; fi`
   - PowerShell: `if ((Get-ChildItem -Force "<wt>" | Where-Object Name -in '.venv','node_modules') -or (Test-Path "<wt>\<hf>\*.md")) { "STOP: dep link or handoff in <wt>" } else { git worktree remove "<wt>" }`

   STOP → leave the worktree and report which link or handoff is left. `git worktree remove` refuses (untracked or modified files) → stop and report `git -C "<wt>" status --short`; never `--force`.
