---
name: repo-showcase
description: Make a repo public-facing on its working tree — README rewritten around outcome and demo, stale docs pruned, outdated claims fixed, secrets and private names found, GitHub metadata proposed — then hand off to /repo-scrub. Use for "showcase this repo", "polish the README for public", "prep for open-source or portfolio".
argument-hint: "[owner/repo] (default: current repo)"
---

Working tree only. History and visibility belong to `/repo-scrub`. **Gate**: every redaction, README rewrite, metadata change, commit, and push needs an explicit yes.

## 1. Ask (one batch, each with its default)

1. **Outcome**: what a stranger should do after reading (default: try it in under 5 minutes).
2. **Audience** (default: developers deciding whether to use or contribute).
3. **Emphasis**: the one thing worth a look (default: the latest merged feature or current headline claim, confirmed rather than invented).

"go" → defaults.

## 2. Doc inventory

Every tracked doc (`README*`, `docs/**`, `CONTRIBUTING*`, stray notes): table Path · keep / merge / delete · reason. Untracked docs are listed separately as `not shipped` and never rewritten or published. Act on rows only after a yes, echoed back.

## 3. Claims vs reality

Check every factual claim (languages, versions, install steps, commands, badges, "beta", architecture) against code, config and `git log`. Report `claim file:line` — `evidence file:line or SHA`. These feed §4 and the diff gate.

**License**: no `LICENSE*` file → flag it here and gate it. Offer the user the choice (name a few common ones); never pick one for them, and don't name a license in the README until they have.

## 4. README draft (lean)

1. One-line pitch. 2. Result: what using it produces. 3. Demo slot: `<!-- screenshot/GIF: paste path or URL -->` for the user to fill; media and metrics are never fabricated. 4. Quickstart, actually run: in a scratch venv or a clean clone (`git clone . "$(mktemp -d)/x"`; a working tree with an untracked `skilleddocs/` can break `pip install .`, see [TRACKING.md](../handoff-auto/TRACKING.md)), execute each quickstart command and report pass/fail with the output; fix or drop what fails. 5. Architecture, only if the audience needs it. 6. Credits and license.

Draft only; the file changes at §7.

## 5. Secrets and private names

Tracked files: key/token/connection-string patterns (`gitleaks dir .` if installed), un-ignored `.env`. Personal names: grep for email addresses, then read comments and docs for person names; flag any that aren't authors (`git shortlog -sne`) or already public. Report `file:line`; redact per item on yes.

## 6. Metadata

Propose description, topics, homepage; show `gh repo edit <o/r> --description "…" --add-topic … --homepage …`; run on yes. No GitHub remote (`git remote -v` shows none, or a non-GitHub host) → print the command for later and skip.

## 7. Gate: diff, commit, push

Show the full README diff plus one line per doc change and redaction. Commit on yes, on a branch, one logical change per commit (`docs: rewrite README for public release`). Push on a separate yes.

## 8. Hand off and record

Next step: `/repo-scrub` for the history scan and the visibility flip, kept separate on purpose. Save inventory, claims, findings, and what was done to `skilleddocs/showcase/<local-date>.md`, uncommitted unless asked (and not counted among the files you commit in §7). Untracked → exclude `skilleddocs/` per [TRACKING.md](../handoff-auto/TRACKING.md) (it also covers the `pip install .` hazard).
