# repo-scrub

*`SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Scans a GitHub repo's **full git history** for secrets and oversized files, lets you choose exactly what to scrub, rewrites history safely in a throwaway clone, force-pushes, and only then flips the repo private → public. Every step with side effects has an explicit confirmation gate.

## When to use

- Making a private repo public / open-sourcing it.
- Cleaning secrets or huge blobs out of history before publishing.

## How to invoke

```
/repo-scrub [owner/repo]
```

Defaults to the current repo. User-invoked only (`disable-model-invocation: true`) because it rewrites history and force-pushes.

## How it works

0. Confirms the target repo and that you accept a history rewrite + force-push.
1. **Prereq check** — version-checks each tool; stops with the install command if one is missing.
2. **Confirm target** — `gh repo view … --json name,owner,isPrivate,defaultBranchRef`.
3. **Git LFS check** — bails with a warning before scanning if `.gitattributes` shows LFS-tracked paths; `git filter-repo` has no LFS awareness.
4. **Scan (throwaway clone #1)** — `gitleaks git` (or `detect --source` pre-8.19) over all history, `git filter-repo --analyze`. [`scripts/summarize_findings.py`](scripts/summarize_findings.py) merges them into `findings.json` — written to a work dir *outside* the clone — with IDs `S1…` (secrets, deduped by rule + value, fingerprint only, no raw value on disk) and `L1…` (large blobs, sized by bytes accumulated across all versions of that path in history). The clone is then discarded.
5. **Report** — table of every finding (no raw secret values, just fingerprints) + summary line.
6. **Select** — you pick per ID or in bulk; Claude echoes back scrub vs keep lists.
7. **Rotate first (mandatory)** — rotate/revoke every selected secret at its source before any rewrite; a rewrite doesn't un-leak a secret that was ever pushed. Checklist by type (cloud keys, API tokens, private keys/certs, DB passwords, webhook URLs). Hard gate.
8. **Collaborator / open-PR safety** — lists collaborators, invitations, open PRs, fork count; drafts a re-clone notice. Hard gate.
9. **Rewrite (fresh clone #2)** — [`scripts/build_replace_text.py`](scripts/build_replace_text.py) re-derives each secret's value from the gitleaks report by fingerprint and writes `expressions.txt` without ever echoing a value; one `git filter-repo` call, `--replace-text`/`--path …--invert-paths` each included only if that category was actually selected. For large files you choose: strip entirely, or strip history and re-add the current version.
10. **Verify** — re-run gitleaks, spot-check sizes, before/after `git count-objects -vH`. Confirm gate.
11. **Force-push** — re-adds `origin`, `push --force --all` and `--tags`.
12. **Post-push** — lists PRs that must be recreated; notes that old commits can still be reachable on GitHub via `refs/pull/*`/cached views until GitHub Support GCs them.
13. **Visibility flip** — `gh repo edit --visibility public …` after a separate gate explaining the consequences; verifies `isPrivate`.
14. **Cleanup** — deletes the work dir (gitleaks report, findings.json, expressions.txt) and leftover clones.

Bails out on Git LFS repos (step 3). Never scans or rewrites your working clone.

## Design principles

- **Going public is one-way.** Forks, caches and scrapers copy history within minutes and GitHub has no hook on the visibility toggle, so every cleanup happens before the flip, and the flip is its own gate.
- **Rotation before rewrite.** A rewrite doesn't un-leak a secret that was ever pushed; rotating at the source is what protects you, the history rewrite is hygiene.
- **Complete report, no raw values.** Every finding is shown, including ones you keep, but secrets appear only as fingerprints; the helper scripts never print or store a value.
- **Throwaway clones only.** Scanning and rewriting happen in fresh clones under a temp work dir, never your working clone.

## Use cases

- Open-sourcing a repo that started private.
- Removing a committed `.env` or API key from every commit before publishing.
- Stripping large binaries (demo videos, datasets) out of history to shrink the repo, while optionally keeping the current file.
- A pre-publish audit where you scrub nothing: the full report still tells you what is in history.

## Tips

- Have rotation access ready (cloud console, API dashboards) before you start; the rewrite waits on it. [`ROTATE.md`](ROTATE.md) has the checklist by secret type.
- Selecting nothing is not "scrub everything": you pick per ID or in bulk ("all secrets", "over 50MB", a path glob) and Claude echoes the final lists.
- Collaborators and open PRs need to re-clone or recreate after the force-push; let Claude draft the notice before the push.
- Old commits can stay reachable on GitHub (`refs/pull/*`, direct SHA, cached views) until GitHub Support garbage-collects them.
- Repos using Git LFS are out of scope: it stops before scanning.
- Want the working tree tidied first (README, stale docs)? Run [`repo-showcase`](../repo-showcase/) before this.

## Example

```
/repo-scrub myorg/tool
```

Finds `S1` (an API key in `config/dev.env`, 3 commits) and `L1` (a 340 MB demo video, accumulated across history). You scrub both; Claude tells you to rotate the API key first and waits for confirmation, then warns about 1 open PR, you approve, it rewrites clone #2, verifies gitleaks is clean, force-pushes, lists the PR to recreate, asks separately before making the repo public, then deletes the work dir holding the gitleaks report and findings.json.

## Related

Standalone; no other skills or agents.

## Prereqs

`gh` (authenticated), [`gitleaks`](https://github.com/gitleaks/gitleaks), [`git-filter-repo`](https://github.com/newren/git-filter-repo), and Python for the helper scripts. Install commands are in the [top README](../README.md#install); the skill also prints the right one if a tool is missing. No separate sizing tool: before/after repo size comes from `git count-objects -vH`.
