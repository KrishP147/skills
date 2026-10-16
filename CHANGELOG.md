# Changelog

One line per user-visible change. The top `## ` heading is always the
version in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json);
`scripts/lint.py` fails when they differ. Bump both together.

## [0.1.0] - 2026-10-15

- Plugin `homepage` and README site link point at https://www.krishpunjabi.com/skills (canonical host; the apex form redirects).
- `spend-guard` also blocks `runpodctl serverless|sls run`, the `sls` alias for create/update, `pod update` with `--volume-in-gb`/`--container-disk-in-gb`, `model add`, global flags before the noun (`--profile x pod create`), and MCP `update-pod` with `volumeInGb`/`containerDiskInGb`.
- Install scripts warn (never delete) on installed skill dirs with the marker that are no longer in the repo ("stale skill(s)"); exit code unchanged.
- `session-bridge` snapshot: LAST USER ASK skips reminders, tool results and agent relays (slash commands shown as `/name args`); Agent/Skill/WebFetch actions labelled; secrets redacted before truncation.
- `spend-guard` default patterns also match `.exe`/`.cmd`, quoted and full-path CLI forms (e.g. `& "C:\...\runpodctl.exe" create`).
- `spend-guard` also covers the PowerShell tool (inline `$env:SPEND_GATE_APPROVED='x';` approval) and more Runpod MCP tools (job submits, endpoint updates, pod start).
- `spend-guard` also blocks `runpodctl start`/`pod start`, noun-first creates (`pod|serverless|network-volume create`), `serverless update`, and network-volume resize (`--size` flag or MCP `update-network-volume` body with `size`).
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
