# wayfinder

*Adapted from Matt Pocock's `wayfinder` (MIT): GitHub Issues only, our ticket types, smart-zone ticket size, and a hand-off to `divide`. `SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Plans an effort too big for one session. It charts a **map** (a GitHub issue labelled `wayfinder:map`) of **decision tickets** (its sub-issues), then resolves one ticket per session until nothing is left to decide. When the way is clear it hands off to `divide`, which turns the destination into board issues.

## When to use

- A loose idea that needs several sessions of deciding before anyone can build it: a rewrite, a migration, a new product area.
- You can't yet list the work, only the questions in the way.
- Not for work you can already split into tasks: use [`divide`](../kanban/divide/) directly. Not for one decision: use [`grill-docs`](../grill-docs/).

## How to invoke

User-invoked only (`disable-model-invocation: true`):

- `/wayfinder <loose idea>` charts a new map.
- `/wayfinder <map # or URL> [ticket # or name]` works the next frontier ticket (or the one you name).

## How it works

1. **Chart**: reads the baseline (open issues, roadmap, decisions doc) as grilling context; if an open issue already covers the effort, asks whether to turn it into the map (off the board, `status:*` removed) or close it pointing at the map. Then grills you to name the destination, then grills breadth-first for the open decisions. Creates the map issue (Destination, Notes, Decisions so far, Not yet specified, Out of scope), creates the tickets it can phrase now as sub-issues, then wires blocking with GitHub's issue-dependencies API (`Blocked by: #n` body lines if that API is unavailable). Fires one `general-purpose` subagent per research ticket.
2. **Work**: loads the map, picks the first open, unblocked, unassigned ticket (a ticket you name that is claimed by someone else or blocked: it asks first), assigns it to you (the claim), and resolves it by type:
   - `wayfinder:research`: a subagent with web search; findings go in the resolution comment (long ones split over several comments, or a committed file if the repo tracks it; a gist only on your yes naming its content and destination; never a link to an untracked file).
   - `wayfinder:prototype`: a rough artifact you react to, inline in the comment or a committed file (a gist only on your yes; one needing its own branch: it asks you).
   - `wayfinder:grilling`: runs `grill-docs`; transcript where `grill-docs` puts it, linked only once committed.
   - `wayfinder:task`: the manual work a decision waits on. If it needs you, you get a checklist; the ticket stays claimed and open until you report it done.
3. **Record**: resolution comment (canonical), close the ticket, one line in the map's Decisions so far, plus a decisions-doc row when the repo has one (grilling tickets skip it: `grill-docs` already wrote theirs, citing the ticket). New questions become tickets; fog that sharpened graduates; anything past the destination is closed as out of scope.
4. **Hand off**: when no tickets or fog remain, offers `divide` on the map, passing it the decision rows and resolution comments as detail. A roadmap line for the map or the old issue gets the children. The new board issues link back to the map, the map gets a `## Handed off` list and closes immediately (this replaces `divide`'s "offer to close the parent later").

## Design principles

- **Plan, don't do.** Tickets end in decisions, not deliverables; the urge to build means it's time to hand off.
- **Off the board.** Maps and tickets carry only `wayfinder:*` labels, never `status:*`, so `next`, the `planner` agent and `meta-orchestrator` skip them. Research runs only inside a wayfinder session.
- **One ticket per session** (research excepted), each sized to the ~75K-token smart zone (this repo's [`hooks/smartzone.py`](../hooks/smartzone.py) warns at that size when installed; the target repo doesn't need it).
- **Fog of war.** Only questions you can phrase precisely become tickets; the rest waits in Not yet specified.
- **Refer by name.** Tickets are named by title with the link inside, never a bare `#42`.

## Use cases

- Choosing a new storage layer: research tickets on candidate APIs, a task to get trial access, a grilling to pick one.
- Planning a v2 of a product area before any issue lands on the board.
- A data migration whose shape is unknown until someone looks at the data.

## Tips

- Run unblocked tickets in parallel sessions; the assignee is the claim, so sessions don't collide.
- Name skills every session should call in the map's Notes; each session reads them.
- A ticket's type lives in its label, not its body; relabel to change how it is resolved.
- Need to override "plan, don't do" for one effort? Say so in the map's Notes.
- The dependencies and sub-issue APIs take the issue's numeric `id`, not its number; the skill looks it up.

## Example

```
/wayfinder move the site from static HTML to a framework
```

Grills you to a destination ("a decision record naming the framework, with a migration outline divide can split"), then creates map #120 with tickets: "Which frameworks keep the slash prompt working?" (research), "Get a preview deploy for the top pick" (task, blocked by the research), and "Pick the framework" (grilling, blocked by both). A subagent resolves the research ticket in the same session. Next session, `/wayfinder 120` claims the task ticket.

## Related

- [`grill-docs`](../grill-docs/): how grilling tickets are resolved and recorded.
- [`divide`](../kanban/divide/): the hand-off from a clear map to board issues.
- [`meta-orchestrator`](../meta-orchestrator/): builds the board issues afterwards; skips `wayfinder:*`.
- [`next`](../kanban/next/): skips `wayfinder:*` issues.

## Prereqs

`gh` authenticated with issue write access on the repo, and `origin` on GitHub; [`grill-docs`](../grill-docs/) installed alongside it. On a fork it asks which repo to write to (fork issues off: it reads the parent).
