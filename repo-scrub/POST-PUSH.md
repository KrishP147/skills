# Resetting an existing clone after the force-push

Step 10's in-place path, for a clone the user keeps instead of re-cloning. Run it in that clone. Nothing is deleted until its copy is saved and checked, and every delete waits for a yes.

`<save>` = a new `mktemp -d` **outside the repo and outside `<tmp>`** (step 12 deletes `<tmp>`), echoed to the user. It holds old content (the secret, if a stash, branch or tag touched it); this file's step 11 offers to delete it.

## 1. Park the WIP, record everything

```
git branch --show-current > <save>/branch.txt
git status --porcelain                      # non-empty -> next line
git stash push -u -m "wip before scrub reset"
git for-each-ref --format='%(refname) %(objectname)' > <save>/refs-before.txt
git stash list --format='%gd %H %gs' > <save>/stashes.txt
```

The WIP is stashed first, so nothing is applied onto a dirty tree. It is now `stash@{0}` and is handled with the rest.

## 2. Save every stash entry

Per entry `n` in `stashes.txt`:

```
git stash show -p --include-untracked "stash@{n}" > <save>/stash-n.patch
```

(`--include-untracked` needs git 2.32+; older git: also `git show "stash@{n}^3" > <save>/stash-n-untracked.patch` when that commit exists.) Show the user each entry with its patch size; an empty patch for an entry that has changes → stop.

## 3. Find unpushed work (before the fetch)

```
git remote                                       # every remote, not only origin
git ls-remote --heads --tags <remote>            # per remote
git for-each-ref refs/heads --format='%(refname:short) %(upstream:short)'
```

- **Local-only branch**: its name is on no remote. Old base = `git merge-base <branch> origin/<default>`.
- **Pushed branch** (`<r>` = the remote holding it): with unpushed commits (`git log --oneline <r>/<b>..<b>` non-empty), copy it first, `git branch <b>-local <b>`, and treat the copy as local-only; old base = `<r>/<b>`.
- **Remote the user did not rewrite** (declined at step 9): its branches and remote-tracking refs keep the old history. Ask: `git remote remove <r>` (drops the refs here; the server copy keeps the secret) or keep (step 10 warns).
- **Local-only tag**: in no `ls-remote` list.
- **LFS branch** (`git lfs ls-files <branch>` non-empty; without git-lfs, `git log -p <old base>..<branch> -- '*.gitattributes' | grep -i filter=lfs` hits): rebase only with git-lfs installed, and step 5 runs it with `GIT_LFS_SKIP_SMUDGE=1`. git-lfs missing → offer only delete or keep as is (its bundle and patches are saved).

Save each one, then list them all for the user with their commits:

```
echo "<branch> <old base SHA> <base branch>" >> <save>/bases.txt    # base branch: <default>, or <b> for a <b>-local copy
git bundle create <save>/branches.bundle <branch>... <tag>...      # annotated tags keep their message
git format-patch -o <save>/<branch> <old base>..<branch>
echo "<tag> $(git cat-file -t <tag>) $(git tag -l --format='%(if)%(contents:signature)%(then)signed%(else)-%(end)' <tag>) $(git log -1 --format='%at %s' <tag>)" >> <save>/tags.txt   # tag|commit, signed|-, author time, subject
git tag -l --format='%(contents:subject)%0a%0a%(contents:body)' <tag> > <save>/tag-<tag>.msg   # annotated only; leaves out the old signature
```

Per branch, ask: **rebase** onto the new history (step 5), **delete** (it stays in `<save>`), or **keep as is** (it keeps the old history and the secret alive in this clone, `gc` can't drop them, and it must never be pushed). Per local-only tag: **re-point** to its rewritten commit (step 5), **delete**, or **keep as is** (same warning). No answer = keep as is.

## 4. Reset the pushed branches

```
git fetch --all --prune && git fetch --all --tags --force
git checkout <branch> && git reset --hard <r>/<branch>       # per pushed branch, <r> = its remote
```

Never merge or `pull` the old history.

## 5. Rebase what the user chose

```
git rebase --onto origin/<base branch> <old base SHA> <branch>    # from bases.txt; LFS branch: GIT_LFS_SKIP_SMUDGE=1 git rebase …
```

A conflict means a commit touched scrubbed content: stop that rebase (`git rebase --abort`) and hand the branch to the user; its saved copy is in `<save>`. A branch that deletes a file the rewrite edited (a `/repo-showcase` branch, say) always conflicts: merge it before `/repo-scrub`, or resolve with `git rm <file>` on a yes.

`git rebase --abort` itself fails (an LFS smudge, "untracked … would be overwritten") → `GIT_LFS_SKIP_SMUDGE=1 git rebase --abort`; still failing → `git rebase --quit && GIT_LFS_SKIP_SMUDGE=1 git checkout -f <noted branch>`, then `git status --short --untracked-files=all`: leftovers from the half-done checkout are deleted only on a yes (the WIP is safe in its stash). The branch itself is unchanged; hand it to the user.

Then per tag to re-point, find its rewritten commit by author time and subject from `tags.txt`:

```
git log --branches --remotes --not <tag> --format='%H %at %s' | grep -F '<at> <subject>'   # exactly one SHA, else warn and keep the tag as is
git tag -f -a <tag> <new sha> -F <save>/tag-<tag>.msg             # annotated
git tag -f <tag> <new sha>                                         # lightweight
```

A tag marked `signed` in `tags.txt`: the re-point drops the signature. Ask to re-sign with the user's own key (`-s` in place of `-a`, then `git tag -v <tag>`); no → say it is now unsigned.

## 6. Re-create the stash entries on the new history

Oldest first (highest `n`), the WIP entry last. Each on the branch named in its message (`WIP on <b>:` / `On <b>:`), falling back to the noted branch; the tree is clean before each:

```
git checkout <b>
git stash apply <sha from stashes.txt>       # conflict -> git apply --reject <save>/stash-n.patch, fix *.rej
git stash push -u -m "<original message>"
```

Verify each re-created entry against its saved patch (only `index` lines may differ):

```
diff <(git stash show -p --include-untracked stash@{0} | grep -v '^index ') <(grep -v '^index ' <save>/stash-n.patch)
```

Any difference → stop and show it. The stash list now holds every entry twice: the new ones on top, the old ones below.

## 7. Drop the old copies (only after step 6 verified all of them)

```
git stash list --format='%gd %H'      # drop each SHA listed in stashes.txt, highest index first
git stash drop "stash@{k}"
git branch -D <branch>                # only the branches the user said to delete
git tag -d <tag>                      # likewise
```

## 8. Expire and collect

```
git reflog expire --expire=now HEAD $(git for-each-ref --format='%(refname)' refs/heads refs/remotes | while read -r r; do git reflog exists "$r" && echo "$r"; done)
git gc --prune=now
```

Only refs that have a reflog: naming one without (any tag; a remote-tracking ref no fetch has updated since the clone) exits 255. No `refs/tags` for the same reason. Not `--all`: that also clears the stash list, while `refs/stash` itself survives and would pin the old history. The old stash entries are gone after step 7, so the stash reflog holds only new-history entries.

## 9. Restore the WIP and verify

```
git checkout <noted branch> && git stash pop     # the WIP entry; a conflicting pop keeps it: resolve, then git stash drop
git status --short
git stash list                                   # every non-WIP entry, re-created
git for-each-ref --format='%(refname) %(objectname)' | sort | comm -23 <(sort <save>/refs-before.txt) -   # refs the rewrite changed (old line)
git cat-file -e <old SHA from each line above>   # must fail; an unchanged ref's SHA is kept and is not checked
git log --all -m -S'<string>' --oneline          # each scrubbed personal string: no output, unless a branch or tag was kept as is
git log --all --format='%an %ae %cn %ce %B' | grep -F -i '<string>'   # same, for messages and identities
git rev-parse "<tag>^{commit}"                   # each re-pointed tag: the new SHA from step 5
```

Report all of it.

## 10. Warn about what was kept

Per branch, tag or remote kept as is in step 3 or 5 (including any left unanswered), print:

```
WARNING: <branch|tag|remote> <name> was kept as is. It still holds the pre-rewrite history, including the scrubbed secret. Never push it.
```

## 11. Offer to delete `<save>`

```
du -sh <save>
```

Show the path and size. **Gate**: `rm -rf <save>` only on an explicit yes. Anything else → say `<save>` is kept at that path and still holds the old content, including the secret if a stash, branch or tag touched it.
