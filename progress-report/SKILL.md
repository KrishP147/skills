---
name: progress-report
description: Write a short progress report of what an orchestrated or long session did since the last report (never overlapping): done, what worked, what didn't, concerns, decisions made for the user, manual steps. Use for "update doc", "what's been done", "write up progress".
argument-hint: "[reports folder] [docx] [full]"
---

A document the user reads in two minutes.

## 1. Range

- **Folder**: the one given, else `skilleddocs/reports/` (untracked → exclude `skilleddocs/` per [TRACKING.md](../handoff-auto/TRACKING.md)).
- **Ledger**: `skilleddocs/orchestrator/ledger.md` (older runs: `ledger.md` in the folder). None → reconstruct from `git log`, merged PRs, issues, and this conversation, and say so in the report.
- **Watermark**: `.last-reported` in the folder = last ledger entry reported + that report's filename. None → report #1, covers everything.

**No overlap**: cover entries `watermark+1 … latest`. Something already reported that later changed (revert, reversed decision, broken "done") goes under *Revisions*, citing the earlier report. `full` → ignore the watermark; title it "Full report".

## 2. Sections (this order; an empty one says "none")

- **Header**: `Progress report #N · <date> · covers <start> → <end> (<zone>, ledger NNN–MMM)` + repo/branch + previous report.
- **Summary**: 3–6 bullets.
- **Done**: table, Issue · Title · PR · Tests · CI.
- **What worked** / **What didn't** (each with what was done about it).
- **Concerns**: ranked, blockers marked.
- **Decided for you**: `Q → A · reason · where it landed`, reversible.
- **Assumed decisions open**: `A-n` from ledger `assumption` entries / decision record, still unconfirmed.
- **Manual steps for you**: numbered.
- **Revisions to earlier reports**.
- **Next up**: 2–4 bullets.

Bullets, one idea each, numbers in the table, 1–2 pages. Times in the user's local zone, taken from the ledger, `git log --date=format-local`, or API UTC timestamps via `datetime.fromisoformat(s).astimezone()`; zone from `python -c "import datetime as d; print(d.datetime.now().astimezone().tzname())"`. Never estimated or offset by hand.

## 3. Links

Every reference in every section is a link (resolve the repo URL once: `gh repo view --json url -q .url`): `#n` → `/issues/n`, `PR #n` → `/pull/n`, 7–40-char hex → `/commit/<sha>`, `D<k>`/ADR ids → the decisions file if one exists. Short link text, no bare URLs; leave existing links and code spans alone. Do it in one helper applied to every paragraph and cell, then check link count ≥ the `#n` mentions in the ledger range.

## 4. Write

`NNN-YYYY-MM-DD-<slug>.md` in the folder (local date; never overwrite). `docx` → same name `.docx`, via the `docx` skill or `python-docx`: heading styles, real bullets, a Done table, real hyperlinks. Read it back once to check nothing's empty.

## 5. Advance

Write `.last-reported` (latest entry + filename), append a ledger `report` entry with the range, and print the report path + range.
