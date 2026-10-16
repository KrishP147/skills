---
name: score-loop
description: Run an unattended experiment loop that hill-climbs one rerunnable numeric score — local grader-mirroring harness, one hypothesis per commit, keep only gains beyond the noise margin, auto-revert the rest, append-only results ledger; stops on budget, deadline or plateau. Use for "improve this score", "hill-climb a metric", "optimize until plateau/deadline", or "resume" / "status" / "summary" of a score loop.
argument-hint: "[setup | resume | status | summary]"
---

You run **one metric** up (or down) unattended, one hypothesis per commit, and log every experiment to `skilleddocs/experiments.md`. Only for a score you can rerun and that is a number; an unrepeatable or subjective score → say so and stop.

Commands: `setup` (default; also when `experiments.md` has no setup header), `resume`, `status`, `summary`.

## 1. Setup (confirmed once)

1. Fill the header below from the request and the repo; ask only for what's missing. Create the loop branch off the current HEAD.
2. **Harness first.** No local harness that mirrors the grader → write one and commit it before experiment 1. It runs a **correctness check** (pass/fail) and the score **N times**, and prints the median.
3. **Noise margin**: run the baseline N times; propose margin = max − min of those runs.
4. **Calibrate** (after the gate): one official submission of the baseline; record the local–official gap. A gap wider than the margin → fix the harness before experiment 1. No official grader → skip and write `calibration: none (no official grader)`.
5. Freeze time = deadline − max(10% of (deadline − now), 30 min).
6. Gate: show the filled header and each outward action (the calibration submission, the quota, any paid step). One explicit yes covers this setup; anything vaguer is a no. Then write the header, run the calibration, and go unattended.

```
# Score loop: <slug>
- metric: <name>, <higher|lower> is better
- grader: <official grader cmd/URL, or none>
- harness: <local cmd>  (correctness check + median of N=<n>)
- submission: <path or cmd>
- quota: <official submissions pre-approved, or 0 = ask each time>
- spend cap: <amount, or 0>
- deadline: <local datetime, or none>  freeze: <datetime>
- noise margin: <value>  (from <n> baseline runs: <values>)
- calibration: local <x> vs official <y>
- K: 5   parallel: 1
- branch: <prefix>score-loop/<slug>   resume: /score-loop resume

## Ledger
| n | time | commit | hypothesis | local median | official | keep/revert | note |
|---|---|---|---|---|---|---|---|

## Next ideas
- <idea>
```

`<prefix>` is the user's branch prefix with its slash (from their `CLAUDE.md`), or empty. Commit `experiments.md` or leave it untracked per [TRACKING.md](../handoff-auto/TRACKING.md).

## 2. Loop

Per experiment:

1. Pick the most promising idea from **Next ideas**; the list empty → add 3 from what the ledger shows so far.
2. Make one change for that one hypothesis; commit `exp <n>: <hypothesis>`.
3. Run the harness (local runs are ungated).
4. Decide, then append one ledger row:
   - Correctness check fails → `git revert --no-edit <sha>`, `invalid`; not counted toward K.
   - Median beats the best by more than the margin → `keep`; it is the new best.
   - Beats it by the margin or less → `git revert --no-edit <sha>`, `noise`.
   - Worse → `git revert --no-edit <sha>`, `revert`.
5. A failed idea gets one line in Next ideas saying why. The user may append ideas at any time; read the list fresh each experiment.

Ledger rows are append-only: reverted rows stay, a correction is a new row.

**Parallel** (`parallel: N > 1`, opt-in): spawn N subagents, each with its own worktree and branch off the loop branch and one idea. Each runs the harness and returns its median and correctness. One row per variant; merge only the best qualifying variant into the loop branch, then remove the worktrees. Graders that share the machine get noisier: say so at setup.

## 3. Outward actions

- **Official submission**: only inside the setup quota; past it, show the exact submission and wait for an explicit yes. Record the result in the row's `official` column.
- **Paid** (submission, compute, API): through [spend-gate](../spend-gate/SKILL.md), which takes its own yes per action. The spend cap is a ceiling, not approval.
- Push or merge: only on an explicit yes to that push or merge.

## 4. Stops

Check before each experiment:

- **Budget**: the spend cap is reached, or the next experiment would pass it.
- **Deadline**: freeze time reached → no new experiments; rerun the harness on the best commit, show the final submission and submit on a yes, then §5.
- **Plateau**: K consecutive experiments without a `keep` (`invalid` rows don't count).

On any stop: §5, then report why it stopped.

**Context degrading** (smartzone warning, or the ledger no longer fits your head): finish or revert the current experiment, then call `handoff-auto` with "continue the score loop from skilleddocs/experiments.md: /score-loop resume", and stop.

## 5. Summary

From the ledger only, no reruns: kept commits ranked by gain over the best before them, reverted ideas with why, `noise` rows, `invalid` rows, best local and official score. Append it to `experiments.md` under `## Summary <date>` and print it. Ablation reruns only when the user asks.

## Commands

- `resume`: read the header and ledger, switch to the loop branch. A commit at HEAD with no ledger row → evaluate it as that experiment. Recheck the stops, then §2. No new setup gate.
- `status` (read-only): best (commit, local, official), experiment count (kept / noise / revert / invalid), time to freeze and deadline, spend and quota left, next idea.
- `summary`: §5 now.

Backlog of issues instead of one metric → that is `meta-orchestrator`, not this skill; never invoke it from here. Live session status → `sitrep`.
