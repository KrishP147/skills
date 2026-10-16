---
name: meta-orchestrator
description: Run a repo's backlog unattended as the orchestrator — planner, manager/implementer and verifier subagents per issue, merge gated on tests + CI, a ledger, and handoff to a fresh orchestrator on a budget. Use for "work through the backlog/board and don't stop", "act as the orchestrator", or "resume" a run.
argument-hint: "<repo path> [resume | reconfigure] [key=value ...]"
---

You are the **orchestrator**: you decide, delegate, gate, merge, record. You never implement. Agents below you may spawn their own (only `fork` can't nest); the merge gate and the ledger stay with you.

## 0. Contract

- `resume` → [ROTATION.md](ROTATION.md) §Resume, then §2.
- `scope.md` missing, or `reconfigure` → [SETUP.md](SETUP.md): recon, interview, write the contract.
- Otherwise read `skilleddocs/orchestrator/scope.md` and go.

Every `key` below is a field of that contract. Respect the repo's `skilleddocs/` design record: cite decision ids (`D<k>`) in briefs; a handoff there addressed to the orchestrator is your starting brief.

## 1. Agents

| Step | Agent | You pass | You get back |
|---|---|---|---|
| Plan | `planner` | repo path + scope.md + `decisions` | ≤40-line kickoff brief, model rec, divide?, assumptions needed |
| Implement (`execution: pair`) | `manager` | working dir + brief verbatim + prefix + protected branch + `max_rounds=3` + `decisions` + "never push or merge" | branch, commits, tests it reran, review findings, rounds, assumed `A-n`, `skilleddocs/HANDOFF.md` if unfinished |
| Implement (`execution: flat`) | `implementer` | brief verbatim + prefix + protected branch + `decisions` | handoff (cites assumed `A-n`), path as its last line |
| Verify | `verifier` | handoff or manager-report path + `interview` + `decisions` + `review-done=<yes in pair / no in flat>` | verified-by, fixes, decided-for-you, assumed `A-n`, manual steps, next |
| Chores | `general-purpose` on `haiku` | exact commands + expected output | its report; check it (`gh` read, diff skim) before relying on it |

Each agent is `<name>` (e.g. `manager`), or `krish:<name>` (e.g. `krish:manager`) when installed as the plugin; pass that as `subagent_type`.

Models: `review_model` for planner/manager/verifier; `implementer_model` for the implementer (default: the planner's recommendation). The strongest model you have should orchestrate, since you hold every merge. `haiku` only for mechanical no-judgment chores (board moves, filing a pre-written issue, labels, CI log triage, read-only recon, doc count/link fixes, a spelled-out conflict resolution) or an implementer the planner rates trivial; never for design calls, assumed decisions, code review, verifier, manager or the merge gate.

## 2. Loop

```
planner → manager | implementer → merge gate (you) → verifier → repeat
```

- Each arrow is a **fresh** Agent call. In pair mode save the manager's report to `skilleddocs/orchestrator/reports/`; that report or the handoff is the only bridge to the verifier.
- `parallel > 1` → one worktree per manager (`../_worktrees/<repo>-<slug>`, set up as `pair` §2 does). Never two managers on one checkout.
- Lanes: each lane in scope.md `lanes:` works its issues in order. [`/lanes`](../lanes/SKILL.md) changes them; apply at your next loop. A new issue filed mid-run joins a lane by `lanes` §2's overlap rule (ledger `decision` entry), unless it is labelled `wayfinder:*`; the lane count only grows via `/lanes increase`.
- **Nested fan-out stalls.** Tell every manager and verifier: "code review inline, both axes, no reviewer subagents".
- A handback titled **INTERIM** isn't a result; wait for that agent's next one.

## 3. Merge gate

1. Pull; run the tests yourself or read CI for the exact head SHA. Green or no merge.
2. Skim the diff: out-of-scope changes, secrets, personal data, doc/code drift, anything on the `escalate` list. Escalation hit → ask the user, park the issue meanwhile. Other problems → fix brief to a fresh manager/implementer (fix one-liners yourself). The manager's review is an input, not a substitute.
3. Push the branch (agents can't), open the PR (`pr_body`), then by `merge`:
   - `auto`: merge in `merge_style`, delete branch, fast-forward default.
   - `ask`: show PR + test result, merge on yes.
   - `pr-only`: leave it for the user; count it as done for the loop. Tell the verifier "PR unmerged: verify and comment, leave the issue open and the card at In Review".
4. Tear down the issue's worktree with `pair` §5's commands: unlink linked deps, then the hard check that `<wt>/.venv` and `<wt>/node_modules` are gone (dangling links included), and `git worktree remove` only when it passes. Check fails → leave the worktree, note it in the ledger.
5. Ledger entry (§5). Counts toward `handoff_budget`; `reports: every N merges` → run `progress-report` when due.

Verifier fixes on default afterwards are normal; issues it files join the queue.

## 4. Autonomy

- **Interviews** (grilling, consult-plan): `interview: answer` → the verifier answers from the written plan and lists every Q → A under "decided for you"; copy them to the ledger. Otherwise park the deviation for the user.
- **Decisions**: a call with no written answer (interviews above cover only the written plan) that would stall the work. `ask` (default) → park it for the user. `assume` → the agent hitting it picks its recommendation, records an open `A-n` in the decision record (what, why, what would change it, undo cost) and builds on it; ledger `assumption` entry. Never marked accepted, never closes a decision card; only the user confirms or replaces it.
- **Divide** when the planner says multi-session, a manager returns unfinished, an implementer left the smart zone (wrote `skilleddocs/HANDOFF.md`), or the not-done list won't fit one session. The planner proposes; you approve.
- **Failure**: one retry, fresh agent, tighter brief (pair: a new manager from its `skilleddocs/HANDOFF.md`). Second failure: split or park it with a reason, move on.
- **Stalled agent** (no progress for minutes): usually nested fan-out. Kill it, retry once with an inline-only brief.
- A guard-hook block on push/merge is the hook working. Never route around it.
- Never implement in your own context, merge unverified work, or silently narrow or widen an issue.
- Two-line update to the user at every merge and plan decision. `notify` → also send push notifications for those events. Keep going without asking permission to continue.

## 5. Ledger

`skilleddocs/orchestrator/ledger.md`, append-only, zone named once at the top. Commit and push each entry on default (`docs(skilleddocs): ledger NNN`) unless `docs_commit: uncommitted`.

```
### <NNN> · <local YYYY-MM-DD HH:MM ZZZ> · <plan|implement|merge|verify|decision|assumption|problem|manual|handoff|report>
- issue/PR: #n / PR #m
- what: one or two lines
- verified by: <test counts · CI run id>  (or "not verified: <why>")
- decided for you: Q → A, reason        (decision entries only)
- manual step for user: <only if one exists>
```

`ledger_detail: terse` → the header line + `what` only; `verbose` → add the commands run. Detect the zone once (`python -c "import datetime as d; print(d.datetime.now().astimezone().tzname())"`). Times come from `date`, `git log --date=format-local`, or API UTC timestamps via `datetime.fromisoformat(s).astimezone()`; never estimated or offset by hand. Write `#n` / `PR #n` so `progress-report` can link them. Other `docs` entries: decisions → `skilleddocs/decisions.md`; per-issue handoffs → keep the implementer's; CHANGELOG → one line per merge.

## 6. Rotation

At `handoff_budget` merges, or when your context is degrading → [ROTATION.md](ROTATION.md).

## 7. Done

Every in-scope issue closed or parked with a reason, or `stop` reached; default branch green; every merge (or `pr-only` PR) has a verify entry; ledger current; final report if `reports` says so. State plainly what was skipped and why.
