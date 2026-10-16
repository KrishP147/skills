# Changelog

One line per user-visible change. The top `## ` heading is always the
version in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json);
`scripts/lint.py` fails when they differ. Bump both together.

## [0.1.0] - 2026-10-15

- Installable as a Claude Code plugin: `/plugin marketplace add KrishP147/skills`, then `/plugin install krish@krish`.
- Plugin ships every skill (as `/krish:<skill>`), the four agents (as `krish:<agent>`) and the `guard-git` hook.
- `guard-git` gains `--plugin`: as a plugin hook it guards only the `implementer` and `manager` agents, so your own session can still push. Without Python 3.8+ the plugin hook blocks only those two agents, not your session.
- `pair`, `meta-orchestrator`, `implementer` and `manager` name agents and skill files in a form that works under both installs.
- `scripts/lint.py` checks this file's top version against `plugin.json`.
- Skill evals under `evals/` (trigger, near-miss and behaviour cases in the `claude plugin eval` format); `python scripts/evals.py` validates them and prints the paid run command without running it.
- Sample workflows: a `/workflows` page on the site and a Sample workflows section on each skill page, from `site/data/workflows.json`.
