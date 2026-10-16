---
name: spend-gate
description: Gate any billable action (GPU pods/instances, paid APIs or tiers, cloud credits) behind a cost estimate, a live balance check, and an explicit yes for that action. Use before any create/deploy on a paid provider (runpodctl, vultr-cli, aws/gcloud/az, modal, provider MCP create/deploy/run/start/update), any paid API call, or when spend-guard blocks one.
---

Every billable action gets its own gate, every time: estimate → balance → explicit yes → log. A budget, a spend cap, or an earlier "go ahead with the plan" is context, not approval.

1. **Classify**: pod/instance creation, paid deploys, MCP create/deploy/run/start/update tools on a paid provider (e.g. job submits, endpoint updates, pod start), per-token or per-request paid APIs. Unsure → treat as billable.
2. **Estimate**: unit price × hours/tokens/requests. Prefer the tool's own quote or dry run; else the provider's pricing page, cited with URL and read date. Remembered prices don't count.
3. **Balance**: read-only billing/credit call where one exists (`list-billing`, `get-account`). Read-only calls only.
4. **Gate**: show the command, unit price + source, estimated total, live balance. Wait for an explicit yes to *this* action, repeats of approved actions included.
5. **Log** before running, in `skilleddocs/spend.md` (create with header):
   ```markdown
   | when (local) | amount | purpose | price source | resource id |
   |---|---|---|---|---|
   ```
   Fill the resource id into the same row once known. Untracked → exclude `skilleddocs/` per [TRACKING.md](../handoff-auto/TRACKING.md) (it also covers the `pip install .` hazard).
6. **Run**, then for anything that bills while idle (pod, instance, endpoint, volume): give the teardown or auto-stop now, and remind again when the work is done.

Blocked by the spend-guard hook → [HOOK.md](HOOK.md).
