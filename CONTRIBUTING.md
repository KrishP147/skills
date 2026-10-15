# Contributing

Thanks for growing this repo. A few rules keep it small, consistent, and safe
to publish.

## 1. Watch this first (mandatory)

Before writing a skill, watch [this video by Matt Pocock](https://www.youtube.com/watch?v=v4F1gFy-hqg).

Why: it is the shared context for how this repo is built. The skills here
follow a few principles in that spirit: small, composable skills rather than
one giant prompt; grill a plan before building it; keep sessions in the
model's "smart zone" by handing off to a fresh session instead of letting one
run long; and keep a human gate on outward actions (pushes, merges, posts).
A skill written with that context tends to fit these conventions instead of
fighting them.

## 2. What a submission looks like

A skill submission is a directory containing:

- `SKILL.md` — the prompt Claude loads. Start from
  [`templates/skill/SKILL.md`](templates/skill/SKILL.md).
- `README.md` — for humans, following
  [`templates/skill/README.md`](templates/skill/README.md) exactly: the same
  `## ` headings, in the same order (`What it does`, `When to use`,
  `How to invoke`, `How it works`, `Design principles`, `Use cases`, `Tips`,
  `Example`, `Related`, `Prereqs`). The site parses these headings to build
  the skill's page and `scripts/lint.py` warns when one is missing, so don't
  rename or drop them (`## Invoke` is accepted for `How to invoke`).

## 3. Writing the SKILL.md

Follow Matt Pocock's [`writing-for-agents`](https://github.com/mattpocock/skills/tree/main/skills/productivity/writing-for-agents). In short:

- **Description = trigger.** It's loaded in every session, so it says what the skill is plus one phrase per distinct trigger. Collapse synonyms. User-only skills (`disable-model-invocation: true`) get a one-line human summary.
- **Every line changes behaviour.** Cut instructions the model already follows ("be careful", "read the file first") and explanations that don't alter what it does. Keep the gotchas no config file would tell it.
- **Inline what every run needs; disclose the rest.** Material only some runs reach (a fallback path, a rare branch, a long template) goes in a sibling file (`SETUP.md`, `ROTATE.md`) behind a link that says when to read it. Lint fails on a broken relative link.
- **One source of truth.** Board operations live in [`kanban/next/BOARD.md`](kanban/next/BOARD.md); point at it instead of repeating it. Scripts beat inline code blocks the agent must retype.
- **Say the target, not the taboo.** "Push belongs to the caller" over "NEVER push". Keep a hard prohibition only for real guardrails, paired with what to do instead.
- **Gate** means: show the exact action, wait for an explicit yes to that action; anything vaguer is a no.

## 4. Rules

- **Generic and user-facing.** No project names, company names, or personal
  data — yours or anyone else's. `scripts/lint.py` runs a forbidden-word
  check; a skill that only makes sense inside one specific project doesn't
  belong here. The word list itself is never committed: put your own
  words (one per line, `#` comments allowed) in an untracked repo-root
  `.lint-forbidden.txt`, or set the comma-separated `SKILLS_LINT_FORBIDDEN`
  env var — e.g. `SKILLS_LINT_FORBIDDEN=acme-internal,project-codename`.
  With neither set, the check is silently skipped.
- **License.** Contributions are made under this repo's MIT license (see
  [`LICENSE`](LICENSE)).
- **Credit third-party work.** If your skill is copied or adapted from
  someone else's, add an entry to
  [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) naming the source and
  its license, the same way the existing entries do.
- **Docs written by skills go under `skilleddocs/`.** If your skill produces
  documents (handoffs, reports, decisions, ...), write them into a repo's
  `skilleddocs/` convention rather than inventing a new location — see the
  root [`README.md`](README.md#where-skills-write-skilleddocs) for the
  layout.

## 5. Test locally before opening a PR

```bash
python scripts/lint.py
```

Fix anything it reports as a failure. It also prints `WARN:` lines (to
stderr) for a skill README missing one of the required headings above —
warnings don't fail the run, but fix them before submitting if they're
about your own skill. To test the forbidden-word check locally, drop a
throwaway word into `.lint-forbidden.txt` at the repo root (gitignored),
confirm `python scripts/lint.py` fails naming it, then delete the file.

Install into a throwaway location instead of your real `~/.claude/`, so you
can check the result without touching your own setup:

```sh
# sh / bash / git-bash / mac / linux
CLAUDE_SKILLS_DIR=/tmp/claude-test/skills CLAUDE_AGENTS_DIR=/tmp/claude-test/agents ./scripts/install-skills.sh
```

```powershell
# PowerShell
$env:CLAUDE_SKILLS_DIR = "$env:TEMP\claude-test\skills"
$env:CLAUDE_AGENTS_DIR = "$env:TEMP\claude-test\agents"
.\scripts\install-skills.ps1
```

Both install scripts read `CLAUDE_SKILLS_DIR` / `CLAUDE_AGENTS_DIR` and fall
back to the real `~/.claude/skills` and `~/.claude/agents` only when those
are unset. Delete the temp directory when you're done.

## 6. The site

Every skill's `README.md` becomes a page on the
skills site at `/<name>`, built from the headings above. There's no
separate docs step — write the README once, well. Community tips, corrections,
and "here's how I use this" notes belong in that page's comments (GitHub
Discussions), not in the README itself.

## 7. Opening the PR

Use the pull request template's checklist. It asks you to confirm: you
watched the video, `python scripts/lint.py` passes, your README follows the
template, there's nothing project-specific or personal in the submission, and
any third-party work is credited.
