# Setup: the run contract

First run on a repo, or `reconfigure`. Output: `skilleddocs/orchestrator/scope.md`, the contract every later step and every resumed orchestrator obeys.

## 1. Recon (read-only)

- Contributing guide, `CLAUDE.md` / `AGENTS.md`, `skilleddocs/` (decisions, grills, handoffs: the design record).
- Skills the repo names exist (repo `.claude/skills/` wins over `~/.claude/skills/`). The `planner`, `manager`, `implementer`, `verifier` agents exist (`~/.claude/agents/*.md`, or `krish:<agent>` from the plugin); missing → tell the user to run the skills repo's install script or install its plugin, meanwhile use `general-purpose` with the same model and brief.
- Branches with unpushed commits, open issues and PRs, last CI on default, untracked personal files (never commit them; offer to gitignore).
- Repo's merge style (recent merge commits vs squash), test command, default branch, the user's branch prefix.

## 2. Resolve defaults

Later layers override earlier ones:

1. Built-in defaults (table below).
2. `~/.claude/orchestrator-defaults.md`, the user's saved preferences, if it exists.
3. The repo's `AGENTS.md` / `CLAUDE.md` rules.
4. Arguments passed to this run.

Any key settled by layers 2–4 is not asked again.

## 3. Interview

Use the AskUserQuestion tool when available (≤4 questions per call, recommended option first and labelled "(Recommended)"); else numbered questions in one message. Recon facts are yours to find; only decisions go to the user.

**Round 0**: one question: show the resolved contract as a compact table, ask "Use these, or customize?". "Use these" → skip to "Write the contract" below. Customize → rounds 1–4, skipping keys already settled.

| Round | Keys |
|---|---|
| 1. Run shape | `scope`, `exclude`, `stop`, `execution`, `parallel` + `lanes` (run the [`lanes`](../lanes/SKILL.md) grouping on the queue instead of asking a bare number) |
| 2. Control | `merge`, `merge_style`, `pr_body`, `interview`, `decisions`, `escalate` |
| 3. Documentation | `docs`, `docs_commit`, `reports`, `report_format` + `ledger_detail` |
| 4. Models and pacing | `implementer_model`, `review_model`, `handoff_budget`, `notify` |

`order`, `prefix` and `timezone` come from recon (shown in Round 0) unless the user changes them. Then one batch for anything recon left unclear (stray branches, issues that look gated or need a human). Ask again later only for destructive or scope-changing calls.

## Keys

| Key | Options (default first) | Effect |
|---|---|---|
| `scope` | all open issues · label filter `<label>` · explicit list `#a #b` | what the planner may pick |
| `exclude` | gated / people / external-input issues · custom labels | planner drops these; `wayfinder:*` issues are always excluded (planning tickets, worked only via `/wayfinder`) |
| `order` | priority label → board order → oldest · roadmap order · explicit | planner's ordering |
| `stop` | queue empty · after N merges (per run, not reset on resume) · after a time box | when SKILL.md §7 "done" applies |
| `execution` | `pair` · `flat` | manager per issue, or implementer directly |
| `parallel` | 1 · the count [`lanes`](../lanes/SKILL.md) proposes (file-disjoint groups of the queue) | concurrent issues, one worktree per lane; `lanes:` maps each named lane to its issues |
| `target_repo` | `origin`'s repo · on a fork, asked: the fork or the parent (the parent only on an explicit yes naming it) | every `gh` write (issues, cards, PRs); per the `next` skill's `BOARD.md`, Target repo section |
| `merge` | `auto` when the gate is green · `ask` before each merge · `pr-only` (open PRs, user merges) | SKILL.md §3 step 3 |
| `merge_style` | repo's existing style · squash · merge commit · rebase | how PRs land |
| `interview` | `answer` (agents answer for me from the written plan) · `park` (deviations wait for me) | verifier + consult-plan |
| `decisions` | `ask` (park calls with no written answer) · `assume` (agent picks its recommendation, records open `A-n` for me to confirm) | SKILL.md §4; briefs carry `decisions=` |
| `escalate` | multi-select: new dependency · schema/migration · deleting files · public API change · CI/config change · anything billable (always on) | pause and ask before merging such a change |
| `docs` | multi-select: ledger (always on) · decisions register · per-issue handoffs · manager reports kept · CHANGELOG entries | what gets written under `skilleddocs/` |
| `docs_commit` | `commit` (on default as written) · `uncommitted`; default per [TRACKING.md](../handoff-auto/TRACKING.md), forced `uncommitted` on a fork | where the paper trail lives |
| `reports` | `handoff` · `every N merges` · `end` · `on-request` | when `progress-report` runs |
| `report_format` | markdown · docx | progress-report output |
| `ledger_detail` | `standard` · `terse` · `verbose` | ledger entry size |
| `pr_body` | summary + `Closes #n` · detailed (changes, tests, risks) | PR descriptions |
| `implementer_model` | `planner` (its recommendation) · `sonnet` · `opus` | implementer model |
| `review_model` | opus · sonnet | planner, manager, verifier |
| `handoff_budget` | 10 merges · 5 · 20 · custom | rotation point (ROTATION.md) |
| `notify` | `none` · `blockers` · `all` (blockers + merges + finish) | needs the PushNotification tool |
| `prefix` | from the user's `CLAUDE.md`, else `feat` | branch prefix |
| `timezone` | machine's zone | ledger timestamps |

## 4. Write the contract

`skilleddocs/orchestrator/scope.md`: repo path, default branch, then every key above as `key: value` in a fenced `yaml` block, then free-text notes (exclusion reasons, who answers what). Commit it on the default branch: `docs(skilleddocs): orchestrator scope`. Lanes set by [`lanes`](../lanes/SKILL.md) → also start the ledger (SKILL.md §5) with its `decision` entry as 001 (`lanes` §5 step 2), committed with scope.md. (`docs_commit: uncommitted` → leave it untracked and git-excluded per TRACKING.md; the ledger then lives only on this machine. Say so.)

## 5. Offer to save as defaults

Ask once: "Save these as your defaults for future runs?" On yes, write the non-repo-specific keys (everything except `scope`, `exclude`, `order`, `prefix`) to `~/.claude/orchestrator-defaults.md` in the same yaml form. Never write it without a yes.
