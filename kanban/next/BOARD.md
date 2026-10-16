# Board reference

Shared by every skill and agent that calls `gh`, reads or moves a card. Single source of truth: other files point here instead of repeating it.

## Target repo

Resolve once, before any other `gh` call:

```
gh repo view "$(git remote get-url origin)" --json nameWithOwner,isFork,parent
```

Name `origin`: on a fork clone a bare `gh repo view`, and any `gh` call without a repo, resolves to the `upstream` remote, i.e. the parent. Fails → stop and say why: `origin` isn't a GitHub remote, or `gh` isn't authenticated (`gh auth status`).

- `<owner>/<repo>` = `nameWithOwner`. Pass it on every `gh` call that takes one: `-R <owner>/<repo>` (`issue`, `pr`, `label`, `run`, `workflow`, `release`); `gh project` takes `--owner <owner>` (`item-edit` takes none: its ids come from that owner's lookup); `gh api` uses explicit `repos/<owner>/<repo>/…` paths (graphql: `owner:`/`name:` from it); `gh repo view`/`edit` take it positionally.
- **Fork** (`isFork` true): before the first write (issue, comment, label, card move, PR, repo edit), stop and ask which repo to write to: the fork `<owner>/<repo>` or the parent `<parent.owner.login>/<parent.name>`. Write to the parent only after an explicit yes naming it; that repo is then the target for writes. Unattended with no answer in the brief → write nothing to GitHub and say so in the handoff. Reading the parent for context (its issues, PRs, CI) is fine.
- Not a fork: unchanged, apart from the explicit `-R`.

## Find the board

`gh project list --owner <owner> --format json` (`<owner>` per Target repo) returns every project the owner has. Match by title (`<repo> Board`, as `kanban-setup` names it) or by items linking this repo. One match: use it. Several: ask. None, in order:

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
gh label create status:<name> --color <hex> --force -R <owner>/<repo>
gh issue edit <n> -R <owner>/<repo> --remove-label status:<old> --add-label status:<new>
```

## Transitions

| Event | Who | Status |
|---|---|---|
| Branch created | `pair` / `implementer` | In Progress + comment "Started on branch `<b>`" |
| Session ends complete | `session-handoff` | In Review |
| Verified, merged | `update-progress` | Done, issue closed |
| Verified, not merged | `update-progress` | In Review + comment |
| New issue (divide, consult-plan) | that skill | Todo |

A board error never blocks the task: note it and carry on.
