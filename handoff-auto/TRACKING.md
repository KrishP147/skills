# Handoff tracking

Shared by every skill and agent that writes under `skilleddocs/` (handoffs, `HANDOFF.md`, orchestrator files). Single source of truth: other files point here instead of repeating it.

## Commit or keep untracked

**Fork** = `gh repo view "$(git remote get-url origin)" --json isFork -q .isFork` prints `true` (name origin: a bare `gh repo view` resolves to `upstream` when that remote exists); if `gh` can't answer, an `upstream` remote counts as a fork.

**Commit** only when not a fork and either:
- the repo already tracks `skilleddocs/`: `git ls-tree -r --name-only <default> -- skilleddocs` prints something, or
- its `AGENTS.md` / `CLAUDE.md` opts in.

**Otherwise, and always on a fork**: leave the file untracked and exclude the folder (works in worktrees; appends only if missing):

```sh
ex=$(git rev-parse --git-path info/exclude); mkdir -p "$(dirname "$ex")"
grep -qxF 'skilleddocs/' "$ex" 2>/dev/null || echo 'skilleddocs/' >> "$ex"
```

**Packaging hazard.** Excluding keeps `git status` clean but not the build: in a flat-layout Python project (no `src/`, no explicit `packages`), setuptools auto-discovery scans the folder, so an untracked `skilleddocs/` fails `pip install .` with "Multiple top-level packages discovered in a flat-layout: ['pkg', 'skilleddocs']". Two remedies, both checked to work: install from a clean clone (`git clone . "$(mktemp -d)/x"`, then `pip install` that path), or, with the user's yes since it edits the project, list the real package: `[tool.setuptools.packages.find]` with `include = ["<pkg>*"]` in `pyproject.toml`. Any quickstart or install check a skill runs uses the clean clone.

`meta-orchestrator`'s `docs_commit` picks this for its own files; it defaults to the rule above and is always `uncommitted` on a fork.

## `HANDOFF.md` never ships

`skilleddocs/HANDOFF.md` is gone from a branch before it is handed back or pushed. Untracked: nothing to do; it stays on disk for the next round. Committed: delete it in a commit (`git rm`) and name the last SHA that held it.

Before handing back or pushing, check `git diff --name-only <base>...HEAD`: no `skilleddocs/HANDOFF.md`, and in untracked mode nothing under `skilleddocs/`. A hit → remove it in a commit, then recheck.
