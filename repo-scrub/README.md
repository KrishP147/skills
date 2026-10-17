# repo-scrub

*`SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Scans a GitHub repo's **full git history** for secrets and oversized files.

- Lets you choose exactly what to scrub.
- Rewrites history safely in a throwaway clone.
- Force-pushes.
- Only then flips the repo private → public.
- Every step with side effects has an explicit confirmation gate.

## When to use

- Making a private repo public / open-sourcing it.
- Cleaning secrets or huge blobs out of history before publishing.

## How to invoke

```
/repo-scrub [owner/repo]
```

Defaults to the current repo. Only you can run it (`disable-model-invocation: true`), because it rewrites history and force-pushes.

## How it works

1. **Prereqs and target** — version-checks each tool (stops with the install command if one is missing), then `gh repo view … --json name,owner,isPrivate,defaultBranchRef` and confirms you accept a history rewrite + force-push.
   - `<tmp>` is one `mktemp -d` path, echoed once.
   - Lists every other remote in your clone (each is its own copy of the history, scanned, rewritten and pushed to on a yes).
   - Lists every submodule (a separate repo to scrub on its own; relative URLs flagged).
2. **Git LFS bail-out** — stops with a warning if the root `.gitattributes` shows LFS-tracked paths; `git filter-repo` has no LFS awareness.
   - The same check runs over all history in step 3 to catch nested files and other branches.
3. **Scan (throwaway clone #1)**
   - `gitleaks git --log-opts="--all -m"` (or `detect --source` pre-8.19) over all history, merge commits included (a secret added only in a conflict resolution is invisible without `-m`).
   - Other remotes' branches fetched in, `git filter-repo --analyze`.
   - [`scripts/summarize_findings.py`](scripts/summarize_findings.py) merges them into `findings.json`, written to a work dir *outside* the clone.
     Secrets get IDs `S1…`: deduped by rule + value, or by location when the value is empty; fingerprint only, no raw value on disk.
     Large blobs get IDs `L1…`: sized by bytes accumulated across all versions of that path in history.
   - Personal strings handed over by `repo-showcase` (or named by you) get a `git log --all -m -S'<string>'` and `--grep` check each, since gitleaks has no rule for names or emails; hits become `P1…`.
   - Emails in commit messages and author/committer identities other than yours are found the same way (`git log --all --format=…`).
   - Signed commits and tags are counted: a rewrite drops every signature.
   - The clone is then discarded.
4. **Report** — a table of every finding (no raw secret values, just fingerprints) and a summary line.
5. **Select** — you pick per ID or in bulk; Claude echoes back scrub vs keep lists.
6. **Gates before any rewrite** — both are hard gates.
   - **Rotate first (mandatory)**: rotate/revoke every selected secret at its source; a rewrite doesn't un-leak a secret that was ever pushed.
   - Checklist by type (cloud keys, API tokens, private keys/certs, DB passwords, webhook URLs).
   - Then **collaborator / open-PR safety**: lists collaborators, invitations, open PRs, fork count; drafts a re-clone notice.
7. **Rewrite (fresh clone #2)**
   - [`scripts/build_replace_text.py`](scripts/build_replace_text.py) re-derives each secret's value from the gitleaks report by fingerprint and writes `expressions.txt` without ever echoing a value.
   - One `git filter-repo` call. `--replace-text` and `--path …--invert-paths` are each included only if that category was selected.
   - A selected `P` finding adds a `literal:<string>==>REDACTED` rule (`--replace-message` too for message hits).
   - A selected author identity goes through `--mailmap` to the replacement you pick, and one you keep is recorded as "author identities stay".
   - For large files you choose: strip entirely, or strip history and re-add the current version.
8. **Verify**
   - Re-run gitleaks (`-m` again).
   - `git log --all -m -S` per scrubbed personal string plus a grep of every message and identity (must print nothing).
   - Spot-check sizes, before/after `git count-objects -vH`.
   - Confirm gate.
   - Offers to re-sign each previously signed tag with your own key; commits stay unsigned.
9. **Force-push**
   - Re-adds `origin`, checks `git branch` lists every branch to keep (the fresh clone's `origin/*` became local branches, which is what `--all` pushes).
   - Then `push --force --all` and `--tags`; each other remote gets its branches on its own yes.
   - If a hook blocks the push, it gives you the two commands to run yourself.
10. **Post-push** — every local copy, yours included, still holds the old history.
    - Re-clone (after copying out WIP, stashes and unpushed branches and tags), or reset it in place per [`POST-PUSH.md`](POST-PUSH.md).
    - The in-place reset, in order:
      - Stash your WIP first.
      - Save every stash entry (untracked files included) and every local-only or unpushed branch and tag as patches/bundle outside the repo.
      - `git fetch && git reset --hard origin/<branch>` per pushed branch.
      - Rebase the unpushed branches you choose onto the new history (an LFS branch only with git-lfs installed, with a recovery path when the rebase or its abort fails).
      - Re-point the tags you choose to their rewritten commits (annotated message kept, old signature left out, re-signed on your yes).
      - Re-create the stashes and check each against its saved patch.
      - Delete a branch or tag only on your yes.
      - Then expire the reflog and `gc`; never `git pull`.
    - Finally it warns about every branch or tag you kept as is, or didn't answer for. It still holds the old history, secret included; never push it.
    - It offers to delete the save folder, showing its path and size; it deletes only on your yes, else tells you the folder still holds the old secret.
    - Lists PRs that must be recreated.
    - Notes that old commits can still be reachable on GitHub via `refs/pull/*`/cached views until GitHub Support garbage-collects them.
11. **Visibility flip** — `gh repo edit --visibility public …` after a separate gate explaining the consequences; verifies `isPrivate`.
12. **Cleanup** — deletes the work dir (gitleaks report, findings.json, expressions.txt) and leftover clones.

- Bails out on Git LFS repos (steps 2-3).
- Scanning and rewriting never happen in your working clone.
- Step 10 does change it if you choose the in-place reset: it resets your pushed branches to the new history, and it deletes local branches and tags only when you say yes, after saving them.

## Design principles

- **Going public is one-way.** Forks, caches and scrapers copy history within minutes and GitHub has no hook on the visibility toggle, so every cleanup happens before the flip, and the flip is its own gate.
- **Rotation before rewrite.** A rewrite doesn't un-leak a secret that was ever pushed; rotating at the source is what protects you, the history rewrite is hygiene.
- **Complete report, no raw values.** Every finding is shown, including ones you keep, but secrets appear only as fingerprints; the helper scripts never print a value.
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

- Finds `S1` (an API key in `config/dev.env`, 3 commits) and `L1` (a 340 MB demo video, accumulated across history).
- You scrub both.
- Claude tells you to rotate the API key first and waits for confirmation.
- Then it warns about 1 open PR, you approve, it rewrites clone #2, verifies gitleaks is clean, force-pushes, and lists the PR to recreate.
- It asks separately before making the repo public.
- Then it deletes the work dir holding the gitleaks report and findings.json.

## Related

- [`repo-showcase`](../repo-showcase/) tidies the working tree first, then hands off here for history and visibility.

## Prereqs

- `gh` (authenticated), [`gitleaks`](https://github.com/gitleaks/gitleaks), [`git-filter-repo`](https://github.com/newren/git-filter-repo), and Python for the helper scripts.
- Install commands are in the [top README](../README.md#install); the skill also prints the right one if a tool is missing.
- No separate sizing tool: before/after repo size comes from `git count-objects -vH`.
