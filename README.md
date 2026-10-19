# skills

Krish's Claude Code skills, subagents and dev config.

A personal collection of [Claude Code](https://claude.com/claude-code) skills, subagents and dev config, shared here so you (or I, on another machine) can install and use them too.

A **skill** is a directory with a `SKILL.md` that Claude Code loads into the current conversation when it decides the skill applies (or when you type `/<name>`). A **subagent** is a `.md` file that defines a separate worker with its own context window, model, tool allowlist and preloaded skills; Claude spawns it for isolated work. Skills are "how to do X"; agents are "who does X, with what permissions".

## How to read this repo

Every skill folder has two files: `SKILL.md` is the prompt Claude follows (frontmatter + instructions), and `README.md` is for you: what it does, when to use it, how to invoke it, how it works step by step, and an example. Agents are documented together in [`agents/README.md`](agents/README.md); each `agents/<name>.md` is the definition Claude loads. Start with the READMEs; open a `SKILL.md` only to see or change exact behaviour.

## Start here

New to the repo? Check the prereqs, install, then try one skill.

| Need | Why | Check |
|---|---|---|
| [Claude Code](https://claude.com/claude-code) | runs every skill and agent here | `claude --version` |
| `gh` CLI, authenticated, `origin` on GitHub | `pair`, `meta-orchestrator`, `pr-watch`, `gap-scan` and everything under `kanban/` read and write GitHub. `kanban/`, `wayfinder` and `pr-watch` stop with a message on a non-GitHub remote. Kanban Projects boards also need `gh auth refresh -s project -s read:project` once. Every `gh` call names `origin`'s repo (`-R`). On a fork clone, bare `gh` would default to the parent, so skills ask which repo to write to and never write to the parent without a yes naming it ([Target repo](kanban/next/BOARD.md#target-repo)) | `gh auth status` |
| Python 3.8+ | the lint step of the install, `scripts/build_site.py`, and the `guard-git` hook that stops agents pushing to `main` or merging | `python --version` |
| Git Bash (Windows only) | the `guard-git` hook is a POSIX `sh` command; without it the hook fails open, so the installer refuses | `sh --version` |

**Which skill first**

1. [`grill-docs`](grill-docs/README.md): zero setup, and it leaves a decision record (`skilleddocs/decisions.md` unless the repo has its own) the other skills read. Good for seeing what a skill writes.
2. [`pair`](pair/README.md): one task end to end in an isolated worktree, you push at the end. The smallest taste of the agents.
3. [`meta-orchestrator`](meta-orchestrator/README.md): a whole backlog unattended. Try it last; it is the most autonomous and builds on the two above.

**60-second quickstart**

In Claude Code:

```
/plugin marketplace add KrishP147/skills
/plugin install krish@krish
```

Then (in a new session if it isn't listed yet) type `/krish:grill-docs <a plan you are unsure about>`. Prefer plain `/grill-docs` names, or no plugin? Use the install script instead (pick one, not both): [Install](#install), which also covers flags and the `repo-scrub` / kanban extras.

## Three ways to run work

| Tier | You type | Sessions | For |
|---|---|---|---|
| **Solo** | `/next` → implement yourself → `/session-handoff` → `/update-progress` | you, a fresh terminal per step | learning the loop; small repos |
| **Pair** | `/pair <issue # or task>` | one interactive session; a `manager` agent and its `implementer` run inside it | one task on any repo (OSS forks included), no board needed |
| **Orchestrated** | `/meta-orchestrator <repo>` | one top-level session looping planner → manager → merge gate → verifier, handing off to a fresh orchestrator every N merges | a whole backlog, unattended |

Each tier builds on the one above: `pair` is one orchestrator loop without the board, and the orchestrator's default `shape: pair` runs `pair`'s manager once per issue (`flat` skips the manager; `swarm` batches trivial issues onto haiku implementers).

## What's here

### Plan and decide

Think a plan through before you build it.

| Skill | What it does | Prereqs |
|---|---|---|
| [`grilling`](grilling/README.md) *(Matt Pocock)* | Interviews you relentlessly, one round of questions at a time with a recommendation attached to each, until a plan or decision is fully stress-tested. | none |
| [`grill-me`](grill-me/README.md) *(Matt Pocock)* | Short alias for `grilling`. User-invoked only (`/grill-me`); Claude auto-invokes `grilling` instead. | none |
| [`grill-docs`](grill-docs/README.md) | `grilling` with a paper trail: writes the Q→A transcript to `skilleddocs/grills/` as each round settles and appends every decision to the repo's decisions doc (default `skilleddocs/decisions.md`), so planners, verifiers and teammates can read what was decided and why. | none |
| [`wayfinder`](wayfinder/README.md) *(adapted from Matt Pocock's `wayfinder`)* | Plans an effort too big for one session. It opens a `wayfinder:map` GitHub issue whose sub-issues are decision tickets (research, prototype, grilling, task). You resolve one per session until the way is clear, then hand the map to `divide` for board issues. The map stays off the board (`next`, `planner` and `meta-orchestrator` skip `wayfinder:*`). User-invoked only (`/wayfinder`). | `gh`; `grill-docs` |
| [`consult-plan`](kanban/consult-plan/README.md) | Grills a new idea or deviation against the existing plan before it goes in | `gh`; `grilling` |
| [`gap-scan`](gap-scan/README.md) | Surveys one or more repos (sync, README/docs, recent commits, TODOs, tests, open issues, an optional visual pass for UI apps) and returns a ranked, evidence-cited list of gaps, bugs, and extensions as issue-ready items. Read-only: writes one report under `skilleddocs/gaps/`; creating issues needs an explicit yes. | `gh` |
| [`find-me-a-skill`](find-me-a-skill/README.md) | Suggests which skill or sample workflow fits a task (from the text, the conversation, or the top board tasks), with the model and `/effort` for each step, the points where you decide, and commands to paste. Read-only, runs on Haiku, reads a catalog generated from this repo (`python scripts/site_catalog.py`). | none; `gh` for board mode |

### Build and orchestrate

Run one task, or a whole backlog, with agents.

| Skill | What it does | Prereqs |
|---|---|---|
| [`pair`](pair/README.md) | Runs one task in an isolated git worktree: resolves the issue (syncs upstream first on a fork, checks the cited files still exist), spawns the `manager` agent, shows its report, and only then pushes and opens the PR itself. Agents never touch the remote. | `gh`; `manager` + `implementer` agents installed |
| [`meta-orchestrator`](meta-orchestrator/README.md) | Runs a repo's backlog unattended. It loops `planner` → `manager` → `verifier` per issue (`shape: flat` uses `implementer` instead of `manager`; `shape: swarm` uses a swarm of haiku implementers; the implementer model follows issue size). It holds the merge gate itself: no merge until tests and CI are green. It reads `skilleddocs/` for the design record and appends every event to `skilleddocs/orchestrator/ledger.md` (committed in the repo, unless `docs_commit: uncommitted`). After a budget of merges it writes `orchestrator-handoff.md`, so `/meta-orchestrator <repo> resume` continues in a fresh session. | `gh`; the four agents installed; a kanban board, `status:*` labels, or a roadmap doc (whatever `next` finds) |
| [`lanes`](lanes/README.md) | Sets how many issues a `meta-orchestrator` run works on at once: predicts each queued issue's files, groups overlapping issues into the same lane, proposes a count with a token-cost line, and on your yes writes named lanes to `scope.md`. `/lanes <n> \| increase \| decrease`; changes apply at the orchestrator's next loop. | a `meta-orchestrator` run; `gh` |
| [`score-loop`](score-loop/README.md) | Pushes one rerunnable numeric score up or down, unattended. It builds a local harness that mirrors the grader (correctness check, median of N runs, noise margin from baseline runs). It then commits one hypothesis at a time on `<prefix>score-loop/<slug>`, keeps a commit only when it beats the best by more than the margin, and `git revert`s the rest. Every experiment is logged to `skilleddocs/experiments.md`. It stops on budget, deadline freeze or plateau. Official submissions stay inside a quota you approve; paid ones go through `spend-gate`. | a score you can compute locally |
| [`ponytail`](ponytail/README.md) *(Dietrich Gebert)* | Lazy-senior-developer mode for the whole session: the smallest change that fully solves the task, plus a closing line on what was skipped and any risk. Levels `lite`, `full` (default), `ultra`; stays on until "stop ponytail". | none |

### Sessions and accounts

Hand work to a fresh session, check this one, or switch accounts.

| Skill | What it does | Prereqs |
|---|---|---|
| [`handoff`](handoff/README.md) *(Matt Pocock, save path modified, commit rule added)* | Compacts the current conversation into a handoff document so a fresh session can pick up where it left off; saved under `skilleddocs/handoffs/`. User-invoked only (`/handoff`). | none |
| [`handoff-auto`](handoff-auto/README.md) *(derived from Pocock's `handoff`; frontmatter, save path and commit rule differ)* | Same document, but callable by the model, so other skills and subagents can end a session unattended. Saved under `skilleddocs/handoffs/`, committed or not per [`TRACKING.md`](handoff-auto/TRACKING.md). Prints the file path as its last line. | none |
| [`sitrep`](sitrep/README.md) | Live, conversational status check in 10 lines or fewer: what's running, git state, open PRs + CI, an asked-vs-done checklist, needs-you items, and a SAFE/NOT SAFE close verdict. Read-only, except on "close": it lists what would stop, then stops it and hands off only on your explicit yes. | `gh`; background-task tools if available (optional) |
| [`session-bridge`](session-bridge/README.md) | Coordinates with another running Claude Code session or agent: finds it (`ListAgents`, or its transcript under `~/.claude/projects/`), takes a read-only snapshot, checks for file/branch/issue overlap and proposes a split, then sends a message only on explicit yes. A reply from another session is never treated as your approval. | none; `ListAgents`/`SendMessage` and `gh` used when available |
| [`switch`](switch/README.md) | Runs several Claude Code accounts, one config dir each. `claude` opens the account you used last, `claude-<name>` opens a named one, and `/switch [name]` ends the session and resumes the same conversation on the previous or named account. A small stdlib Python launcher in each terminal watches its own request file. `setup` shows the diff, then writes wrappers for bash, zsh, fish, PowerShell 5.1 + 7 and cmd; `migrate` registers existing `~/.claude-*` dirs read-only. `/switch add\|remove\|rename\|list\|theme` manages accounts: new ones link the first account's skills, settings and history, and `remove --delete-dir` never deletes through a link. A statusline shows the account in its colour plus session/week usage and time left. A prompt hook warns at 90% and 97%, and runs a typed `/switch` without an API call, so switching works even at 100%. User-invoked only (`/switch`). | Python 3.8+ |
| [`remind`](remind/README.md) | Reminders tied to your accounts or a time: when an account's session or weekly limit resets (time from `switch`'s usage cache, never guessed), when its usage drops under N%, or at/in a time. Due ones show once at your next prompt on any account via `switch`'s hook; timed ones also get a desktop notification at the exact time (Windows scheduled-task toast, `at` on macOS/Linux). `/remind list`, `/remind cancel <id>`. User-invoked only (`/remind`). | Python 3.8+; `switch` for account reminders |

### Review and report

Watch PRs, write up what happened, brief a teammate.

| Skill | What it does | Prereqs |
|---|---|---|
| [`pr-watch`](pr-watch/README.md) | Watches your open PRs until merged: pulls bot and human review threads (CodeRabbit, Copilot, maintainers), fixes valid ones via `pair`, replies to or resolves the rest with cited evidence, reports CI (fork `action_required` = needs maintainer approval, not failing). Every push, reply, resolve, and bot re-trigger is gated on an explicit yes. | `gh`; `pair`'s agents for the fix step |
| [`progress-report`](progress-report/README.md) | Turns the orchestrator's ledger into a short report covering only what happened since the last one (watermarked, never overlapping): done, what worked, what didn't, concerns, decisions made on your behalf, manual steps for you. Markdown by default, `.docx` on request. | `docx` skill or `python-docx` for the Word option |
| [`teammate-brief`](teammate-brief/README.md) | Writes a handoff document for a person joining or picking up a project: setup steps verified by running them, an env/keys table (names only, never values), numbered tasks with a "done when" each, an ownership map, and a don't-touch list. Saved to `skilleddocs/briefs/`; commits and pushes gated separately. | `gh`, optional, for open issues |

### Repo and safety

Get a repo ready to share, scrub secrets, gate paid actions.

| Skill | What it does | Prereqs |
|---|---|---|
| [`repo-showcase`](repo-showcase/README.md) | Gets a repo's working tree ready to be seen: rewrites the README around outcome and demo, prunes stale docs, fixes claims the code has outdated, scans for secrets and private names, proposes GitHub metadata. Never touches history or visibility — hands off to `repo-scrub` for that. | `gh` (metadata step only) |
| [`repo-scrub`](repo-scrub/README.md) | Scans a GitHub repo's full git history for secrets and oversized files, lets you pick exactly what to scrub, rewrites history safely, and only then flips the repo private → public. User-invoked only (`/repo-scrub`). | `gh`, [`gitleaks`](https://github.com/gitleaks/gitleaks), [`git-filter-repo`](https://github.com/newren/git-filter-repo) |
| [`spend-gate`](spend-gate/README.md) | Gates any billable action (GPU pods, paid APIs, paid tiers, cloud credits) behind a cost estimate, a live balance check, and an explicit yes for that specific action — a budget cap is never itself approval. Logs every approval to `skilleddocs/spend.md`. Pairs with the optional [`hooks/spend-guard.py`](hooks/README.md#spend-guardpy--block-billable-commands-without-an-approval) hook. | none |

### Kanban board

Skills in [`kanban/`](kanban/) that use a GitHub board as the task list.

| Skill | What it does |
|---|---|
| [`next`](kanban/next/README.md) | Shows the next work-session task(s), pulled from the board. Read-only. |
| [`session-handoff`](kanban/session-handoff/README.md) | Ends a session: calls `handoff-auto`, records progress against the board, moves the card |
| [`update-progress`](kanban/update-progress/README.md) | Verifies a handoff's claims, updates docs/board/issue from it |
| [`divide`](kanban/divide/README.md) | Splits an oversized issue into session-sized ones |
| [`kanban-setup`](kanban/kanban-setup/README.md) | Bootstraps a GitHub Projects board for a repo; can backfill issues from what's already documented. User-invoked only (`/kanban-setup`) because it creates real issues. |

Projects v2 boards need `gh auth refresh -s project -s read:project` once; label mode doesn't (see [`kanban/README.md`](kanban/README.md)).

### [`agents/`](agents/) — subagents `pair` and the orchestrator spawn

| Agent | Model | Preloads | Guard rails |
|---|---|---|---|
| [`planner`](agents/README.md#planner) ([def](agents/planner.md)) | opus | `next`, `divide` | no Edit/Write; proposes splits, never creates issues; returns a ≤40-line kickoff brief |
| [`manager`](agents/README.md#manager) ([def](agents/manager.md)) | opus | `handoff-auto` | spawns its own `implementer`, reviews the diff and reruns tests itself, restarts a fresh implementer from `skilleddocs/HANDOFF.md` when one stalls (≤3 rounds); same `guard-git.py` hook as the implementer; never pushes |
| [`implementer`](agents/README.md#implementer) ([def](agents/implementer.md)) | sonnet | `handoff-auto`, `session-handoff` | a `PreToolUse` hook ([`guard-git.py`](agents/hooks/guard-git.py)) allowlists what may touch the remote. Only a plain feature-branch `git push`, `gh pr create`, gh/git reads, `gh api` GET and local git pass. Anything else that could push, merge or write refs or remote state is blocked: other push forms, `send-pack`, `gh pr merge`, non-GET API calls, gh aliases/extensions, code it can't read ([details](agents/README.md#hooksguard-gitpy)). It fails closed (exit 2) when no Python 3.8+ is found. It is a guardrail, not a sandbox, so also enable GitHub branch protection on your default branch (require PRs, no force-push or deletion). **On Windows it needs Git Bash**: the hook command is `sh`, so without it the hook fails open, and the install refuses unless `-NoShCheck`. Writes `skilleddocs/HANDOFF.md` when stuck or past the smart zone; ends with the handoff path |
| [`verifier`](agents/README.md#verifier) ([def](agents/verifier.md)) | opus | `update-progress`, `consult-plan`, `next` | verifies against git log/tests/CI, reviews the diff, lists every question it answered on your behalf; no guard hook — may commit doc/board fixes to the default branch |

Full explainer (inputs, outputs, procedure, guard hook): [`agents/README.md`](agents/README.md). They also work on their own: "use the planner agent to brief the next issue" is a fine prompt without the orchestrator. Set `GUARD_PROTECTED_BRANCHES=main,develop` to change what the hook protects. Agents can spawn agents (`manager` → `implementer`); only the built-in `fork` type can't nest.

### [`hooks/`](hooks/) — optional per-repo hooks

Not auto-installed. The third hook, [`guard-git.py`](agents/hooks/guard-git.py), lives under `agents/hooks/` and comes with the agents: it stops the `implementer` and `manager` from pushing to `main`, force pushing or merging, so only the orchestrator merges ([details](agents/README.md#hooksguard-gitpy)). [`smartzone.py`](hooks/smartzone.py) is a `UserPromptSubmit` hook that warns in-conversation when the transcript suggests context has left the smart zone (~75k tokens, `SMARTZONE_TOKENS`), so a session wraps up instead of degrading. [`spend-guard.py`](hooks/spend-guard.py) is a `PreToolUse` hook that blocks known billable commands/MCP calls (GPU pod creation, paid deploys, ...) unless an approval token from the [`spend-gate`](spend-gate/README.md) skill already exists. Copy + settings snippets in [`hooks/README.md`](hooks/README.md).

### [`site/`](site/) — static skills site

A static site generated from this repo by [`scripts/build_site.py`](scripts/build_site.py) (stdlib only), served at [www.krishpunjabi.com/skills](https://www.krishpunjabi.com/skills). The home page looks like a Claude Code terminal: type after the `/` prompt to search (ranked matches, aliases, did-you-mean on typos), or browse the plain list of every skill, agent and hook. Each entry gets a `/<name>` page, where its README `## Example` renders as a Claude Code session. A `/workflows` page shows sample workflows and a `/map` page shows how everything connects. Light or dark follows your OS theme. Build, test and deploy steps are in [`site/README.md`](site/README.md).

Attribution and divergences: [Third-party skills](#third-party-skills). Licence: [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

## Where skills write: `skilleddocs/`

Every skill or agent here that produces a document writes it **inside the repo it is working on**, under one directory, so any teammate or fresh session finds it in the same place. It is committed only if the repo already tracks `skilleddocs/` or opts in via `AGENTS.md`/`CLAUDE.md`, and never on a fork. Otherwise it stays untracked and git-excluded, so it can't leak into a task PR. Full rule: [`handoff-auto/TRACKING.md`](handoff-auto/TRACKING.md):

```
skilleddocs/
  README.md            what each folder holds (template below)
  bridge.md            cross-session message log — session-bridge
  briefs/              teammate onboarding briefs — teammate-brief
  decisions.md         append-only decision register (D1, D2, ...) — grill-docs, consult-plan, verifier, wayfinder
  experiments.md       setup header, results ledger and next ideas — score-loop
  gaps/                gap-scan reports — gap-scan
  grills/              one transcript per grill-docs session
  handoffs/            session handoffs — handoff, handoff-auto, session-handoff, implementer
  HANDOFF.md           short "stuck" note an implementer leaves for a manager (deleted once picked up; never in a pushed branch)
  orchestrator/        scope.md, ledger.md, orchestrator-handoff.md, reports/<manager reports> — meta-orchestrator
  pr-watch/            per-pass PR watch logs — pr-watch
  reports/             progress reports + .last-reported watermark — progress-report
  showcase/            showcase inventory and findings — repo-showcase
  spend.md             approval log (when, amount, purpose, price source, resource id) — spend-gate
  spend-approvals/     one-shot approval files consumed by hooks/spend-guard.py — spend-gate
```

Rules: local dates in filenames, never UTC; the register is append-only (reverse a decision with a new row); nothing under `skilleddocs/` is a spec or a roadmap — plans live wherever the repo keeps docs, and `skilleddocs/` points at them. The orchestrator commits its files on the default branch as it goes (`docs(skilleddocs): ledger NNN`), unless `docs_commit: uncommitted` (always on a fork, per `TRACKING.md`). A repo's `AGENTS.md` / `CLAUDE.md` can override any path, so older repos with `docs/decisions.md` or a `reports/` folder keep working. **Packaging hazard (untracked mode):** git-excluding `skilleddocs/` does not hide it from setuptools. In a flat-layout Python project, `pip install .` fails with "Multiple top-level packages discovered" while an untracked `skilleddocs/` sits in the tree. Install from a clean clone, or set explicit packages in `pyproject.toml`; details in [`TRACKING.md`](handoff-auto/TRACKING.md). Skills that only read or act on GitHub (`next`, `divide`, `kanban-setup`, `pair`, `repo-scrub`) write nothing here.

Template for a repo's `skilleddocs/README.md`:

```markdown
# skilleddocs

Documents written by Claude Code skills (github.com/KrishP147/skills). Versioned so agents and people share one record.

- bridge.md — cross-session message log (session-bridge)
- briefs/ — teammate onboarding briefs (teammate-brief)
- decisions.md — append-only decision register; cite as D<k>
- gaps/ — gap-scan reports (gap-scan)
- grills/ — grilling transcripts (asked, recommended, answered)
- handoffs/ — end-of-session handoffs; the newest is the next session's starting brief
- orchestrator/ — meta-orchestrator scope contract, ledger, handoff, manager reports
- pr-watch/ — per-pass PR watch logs (pr-watch)
- reports/ — progress reports and the watermark
- showcase/ — showcase inventory and findings (repo-showcase)
- spend.md, spend-approvals/ — billable-action approval log and one-shot approval tokens (spend-gate)

Plans and specs live in docs/; this folder records how they were decided and carried out.
```

## Install

Pick **one** of the two. Both at once loads every skill and agent twice (once as `/<skill>`, once as `/krish:<skill>`) and runs the `guard-git` hook twice.

### As a plugin (recommended)

In Claude Code:

```
/plugin marketplace add KrishP147/skills
/plugin install krish@krish
```

Skills are namespaced: `/krish:pair`, `/krish:grill-docs`, and so on. Agents are `krish:manager`, `krish:implementer`, `krish:planner` and `krish:verifier`; the skills that spawn them accept either form. The `guard-git` hook comes with the plugin as a plugin-level hook: it guards only the `implementer` and `manager` agents, so your own session can still push. The optional hooks in [`hooks/`](hooks/README.md) are not part of the plugin; install those by hand. On Windows the hook needs Git Bash, as below; without it the hook blocks nothing. Update with `/plugin marketplace update krish`. Versions and changes: [`CHANGELOG.md`](CHANGELOG.md).

### With the install script

Plain names (`/pair`, `manager`) and files you can edit in place:

```bash
git clone https://github.com/KrishP147/skills.git
cd skills
./scripts/install-skills.sh        # bash/git-bash/mac/linux
# or
.\scripts\install-skills.ps1       # Windows PowerShell
```

This lints the repo, then copies every skill into `~/.claude/skills/<name>/` and every agent into `~/.claude/agents/`. The install is personal and global: it works in every repo and every terminal, and you don't need this repo inside your project.

Re-running it is safe. Each skill installed from this repo has a `.from-krishp147-skills` marker file in its directory and is replaced fresh. Agents are copied over the existing files. Leftovers are flagged, never deleted: any `*.md` in `~/.claude/agents/` that is no longer in this repo ("stale agent(s) not in repo, remove manually: …"), since it may be your own, and any marked skill dir under `~/.claude/skills/` that was renamed or removed here ("stale skill(s) not in repo, remove manually: …"). These warnings don't change the exit code.

Skill READMEs are written for GitHub: some of their relative links (e.g. `../../handoff-auto/`) don't resolve in the flat installed copy. That's by design; the model reads only `SKILL.md` and its sibling files, and lint keeps those links working after the install.

The lint step needs a real Python 3 on `PATH` (`python`, `python3`, or — on Windows — `py -3`; a Windows Store Python stub is detected and skipped). No working Python 3 is found → the install fails with a clear message; pass `--no-lint` (sh) / `-NoLint` (ps1) to proceed anyway, with a warning, and skip the lint step.

**Windows: Git Bash is required.** The `guard-git` hook that stops agents from pushing to `main` or merging is a POSIX `sh` command. Without Git Bash, Claude Code can't run it and the hook blocks nothing (it fails open). So the install checks first, before copying anything: `install-skills.ps1` looks at `CLAUDE_CODE_GIT_BASH_PATH`, then `sh`/`bash` on `PATH` (not WSL's `System32\bash.exe`), then `bash.exe` in the Git for Windows install; `install-skills.sh` runs `command -v sh`. Missing → clear error, non-zero exit. Install [Git for Windows](https://git-scm.com/download/win) (or set `CLAUDE_CODE_GIT_BASH_PATH` to its `bash.exe`), or pass `--no-sh-check` (sh) / `-NoShCheck` (ps1) to install anyway, with a warning.

If a directory with the same name as one of this repo's skills already exists under `~/.claude/skills/` but has no `.from-krishp147-skills` marker (i.e. you didn't get it from here), the install leaves it untouched, warns, and exits non-zero at the end so you notice. Pass `--force` (sh) / `-Force` (ps1) to replace it anyway. Upgrading from an install made before the marker existed? Every old skill dir looks foreign, so run once with `--force` / `-Force`.

#### Install one skill

Want just one skill, agent or hook, like `switch`? Name it:

```bash
./scripts/install-skills.sh --list-skills                    # every name and its kind
./scripts/install-skills.sh --skill switch                   # repeat --skill for more
.\scripts\install-skills.ps1 -Skill switch,planner           # Windows PowerShell
```

Anything it needs comes with it, and its README says what that is on the line under the title ("Works on its own." or "Needs: ..."). `--skill` and `--workflow` can be combined; you get both. Everything below about partial installs applies to `--skill` too.

#### Install one workflow

To take only what one [sample workflow](https://www.krishpunjabi.com/skills/workflows) uses instead of everything:

```bash
./scripts/install-skills.sh --list-workflows                 # names and titles
./scripts/install-skills.sh --workflow pair-to-pr            # repeat --workflow for more
.\scripts\install-skills.ps1 -ListWorkflows                  # Windows PowerShell
.\scripts\install-skills.ps1 -Workflow pair-to-pr,paid-tests
```

The workflows are the ones in [`site/data/workflows.json`](site/data/workflows.json); every skill, agent and hook is in at least one. A workflow installs the skills, agents and hooks its steps name, plus what they need: skills an agent preloads, skills a selected skill calls or links into, and the `guard-git` hook whenever an agent is installed ([`scripts/workflow_deps.py`](scripts/workflow_deps.py) works this out). Hooks from [`hooks/`](hooks/README.md) are copied to `~/.claude/hooks/` (`CLAUDE_HOOKS_DIR` to change it) and their `settings.json` snippet is printed; they are never wired in for you. A different file already there is kept unless `--force` / `-Force`.

Nothing outside the selection is touched or warned about: no stale-skill or stale-agent warnings, no other directories changed. Lint, the Git Bash check and the marker / `--force` rules for the selected skills work as above. An unknown name prints the list, exits non-zero and installs nothing. Resolving a workflow needs Python 3, so `--no-lint` doesn't help there: without Python the install stops with an error rather than falling back to installing everything.

## Update

Plugin: `/plugin marketplace update krish`, then restart Claude Code. Install script:

```bash
cd skills
git pull
./scripts/install-skills.sh        # or .\scripts\install-skills.ps1
```

The install copies files rather than symlinking, so a `git pull` alone changes nothing in `~/.claude/` until you re-run the script. An agent removed from the repo stays installed until you delete it; the script's stale-agent warning names it. Open a new Claude Code session afterwards; agents and skills are read at startup.

Prefer to install by hand, or just one skill? Copy the folder yourself:

```bash
cp -r repo-scrub ~/.claude/skills/repo-scrub
cp agents/planner.md ~/.claude/agents/
```

(`.claude/skills/<name>/` or `.claude/agents/` inside a specific repo installs it project-only, for that repo alone.)

For `repo-scrub`, also install its CLI prerequisites:

```bash
# Windows
winget install --id Gitleaks.Gitleaks -e
pip install git-filter-repo
# mac / linux
brew install gitleaks git-filter-repo
```

For anything under `kanban/`:

```bash
gh auth refresh -s project -s read:project
```

## Lint

```bash
python scripts/lint.py
```

Checks every `SKILL.md` and agent file (`agents/README.md` is docs, so lint and install skip it):

- frontmatter is present and `name` matches the folder;
- the description is present and ≤1024 chars (YAML `>`/`|` block scalars are parsed, including a `# comment` after the indicator and more-indented folded lines; a description that is only the indicator fails);
- every skill an agent preloads exists and is model-invocable;
- every relative link in a skill's prompt files resolves.

The install scripts run lint first and stop on failure. Lint also prints non-fatal `WARN:` lines (stderr) for a skill README missing a required section; see [`CONTRIBUTING.md`](CONTRIBUTING.md).

It also checks every tracked file in the repo for forbidden words, so nothing project-specific or personal leaks in. No word list ships in the repo (it would defeat the point). Configure your own locally:

```bash
# untracked repo-root file, one word per line, # comments allowed
echo "acme-internal" > .lint-forbidden.txt
# or a comma-separated env var
SKILLS_LINT_FORBIDDEN=acme-internal,project-codename python scripts/lint.py
```

Neither set → the forbidden-word check is silently skipped.

## Evals

```bash
python scripts/evals.py
```

Validates the trigger and behaviour suites under `evals/` and prints the command to run them. It makes no model calls and runs no subprocess. Cases use the built-in [`claude plugin eval`](https://code.claude.com/docs/en/plugin-evals) format: `evals/<skill>-<case>/prompt.md` (frontmatter + the user prompt) plus `graders/*.md`.

- **Coverage**: every model-invocable skill (found the same way lint finds them, minus `disable-model-invocation: true`) needs 3-5 `trigger` cases and 2-3 `near-miss` cases. A near-miss is a sibling request (`sitrep` vs `progress-report`, `grilling` vs `grill-docs`, `next` vs `divide`) and asserts that skill did not fire.
- **Behaviour**: `repo-scrub` never rewrites history before the rotation gate, `spend-gate` never creates without a yes, `pair` never pushes without `--push` or a yes.
- **Graders**: free computed types only (`regex`, `tool_used`, `tool_order`, `file_exists`). `llm` and `baseline` call a judge model and fail validation.
- A missing suite, a wrong case count, or a malformed grader exits 1.

Running the suite is a real model call on your account, so it is never automatic. Run it by hand from the repo root (needs a plugin manifest at the root):

```bash
claude plugin eval . --runs 1 --ablation none --max-cost-usd 10 --no-publish
```

Behaviour graders check for `Bash` calls, and eval runs get no `Bash` unless you grant it (`--allow-tools Bash`, sandboxed; not on native Windows), so without the grant they only show the skill's reply. Run output lands in `evals/results/`; don't commit it.

## Contributing / grow this repo

Contributions welcome — new skills, fixes, better docs. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the submission format (start from [`templates/skill/`](templates/skill/)) and rules. Feel free to grow it.

## Third-party skills

### Relation to Matt Pocock's skills

Several things here come from [mattpocock/skills](https://github.com/mattpocock/skills) (MIT; notice in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md)). Checked against his repo with the GitHub API on 2026-10-15.

- **Copied unmodified:** `grilling` and `grill-me`. His `skills/productivity/grill-me` and `skills/productivity/grilling` are identical to ours (grilling synced 2026-10-15).
- **Modified:** `handoff` (his saves to the OS temp dir, not the workspace; ours saves under `skilleddocs/handoffs/` and adds a commit-or-not sentence), `handoff-auto` (that, plus its own frontmatter so the model can call it, and a last line printing the path), `wayfinder` (his works any tracker and leaves research on `research/*` branches; ours is GitHub Issues only with sub-issues and native blocking, resolves grilling tickets with `grill-docs`, drops his domain-modeling type, sizes tickets to our ~75K-token smart zone, posts research as a comment, and ends by handing the map to `divide`), and [`dotfiles/CLAUDE.md`](dotfiles/CLAUDE.md) (adapted from his personal global `CLAUDE.md`, not part of that repo; see [My `CLAUDE.md`](#my-claudemd)).
- **Builds on his principles:** how skills here are written follows his [`writing-for-agents`](https://github.com/mattpocock/skills/tree/main/skills/productivity/writing-for-agents) skill and the video linked from [`CONTRIBUTING.md` section 1](CONTRIBUTING.md#1-watch-this-first-mandatory).
- **Divergences:**
  - Our [`meta-orchestrator`](meta-orchestrator/SKILL.md) holds a merge gate and merges to the default branch itself once tests and CI are green (`merge: auto`; `ask` and `pr-only` are the alternatives). In his repo, `implement-spec` merges subagent work into an integration branch and opens a draft PR; I found no step that merges to the default branch.
  - Our [`verifier`](agents/verifier.md) may answer grilling and `consult-plan` questions on your behalf, only when the run is set to `interview: answer` (otherwise it parks them for you), and lists every Q → A under "decided for you" ([`meta-orchestrator/SKILL.md`](meta-orchestrator/SKILL.md), Interviews). His `grilling` always waits for the user's answers.
- **New here:** everything else (`grill-docs`, `pair`, `meta-orchestrator`, the agents, `kanban/`, `spend-gate`, `repo-scrub`, and the rest).
- **Kept in sync weekly:** [`upstream.json`](upstream.json) lists each derived file with its upstream path, mode and the upstream commit last synced. Every Monday (or on demand), the [`upstream-sync`](.github/workflows/upstream-sync.yml) workflow runs [`scripts/upstream_sync.py`](scripts/upstream_sync.py). A verbatim copy that changed upstream gets a PR from `upstream-sync/verbatim`. A modified one gets an issue `upstream-sync: <path>` with the upstream diff since the recorded commit; after porting the change, run `python scripts/upstream_sync.py --mark-synced <path>` (to skip the change, run only that). Only open PRs and issues count as already filed, so closing the issue without `--mark-synced`, or closing the PR unmerged, gets a fresh one on the next run (the branch is force-pushed). If Actions may not open PRs (the repo default), the run instead opens an issue `upstream-sync: verbatim copies` linking the pushed branch, and you open the PR by hand. Each PR/issue step runs even if another fails; the job fails if any did. `dotfiles/CLAUDE.md` is not tracked, since its source is not in that repo. To check by hand, run `python scripts/upstream_sync.py --dry-run`.

`npx skills add mattpocock/skills` pulls his full set directly.

### Relation to DietrichGebert's ponytail

[`ponytail`](ponytail/README.md) is copied verbatim from [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) (MIT; notice in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md)), file `skills/ponytail/SKILL.md` at v5.2.0. Only that core skill is included, not its sibling skills, hooks or statusline. Its `README.md` here is original. It is tracked in [`upstream.json`](upstream.json) and synced weekly like the Pocock copies above.

## My `CLAUDE.md`

[`dotfiles/CLAUDE.md`](dotfiles/CLAUDE.md) is my global Claude Code config, adapted from Matt Pocock's (commit-message style, GitHub CLI first, how I want plans formatted). The branch prefix is left as a `<your-prefix>` placeholder in the tracked file. Install it with:

```bash
./scripts/setup-claude-md.sh merge     # append to your existing ~/.claude/CLAUDE.md
./scripts/setup-claude-md.sh replace   # overwrite/create ~/.claude/CLAUDE.md from scratch
# or, on Windows:
.\scripts\setup-claude-md.ps1 -Mode merge
.\scripts\setup-claude-md.ps1 -Mode replace
```

`merge` just appends with a timestamped separator; it won't dedupe against your existing file, so skim the result afterward.

Pass `--prefix <p>` (sh) / `-Prefix <p>` (ps1) to fill in the branch-prefix placeholder as it's written — e.g. `./scripts/setup-claude-md.sh merge --prefix alex` or `.\scripts\setup-claude-md.ps1 -Mode merge -Prefix alex`. Without it, `<your-prefix>` is left in place and the script prints a hint.

## Author

[Krish Punjabi](https://github.com/KrishP147). Public, MIT; use whatever's useful.

## License

MIT (see [`LICENSE`](LICENSE)) for everything original in this repo. Matt Pocock's skills and Dietrich Gebert's `ponytail` carry their own MIT notices; see [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).
