# Adding "In Review" to an existing Status field

`gh project field-create` only makes new fields; it can't add an option to the existing Status field. Use `updateProjectV2Field`, which **replaces** the option list: pass every existing option back with its `id` (keeps cards already set to it), plus the new one without an `id`.

```
gh api graphql -f query='
mutation {
  updateProjectV2Field(input: {
    fieldId: "<status-field-id>",
    singleSelectOptions: [
      {id: "<todo-id>", name: "Todo", color: GRAY, description: ""},
      {id: "<in-progress-id>", name: "In Progress", color: YELLOW, description: ""},
      {name: "In Review", color: PURPLE, description: ""},
      {id: "<done-id>", name: "Done", color: GREEN, description: ""}
    ]
  }) { projectV2Field { ... on ProjectV2SingleSelectField { id options { id name } } } }
}'
```

IDs come from `gh project field-list <number> --owner <owner> --format json`. Prefer not to script it → tell the user to add the option by hand (project UI → Status field → edit → add option).
