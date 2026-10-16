# Changelog

One line per user-visible change. The top `## ` heading is always the
version in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json);
`scripts/lint.py` fails when they differ. Bump both together.

## [0.1.0] - 2026-10-15

- Docs fixes from batch-4 testing (#148): `lanes` file sets keep only where a change lands, uncertain-area rule and an unbounded-issue `serial` lane; rotation resume resets `handoff_budget` but not per-run `stop: after N merges`; implementer wording no longer claims it cannot local-merge; verifier states git facts only from its own commands; manager handles Agent tools with no foreground mode (no fabricating, no sleep-poll, notification wakes it).
- `progress-report`: one-pass link rule (headings, code spans, existing links and decimal CI run ids left alone; no `PR #n` double links), `Progress report NNN` header, `.last-reported` is `<NNN> <filename>`, un-ledgered git work is reported as "not in ledger", and the zone prints a UTC offset on Windows.
- `pair`/`meta-orchestrator`: Windows `.venv`/`node_modules` link and teardown commands work from Git Bash and PowerShell; a hard check stops `git worktree remove` while a dep link (dangling included) remains.
- Agents: manager, implementer and verifier honour `decisions=assume` (open `A-n` recorded and reported); planner README lists **Assumptions needed**.
- `meta-orchestrator`: `decisions: ask|assume` (assume = agent picks its recommendation, logs open `A-n` until you confirm; shown in handoffs and `progress-report`) and a `haiku` chores tier for mechanical no-judgment tasks.
- `upstream-sync`: when the PR can't be opened, files an issue linking the `upstream-sync/verbatim` branch; a failed step no longer skips the modified-file issues, and the run fails only after trying every step.
- CI runs `install-skills.sh` and `install-skills.ps1` into fresh temp dirs (ubuntu, plus `.ps1` on windows-latest) and checks skill, agent and marker counts.
- Plugin `homepage` and README site link point at https://www.krishpunjabi.com/skills (canonical host; the apex form redirects).
- `spend-guard` also blocks `runpodctl serverless|sls run`, the `sls` alias for create/update, `pod update` with `--volume-in-gb`/`--container-disk-in-gb`, `model add`, global flags before the noun (`--profile x pod create`), and MCP `update-pod` with storage keys (v2 `disk`, `mounts.persistent`, `templateId`; v1 `volumeInGb`/`containerDiskInGb`). Global-flag prefix parses linearly (a long flag run no longer backtracks exponentially) and also matches `--x=-1`, quoted values, `--`, and hyphenated profile names like `serverless-prod`.
- Install scripts warn (never delete) on installed skill dirs with the marker that are no longer in the repo ("stale skill(s)"); exit code unchanged.
- `session-bridge` snapshot: LAST USER ASK skips reminders, tool results and agent relays (slash commands shown as `/name args`); Agent/Skill/WebFetch actions labelled; secrets redacted before truncation.
- `spend-guard` default patterns also match `.exe`/`.cmd`, quoted and full-path CLI forms (e.g. `& "C:\...\runpodctl.exe" create`).
- `spend-guard` also covers the PowerShell tool (inline `$env:SPEND_GATE_APPROVED='x';` approval) and more Runpod MCP tools (job submits, endpoint updates, pod start).
- `spend-guard` also blocks `runpodctl start`/`pod start`, noun-first creates (`pod|serverless|network-volume create`), `serverless update`, and network-volume resize (`--size` flag or MCP `update-network-volume` body with `size`).
- `score-loop`: freeze lead capped for short deadlines (setup refuses if one experiment doesn't fit), noise margin relative to the best, harness must defeat caching, `## Tried` list apart from Next ideas, summary ranks kept commits by relative gain.
- Installable as a Claude Code plugin: `/plugin marketplace add KrishP147/skills`, then `/plugin install krish@krish`.
- Plugin ships every skill (as `/krish:<skill>`), the four agents (as `krish:<agent>`) and the `guard-git` hook.
- `guard-git` gains `--plugin`: as a plugin hook it guards only the `implementer` and `manager` agents, so your own session can still push. Without Python 3.8+ the plugin hook blocks only those two agents, not your session.
- `pair`, `meta-orchestrator`, `implementer` and `manager` name agents and skill files in a form that works under both installs.
- `scripts/lint.py` checks this file's top version against `plugin.json`.
- Skill evals under `evals/` (trigger, near-miss and behaviour cases in the `claude plugin eval` format); `python scripts/evals.py` validates them and prints the paid run command without running it.
- Sample workflows: a `/workflows` page on the site (also `/workflows` in the slash prompt) and a Sample workflows section on each skill page, from `site/data/workflows.json`.
- Skills map: a `/map` page on the site (also `/map` in the slash prompt) grouping every skill, agent and hook, with arrows built from Related links, agent preloads and the sample workflows.
- New `wayfinder` skill (adapted from Matt Pocock's): plans an effort too big for one session as a `wayfinder:map` issue of decision tickets, then hands off to `divide`; `next` and `planner` skip `wayfinder:*` issues.
- `find-me-a-skill`: suggests the skill or workflow for a task with model and effort per step, from a generated `CATALOG.md`; site pages show a "suggested model · effort" chip.
- New `score-loop` skill: hill-climbs one rerunnable numeric score unattended, one hypothesis per commit, keeping only gains beyond a measured noise margin and `git revert`ing the rest, with a results ledger in `skilleddocs/experiments.md`; stops on budget, deadline freeze or plateau.
