---
name: progress-report
description: Write a short progress report of what an orchestrated or long session did since the last report (never overlapping): done, what worked, what didn't, concerns, decisions made for the user, manual steps. Use for "update doc", "what's been done", "write up progress".
argument-hint: "[reports folder] [docx] [full]"
---

A document the user reads in two minutes.

## 1. Range

- **Folder**: the one given, else `skilleddocs/reports/`.
- **Ledger**: `skilleddocs/orchestrator/ledger.md` (older runs: `ledger.md` in the folder). None → reconstruct from `git log`, merged PRs, issues, and this conversation, and say so in the report.
- **Watermark**: `.last-reported` in the folder, one line `<NNN> <report filename>` (e.g. `007 002-2026-10-16-x.md`). NNN = last ledger entry reported. No ledger → NNN = the last reported commit SHA instead. No file → report 001, covers everything.

**No overlap**: cover entries `watermark+1 … latest` (no ledger: commits after the SHA). Ledger present → also scan `git log` and merged PRs since the watermark's time; work with no ledger entry goes in the report marked "not in ledger". Something already reported that later changed (revert, reversed decision, broken "done") goes under *Revisions*, citing the earlier report. `full` → ignore the watermark; title it "Full report".

## 2. Sections (this order; an empty one says "none")

- **Header**: `Progress report NNN · <date> · covers <start> → <end> (<zone>, ledger NNN–MMM)` + repo/branch + previous report. No `#` before the number (reads as an issue ref).
- **Summary**: 3–6 bullets.
- **Done**: table, Issue · Title · PR · Tests · CI.
- **What worked** / **What didn't** (each with what was done about it).
- **Concerns**: ranked, blockers marked.
- **Decided for you**: `Q → A · reason · where it landed`, reversible.
- **Assumed decisions open**: `A-n` from ledger `assumption` entries / decision record, still unconfirmed.
- **Manual steps for you**: numbered.
- **Revisions to earlier reports**.
- **Next up**: 2–4 bullets.

Bullets, one idea each, numbers in the table, 1–2 pages. Times in the user's local zone, taken from the ledger, `git log --date=format-local`, or API UTC timestamps via `datetime.fromisoformat(s).astimezone()`; zone: reuse the one named at the top of the ledger, else run `python -c "import datetime as d; n=d.datetime.now().astimezone(); z=n.tzname(); print(z if ' ' not in z else n.strftime('UTC%z'))"` (abbreviation on Unix, UTC offset on Windows). Never estimated or offset by hand.

## 3. Links

Resolve the repo URL once: `gh repo view --json url -q .url`. Link every reference in every section with **one left-to-right pass** over each paragraph and cell, one combined regex, alternatives tried in this order at each position:

1. existing markdown link `[..](..)` or `<url>` → copy unchanged
2. inline code span → copy unchanged
3. `PR #n` → link "PR #n" to `<repo>/pull/n`
4. `#n` → link "#n" to `<repo>/issues/n`
5. hex sha, 7–40 chars of `[0-9a-f]` with at least one a–f letter, word-bounded → link "<first 7>" to `<repo>/commit/<full>`
6. `D<k>`/`A-<k>`/ADR id → anchor in the decisions file, if one exists

Never link: heading lines (start `#`, incl. the report header), decimal-only tokens (CI run ids). Never re-scan output. Then check link count ≥ the `#n` mentions in the ledger range.

## 4. Write

`NNN-YYYY-MM-DD-<slug>.md` in the folder (local date; never overwrite). `docx` → same name `.docx`, via the `docx` skill or `python-docx`: heading styles, real bullets, a Done table, real hyperlinks. Read it back once to check nothing's empty.

## 5. Advance

Write `.last-reported` (`<NNN> <filename>`; no ledger → last reported SHA), append a ledger `report` entry with the range (no ledger → skip it and say so), and print the report path + range.
