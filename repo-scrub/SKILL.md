---
name: repo-scrub
description: Scan a GitHub repo's full history for secrets and large files, scrub what the user picks, rewrite history safely, then flip it private → public.
argument-hint: "[owner/repo] (default: current repo)"
disable-model-invocation: true
---

Going public is one-way: forks, caches and scrapers copy history within minutes, and GitHub offers no hook on its visibility toggle. So all cleanup happens *before* the flip, and you flip it yourself with `gh`.

Two rules hold throughout:
- **Gate**: each numbered gate below needs the user's explicit go-ahead.
- **Complete report**: every secret and large blob found is shown, including ones the user keeps.

`<tmp>/scrub-work` holds secret-bearing files. Delete it (step 12) on every exit, early ones included.

## 1. Prereqs and target

- `gh auth status`; else user runs `gh auth login`.
- `gitleaks version`; missing → Windows `winget install --id Gitleaks.Gitleaks -e`, mac/linux `brew install gitleaks`. v8.19+ uses `gitleaks git`; older uses `gitleaks detect --source . --log-opts=--all`.
- `git filter-repo --version`; missing → `pip install git-filter-repo` (mac: or brew). Trust the version command, not pip's exit code: a `--user` install can land off PATH.

Missing tool → give the install command and stop.

`gh repo view <repo> --json name,owner,isPrivate,defaultBranchRef` → confirm the repo, and that a rewrite + force-push is OK if anything gets scrubbed.

## 2. LFS bail-out

`gh api repos/<o>/<r>/contents/.gitattributes --jq .content | base64 -d | grep -i lfs` (404 = no LFS). LFS-tracked paths → stop: `filter-repo` has no LFS awareness; this needs manual handling.

## 3. Scan (clone #1)

```
mkdir -p <tmp>/scrub-work
git clone <url> <tmp>/scan-clone && cd <tmp>/scan-clone
git count-objects -vH > <tmp>/scrub-work/before-size.txt
gitleaks git . --report-format json --report-path <tmp>/scrub-work/gitleaks-report.json --no-banner
git filter-repo --analyze
python <skill-dir>/scripts/summarize_findings.py --gitleaks <tmp>/scrub-work/gitleaks-report.json \
  --analysis-dir .git/filter-repo/analysis --out <tmp>/scrub-work/findings.json
```

- gitleaks exit 1 = findings, not failure.
- `summarize_findings.py` merges gitleaks + `.git/filter-repo/analysis/` into `findings.json`: secrets `S1…` (deduped by rule + value, or by location when the value is empty; fingerprint `secret_sha256` only), large blobs `L1…` (bytes accumulated across every version). Use it; the analysis tables are easy to misread.
- `--analyze` spends this clone (filter-repo refuses a second run). Delete `scan-clone` once `findings.json` exists; keep `gitleaks-report.json` until step 12 (step 7 recovers values from it).

## 4. Report

```
3 secrets across 2 files, 2 large blobs totaling 410 MB (accumulated across history)

ID | Type   | Path(s)                  | Detail                 | Commits
S1 | secret | config/dev.env (+1 more) | AWS Access Key         | 3
L1 | large  | assets/demo.mov          | 340 MB (all versions)  | -
```

Raw secret values stay out of the table. Reveal one only on request, looked up by fingerprint in `gitleaks-report.json`.

## 5. Select

Per ID or bulk ("all secrets", "over 50MB", a path glob). Echo back the final **scrub** and **keep** lists. Silence is not "scrub everything".

## 6. Gates before any rewrite

- **Rotation** (any secret selected): walk the user through [ROTATE.md](ROTATE.md). **Gate**: rotation confirmed done.
- **Collaborators**:
  ```
  gh api repos/<o>/<r>/collaborators --jq '.[].login'
  gh api repos/<o>/<r>/invitations
  gh pr list --state open --json number,title,headRefName,author
  gh api repos/<o>/<r>/forks --jq length
  ```
  Anyone affected → draft a notice (what, why, re-clone from scratch, which PRs need recreating); user posts it or skips. Forks can't be messaged; report the count. **Gate**: go-ahead to rewrite.

## 7. Rewrite (clone #2)

```
git clone <url> <tmp>/rewrite-clone && cd <tmp>/rewrite-clone
python <skill-dir>/scripts/build_replace_text.py --gitleaks <tmp>/scrub-work/gitleaks-report.json \
  --findings <tmp>/scrub-work/findings.json --ids S1 S3 --out <tmp>/scrub-work/expressions.txt
```

The script writes `--replace-text` expressions without printing a value. Location-only findings (`secret_sha256: null`) have no value to replace; it skips them, so scrub those by `--path` or by hand. Large blobs, per finding: strip entirely, or strip history but keep the current file (re-add it in a commit after the rewrite: path/size stripping removes HEAD's copy too).

One combined call, only the flags for what was selected:

```
git filter-repo --replace-text <tmp>/scrub-work/expressions.txt --path <paths> --invert-paths
```

(`--strip-blobs-bigger-than <size>` when a threshold describes the selection better.)

## 8. Verify (still reversible)

`git log --oneline -10`, `gitleaks git . --no-banner`, `git count-objects -vH`. Spot-check stripped paths are gone. Show before/after commit count and size. **Gate**.

## 9. Force-push

Only after the step-6 notice went out (or was confirmed unnecessary). filter-repo removed `origin`:

```
git remote add origin <url>
git push origin --force --all && git push origin --force --tags
```

## 10. Post-push

`gh pr list --state open` → name PRs that must be closed and recreated. Tell the user: old commits stay reachable on GitHub (via `refs/pull/*`, direct SHA, cached views) until GitHub Support garbage-collects them. Rotation protects the secret; the push is hygiene.

## 11. Flip visibility

State `gh`'s consequences first: stars/watchers lost, forks detached, push rulesets disabled, Actions history becomes public. **Gate**, separate from the push.

```
gh repo edit <o>/<r> --visibility public --accept-visibility-change-consequences
gh repo view <o>/<r> --json isPrivate
```

## 12. Cleanup

```
rm -rf <tmp>/scrub-work <tmp>/scan-clone <tmp>/rewrite-clone
```
