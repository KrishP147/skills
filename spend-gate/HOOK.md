# When spend-guard blocks

`hooks/spend-guard.py` (optional `PreToolUse` hook) blocks known billable commands and MCP calls. A block is the hook working.

After the gate's explicit yes (never before; the hook can't tell whether you asked):

- **Approval file** (works for MCP calls too): `mkdir -p skilleddocs/spend-approvals && touch skilleddocs/spend-approvals/<label>`. One-shot: the hook consumes the first file it finds and allows the next matching action. Name and contents are just audit trail; copy the `spend.md` row into it. Untracked → exclude `skilleddocs/` per [TRACKING.md](../handoff-auto/TRACKING.md) (it also covers the `pip install .` hazard).
- **Single Bash command**: prefix `SPEND_GATE_APPROVED=<label> <command>`. An `export` in another Bash call doesn't reach the hook.
- **Single PowerShell command**: start it with `$env:SPEND_GATE_APPROVED='<label>'; <command>`. Leading only, literal value (no `$null`/`$var`); a mid-string assignment or a Bash-style prefix does not count.
