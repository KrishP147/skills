# teammate-brief

*`SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Writes a handoff document for a person joining or picking up a project. It covers:

- What the project is.
- Setup steps verified by actually running them.
- Which env vars/keys they need and where to get them (names only, never values).
- Numbered tasks with a "done when" each.
- Who owns what.
- What not to touch.

## When to use

- "Brief my teammate", "write an onboarding doc for X".
- "Hand this project to someone", "what does the new person need to know".
- Not for an agent resuming work — that's [`handoff`](../handoff/README.md).
- Not a public README — that's [`repo-showcase`](../repo-showcase/README.md).
- Not a live status check — that's [`sitrep`](../sitrep/README.md).

## How to invoke

```
/teammate-brief [teammate name or role]
```

Model-invocable, so the trigger phrases above work without the slash.

## How it works

1. **Ask up front, one batch** — audience, role, stack experience, each with a recommended default.
   - Proceeds on the answers or the defaults.
2. **What it is, then setup** — opens with what the project is and its state.
   - Gathers steps from README/package files/Makefile/etc.
   - Runs each one in the current environment.
   - Marks any step it didn't run as "unverified" with the reason (destructive, needs credentials, too slow).
3. **Env vars and keys table** — variable name, what it's for, where to get it (dashboard, teammate, secrets manager).
   - Names only, never values.
   - Never read from an actual `.env`/secrets file.
4. **Numbered tasks** — each with a concrete "done when".
   - Pulled from open issues where the repo has them.
   - Skips `wayfinder:*` planning tickets and issues In Progress or In Review on the board.
5. **Ownership map** — area/path -> who to ask.
6. **Don't-touch list** — what to leave alone and why, per item.
7. **Draft, then write** — shows the full draft before writing.
   - Saves to `skilleddocs/briefs/<name>-<local-date>.md` on confirmation (`teammate` when no name was given).
8. **GATE**
   - Commits only when [`TRACKING.md`](../handoff-auto/TRACKING.md) allows it and on yes.
   - Pushes only on a separate yes.
   - Never shares or sends the document anywhere.

## Design principles

- **Verified, not copied.** Setup steps are run, not transcribed from a
  stale README — anything not actually run is labeled unverified with why.
- **Names, never values.** The env/keys table tells a teammate what to get
  and where, and never touches an actual secret.
- **For a person, not an agent.** Plain language, no skill/tool/session
  jargon — this document is read once, by someone who isn't running Claude.

## Use cases

- Onboarding a new contributor to a project they didn't build.
- Handing your own project to a teammate before time off or a role change.
- Splitting ownership of a repo across people and writing down who owns what.

## Tips

- No strong opinions on the §1 questions? Say "go" — the defaults assume a
  newcomer, which means more detail, not less.
- If a setup step needs credentials you don't have, say so — an "unverified"
  step with a clear reason is more useful than a guess presented as fact.
- Re-run this after a project's setup changes; a brief written against an
  old `Makefile` is worse than no brief.

## Example

```
/teammate-brief new backend dev
```

- Asks audience/role/experience, gets "go" (defaults accepted, assumes new to the stack).
- Runs `npm install` and `npm test` and watches both pass.
- Finds `PAYMENTS_KEY` and `DB_URL` read from the environment and notes where each comes from.
- Pulls three open issues into numbered tasks with a "done when" each.
- Maps `api/` and `infra/` to their owners.
- Lists `migrations/` as don't-touch with the reason.
- Shows the full draft.
- Writes `skilleddocs/briefs/new-backend-dev-2026-09-26.md` on yes.
- Commits on a separate yes.
- Does not push or share it further without being asked.

## Related

- [`handoff`](../handoff/README.md) — the agent/conversation-state
  counterpart; use that when a session, not a person, is picking up the work.
- [`repo-showcase`](../repo-showcase/README.md) — the public-facing
  counterpart; use that for a stranger landing on the repo, not a teammate
  joining the team.
- [`sitrep`](../sitrep/README.md) — a live "right now" status check, not a
  document.

## Prereqs

`gh`, optional, for open issues (the task list is asked from you without it).
