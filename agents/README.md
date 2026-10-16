# agents/ — subagents

*Each `<name>.md` here is the agent definition Claude Code loads (frontmatter + system prompt); this file is for you. `README.md` itself is skipped by the install scripts and the linter.*

A subagent runs in its own context window with its own model, tool allowlist and preloaded skills. Claude spawns one with `Agent(subagent_type="<name>", prompt=…)`. [`pair`](../pair/) and [`meta-orchestrator`](../meta-orchestrator/) spawn these, but each also works on its own ("use the planner agent to brief the next issue").

Installed by `scripts/install-skills.*` into `~/.claude/agents/`, with `hooks/` into `~/.claude/agents/hooks/`. Installed as the `krish` plugin instead, they are `krish:planner`, `krish:manager`, `krish:implementer` and `krish:verifier`; skills they preload resolve by bare name either way.

| Agent | Model | Preloads | Spawned by |
|---|---|---|---|
| [`planner`](#planner) | opus | `next`, `divide` | `meta-orchestrator` |
| [`manager`](#manager) | opus | `handoff-auto` | `pair`; `meta-orchestrator` (`execution: pair`) |
| [`implementer`](#implementer) | sonnet | `handoff-auto`, `session-handoff` | `manager`; `meta-orchestrator` (`execution: flat`) |
| [`verifier`](#verifier) | opus | `update-progress`, `consult-plan`, `next` | `meta-orchestrator` |

## planner

- **Role:** picks the next single unit of work from the board and writes the kickoff brief. Read-only: `disallowedTools: Edit, Write, NotebookEdit`; never creates issues. `maxTurns: 40`.
- **You pass:** repo path + scope contract (exclusions such as gated issues / people tasks / labels, ordering rule).
- **How it works:** runs `next` → drops excluded items → picks exactly one task → uses `divide` to *propose* a split if it looks multi-session → if nothing is left, says so and stops.
- **You get back (≤40 lines):** issue + acceptance checklist, key files, decisions/ADRs to respect, branch name `<prefix>/issue-<n>-<slug>`, gotchas, recommended model (and why), divide yes/no + proposed split.
- **Design principles:** read-only by construction (`disallowedTools`), so it can only propose, never change the board; exactly one task per brief; the ≤40-line cap keeps the brief cheap to pass verbatim to the next agent.
- **Use cases:** briefing the next issue for a `meta-orchestrator` loop; asking on your own "use the planner agent to brief the next issue" before starting work by hand.
- **Tips:** put gated issues, people tasks and labels to skip in the scope contract's `exclude`, or the planner may pick them. A proposed split is only a proposal; create the issues yourself (or with `divide`).
- **Prereqs:** `gh` authenticated, plus the `project` scope for a kanban board (see [`kanban`](../kanban/README.md#prerequisite-the-project-oauth-scope)); the `next` and `divide` skills installed.

## manager

- **Role:** owns one task end to end in a worktree. Never implements itself: briefs an implementer, then reviews its work as if it didn't trust it. `maxTurns: 150`.
- **You pass:** working directory (absolute, usually a worktree on the task branch), task + acceptance checklist, rules (branch prefix, protected branch, commit style, `CONTRIBUTING.md`/`AGENTS.md` path), `max_rounds` (default 3).
- **How it works:**
  1. Orients read-only; confirms every file the task cites exists; detects the test command.
  2. Writes a ≤40-line brief (includes "if stuck, write `skilleddocs/HANDOFF.md`, commit only if [`TRACKING.md`](../handoff-auto/TRACKING.md) says so, stop").
  3. Spawns an `implementer` (not `fork`, no `isolation`) in the foreground by default, blocking until it finishes; if it ends up backgrounded, never sleep-polls — ends the turn titled **INTERIM — implementer still running** and relies on the completion notification (callers must not act on it).
  4. Reviews every round itself, inline: commit scope, `git diff <base>...HEAD`, reruns tests + lint, and checks `git diff --name-only <base>...HEAD` carries no `skilleddocs/HANDOFF.md` (nothing under `skilleddocs/` when untracked). Fixes one-liners; larger gaps go to the next round. Never spawns reviewer subagents.
  5. Retries with a **fresh** implementer + `skilleddocs/HANDOFF.md`/findings, up to `max_rounds`; deletes `HANDOFF.md` once picked up (in a commit if tracked).
- **You get back:** branch + base/head SHA, commits, tests (command + counts) and lint run by it, review findings and who fixed each, rounds used, `skilleddocs/HANDOFF.md` path (or the last SHA that held it, if tracked) if unfinished, manual steps (e.g. the push).
- **Guard:** same `guard-git.py` hook as the implementer. Never pushes, merges or opens PRs — the caller does. Never deletes links or worktrees either, and never a recursive delete through a linked `node_modules`/`.venv` — teardown is the caller's job.
- **Design principles:** never implements, only briefs and reviews, treating the implementer's "pass" as a claim to rerun; review stays inline in its own context (no reviewer subagents, nested fan-out stalls); a stalled round restarts a fresh implementer from `HANDOFF.md` instead of stretching one context.
- **Use cases:** one task inside a worktree for [`pair`](../pair/); each task of a `meta-orchestrator` run in `execution: pair` mode.
- **Tips:** pass the working directory as an absolute path; it is handed to the implementer verbatim. Raise `max_rounds` only for tasks you expect to need several fresh starts. An **INTERIM** report means the implementer is still running, so don't act on it.
- **Prereqs:** the `implementer` agent and `handoff-auto` skill installed; Python 3.8+ (and Git Bash on Windows) for the guard hook.

## implementer

- **Role:** implements one well-specified issue from a kickoff brief on its own branch. `maxTurns: 200`.
- **You pass:** the kickoff brief verbatim + branch prefix + protected branch (from `manager` or the orchestrator).
- **How it works:** branches `<prefix>/issue-<n>-<slug>` off a freshly pulled default; if it created the branch, marks the issue started (card → In Progress, or `status:todo` → `status:in-progress`, creating that label first if missing; skipped with no board) and comments "Started on branch …", fail-soft (an error goes in the handoff, never blocks); commits small; runs the repo's detected test command before claiming done. Multi-session task or low turns → writes the handoff early. Stuck or past ~100k tokens → writes `skilleddocs/HANDOFF.md` (done / not done / next step / failed attempts), commits it only if [`TRACKING.md`](../handoff-auto/TRACKING.md) says so (never on a fork), stops, so a manager can restart a fresh implementer from it.
- **You get back:** calls `session-handoff` (which wraps `handoff-auto`); final message ends with the handoff document's absolute path on its own line.
- **Guard:** `guard-git.py` hook (below).
- **Design principles:** one issue, one session, small commits; "done" means it watched the tests pass; push and merge belong to the caller and the hook enforces it; board errors never block, they go in the handoff.
- **Use cases:** the worker under a `manager` (via `pair`) or directly under `meta-orchestrator` with `execution: flat`; any well-specified issue you want implemented unattended.
- **Tips:** give it a real kickoff brief (checklist, key files, branch prefix, protected branch); scope that grows past one session makes it stop early and hand off. A guard-hook block is reported, not worked around. Its last output line is the handoff path, which callers parse.
- **Prereqs:** `handoff-auto` and `session-handoff` installed; `gh` (with the `project` scope) for the card move; Python 3.8+ (and Git Bash on Windows) for the guard hook.

## verifier

- **Role:** verifies an implementation session and closes the loop. `maxTurns: 120`. No guard hook.
- **You pass:** handoff path (or saved manager report path), whether it may answer interview-style questions on your behalf, `review-done=yes|no` (default no; `yes` = a manager already reviewed and reran tests).
- **How it works:**
  1. Runs `update-progress` end to end: claims vs `git log`, tests, CI, code review (skipped if `review-done=yes`), docs/board/issue updates. Code review is inline, two axes (standards + spec), no reviewer subagents.
  2. Deviations: if authorized, answers `consult-plan` itself from the written plan and lists every Q → A; if not, records the deviation and leaves the plan untouched.
  3. Calls `next`.
- **You get back:** verified-by (tests + CI run id), findings fixed / issues filed, decided-for-you list, manual steps for you, then `next`'s output unedited.
- **Design principles:** a claim is not evidence, so every handoff claim is checked against `git log`, tests and CI; code review is inline on two axes (standards + spec) with no reviewer subagents; a deviation changes the plan only when you authorized it to answer for you.
- **Use cases:** closing the loop after an implementer or manager finishes in a `meta-orchestrator` run; checking a handoff by hand before you trust it.
- **Tips:** pass `review-done=yes` when a manager already reviewed and reran tests, to skip a second review. Without permission to answer for you, deviations come back as manual steps rather than plan changes.
- **Prereqs:** `update-progress`, `consult-plan` and `next` installed; `gh` authenticated, plus the `project` scope for a kanban board.

## hooks/guard-git.py

`PreToolUse` hook on `Bash|PowerShell`, wired in the `implementer` and `manager` frontmatter. Exits 2 (blocks, reason on stderr) or 0 (allows).

**As a plugin.** Claude Code ignores `hooks` frontmatter in plugin agents, so the plugin wires the same command once, plugin-wide, in [`.claude-plugin/plugin.json`](../.claude-plugin/plugin.json), with `--plugin`. That hook fires for every session, so with `--plugin` it reads `agent_type` from the hook input and enforces only for `implementer`/`manager` (bare or `<plugin>:`-prefixed); the main session and other agents pass through (exit 0).

**It is a guardrail, not a sandbox.** It stops an agent's honest mistakes and the obvious workarounds; it can't see inside script files, pre-existing shell aliases/functions, or `curl` to the GitHub API. Pair it with GitHub branch protection (require PRs, no force-push) on the default branch.

**Parsing.** Stdlib Python 3.8+. Splits the command on newlines, `;`, `&&`, `||`, `&`, `|` and `( )`, respecting quotes and dropping `# comments`; tokenizes each piece with `shlex` (POSIX). It recurses into `bash`/`sh`/`zsh -c`, `pwsh`/`powershell -Command` and `-EncodedCommand`, `cmd /c`, `eval`, `$(...)` and backticks, and `echo … | sh` / `bash <<EOF` (a shell reading stdin), `find -exec/-execdir/-ok … ;` and `watch …`. Here-doc bodies fed to anything else are data, so a commit message that says "push to main" is fine. Bash brace expansion is applied to every word (`ma{i,}n` → `main man`, `{a..c}`; quoted braces too, conservatively; over 64 results → unreadable). Before the git subcommand it skips `VAR=x`, `env` (incl. `-S`), `command`, `sudo`, `timeout`, `time -p`, `setsid`, `nohup`, `chronic`, `xargs`, full paths and `git.exe`, and git global options (`-C dir`, `-c k=v`, `--git-dir`, `--work-tree`, `--no-pager`, …). It resolves git aliases (`-c alias.p=push`, `git config alias.*`).

**Blocked:**

- `git push` with `--force*` (incl. `--force-with-lease=…`, `--force-if-includes`), a short-flag group containing `f` or `d` (`-f`, `-uf`, `-d`), `--mirror`, `--delete`, `--all`/`--branches`, `--prune`
- a refspec starting with `+` (force, any branch), a `:branch` delete refspec, a wildcard refspec, or one whose destination is protected: `main`, `HEAD:main`, `x:refs/heads/main`, `refs/heads/main`, DWIM `HEAD:heads/main`, `refs/heads//main` (case-insensitive); a destination of `@{-1}`-style or `-`
- `git send-pack` / `git http-push` with `--force`, `--all`, `--mirror`, `--stdin`, no refs (= matching branches), or any refspec the push rules above block
- a push with no refspec (`git push`, `git push origin`) or `HEAD`/`$(git branch --show-current)` as refspec while the current branch is protected (`cd dir` and `git -C dir` are followed)
- a refspec it can't read (`$BRANCH`, `$(…)`, `xargs`- or `find {}`-supplied): spell the branch name out
- `gh pr merge`, `gh repo delete`; `gh api` on `pulls/N/merge` or `merges` (any method), writes (`-X`/`--method` non-GET, or `-f`/`-F` fields) to `git/refs/heads/<protected>` or `branches/<protected>/protection` (endpoint `//` and `/./` collapsed first, so `refs/heads//main` and `branches/./main/protection` count; a ref with a `..` segment or `%`-escape is unreadable, so a write to it is blocked), `DELETE repos/o/r`, and graphql `mergePullRequest`/ref/repo-delete mutations
- `git branch -D/-d/--delete <protected>`
- an unparseable command (unbalanced quotes) that mentions `push` alongside a protected name or a force/delete marker, and any internal error while analysing a command that mentions push/merge/delete (fail closed)

**Allowed (no false positives):** `git push origin krish/x`, `git push -u origin HEAD` on a feature branch, `git commit -m "fix main push"`, `git log main..HEAD`, `gh pr view 5`, `gh api repos/o/r/pulls/5`. `echo git push origin main` is allowed on purpose: the words are arguments to `echo`, nothing runs them (piped into `sh`, it's blocked).

**Interpreter fallback.** The frontmatter `command:` is POSIX `sh` (Claude Code runs hook commands with `sh -c` on macOS/Linux and Git Bash on Windows). It probes `python3`, `python`, `py` for 3.8+ (stdin from `/dev/null`, so the hook JSON stays unread) and `exec`s the first that passes; if none does, it prints the reason and exits 2. A naive `python3 x || python x` would be wrong: a real block (exit 2) from the first would fall through to the second, which reads empty stdin and allows. The Windows Store `python3` stub fails the probe and is skipped. A missing hook file also exits 2 (Python's "can't open file"). Tested with Git Bash (`sh`, `bash`, `dash`), `docker run python:3.12-slim` and `python:3.8-slim` (dash; push to main → 2, feature push → 0) and `debian:bookworm-slim` (no Python → 2). **Windows needs Git Bash.** Without it, Claude Code falls back to PowerShell, which can't parse the `sh` command; that non-2 exit doesn't block, so the hook fails open and guards nothing. The install scripts check for it before copying anything (`install-skills.ps1`: `CLAUDE_CODE_GIT_BASH_PATH`, then `sh`/`bash` on `PATH` (WSL's `System32\bash.exe` doesn't count), then `bash.exe` in the Git for Windows install; `install-skills.sh`: `command -v sh`) and exit non-zero if it's missing. `-NoShCheck` / `--no-sh-check` installs anyway, with a warning.

**Known limits.** The hook reads the command text the agent runs, nothing more. It doesn't see what a script file does (`./push.sh`, `python deploy.py`), shell aliases or functions defined in the user's shell profile, or direct HTTP calls to the GitHub API (`curl`, `Invoke-RestMethod`, a Python `requests` call). GitHub branch protection is the backstop for all of these.

Protected branches: `GUARD_PROTECTED_BRANCHES` (comma list), default `main,master`. A block is working as intended, not something for the agent to route around. Self-test (every case above, current branch injected, plus stdin end-to-end runs and the `--plugin` agent filter): `python agents/hooks/guard-git.py --self-test`.

## Example

One issue through all three steps, as an orchestrator (or you) calls them.
The manager briefs and spawns its own `implementer` inside its turn, so only
its report comes back; you push and merge in between:

```transcript
⏺ Agent(subagent_type="planner", prompt="~/code/myrepo; exclusions: label needs-design; order: priority label")
  ⎿ Issue: #31 Add CSV export (checklist: 3 items)
    Key files: src/export.py, tests/test_export.py
    Constraints: none
    Branch: feat/issue-31-csv-export
    Gotchas: none
    Model: sonnet, narrow and well-specified
    Divide: no
⏺ Agent(subagent_type="manager", prompt="working directory: /home/you/code/_worktrees/myrepo-issue-31-csv-export; <the brief, verbatim>; prefix=feat; protected=main; max_rounds=3; never push or merge")
  ⎿ Branch: feat/issue-31-csv-export, base 1a2b3c4, head 5d6e7f8
    Commits: 5d6e7f8 feat: CSV export (#31)
    Tests: pytest, 118 passed; lint clean (run by me)
    Findings: none
    Rounds: 1 of 3
    Unfinished: none
    Manual steps for caller: push, open the PR, merge
⏺ Bash(git push -u origin feat/issue-31-csv-export && gh pr create --fill)
  ⎿ https://github.com/you/myrepo/pull/44
⏺ Merged PR #44; saved the manager's report to skilleddocs/orchestrator/reports/.
⏺ Agent(subagent_type="verifier", prompt="skilleddocs/orchestrator/reports/<#31 report>; interview=park; review-done=yes")
  ⎿ Verified by: 118 passed · CI run 9876543210
    Findings: none
    Decided for you: none
    Manual steps for user: none
    1. #28 Rework auth flow (unestimated, strong model: needs-design)
```
