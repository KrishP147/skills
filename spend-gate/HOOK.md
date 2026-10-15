# When spend-guard blocks

`hooks/spend-guard.py` (optional `PreToolUse` hook) blocks known billable commands and MCP calls. A block is the hook working.

After the gate's explicit yes (never before; the hook can't tell whether you asked):

- **Approval file** (works for MCP calls too): `mkdir -p skilleddocs/spend-approvals && touch skilleddocs/spend-approvals/<label>`. One-shot: the hook consumes the first file it finds and allows the next matching action. Name and contents are just audit trail; copy the `spend.md` row into it.
- **Single Bash command**: prefix `SPEND_GATE_APPROVED=<label> <command>`. An `export` in another Bash call doesn't reach the hook.
