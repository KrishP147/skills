# Reply and resolve

Reply to a thread (input takes `pullRequestReviewThreadId` + `body`, not `id`):

```
gh api graphql -f query='
mutation($id:ID!,$body:String!){
  addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$id, body:$body}){ comment{ url } }
}' -F id=<threadId> -F body="Fixed in <sha>: <one line>"
```

Resolve:

```
gh api graphql -f query='
mutation($id:ID!){ resolveReviewThread(input:{threadId:$id}){ thread{ isResolved } } }' -F id=<threadId>
```

Replies and resolves go to the PR's repo, the `<o/r>` named at the gate. The PR's opener or anyone with write access to the base repo can resolve, so on your own fork PR you usually qualify. Try it; on failure, say so and leave the thread for a maintainer.

Bot re-trigger (fresh yes only): `gh pr comment <n> --repo <o/r> --body "@coderabbitai review"`. Bots are often disabled for external contributors on fork PRs; say so instead of waiting.
