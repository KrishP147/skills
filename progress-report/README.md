# progress-report

*`SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Turns a run's ledger into a short progress report (1–2 pages) covering **only what happened since the last report** — never overlapping. Markdown by default, `.docx` on request. Every issue/PR/commit reference is a link.

## When to use

- "Make a report", "an update doc", "what's been done", "write up progress".
- Typically during or after a [`meta-orchestrator`](../meta-orchestrator/) run, but works on any long session (reconstructs a ledger if none exists).

## How to invoke

```
/progress-report [reports folder] [docx] [full]
```

- `docx` — Word file instead of Markdown (uses the `docx` skill if available, else `python-docx`).
- `full` — ignore the watermark, cover everything, titled "Full report".

Model-invocable, so asking for "an update doc" works too.

## How it works

1. **Find the source.** Reports folder (default the repo's `skilleddocs/reports/`); ledger at `skilleddocs/orchestrator/ledger.md`. No ledger → reconstructs one from `git log`, merged PRs, issues and the conversation, and says so.
2. **Watermark.** `.last-reported` holds `<NNN> <report filename>`, NNN = last reported ledger entry. The new report covers `watermark + 1 … latest`. Earlier items only reappear under "Revisions to earlier reports" if they changed (revert, reversed decision, broken "done").
3. **Fixed sections:** header (report #, date, time range in your local zone, ledger range), Summary, Done (table), What worked, What didn't, Concerns (ranked, blocking flagged), Decisions made on your behalf, Manual steps for you, Revisions to earlier reports, Next up. Empty → "none".
4. **Link everything.** Resolves the repo URL once; `#n`, `PR #n`, commit hashes and decision ids (if the repo has a decisions doc/ADRs) become links in every section. Checks the link count afterwards.
5. **Write** `NNN-YYYY-MM-DD-<slug>.md` (or `.docx`) in the reports folder; never overwrites an earlier report; reads it back to check.
6. **Advance the watermark:** updates `.last-reported`, appends a `report` entry to the ledger. Prints the path and entry range.

Reads: `skilleddocs/orchestrator/ledger.md`, `.last-reported`, git/gh. Writes: the report, `.last-reported`, a ledger entry.

## Design principles

- **Never overlapping.** A watermark (`.last-reported`) means each report covers only new ledger entries; anything earlier reappears only under "Revisions to earlier reports" when it changed.
- **Readable in two minutes.** Fixed sections, bullets with one idea each, numbers in a table, 1 to 2 pages.
- **Every reference is a link, every time is real.** Issues, PRs, commits and decision ids are linked; times come from the ledger, `git log` or API timestamps in your local zone, never estimated.

## Use cases

- Catching up after a `meta-orchestrator` run you left unattended.
- A periodic update during a long run, each one picking up where the last stopped.
- Writing up a long manual session with no ledger (it reconstructs one from git, PRs, issues and the conversation, and says so).
- A Word document to send to someone else (`docx`).

## Tips

- Use `full` when you want everything in one document regardless of earlier reports; the watermark is ignored for that run.
- Reports are numbered and never overwritten, so the folder is a running history.
- The "Decided for you" and "Manual steps for you" sections are the ones to read first after an unattended run.
- Pass a folder to keep reports outside `skilleddocs/reports/`; its `.last-reported` file lives in that folder.

## Example

```
/progress-report skilleddocs/reports/
```

Watermark says 5; ledger is at 22. Writes `skilleddocs/reports/002-2026-09-23-auth-and-export.md` covering entries 6–22 (Done table with 4 merged PRs, one flaky-CI item under "What didn't", two decisions made on your behalf), sets `.last-reported` to 22, appends a `report` ledger entry, prints the path.

## Related

- [`meta-orchestrator`](../meta-orchestrator/) writes the ledger it reads.
- `docx` skill (optional) for Word output.

## Prereqs

`gh` to resolve the repo URL for links. For `docx`: the `docx` skill or `python-docx`.
