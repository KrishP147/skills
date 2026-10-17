# find-me-a-skill

*`SKILL.md` is the prompt Claude follows; this file is for you.*

Works on its own.

## What it does

Tells you which skill or sample workflow fits a task, which model and
`/effort` level to run each step at, where you'll be asked to decide
something, and the exact commands to paste. It suggests and stops: it
never starts the work itself.

## When to use

- "Which skill should I use for this", "find me a skill", "how should I run
  this", "what model / effort for this".
- At the start of a session, with no task in mind: it reads the top board
  tasks and suggests one option for each.
- Not for running anything: paste its commands to do that. Not for a list
  of every skill either; that's the site's home page or the
  [`CATALOG.md`](CATALOG.md) it reads.

## How to invoke

```
/find-me-a-skill <task>
/find-me-a-skill
```

Model-invocable, so the trigger phrases above work too. With no text it
uses the conversation's goal, then the board.

## How it works

1. **Task.**
   - The text after the command.
   - Else the goal of the conversation so far.
   - Else the top 1-3 tasks on the repo's board, found the way
     [`next`](../kanban/next/) does (its `BOARD.md`).
   - No repo or no board: it asks what the task is.
2. **Candidates.** Every skill Claude can see in this session (this
   collection, plugins, built-ins) plus the entries and sample workflows in
   [`CATALOG.md`](CATALOG.md).
3. **Options, at most 3.**
   - The primary pick is the best fit from everything installed.
   - When an entry or workflow from this collection fits and isn't already
     the pick, it adds that too.
   - Any option from the catalog is labelled "from your collection".
   - A catalog option is labelled "not installed", with the install command,
     when it isn't in this session's skill list, in
     `~/.claude/skills/<name>/` or in the plugin's install dir. With no
     plugin installed, that last check is skipped and the reply says so.
     User-only skills never show in the session's list, installed or not.
   - Plugin installs get the `krish:` prefix on commands.
   - Nothing fits: it says so, names the nearest option and suggests doing
     the task directly.
4. **Model and effort per step.**
   - Starts from `CATALOG.md`'s defaults. For a large or risky task, effort
     goes up first, and the model only once effort is at `max`. A small task
     works the same way in reverse.
   - A skill that isn't in the catalog shows its origin (plugin or built-in)
     and an `estimate` label.
5. **Reply.** Per option: why it fits, the steps with model and effort,
   the points where you decide, then `/model`, `/effort` and the invocation
   for option 1, ready to paste.

Reads: `CATALOG.md`, this conversation, the board (via `gh`) in board mode.
Writes: nothing.

## Design principles

- **Suggest, don't run.** It runs on Haiku at low effort, so it must not
  start heavy work by accident; you start it by pasting the commands.
- **One generated catalog.** `CATALOG.md` is generated from the repo
  (`python scripts/site_catalog.py`), and a test fails when it drifts. So
  the skill works offline in any repo, and its defaults match the site's
  "suggested model · effort" chips.
- **Broad first, own collection second.** The best tool for the task wins
  even when it's a plugin or built-in; this collection gets a second slot
  only when it genuinely fits.

## Use cases

- You know the task but not which skill or sample workflow covers it.
- Picking a cheaper model or lower effort for a routine step, and a stronger
  one for the step that needs judgment.
- Starting a session cold: "what should I do next, and how should I run it".

## Tips

- The `model: haiku` and `effort: low` frontmatter applies for this turn
  only. If your setup ignores the override, run `/model haiku` first, then
  switch to the suggested model before pasting the commands.
- Say the size or risk ("big refactor", "one-line fix") and the suggestion
  moves a tier or level accordingly.
- Defaults live in `site/data/meta.json` (`model_effort`). After editing
  them, or any skill description or workflow, regenerate the catalog with
  `python scripts/site_catalog.py`.

## Example

Three runs, each traced to entries in [`CATALOG.md`](CATALOG.md): a task in
words, an idea to test, and an empty prompt that falls back to the board.

```transcript
> /find-me-a-skill address the review comments on PR 12
⏺ Read(CATALOG.md)
  ⎿ | pr-watch | skill | sonnet | high | `/pr-watch` | Watch the user's open PRs to merge ... | pair-to-pr |
⏺ Task: address the review comments on PR 12
  1. pr-watch (skill, from your collection): reads every review thread, fixes the valid ones via pair, replies to or resolves the rest with evidence.
     Steps: /pr-watch (sonnet · high) -> pair -> manager agent (opus · high) -> implementer agent (sonnet · medium)
     You decide: each push, reply and resolve; a force push needs its own yes.
  Run option 1:
  /model sonnet
  /effort high
  /pr-watch 12
> /find-me-a-skill I want to stress-test an idea for a plugin system before anyone builds it
⏺ Read(CATALOG.md)
  ⎿ ### pitch-an-idea: Pitch an idea against the plan
⏺ Task: stress-test a plugin-system idea against the plan
  1. pitch-an-idea (workflow, from your collection): grills the idea one round at a time, then checks it against open issues and recorded decisions.
     Steps: you: type /grill-me -> /grill-me (opus · high) -> /grilling (opus · high) -> you: answer each round -> /consult-plan (opus · high) -> you: fits, conflicts or extends
     You decide: every round's answer; what happens to the idea.
  2. grill-docs (skill, from your collection): the same interview, recorded to skilleddocs/ as it settles.
     Steps: /grill-docs (opus · high)
  Run option 1:
  /model opus
  /effort high
  /grill-me a plugin system for the CLI
> /find-me-a-skill
⏺ No task in the prompt or the conversation: reading the board.
⏺ Bash(gh project list --owner @me --format json)
  ⎿ myrepo Board (#3)
⏺ Bash(gh project item-list 3 --owner @me --format json)
  ⎿ Todo: #31 Security pass on the auth refactor branch (size M), #32 Rewrite the sync engine (size L)
⏺ #31 Security pass on the auth refactor branch
  1. security-review (skill, built-in): reviews the branch's pending changes for security issues.
     Steps: /security-review (opus · high, estimate)
  2. gap-scan (skill, from your collection): ranked, evidence-cited gaps report to turn into issues.
     Steps: /gap-scan (opus · high) -> you: pick the items worth doing
  #32 Rewrite the sync engine
  1. divide (skill, from your collection): size L, too big for one session; splits it into session-sized issues.
     Steps: /divide (opus · high, up from medium for size L) -> you: approve the split
  Run for #31:
  /model opus
  /effort high
  /security-review
```

## Related

- [`next`](../kanban/next/): the board lookup it reuses when you give no
  task.
- [`pair`](../pair/) and [`meta-orchestrator`](../meta-orchestrator/): what
  most implementation suggestions end up pasting.
- [`grilling`](../grilling/): the usual pick when the task isn't clear
  enough to choose a skill for.

## Prereqs

None for a task in words. Board mode needs `gh` with the `project` scope,
as [`next`](../kanban/next/) does.
