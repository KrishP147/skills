# Resetting an existing clone after the force-push

Step 10's in-place path, for a clone the user keeps instead of re-cloning. Run it in that clone. Nothing is deleted until its copy is saved and checked, and every delete waits for a yes.

`<save>` = a new `mktemp -d` **outside the repo and outside `<tmp>`** (step 12 deletes `<tmp>`), echoed to the user. It holds old content (the secret, if a stash or branch touched it); this file's step 11 offers to delete it.

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
git ls-remote --heads --tags origin
git for-each-ref refs/heads --format='%(refname:short) %(upstream:short)'
```

- **Local-only branch**: its name is not on the remote. Old base = `git merge-base <branch> origin/<default>`.
- **Pushed branch with unpushed commits**: `git log --oneline origin/<b>..<b>` is non-empty. Copy it first, `git branch <b>-local <b>`, and treat the copy as local-only; old base = `origin/<b>`.
- **Local-only tag**: not in the `ls-remote` list.

Save each one, then list them all for the user with their commits:

```
echo "<branch> <old base SHA> <base branch>" >> <save>/bases.txt    # base branch: <default>, or <b> for a <b>-local copy
git bundle create <save>/branches.bundle <branch>...
git format-patch -o <save>/<branch> <old base>..<branch>
```

Per branch, ask: **rebase** onto the new history (step 5), **delete** (it stays in `<save>`), or **keep as is** (it keeps the old history and the secret alive in this clone, `gc` can't drop them, and it must never be pushed). Same for each local-only tag: delete or keep. No answer = keep as is.

## 4. Reset the pushed branches

```
git fetch origin --prune && git fetch origin --tags --force
git checkout <branch> && git reset --hard origin/<branch>     # per pushed branch
```

Never merge or `pull` the old history.

## 5. Rebase what the user chose

```
git rebase --onto origin/<base branch> <old base SHA> <branch>    # from bases.txt
```

A conflict means a commit touched scrubbed content: stop that rebase (`git rebase --abort`) and hand the branch to the user; its saved copy is in `<save>`.

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
git reflog expire --expire=now HEAD $(git for-each-ref --format='%(refname)' refs/heads refs/remotes refs/tags)
git gc --prune=now
```

Not `--all`: that also clears the stash list, while `refs/stash` itself survives and would pin the old history. The old stash entries are gone after step 7, so the stash reflog holds only new-history entries.

## 9. Restore the WIP and verify

```
git checkout <noted branch> && git stash pop     # the WIP entry; a conflicting pop keeps it: resolve, then git stash drop
git status --short
git stash list                                   # every non-WIP entry, re-created
git cat-file -e <old SHA from refs-before.txt>   # must fail, unless a branch was kept as is
git log --all -S'<string>' --oneline             # each scrubbed personal string: no output
```

Report all of it.

## 10. Warn about what was kept

Per branch or tag kept as is in step 3 (no answer included), print:

```
WARNING: <branch|tag> <name> was kept as is. It still holds the pre-rewrite history, including the scrubbed secret. Never push it.
```

## 11. Offer to delete `<save>`

```
du -sh <save>
```

Show the path and size. **Gate**: `rm -rf <save>` only on an explicit yes. Anything else → say `<save>` is kept at that path and still holds the old content, including the secret if a stash or branch touched it.
