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
- **You pass:** repo path + scope contract (exclusions such as gated issues / people tasks / labels, ordering rule, `lanes`), issues in flight, optional `decisions` (`ask`|`assume`).
- **How it works:** runs `next` → drops excluded items and `wayfinder:*` issues → picks exactly one task (with `lanes:`, one per lane whose head isn't in flight) → uses `divide` to *propose* a split if it looks multi-session → if nothing is left, says so and stops.
- **You get back (≤40 lines):** issue + acceptance checklist, key files, decisions/ADRs to respect, branch name `<prefix>/issue-<n>-<slug>`, gotchas, recommended model (and why), divide yes/no + proposed split, **Assumptions needed** (when `decisions=assume`).
- **Design principles:** read-only by construction (`disallowedTools`), so it can only propose, never change the board; exactly one task per brief; the ≤40-line cap keeps the brief cheap to pass verbatim to the next agent.
- **Use cases:** briefing the next issue for a `meta-orchestrator` loop; asking on your own "use the planner agent to brief the next issue" before starting work by hand.
- **Tips:** put gated issues, people tasks and labels to skip in the scope contract's `exclude`, or the planner may pick them. A proposed split is only a proposal; create the issues yourself (or with `divide`).
- **Prereqs:** `gh` authenticated, plus the `project` scope for a kanban board (see [`kanban`](../kanban/README.md#prerequisite-the-project-oauth-scope)); the `next` and `divide` skills installed.

## manager

- **Role:** owns one task end to end in a worktree. Never implements itself: briefs an implementer, then reviews its work as if it didn't trust it. `maxTurns: 150`.
- **You pass:** working directory (absolute, usually a worktree on the task branch), task + acceptance checklist, rules (branch prefix, protected branch, commit style, `CONTRIBUTING.md`/`AGENTS.md` path), `max_rounds` (default 3), `decisions` (`ask`|`assume`, default `ask`).
- **How it works:**
  1. Orients read-only; confirms every file the task cites exists; detects the test command.
  2. Writes a ≤40-line brief (includes "if stuck, write `skilleddocs/HANDOFF.md`, commit only if [`TRACKING.md`](../handoff-auto/TRACKING.md) says so, stop").
  3. Spawns an `implementer` (not `fork`, no `isolation`) with `run_in_background` unset so the call blocks. Some Agent tool versions have no foreground mode; then, or if the call returns early, it never fabricates a result or sleep-polls, ends the turn with a plain-text status and lets the completion notification wake it. Only with no notification path does it return **INTERIM — implementer still running** (callers must not act on it).
  4. Reviews every round itself, inline: commit scope, `git diff <base>...HEAD`, reruns tests + lint, and checks `git diff --name-only <base>...HEAD` carries no `skilleddocs/HANDOFF.md` (nothing in the handoff folder, `AGENTS.md`/`CLAUDE.md`'s else `skilleddocs/handoffs/`, in commit mode; nothing under `skilleddocs/` or that folder when untracked). Fixes one-liners; larger gaps go to the next round. Never spawns reviewer subagents.
  5. Retries with a **fresh** implementer + `skilleddocs/HANDOFF.md`/findings, up to `max_rounds`; deletes `HANDOFF.md` once picked up (in a commit if tracked).
- **You get back:** branch + base/head SHA, commits, tests (command + counts) and lint run by it, review findings and who fixed each, rounds used, **Assumed** open `A-n` ids, `skilleddocs/HANDOFF.md` path (or the last SHA that held it, if tracked) if unfinished, manual steps (e.g. the push).
- **Guard:** same `guard-git.py` hook as the implementer. Never pushes, merges or opens PRs — the caller does. `gh` is read-only (plus `gh pr create`), so card moves, issue comments and labels go to the caller as manual steps. Never deletes links or worktrees either, and never a recursive delete through a linked `node_modules`/`.venv` — teardown is the caller's job.
- **Design principles:** never implements, only briefs and reviews, treating the implementer's "pass" as a claim to rerun; review stays inline in its own context (no reviewer subagents, nested fan-out stalls); a stalled round restarts a fresh implementer from `HANDOFF.md` instead of stretching one context.
- **Use cases:** one task inside a worktree for [`pair`](../pair/); each task of a `meta-orchestrator` run in `execution: pair` mode.
- **Tips:** pass the working directory as an absolute path; it is handed to the implementer verbatim. Raise `max_rounds` only for tasks you expect to need several fresh starts. An **INTERIM** report means the implementer is still running, so don't act on it.
- **Prereqs:** the `implementer` agent and `handoff-auto` skill installed; Python 3.8+ (and Git Bash on Windows) for the guard hook.

## implementer

- **Role:** implements one well-specified issue from a kickoff brief on its own branch. `maxTurns: 200`.
- **You pass:** the kickoff brief verbatim + branch prefix + protected branch + `decisions` (from `manager` or the orchestrator).
- **How it works:** branches `<prefix>/issue-<n>-<slug>` off a freshly pulled default; if it created the branch, lists "card → In Progress + comment "Started on branch …"" as a manual step in its handoff (its `gh` is read-only, so its caller does it); commits small; runs the repo's detected test command before claiming done. Multi-session task or low turns → writes the handoff early. Stuck or past ~100k tokens → writes `skilleddocs/HANDOFF.md` (done / not done / next step / failed attempts), commits it only if [`TRACKING.md`](../handoff-auto/TRACKING.md) says so (never on a fork), stops, so a manager can restart a fresh implementer from it.
- **You get back:** calls `session-handoff` (which wraps `handoff-auto`); final message ends with the handoff document's absolute path on its own line; the handoff cites any open `A-n` it assumed.
- **Guard:** `guard-git.py` hook (below).
- **Design principles:** one issue, one session, small commits; "done" means it watched the tests pass; push and PR merge belong to the caller and the hook blocks pushes to protected branches and PR merges (local `git merge` is left to the caller); board errors never block, they go in the handoff.
- **Use cases:** the worker under a `manager` (via `pair`) or directly under `meta-orchestrator` with `execution: flat`; any well-specified issue you want implemented unattended.
- **Tips:** give it a real kickoff brief (checklist, key files, branch prefix, protected branch); scope that grows past one session makes it stop early and hand off. A guard-hook block is reported, not worked around. Its last output line is the handoff path, which callers parse.
- **Prereqs:** `handoff-auto` and `session-handoff` installed; `gh` for reads (card moves are the caller's); Python 3.8+ (and Git Bash on Windows) for the guard hook.

## verifier

- **Role:** verifies an implementation session and closes the loop. `maxTurns: 120`. No guard hook.
- **You pass:** handoff path (or saved manager report path), whether it may answer interview-style questions on your behalf, `review-done=yes|no` (default no; `yes` = a manager already reviewed and reran tests), `decisions` (`ask`|`assume`, default `ask`), user-answered `D<k>` (settled; never re-decided).
- **How it works:**
  1. Runs `update-progress` end to end: claims vs `git log`, tests, CI, code review (skipped if `review-done=yes`), docs/board/issue updates. Code review is inline, two axes (standards + spec), no reviewer subagents.
  2. Deviations: if authorized, answers `consult-plan` itself from the written plan and lists every Q → A; if not, records the deviation and leaves the plan untouched.
  3. Calls `next`.
- **You get back:** verified-by (tests + CI run id), findings fixed / issues filed, decided-for-you list, assumed open `A-n` list, manual steps for you, then `next`'s output unedited.
- **Design principles:** a claim is not evidence, so every handoff claim is checked against `git log`, tests and CI; code review is inline on two axes (standards + spec) with no reviewer subagents; a deviation changes the plan only when you authorized it to answer for you.
- **Use cases:** closing the loop after an implementer or manager finishes in a `meta-orchestrator` run; checking a handoff by hand before you trust it.
- **Tips:** pass `review-done=yes` when a manager already reviewed and reran tests, to skip a second review. Without permission to answer for you, deviations come back as manual steps rather than plan changes.
- **Prereqs:** `update-progress`, `consult-plan` and `next` installed; `gh` authenticated, plus the `project` scope for a kanban board.

## hooks/guard-git.py

`PreToolUse` hook on `Bash|PowerShell`, wired in the `implementer` and `manager` frontmatter. Exits 2 (blocks, reason on stderr) or 0 (allows).

**As a plugin.** Claude Code ignores `hooks` frontmatter in plugin agents, so the plugin wires the same command once, plugin-wide, in [`.claude-plugin/plugin.json`](../.claude-plugin/plugin.json), with `--plugin`. That hook fires for every session, so with `--plugin` it reads `agent_type` from the hook input and enforces only for `implementer`/`manager` (bare or `<plugin>:`-prefixed); the main session and other agents pass through (exit 0). Without Python 3.8+ the plugin command can't run guard-git, so it greps the hook input for the same `agent_type` match: those two agents are blocked (exit 2), everything else passes (exit 0), so a missing Python never locks your own session's Bash.

**It is a guardrail, not a sandbox.** It stops an agent's honest mistakes and the obvious workarounds; it can't see inside script files, shell profile aliases/functions, or code built at runtime. **Turn on GitHub branch protection on your default branch** (require a PR, required checks, no force-push, no deletion): that is the server-side backstop for anything a local hook can't read.

**Fail-closed allowlist (#174).** After the parsing below, every piece of the command that could push, merge, delete or write remote state must match a known-safe form, or the command is blocked:

- `git push [-u|--set-upstream|-v|-q|-n|--dry-run|--porcelain|--no-verify] <remote> <branch>[:<same branch>]` with a literal, non-protected branch name; `HEAD:<branch>`; bare `git push` / `git push <remote> HEAD` when the current branch is readable and not protected. Any other push option (`--tags`, `--repo`, `-o`, `--receive-pack`, …), a `refs/…` or reflog source, a different source branch, or a remote it can't read blocks. A tag push blocks too: `git push origin tag v1`, a name that is a local tag but not a local branch, one tagged earlier in the command (`git tag x && git push origin x`), or a version-like name (`v1.0`, `3.1`) with no local branch of that name (a tag fetched in the same command isn't visible yet).
- `gh` is read-only except `gh pr create` (#191; any repo/head/base/title/body flags): `pr create/new/view/list/checks/diff/status/checkout`, `issue view/list/status`, `repo view/list/clone`, `release view/list/download`, `workflow view/list`, `run view/list/watch/download`, `label list`, `project view/list/field-list/item-list`, `cache list`, `ruleset view/list/check`, `secret list`, `variable list/get`, `org list`, `alias list`, `extension list/search/browse`, `auth status/token`, `config get/list`, `search`, `status`, `browse --no-browser`, `help`, `version`. Everything else blocks: every issue/label/project write, `gist` and `codespace` (all), `run rerun/cancel/delete`, `release`/`secret`/`variable`/`workflow`/`cache`/`ruleset` writes, `pr merge/close/reopen/ready/edit/comment/review/lock/revert/update-branch`, `repo create/fork/edit/delete/archive/rename/set-default/sync/deploy-key`, `alias set`, and any unknown top-level command (a gh alias or extension can't be read). The subcommand is read both literally and the way gh's parser finds it (an unknown flag before it takes the next word as its value: `gh issue --add-label view edit 5` is `edit`), blocking if either is a write. **Card moves, issue comments and labels belong to the caller** (orchestrator, `pair`, verifier; none is guarded): implementer and manager list them in their handoff. `gh api` is GET only: a non-GET method, or `-f`/`-F`/`--input` without `-X GET` (they imply POST), blocks; `gh api graphql` allows only a literal read query (no `mutation`).
- `curl`/`wget`/`iwr`/`irm` to any `github.com` host (`github.com`, `api.github.com`, `uploads.github.com`) or `/api/v3/`: GET/HEAD only; any URL naming `git-receive-pack` (smart-HTTP push) blocks whatever the method.
- local git (add, commit, branch, merge, rebase, stash, worktree, fetch, pull, checkout/switch, tag, …) stays allowed; `git send-pack`/`http-push` and an unknown git subcommand that names push/merge/sync/delete (`git subtree push`) block; commands git runs for you (`rebase -x`, `submodule foreach`, `bisect run`, `-c key=<value>`) are read like any other command.
- unreadable code that could run a push fails closed: Bash `function f { … }` wrappers, a shell running `<(…)`, `script -c`, `xargs` feeding a shell or interpreter, PowerShell `(expr)` arguments (`git push origin ('ma'+'in')`), `[Diagnostics.Process]::Start`/`ProcessStartInfo` naming git/gh, and inline interpreter code (`deno eval`, `node -e`, …) that mentions push/merge next to a process call or a git/gh word.
- backstop for runners it doesn't model: a command whose head isn't git/gh, a shell, an interpreter, an HTTP client, a handled wrapper or a reader (`echo`, `printf`, `grep`, `rg`, `cat`, `ls`, `test`, `Write-Host`, `Select-String`, …), and whose arguments name a push/merge-capable command (`git … push|send-pack|http-push|subtree|receive-pack`, `gh … pr merge|api|alias|repo`, a gh write as classified above, `api.github.com`, `git-receive-pack`), blocks: `parallel git push …`, `awk 'BEGIN{system("git push …")}'`, `sed '1e git push …'`, `lua -e`, `Rscript -e`. `uv run`/`poetry run`/`pipenv run`, `npm exec`/`npx` (incl. `-c '…'`), `flock` (incl. `-c`), `strace`/`ltrace`, `coproc` and `trap '…'` are unwrapped and the inner command read as usual, so `uv run pytest` and `uv run git push origin krish/x` pass.
- a shell or `.`/`source` reading its script from `/dev/stdin`, `/dev/fd/N` or `/proc/self/fd/N` is a stdin shell (`bash /dev/stdin <<< 'git push …'`).
- write-then-run: a command that writes a file (`>`/`>>`, `tee`, PowerShell `Set-Content`/`Add-Content`/`Out-File`) and runs that same file (`sh x.sh`, `./x.sh`, `. x.sh`, `pwsh -File x.ps1`, `python x.py`) blocks when its text names a push/merge-capable command or a gh write.
- PowerShell splatting into git/gh (`git @a`) can't be read and blocks.
- stdin fed to a command that may run it: a here-doc, here-string or pipe into anything that isn't a shell or a stdin data consumer (`cat`, `grep`, `jq`, `sort`, `tee`, `xargs`, git/gh, `python script.py`, …) blocks when the fed text names a push/merge-capable command (`make -f - <<EOF`, `just --justfile /dev/stdin <<<`, `at now <<<`, `batch`, `tclsh`, `ssh host <<EOF`, `… | crontab -`) or comes from a transformer (`rev … | at now`). `cat > notes.txt <<'EOF' … git push … EOF` and `git commit -F - <<EOF` stay allowed.
- a shell, `iex` or interpreter reading a pipe needs every producer upstream (incl. `{ …; }` and `( … )` groups) to be a literal it reads: `echo`/`Write-Output`, `printf` without `%` or `\x`/`\NNN` escapes, `echo` without `-e` escapes, a `cat` here-doc, a PowerShell string. Anything else (`rev`, `tr`, `sed`, `printf '\x67it …'`, `Get-Content x | iex`) blocks; `echo hi | sh` passes. `cat x.sh | bash` reads like `bash x.sh`.
- inline interpreter code (`-c`/`-e`/eval/stdin) that spawns or evals (`subprocess`, `os.system`, `exec(`, `eval(`, `child_process`, `spawn`, `system(`, `__import__`, `getattr(`, Ruby/Perl backticks) and builds strings at runtime (`'g'+'it'`, `'g'.'it'`, `join`, `bytes.fromhex`, `chr(`, `String.fromCharCode`, `decode`, `atob`, `Buffer.from`, `[::-1]`, `reverse`, `replace(`, `format`/f-strings, `${…}`/`#{…}`, `\x` escapes, `split(`) blocks; `subprocess.run(['pytest','-q'])` and `console.log('a'+'b')` pass.
- `curl -K`/`--config` and `wget -i`/`--input-file`/`-e`/`--execute`/`--config` read options or URLs from a file: blocked when the command names GitHub or gives no URL.
- PowerShell/.NET: `Net.WebClient` `.Upload*`, `HttpClient` `Put/Post/Patch/Delete/Send`, `WebRequest`, in a command naming git/gh/github.com; `Add-Type`, `-ComObject`, `[Activator]::CreateInstance` with a `.Run`/`.Exec`/`ShellExecute`/`Start`/`::Method(` call or a git/gh/GitHub name.
- `cmd /c`: `%x%` and `!x!` expand at run time, so in a command running cmd they are unreadable (`cmd /c set x=main ^& git push origin %x%` blocks).

Commands that can't push or merge (pytest, uv, npm, npx, python/node scripts, file edits) are not on the risky surface and pass untouched. Failing closed has known false positives: an unmodelled tool whose arguments merely mention `git push` (`sed -i 's/git push/…/' README.md`; use the editor tool), a shell fed by a command it can't read (`curl … | sh` installers), and inline code that spawns a process and builds strings (`subprocess.check_output([...]).decode()` in `python -c` or `python - <<EOF`; put it in a script file).

**Parsing.** Stdlib Python 3.8+. Splits the command on newlines, `;`, `&&`, `||`, `&`, `|` and `( )`, respecting quotes and dropping `# comments`; tokenizes each piece with `shlex` (POSIX). It recurses into `bash`/`sh`/`zsh -c`, `pwsh`/`powershell -Command` and `-EncodedCommand`, `cmd [/d] /c` (dropping `^` escapes), `wsl [-e] …`, `eval`, PowerShell `Invoke-Expression`/`iex` (incl. `'…' | iex`), `Invoke-Command`/`icm { … }`, `& { … }`, `. { … }`, `& ("git") …`, any `{ … }` scriptblock (`% { … }`, `try { … }`, `Start-Job { … }`), `Start-Process git -ArgumentList …` or `Start-Process git "push …"` (and `saps`/`start`), `$(...)` and backticks, and `echo … | sh` / `bash <<EOF` / `bash <<< '…'` (a shell reading stdin, incl. `busybox sh`), `find -exec/-execdir/-ok … ;` and `watch …`. `iex (…)` of a literal string concatenation (`'git push ' + 'origin main'`) is evaluated and read. Here-doc bodies fed to a stdin data consumer (`cat`, `git commit -F -`, `gh … --body-file -`, `jq`) are data, so a commit message that says "push to main" is fine. Bash brace expansion is applied to every word (`ma{i,}n` → `main man`, `{a..c}`; quoted braces too, conservatively; over 64 results → unreadable). Before the git subcommand it skips `VAR=x`, `env` (incl. `-S`), `command`, `sudo`, `timeout`, `time -p`, `setsid`, `nohup`, `chronic`, `xargs`, full paths and `git.exe`, and git global options (`-C dir`, `-c k=v`, `--git-dir`, `--work-tree`, `--no-pager`, …). It resolves git aliases (`-c alias.p=push`, the user's `git config alias.*`, and a `git config alias.x …` written earlier in the command) and shell aliases defined in the command (Bash `alias g=git`, PowerShell `Set-Alias`/`New-Alias`/`sal`/`nal`), expanding them on use. It reads `--git-dir`/`--work-tree` and `GIT_DIR`/`GIT_WORK_TREE` (per command, `export`, `env`, PowerShell `$env:`) and checks that repo's current branch for a bare push. It follows the working directory across `cd`, `git -C` (Git Bash `/c/x` and `/cygdrive/c/x` map to `C:\x` on Windows), and PowerShell `Set-Location`/`sl`/`chdir`/`pushd`/`Push-Location` (`-Path`/`-LiteralPath`); for a `PowerShell` tool call it keeps Windows backslash paths (`C:\x\repo`) and treats a trailing backtick as a line continuation, not a dynamic refspec. Each nested shell is read in its own language: `bash -c`/`sh`/`wsl` inside a PowerShell call as POSIX, `pwsh -Command` inside a Bash call as PowerShell (the outer mode is restored after). It tracks `git checkout`/`switch <branch>` (incl. `-t origin/main` → `main`, and `main --`), `git symbolic-ref HEAD refs/heads/<b>` and `git branch -m <b>` earlier in a chain as the new current branch.

**Blocked:**

- `git push` with `--force*` (incl. `--force-with-lease=…`, `--force-if-includes`), a short-flag group containing `f` or `d` (`-f`, `-uf`, `-d`), `--mirror`, `--delete`, `--all`/`--branches`, `--prune`
- a refspec starting with `+` (force, any branch), a `:branch` delete refspec, a wildcard refspec, or one whose destination is protected: `main`, `HEAD:main`, `x:refs/heads/main`, `refs/heads/main`, DWIM `HEAD:heads/main`, `refs/heads//main` (case-insensitive); a destination of `@{-1}`-style or `-`
- `git send-pack` / `git http-push` (any form; not on the allowlist)
- a push with no refspec (`git push`, `git push origin`) or `HEAD`/`$(git branch --show-current)` as refspec while the current branch is protected — or while it can't be determined (unreadable `cd`/`-C` path, detached HEAD, `git checkout/switch` to an unknown or protected name earlier in the chain): a bare/implicit push fails closed
- a push carrying a config override that can redirect it to another branch: `-c push.default=matching|upstream|tracking`, `-c remote.*.push=…`, `-c remote.*.mirror=true`, `--config-env=…`, the `GIT_CONFIG_PARAMETERS`/`GIT_CONFIG_COUNT`+`GIT_CONFIG_KEY_n`/`VALUE_n` env forms, (also set via `env`, `export` or PowerShell `$env:`)
- a persisted `git config` write (any scope, `--add`/`--replace-all`/`--file`, or `git config set`) of `push.default matching|upstream|tracking`, `remote.*.push`, `remote.*.mirror true`, `branch.*.merge` naming a protected or unreadable branch, `include.path`, an unreadable key, or a `rename-section` into `remote.*`/`branch.*`: it would redirect a later, separate `git push`, so the write itself is blocked
- code it can't read, when the command mentions push/merge/delete: `eval $c`, `iex $c`, `iex (expr)` that isn't a literal concatenation, `$c` run as a command, `& $sb`, `. $sb`, `& (expr)`, `Invoke-Command $sb`, `Start-Job $sb`, `$sb.Invoke()`, `[scriptblock]::Create(…).Invoke()`, `InvokeScript(…)` (fail closed)
- an unreadable git subcommand (`git $a origin main`, `git $(…)`), a git alias set to an unreadable value, or a bare push in a `--git-dir`/`GIT_DIR`/`GIT_WORK_TREE` repo that is on a protected branch or can't be read
- a `git config alias.*` write whose value mentions push/merge/delete (any scope)
- base64/hex-decoded text (`base64 -d`, `xxd -r`, `openssl … -d`, `certutil -decode`, `[Convert]::FromBase64String`) reaching a stdin shell, `eval`, `iex`, `sh -c "$(…)"` or inline interpreter code (fail closed, no risky word needed)
- inline interpreter code (`python`/`python3`/`py -c`, `node -e`/`--eval`/`-p`, `perl -e`/`-E`, `ruby -e`, `php`, `bun`, `deno`, or one reading stdin) that names `git push`/`gh pr merge`/`gh api … merge` or a gh write (`subprocess.run(['gh','issue','close','5'])`), mentions push/merge next to a process call (`os.system`, `subprocess`, `exec`, `child_process`, backticks), or writes to `api.github.com`
- `curl`/`wget`/`Invoke-WebRequest`/`iwr`/`Invoke-RestMethod`/`irm` writes (non-GET method, or `-d`/`--data*`/`-F`/`--json`/`-T`/`--post-data`/`-Body`/`-InFile`) to any `github.com` host (or `/api/v3/`), and any request to a `git-receive-pack` URL
- a refspec it can't read (`$BRANCH`, `$(…)`, `xargs`- or `find {}`-supplied): spell the branch name out
- any `gh` command outside the allowlist above, and any non-GET `gh api` call; the older targeted rules still apply and give specific reasons: `gh api` on `pulls/N/merge` or `merges` (any method), writes (`-X`/`--method` non-GET, or `-f`/`-F` fields) to `git/refs/heads/<protected>` or `branches/<protected>/protection` (endpoint `//` and `/./` collapsed first, so `refs/heads//main` and `branches/./main/protection` count; a ref with a `..` segment or `%`-escape is unreadable, so a write to it is blocked), a write to `repos/o/r/contents/<path>` unless an explicit non-protected `branch=` field is given (no `branch=` commits to the default branch, and `--input <file>` or `-F branch=@file` hides the branch, so all are blocked; `-f`/`-F`/`--field`/`--raw-field`, attached `-fbranch=…`, and `--field=branch=…` are all read), `DELETE repos/o/r`, and graphql `mergePullRequest`/ref/repo-delete mutations
- `git branch -D/-d/--delete <protected>`
- an unparseable command (unbalanced quotes) that mentions `push` alongside a protected name or a force/delete marker, and any internal error while analysing a command that mentions push/merge/delete (fail closed)

**Allowed (no false positives):** `git push origin krish/x`, `git push -u origin HEAD` on a feature branch, `git commit -m "fix main push"`, `git log main..HEAD`, `gh pr view 5`, `gh api repos/o/r/pulls/5`, `gh api repos/o/r/contents/x` (GET), `gh api graphql -f query='query{…}'`, `gh pr create … --body "$(cat <<'EOF' … EOF)"`, `gh issue view/list`, `gh pr checks/diff`, `gh run view/list`, `gh project item-list`, `git stash push`, `git config --get`/`get`/`--list`/`list`, `git config branch.krish/x.merge refs/heads/krish/x`, `git -c push.default=matching status`, `eval "$(ssh-agent -s)"`, PowerShell `& $env:ComSpec /c dir`, `& $exe --version`, `cd C:\x; git status`, Git Bash `cd /c/Users/me/feat && git push -u origin HEAD` on a feature branch, `python scripts/x.py`, `python -c "print(1)"`, `node -e "console.log(1)"`, GET `curl https://api.github.com/repos/o/r/pulls`, `base64 -d x > out.bin`. `echo git push origin main` is allowed on purpose: the words are arguments to `echo`, nothing runs them (piped into `sh`, it's blocked).

**Interpreter fallback.** The frontmatter `command:` is POSIX `sh` (Claude Code runs hook commands with `sh -c` on macOS/Linux and Git Bash on Windows). It probes `python3`, `python`, `py` for 3.8+ (stdin from `/dev/null`, so the hook JSON stays unread) and `exec`s the first that passes; if none does, it prints the reason and exits 2 (the plugin command exits 2 only for guarded agents; see **As a plugin**). A naive `python3 x || python x` would be wrong: a real block (exit 2) from the first would fall through to the second, which reads empty stdin and allows. The Windows Store `python3` stub fails the probe and is skipped. A missing hook file also exits 2 (Python's "can't open file"). Tested with Git Bash (`sh`, `bash`, `dash`), `docker run python:3.12-slim` and `python:3.8-slim` (dash; push to main → 2, feature push → 0) and `debian:bookworm-slim` (no Python → 2). **Windows needs Git Bash.** Without it, Claude Code falls back to PowerShell, which can't parse the `sh` command; that non-2 exit doesn't block, so the hook fails open and guards nothing. The install scripts check for it before copying anything (`install-skills.ps1`: `CLAUDE_CODE_GIT_BASH_PATH`, then `sh`/`bash` on `PATH` (WSL's `System32\bash.exe` doesn't count), then `bash.exe` in the Git for Windows install; `install-skills.sh`: `command -v sh`) and exit non-zero if it's missing. `-NoShCheck` / `--no-sh-check` installs anyway, with a warning.

**Known limits.** The hook reads the command text the agent runs, nothing more. It doesn't see what a script file does (`./push.sh`, `python deploy.py`) unless the same command wrote it, shell aliases or functions defined in the user's shell profile, inline interpreter code that builds its command at runtime without a marker it knows (spawn/eval plus concatenation, `join`, `fromhex`, `[::-1]`, … do block), HTTP writes whose URL hides the host (`curl -X PUT $URL`), other HTTP clients (`httpie`, a Python `requests` script file), or a `git config alias.*` value pulled in from a file. Unquoted `C:\x` paths in a Bash call stay unreadable (bash eats the backslashes), so a bare push after one fails closed. GitHub branch protection is the backstop for all of these.

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
