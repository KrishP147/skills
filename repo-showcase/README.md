# repo-showcase

*`SKILL.md` is the prompt Claude follows; this file is for you.*

Needs: `handoff-auto` (installed with it).

## What it does

Gets a repo's working tree ready to be seen.

- Rewrites the README around outcome and demo.
- Prunes stale or internal-only docs.
- Fixes claims the code has quietly outdated.
- Scans for secrets and private names.
- Proposes GitHub metadata (description, topics, homepage).
- It never touches git history or repo visibility — it ends by handing off to [`repo-scrub`](../repo-scrub/README.md) for that.

## When to use

- "Make this repo public-facing", "showcase this repo".
- "Polish the README for public", "get this ready to open-source".
- "Prep this repo for a portfolio/public link".
- Not for the history scan or the private → public flip — that's [`repo-scrub`](../repo-scrub/README.md), invoked separately once this skill's work is committed.

## How to invoke

```
/repo-showcase [owner/repo]
```

Defaults to the current repo. Claude also runs it when you say one of the phrases above.

## How it works

1. **Ask up front, one batch** — outcome, audience, what to emphasize, each with a recommended default; proceeds on the answers or the defaults.
2. **Inventory docs** — every tracked doc in the repo into a keep / merge / delete table with a reason per row.
   - Untracked docs are listed separately as not shipped.
   - Nothing deleted or merged without an explicit yes.
3. **Grep claims against reality**
   - A missing `LICENSE` is flagged and gated (you choose; it never picks one).
   - A license already declared in `package.json`/`pyproject.toml` counts as your pick, and it offers to add the matching file.
   - Every factual claim in the README/docs is checked against the actual code, config, and `git log`.
   - Contradictions are reported as `file:line` (claim) plus `file:line`/commit (evidence).
4. **Rewrite the README, lean by default** — the pieces:
   - One-line pitch.
   - Result.
   - Demo media placeholder(s) the user fills in themselves (never a fabricated screenshot/GIF/metric).
   - Quickstart, actually run from a clean clone. Installs go in a temp prefix or venv, never global, and never by registry name unless that registry entry's repository URL is this repo.
   - The quickstart result is reported; a step whose toolchain isn't installed on this machine is reported `not run: <tool> missing` and kept, never dropped.
   - Architecture only if the audience needs it.
   - Credits.
5. **Scan for secrets and private names**
   - Secrets in tracked files only: key/token/connection-string patterns, un-ignored `.env` files, `gitleaks dir .`.
   - Emails or person names that aren't authors or already public: found with an email grep, then by reading comments and docs (including docs about to be deleted). They are reported as `file:line` and redacted only on yes.
   - Also emails in commit messages and author/committer identities (`git log --all`), minus your own. For other people's identities you choose: rewrite, or "author identities stay".
   - Every such string is kept for the hand-off.
6. **Propose GitHub metadata** — description/topics/homepage, shown as the exact `gh repo edit` command, applied only on yes; no GitHub remote means the command is printed and skipped.
7. **Gate.** Shows the diff summary.
   - Commits (small, one logical change each) only on yes, on a new branch in a separate worktree, so your checkout, WIP and untracked files are never touched.
   - Asks first when a file it changes also holds your WIP.
   - Pushes only on a separate yes.
8. **Hands off to `repo-scrub`** — states plainly that history scanning and the visibility flip happen there, not here.
   - Asks you to merge or push its branch first (otherwise repo-scrub's post-push reset rebases it into a conflict).
   - Passes it every personal string found (redacted, from deleted docs, or only in history) and your identity choice, so they are scrubbed from history too (gitleaks doesn't look for names or emails).
9. **Writes the report** — the doc inventory, contradicted-claims list, and secret/name findings (plus what was done about each) to `skilleddocs/showcase/<local-date>.md`, uncommitted unless asked.

## Design principles

- **Never touches visibility or history.** Those are hard to undo and belong to a dedicated, more careful skill (`repo-scrub`); this one only prepares the working tree.
- **Nothing invented.** Demo media, metrics, and architecture diagrams are placeholders for the user to fill in — never fabricated to make the README look more finished than the repo is.
- **Every outward action gated.** Deletes, redactions, metadata edits, commits, and pushes each need an explicit yes; a diff is always shown first.

## Use cases

- Open-sourcing an internal tool: clean the README and docs before anyone outside the team sees them.
- A portfolio repo whose README has drifted from what the code actually does.
- Before running `repo-scrub`, so the history scan and visibility flip start from an already-honest working tree.

## Tips

- No strong opinions on the step 1 questions? Say "go". The recommended defaults are reasonable starting points, not filler.
- The contradicted-claims grep (step 3) is worth running even if you're not ready to rewrite the README yet — it surfaces drift on its own.
- Run this before `repo-scrub`, not after — a clean working tree makes the history scan's findings easier to read.

## Example

```
/repo-showcase myorg/tool
```

- Asks outcome/audience/emphasis, gets "go" (defaults accepted).
- Inventories 6 docs (keeps 4, merges 1, deletes 1 stale plan doc on yes).
- Finds the README claiming "Python 3.8+" against `pyproject.toml`'s `>=3.11`.
- Rewrites the README with a pitch, a screenshot placeholder, and a corrected quickstart.
- Finds no secrets but one teammate's email in a config comment, redacted on yes.
- Proposes a description and two topics, applied on yes.
- Shows the diff, commits on a branch on yes, pushes on a second yes.
- Writes `skilleddocs/showcase/2026-09-26.md`.
- Ends by pointing at `/repo-scrub` for the history scan and visibility flip.

## Related

- [`repo-scrub`](../repo-scrub/README.md) — the next step: full git-history scan and the private → public flip. This skill never does either.
- [`gap-scan`](../gap-scan/README.md) — surveys repos and ranks gaps; a good way to pick which repo to showcase next.
- [`teammate-brief`](../teammate-brief/README.md) — human-facing handoff; the internal counterpart to a public README.

## Prereqs

`gh` for the metadata proposal step (step 6). None otherwise.
