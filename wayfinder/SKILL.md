---
name: wayfinder
description: Plan an effort too big for one session as a map of decision tickets (GitHub issue + sub-issues) and resolve them one per session until the way is clear, then hand off to divide.
disable-model-invocation: true
---

Adapted from Matt Pocock's `wayfinder` skill (MIT, see THIRD_PARTY_LICENSES.md); tracker, ticket types, ticket size, research output and the hand-off to `divide` differ.

An idea has arrived that no single session can hold, and the way from here to the **destination** is still fogged. This skill charts that way as a **map** on GitHub Issues, then works its **decision tickets** (questions answered by a decision, not slices of a build) one at a time until nothing is left to decide.

Naming the destination is the first act: it fixes the scope and shapes every ticket. It may be a spec, a decision to lock, or a change such as a data migration. The map fits any domain.

## Plan, don't do

Each ticket resolves a decision; the map is done when the way is clear. The urge to start building means you've reached the map's edge: hand off (see [Hand off](#hand-off)). The map's **Notes** may override this for one effort; absent that, produce decisions, not deliverables.

## Refer by name

Every map and ticket is an issue, so it has a **name**: its title. In anything the human reads, use the name, with the link riding inside it (`[Pick the queue](https://github.com/<o>/<r>/issues/42)`), never a bare `#42`.

## The map

One GitHub issue labelled `wayfinder:map`, the canonical artifact. Its tickets are its **sub-issues**. The map is an **index**: it gists each decision and links the ticket that holds it, never restating the detail.

Body (open tickets are not listed; they are open sub-issues, found by query):

```markdown
## Destination

<one or two lines: what reaching the end of this map looks like>

## Notes

<domain; skills every session should call; standing preferences>

## Decisions so far

- [<closed ticket title>](https://github.com/<o>/<r>/issues/<n>): <one-line gist>

## Not yet specified

<!-- fog: in scope, not yet sharp enough to ticket -->

## Out of scope

<!-- ruled beyond the destination; never graduates -->
```

## Tickets

A ticket is a sub-issue of the map whose body is the question, sized to fit one session inside the smart zone (~75K tokens, `SMARTZONE_TOKENS` in `hooks/smartzone.py`):

```markdown
## Question

<the decision or investigation this ticket resolves>

Map: <map link>
```

Each ticket carries exactly one `wayfinder:<type>` label: `research`, `prototype`, `grilling` or `task`. `wayfinder:*` labels are the only labels a map or ticket carries: never `status:*`, never put them on the board. `next`, the `planner` agent and `meta-orchestrator` skip anything labelled `wayfinder:*`.

**Claim** a ticket by assigning it to yourself first, before any work (`gh issue edit <n> --add-assignee @me`), so parallel sessions skip it. Open + unassigned = unclaimed.

**Blocking** uses GitHub's native issue dependencies, so the frontier shows in GitHub's own UI. A ticket is **unblocked** when every ticket blocking it is closed; the **frontier** is the open, unblocked, unclaimed sub-issues.

The answer is never in the body; it's recorded on resolution. Assets made while resolving (prototypes, long findings) are linked, not pasted.

### GitHub operations

The REST APIs take the issue's numeric `id` (`gh api repos/<o>/<r>/issues/<n> -q .id`), not its number.

```
gh label create wayfinder:<type> --color <hex> --force                    # before first use
gh api repos/<o>/<r>/issues/<map>/sub_issues -X POST -F sub_issue_id=<id> # attach ticket to map
gh api repos/<o>/<r>/issues/<map>/sub_issues                              # list tickets (state, assignees, labels)
gh api repos/<o>/<r>/issues/<n>/dependencies/blocked_by -X POST -F issue_id=<blocker id>
gh api repos/<o>/<r>/issues/<n>/dependencies/blocked_by                   # blockers + their state
```

Dependencies API unavailable (404/403) → add a `Blocked by: #<n>` line per blocker to the ticket body and read those lines instead. Say which mode the map uses in its Notes.

## Ticket types

**HITL** tickets resolve only through a live exchange with the human; never answer their side yourself. **AFK** tickets are driven by the agent alone.

- **Research** (AFK): surface a fact a decision waits on (docs, third-party APIs, knowledge bases, the web). Spawn a `general-purpose` subagent with web search; it returns findings, you post them. Long findings → a gist or a file under `skilleddocs/`, linked from the comment. No branches.
- **Prototype** (HITL): make a cheap, rough, concrete artifact to react to (outline, stub, sketch UI or logic) when "how should it look/behave" is the question. Link it as an asset.
- **Grilling** (HITL): the default. Call the Skill tool with `"grill-docs"`; its transcript goes to `skilleddocs/grills/<date>-<ticket-slug>.md`. The resolution comment gists the answers and links the transcript.
- **Task** (AFK where possible, else a precise checklist for the human): manual work a decision is blocked on (sign up for a service, get access, move data to see its shape). The one type that *does*; it earns its place by unblocking a decision. Record what was done and any resulting facts (where credentials live, new URLs, row counts).

## Fog of war

Don't chart what you can't see yet. The **Not yet specified** section holds decisions you can tell are coming but can't phrase yet. Resolving a ticket clears fog ahead of it; graduate what's now specifiable into fresh tickets.

**Fog or ticket?** Can you state the question precisely now (not answer it)? Yes → ticket, even if blocked. No → fog. Don't pre-slice fog into ticket-sized pieces; one patch may become several tickets or none.

Not yet specified excludes what's decided, what's ticketed, and what's out of scope.

## Out of scope

The destination fixes the scope. Work beyond it is not fog: it goes in **Out of scope** and never graduates (it returns only as a fresh effort if the destination is redrawn). A ticket found to sit past the destination: **close** it and add one line to Out of scope (gist, why, link). It stays out of Decisions so far.

## Invocation

Two modes. **Never resolve more than one ticket per session**, research excepted.

### Chart the map

User invokes with a loose idea.

1. **Name the destination.** Call the Skill tool with `"grilling"` to pin it down. It fixes the scope, so settle it first.
2. **Map the frontier.** Grill again, **breadth-first**: across the whole space, surfacing the open decisions and the first takeable steps. **No fog surfaced** (the whole thing fits one session) → no map needed; stop and ask the user how to proceed.
3. **Create the map** (label `wayfinder:map`): Destination and Notes filled, Decisions so far empty, fog sketched into Not yet specified.
4. **Create the tickets you can specify now**, attach each as a sub-issue, then wire blocking in a **second pass** (ids must exist first). Write cross-references in that pass too, with real numbers: a placeholder `#<n>` auto-links to an unrelated issue.
5. **Fire research.** One `general-purpose` subagent per new `research` ticket, in parallel; post each one's findings as that ticket's resolution (see Work through the map, step 4).
6. Stop. Charting is one session's work; it hand-resolves nothing.

### Work through the map

User invokes with a map (URL or number), optionally a ticket. Without one, you pick.

1. Load the **map** body only, not every ticket.
2. Choose: the named ticket, else the first frontier ticket in sub-issue order. **Claim it** before any work.
3. Resolve it as its `wayfinder:<type>` label says (the body never states the type). Fetch related or closed tickets on demand; call any skills the Notes name.
4. Record: post a **resolution comment** (canonical), **close** the ticket, add a line to the map's Decisions so far. If `skilleddocs/decisions.md` exists, also append a row in its format (next `D<k>`, source = ticket link).
5. Add newly surfaced tickets (create, attach, then wire). Graduate fog the answer made specifiable, removing it from Not yet specified. Rule out-of-scope tickets out rather than resolving them. Update or close tickets the decision invalidated.

Other sessions may be working unblocked tickets in parallel: re-read before editing the map body.

## Hand off

When no open tickets and no fog remain, offer `divide` on the map issue to turn the destination into session-sized board issues for `pair` or `meta-orchestrator`. On a yes:

- each new issue links back to the map in its body (divide's `Part of #<map>`), and carries no `wayfinder:*` label;
- the map gets a `## Handed off` section listing them by name (divide's task list goes there);
- close the map: its planning is done, whatever happens to the board issues.
