# When spend-guard blocks

`hooks/spend-guard.py` (optional `PreToolUse` hook) blocks known billable commands and MCP calls. A block is the hook working.

After the gate's explicit yes (never before; the hook can't tell whether you asked):

- **Approval file** (works for MCP calls too): `mkdir -p skilleddocs/spend-approvals && touch skilleddocs/spend-approvals/<label>`. One-shot: the hook deletes the first file it finds and allows the next matching action, so the file is no record; the log is the `skilleddocs/spend.md` row. Names starting with `.` (`.gitkeep`) never count. A call with two billable commands is refused even with a file: run them as separate calls. Untracked → exclude `skilleddocs/` per [TRACKING.md](../handoff-auto/TRACKING.md) (it also covers the `pip install .` hazard).
- **Single Bash command**: prefix `SPEND_GATE_APPROVED=<label> <command>` (or `env SPEND_GATE_APPROVED=<label> <command>`). An `export` doesn't count.
- **Single PowerShell command**: start it with `$env:SPEND_GATE_APPROVED='<label>'; <command>`. Leading only, literal value (no `$null`/`$var`); a mid-string assignment or a Bash-style prefix does not count.
- Both inline forms cover one simple command whose program is the billable one: no `;`, `&&`, `||`, `|`, `&`, newline, `( )`, `$(...)`, backticks, and no wrapper (`bash -c`, `xargs`, `sudo`). Otherwise use one call per billable command, or the file.
- Indirect forms block too and only the file approves them: an alias, function or variable naming a billable CLI (`X=runpodctl; $X create pod`, `Set-Alias`, `& $X`), `Start-Process`, quoting or base64 tricks, REST/GraphQL writes (`curl -X POST rest.runpod.io/v1/pods`, a GraphQL deploy/rent/resume mutation), SDK one-liners (`python -c "import runpod; runpod.create_pod(...)"`), and a variable call target or verb whose value the hook can't read (`$X create pod`, `runpodctl $VERB`) in a command that names a billable program. Prefer the literal command; see the skills repo's `hooks/README.md` (spend-guard section).

A command that only mentions a billable command (`grep`, `echo`, a `git commit -m` message) also trips the hook; this is accepted tripwire behaviour. Rephrase it (e.g. write the text to a file first) or approve it.
