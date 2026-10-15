---
name: pr-watch
description: Watch the user's open PRs to merge — read bot and human review threads, fix valid ones via pair, reply to or resolve the rest with evidence, report CI; every push, reply, and resolve gated on a yes. Use for "watch my PRs", "address the review comments", "drive this PR to merge".
argument-hint: "[PR # | owner/repo] [--once]"
---

You read every thread and check yourself. **Gate**: each push, reply, resolve, or bot re-trigger needs an explicit yes first; a force push needs `--force-with-lease` and its own fresh yes, every time.

No argument: all the user's open PRs. A PR # or `owner/repo` scopes it. `--once`: one pass, report, stop.

## 1. List

`gh search prs --author @me --state open --json number,title,url,repository,isDraft`, then per PR `gh pr view <n> --repo <o/r> --json headRefName,isCrossRepository`. Table: repo, #, title, branch, draft, fork.

## 2. Threads

```
gh api graphql -f query='
query($owner:String!,$repo:String!,$pr:Int!,$after:String){
  repository(owner:$owner,name:$repo){ pullRequest(number:$pr){
    reviewThreads(first:100,after:$after){ pageInfo{hasNextPage endCursor}
      nodes{ id isResolved isOutdated path line
        comments(first:20){ nodes{ author{login} body url createdAt } } } } } } }' \
  -F owner=<o> -F repo=<r> -F pr=<n>
```

Page until `hasNextPage` is false. Classify each unresolved thread, citing its URL:
- **valid**: the reviewer is right
- **outdated**: code has since changed (read the diff; `isOutdated` is only a hint)
- **disagree**: wrong or out of scope
- **question**: needs an answer, not code

## 3. CI

`gh pr checks <n> --repo <o/r> --json name,state,link,workflow`. A fork PR at `action_required` is waiting for maintainer approval, not failing; say so.

## 4. Fix

One `pair` call per PR on its existing head branch, every **valid** thread (path, line, body) as the task. Tell it the PR exists: no new PR, no push. disagree/question threads get replies, not diffs.

## 5. Gate, then push and reply

Show diff summary, commits, test result, and each drafted reply. Push and replies are separate yeses unless the user combines them. Then push, and reply to each thread with the fixing SHA or the reasoning ([MUTATIONS.md](MUTATIONS.md)).

Bot re-trigger (own fresh yes): [MUTATIONS.md](MUTATIONS.md).

Resolve (separate gate, name each thread and why) only threads you fixed or proved outdated. disagree and question threads stay open for the reviewer.

## 6. Watch

Until merged/closed or told to stop: `gh pr view <n> --repo <o/r> --json state,mergedAt,mergeable` via the Monitor tool or a bounded poll, re-running §2–3 each pass.

## 7. Log and end

Each pass → `skilleddocs/pr-watch/<local-date>-<repo>.md`: local time, PR, threads seen/fixed/replied/resolved (URLs), CI, every gate and the user's answer.

End with one line per PR, linked: **merged** (merge commit) / **waiting-on-maintainer** (approval, review, or a bot that won't run) / **needs-you** (open gate, a thread awaiting your answer, failing check).
