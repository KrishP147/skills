# Handoff tracking

Shared by every skill and agent that writes under `skilleddocs/` (handoffs, `HANDOFF.md`, orchestrator files). Single source of truth: other files point here instead of repeating it.

`skilleddocs/` is at the repo root (`git rev-parse --show-toplevel`), never relative to the working dir, so a session in a subfolder writes where root-level readers look.

## Commit or keep untracked

`<default>` = the repo's default branch: `gh repo view "$(git remote get-url origin)" --json defaultBranchRef -q .defaultBranchRef.name`, else `git symbolic-ref --short refs/remotes/origin/HEAD` minus the `origin/` prefix, else whichever of `main` / `master` exists.

**Fork** = `gh repo view "$(git remote get-url origin)" --json isFork -q .isFork` prints `true` (name origin: a bare `gh repo view` resolves to `upstream` when that remote exists); if `gh` can't answer, an `upstream` remote counts as a fork. Same resolution as the `next` skill's `BOARD.md`, Target repo section, which governs every `gh` write.

**Commit** only when not a fork and either:
- the repo already tracks `skilleddocs/`: `git ls-tree --full-tree -r --name-only <default> -- skilleddocs` prints something, or
- its `AGENTS.md` / `CLAUDE.md` opts in, or
- for the handoff folder only: that folder, set by `AGENTS.md`/`CLAUDE.md` outside `skilleddocs/`, already has tracked files on `<default>` (`git ls-tree --full-tree -r --name-only <default> -- <folder>` prints something; `<folder>` from the repo root). Other `skilleddocs/` files still follow the two bullets above.

**Otherwise, and always on a fork**: leave the file untracked and exclude the folder (works in worktrees; appends only if missing):

```sh
ex=$(git rev-parse --git-path info/exclude); mkdir -p "$(dirname "$ex")"
grep -qxF 'skilleddocs/' "$ex" 2>/dev/null || echo 'skilleddocs/' >> "$ex"
```

A handoff folder set by `AGENTS.md`/`CLAUDE.md` outside `skilleddocs/` gets the same exclude line, with its path, unless the third bullet puts it in commit mode.

**Packaging hazard.** Excluding keeps `git status` clean but not the build: in a flat-layout Python project (no `src/`, no explicit `packages`), setuptools auto-discovery scans the folder, so an untracked `skilleddocs/` fails `pip install .` with "Multiple top-level packages discovered in a flat-layout: ['pkg', 'skilleddocs']". Two remedies, both checked to work: install from a clean clone (`git clone . "$(mktemp -d)/x"`, then `pip install` that path), or, with the user's yes since it edits the project, list the real package: `[tool.setuptools.packages.find]` with `include = ["<pkg>*"]` in `pyproject.toml`. Any quickstart or install check a skill runs uses the clean clone.

`meta-orchestrator`'s `docs_commit` picks this for its own files; it defaults to the rule above and is always `uncommitted` on a fork.

## Protected `<default>`

Every skill that commits on `<default>` (`update-progress`, `progress-report`, `teammate-brief`) checks this before writing its files. **Protected** = a PR is required: `gh api repos/<owner>/<repo>/branches/<default>/protection` shows `required_pull_request_reviews`, or `gh api repos/<owner>/<repo>/rules/branches/<default>` lists a `pull_request` rule (`<owner>/<repo>` per the `next` skill's `BOARD.md`, Target repo section). Unprotected only when the rules call answers with no `pull_request` rule and the classic call answers 404 "Branch not protected" (a 403, or a 404 without that message, means no admin rights, not unprotected). Anything else → ask.

Protected → `git fetch origin`, note the current branch, and switch to a docs branch off `origin/<default>` (never the local `<default>`, often stale): `docs/<what>`, prefix per the repo's or user's instructions, else `docs/`; `<what>` named by the calling skill. It exists and isn't an ancestor of `origin/<default>` → switch to it and add the commit; it's merged → suffix `-2`, `-3`, … Write and commit there, then switch back to the noted branch; `<default>` stays as it was. Push, and open the branch's PR, only on the user's yes to that action; no yes → leave the commit local and say so.

## Dated handoffs never ship in a task PR

A dated handoff in the handoff folder (AGENTS.md/CLAUDE.md's, else `skilleddocs/handoffs/`) is not part of the task's change. Commit mode: commit it only when the current branch is `<default>` or `update-progress`'s docs branch (Protected `<default>` above; it is headed for `<default>`, so the pre-push check below leaves the handoff there). On any other branch leave it uncommitted on disk; `update-progress` runs on `<default>` and commits it there after verifying. Untracked mode: nothing to do. Either mode, worktree teardown (`pair` §5 step 1) first moves it into the main checkout's handoff folder.

## `HANDOFF.md` never ships

`skilleddocs/HANDOFF.md` is gone from a branch before it is handed back or pushed. Untracked: nothing to do; it stays on disk for the next round. Committed: delete it in a commit (`git rm`) and name the last SHA that held it.

Before handing back or pushing, check `git diff --name-only <base>...HEAD`: no `skilleddocs/HANDOFF.md`, in commit mode nothing in the handoff folder (except on `update-progress`'s docs branch, which is headed for `<default>`), and in untracked mode nothing under `skilleddocs/` or the handoff folder. A hit → remove it in a commit, then recheck.
