# Board reference

Shared by every skill and agent that reads or moves a card. Single source of truth: other files point here instead of repeating it.

## Find the board

`gh project list --owner <owner> --format json` returns every project the owner has. Match by title (`<repo> Board`, as `kanban-setup` names it) or by items linking this repo. One match: use it. Several: ask. None, in order:

1. **Labels**: `status:todo`, `status:in-progress`, `status:in-review`, `status:done`.
2. **Roadmap doc** (`ROADMAP.md`, `docs/roadmap.md`): its execution-order section is the queue; no card to move.
3. Nothing: tell the user to run `/kanban-setup`.

## Move a card (Projects v2)

IDs are opaque; look them up, never guess:

```
gh project field-list <number> --owner <owner> --format json      # Status field id + option ids
gh project item-list <number> --owner <owner> --format json       # item id
gh project item-edit --id <item> --field-id <field> --project-id <project> --single-select-option-id <option>
```

`item-list` is eventually consistent and can come back empty for items on the board. Then get the item id via:

```
gh api graphql -f query='query{repository(owner:"<owner>",name:"<repo>"){issue(number:<n>){projectItems(first:5){nodes{id project{id number}}}}}}'
```

Adding an issue: `gh project item-add` leaves Status empty, so follow it with `item-edit` to set Status.

## Move a card (labels)

Create the label right before first use, with its fixed color so repeats are no-ops:

| Label | Color |
|---|---|
| `status:todo` | EDEDED |
| `status:in-progress` | FBCA04 |
| `status:in-review` | 5319E7 |
| `status:done` | 0E8A16 |

```
gh label create status:<name> --color <hex> --force
gh issue edit <n> --remove-label status:<old> --add-label status:<new>
```

## Transitions

| Event | Who | Status |
|---|---|---|
| Branch created | `pair` / `implementer` | In Progress + comment "Started on branch `<b>`" |
| Session ends complete | `session-handoff` | In Review |
| Verified | `update-progress` | Done, issue closed |
| New issue (divide, consult-plan) | that skill | Todo |

A board error never blocks the task: note it and carry on.
