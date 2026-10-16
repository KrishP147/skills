# Worktree teardown

Run after the PR merges, from any directory. Untracked and git-excluded files in a worktree are deleted by `git worktree remove` without a word, so every record left in the worktree's doc folders goes to the main checkout first; a linked `node_modules`/`.venv` makes `git worktree remove` or any recursive delete (`rm -rf`, `Remove-Item -Recurse`) empty the main checkout's copy, so links go before that.

Fill in:
- `<wt>`, `<main>`: absolute paths of the worktree and the main checkout.
- `<reg>`: the decisions register, relative to the repo root with `/` (the one `AGENTS.md`/`CLAUDE.md` names; else `docs/decisions.md`; else `skilleddocs/decisions.md`).
- `<more>`: each other doc folder `AGENTS.md`/`CLAUDE.md` names (handoffs, decisions), quoted, relative to the root; empty when none.

## 1. Records into main

Every untracked or ignored file under `skilleddocs/` and `<more>` (dated handoffs, `HANDOFF.md`, the register, anything else) goes to the same subpath in main:
- main lacks it → moved (`mv -n` / `Move-Item`, never overwriting).
- it is `<reg>` and main has one → each worktree row whose id (`A-…`, `D…`: first cell, a capital letter first and a digit last, so the header is skipped) main lacks is appended to main's; a row main already has verbatim is skipped; when every row is in main the worktree copy is deleted. A row whose id main holds with different text → `CLASH`, the worktree copy stays.
- any other file main already has → `CLASH`, left in the worktree. Never overwrite: report both copies to the user.

A file left behind makes step 3 stop. In main, `update-progress` finds the dated handoffs and commits them per [TRACKING.md](../handoff-auto/TRACKING.md).

Git Bash or mac/linux:

```sh
wt="<wt>"; main="<main>"; reg="<reg>"
git -C "$wt" ls-files -o -z -- skilleddocs <more> | while IFS= read -r -d '' f; do
  if [ "$f" = "$reg" ] && [ -f "$main/$f" ]; then
    ok=1; [ -n "$(tail -c1 "$main/$f")" ] && echo >> "$main/$f"
    while IFS= read -r row; do
      id=$(printf '%s' "$row" | cut -d'|' -f2 | tr -d ' ')
      old=$(grep -E "^\| *$id *\|" "$main/$f")
      if [ -z "$old" ]; then printf '%s\n' "$row" >> "$main/$f"; echo "appended $id"
      elif [ "$old" != "$row" ]; then ok=0; echo "CLASH: $id differs in main"; fi
    done < <(grep -E '^\| *[A-Z][A-Za-z0-9-]*[0-9] *\|' "$wt/$f")
    [ $ok = 1 ] && rm "$wt/$f"
  elif [ -e "$main/$f" ]; then echo "CLASH: $f exists in main"
  else mkdir -p "$(dirname "$main/$f")" && mv -n "$wt/$f" "$main/$f" && echo "moved $f"; fi
done
```

PowerShell:

```powershell
$wt = '<wt>'; $main = '<main>'; $reg = '<reg>'
git -C $wt -c core.quotepath=off ls-files -o -- skilleddocs <more> | ForEach-Object {
  $f = $_; $src = Join-Path $wt $f; $dst = Join-Path $main $f
  if ($f -eq $reg -and (Test-Path $dst)) {
    $ok = $true; $have = Get-Content -Encoding UTF8 $dst
    if ((Get-Content -Raw $dst) -notmatch '\n$') { Add-Content -Encoding UTF8 $dst '' }
    foreach ($row in (Get-Content -Encoding UTF8 $src | Where-Object { $_ -cmatch '^\| *[A-Z][A-Za-z0-9-]*[0-9] *\|' })) {
      $id = ($row -split '\|')[1].Trim()
      $old = @($have | Where-Object { $_ -match "^\| *$([regex]::Escape($id)) *\|" })
      if ($old.Count -eq 0) { Add-Content -Encoding UTF8 $dst $row; "appended $id" }
      elseif ($old.Count -ne 1 -or $old[0] -cne $row) { $ok = $false; "CLASH: $id differs in main" }
    }
    if ($ok) { Remove-Item $src }
  } elseif (Test-Path $dst) { "CLASH: $f exists in main" }
  else { New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null; Move-Item $src $dst; "moved $f" }
}
```

## 2. Unlink deps

Removes the link only: Git Bash or mac/linux `rm "<wt>/.venv"` (no `-r`); PowerShell `cmd /c rmdir "<wt>\.venv"` (not `Remove-Item`). Same for `node_modules`.

## 3. Hard check, then remove

Stops on any dep link left (`-L` catches a dangling one) and on anything `git status` still lists under the doc folders, ignored files included:

Git Bash or mac/linux:

```sh
wt="<wt>"; main="<main>"
left=$(git -C "$wt" status --porcelain --ignored --untracked-files=all -- skilleddocs <more>)
if [ -e "$wt/.venv" ] || [ -L "$wt/.venv" ] || [ -e "$wt/node_modules" ] || [ -L "$wt/node_modules" ] || [ -n "$left" ]; then echo "STOP: left in $wt:"; echo "$left"; else git -C "$main" worktree remove "$wt"; fi
```

PowerShell:

```powershell
$wt = '<wt>'; $main = '<main>'
$left = git -C $wt status --porcelain --ignored --untracked-files=all -- skilleddocs <more>
if ((Get-ChildItem -Force $wt | Where-Object Name -in '.venv','node_modules') -or $left) { "STOP: left in ${wt}:"; $left } else { git -C $main worktree remove $wt }
```

STOP → leave the worktree and report what is left (link, `CLASH` file, unmerged rows). `git worktree remove` refuses (untracked or modified files elsewhere) → stop and report `git -C "<wt>" status --short`. Never `--force`.
