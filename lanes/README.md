# lanes

*`SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Sets how many issues a [`meta-orchestrator`](../meta-orchestrator/) run works on at once. It predicts which files each queued issue will touch, groups issues that share files into the same **lane**, proposes a lane count with a cost line, and on your yes writes the lanes into the run's `scope.md`.

## When to use

- Starting a meta-orchestrator run: setup calls it when it reaches `parallel:`.
- "Run 3 at a time", "go faster", "more lanes" mid-run (`/lanes increase`).
- "Too many conflicts", "slow down", "fewer lanes" (`/lanes decrease`).
- Not for one task or a session without an orchestrator: there is no merge gate to keep parallel work safe, so it says so and offers to start a run.

## How to invoke

```
/lanes <n> | increase | decrease
```

- `/lanes 3`: regroup the queue into 3 lanes.
- `/lanes increase` / `decrease`: usually ±1, chosen and explained by the model.

Also model-invocable: meta-orchestrator's setup calls it for `parallel:`.

## How it works

1. **Checks for a run.** No `skilleddocs/orchestrator/scope.md` → explains that lanes only exist inside a meta-orchestrator run and offers to start one.
2. **Predicts file sets.** For each queued issue:
   - paths named in the issue
   - its area labels (only when it names no paths)
   - a quick `git grep` for what it mentions
   - Guesses are flagged as uncertain.
3. **Groups.**
   - Issues whose file sets overlap share a lane, in queue order; the groups left are the independent streams.
   - Lanes get area names (`site`, `hooks`), not numbers.
4. **Picks the count.**
   - Asking for more lanes than there are independent streams, or more than 4, gets questions: a best-guess grouping and the options, never a silent cap.
   - `increase` usually adds one by splitting the longest lane on file-disjoint issues.
   - `decrease` merges two colliding lanes, or folds the shortest into the nearest.
5. **Proposes.**
   - Lanes, their issues and areas, why, and a cost line ("3 lanes ≈ 3× tokens/hour, about the same per issue", plus a number when the ledger has token counts).
   - You can pin an issue to a lane, rename a lane, or move an issue before you say yes.
6. **Writes.** `parallel:` and a named `lanes:` map into `scope.md`, plus a ledger entry.
7. **Takes effect at the orchestrator's next loop.**
   - Running agents are never killed.
   - A removed lane finishes its current issue and its remaining issues move to other lanes.

## Design principles

- **Lanes are file-disjoint or they are one lane.** Two agents editing one file in parallel produce a merge conflict the gate has to unpick; grouping by predicted files avoids it up front.
- **Ask, don't cap.** Past the number of independent streams, or past 4, more lanes mostly add idle or colliding agents; the skill says so and lets you choose.
- **Changes are gentle.** A new count applies at the next loop and never throws away in-flight work.

### Tradeoffs

- **Tokens and rate limits grow linearly.** N lanes burn about N× tokens per hour and hit rate limits N× sooner; cost per issue stays about the same.
- **Needs file-disjoint work.** A queue where most issues touch the same few files has one real stream, however many lanes you ask for.
- **Faster context fill.** The orchestrator tracks every lane's agents and reports, so its context fills faster and it hands off to a fresh orchestrator sooner.
- **The merge gate is serial.** Every lane's work passes through one orchestrator's tests and merges; past about 3 lanes, lanes queue at the gate instead of going faster.

## Use cases

- A mixed backlog (site, hooks, docs) cleared three streams at a time.
- Dropping to one lane when two lanes keep colliding on a shared file.
- Adding a lane mid-run after a batch of new, unrelated issues lands.

## Tips

- Area labels on issues make the predictions much sharper; unlabeled issues with no named paths are flagged uncertain.
- Pin an issue you know touches a shared file to the lane that owns that file.
- New issues filed mid-run join a lane by the same overlap rule; the lane count only changes through `/lanes`.
- Start with 2 on a new repo, watch the ledger for conflicts, then `/lanes increase`.

## Example

Three lanes from a mixed queue:

```transcript
> /lanes 3
⏺ Read(skilleddocs/orchestrator/scope.md)
  ⎿ parallel: 1, queue: #41 #43 #44 #45 #46 #47 #48
⏺ Bash(gh issue view 41 --json body,labels … gh issue view 48 --json body,labels)
⏺ Bash(git grep -l "build_counts\|spend_guard\|Prereqs")
  ⎿ site/build.py
    hooks/spend_guard.py
    README.md
⏺ Predicted file sets: #41 #44 #47 site/; #43 #46 hooks/; #45 README.md; #48 docs label only (uncertain).
  3 independent streams.
  Lanes: 3 (was 1)
    site:   #41 #44 #47        site/, site/build.py
    hooks:  #43 #46            hooks/
    docs:   #45 #48 (?)        README.md, CONTRIBUTING.md
  Why: site and hooks share no files; #48 is guessed from its label, so it goes with the other docs issue.
  Cost: 3 lanes ≈ 3× tokens/hour, about the same tokens per issue. ≈ 1.1M tokens/hour (ledger: ~370k per issue).
  Change anything? You can pin an issue to a lane, rename a lane, or move an issue.
> rename docs to readme, then yes
⏺ Edit(skilleddocs/orchestrator/scope.md)
  ⎿ parallel: 3
    lanes: {site: [41, 44, 47], hooks: [43, 46], readme: [45, 48]}
⏺ Bash(git commit -m "docs(skilleddocs): ledger 012" && git push)
⏺ Written. The orchestrator picks up 3 lanes at its next loop; the issue in flight keeps running.
```

Asking for more lanes than the queue supports:

```transcript
> /lanes 6
⏺ Predicted file sets: #50 #51 #53 src/api/; #52 #54 src/ui/ (#54 uncertain).
⏺ Only 2 independent streams found (api, ui), and 6 is past 4, where the single merge gate becomes the bottleneck.
  Best guess: 2 lanes
    api:  #50 #51 #53        src/api/
    ui:   #52 #54 (?)        src/ui/
  Options:
    (a) 2 lanes (Recommended)
    (b) 3 lanes: split api on #53, which risks a conflict on src/api/routes.py
    (c) 6 lanes anyway: 4 sit idle until new independent issues arrive, ≈ 6× tokens/hour
> a
⏺ Edit(skilleddocs/orchestrator/scope.md)
⏺ Written: 2 lanes, ledger 013.
```

Mid-run, after two collisions:

```transcript
> /lanes decrease
⏺ Lanes api and ui both have upcoming issues touching src/shared/types.ts (#57, #58).
  Proposal: 1 lane (was 2), api then ui in queue order. Cost: ≈ 1× tokens/hour.
  The ui lane finishes #56, which is in flight; #58 moves to api.
> yes
⏺ Written, ledger 019. Applies at the next loop.
```

## Related

- Configures [`meta-orchestrator`](../meta-orchestrator/), whose setup calls it for `parallel:`.
- Each lane runs [`pair`](../pair/)'s worktree pattern with its own `manager` agent.
- [`session-bridge`](../session-bridge/) checks overlap between separate sessions, not lanes of one run.

## Prereqs

A meta-orchestrator run (`skilleddocs/orchestrator/scope.md`); `gh` to read issues.
