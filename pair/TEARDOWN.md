# Worktree teardown

Run after the PR merges, from any directory. Untracked and git-excluded files in a worktree are deleted by `git worktree remove` without a word, so every record left in the worktree's doc folders goes to the main checkout first; a linked `node_modules`/`.venv` makes `git worktree remove` or any recursive delete (`rm -rf`, `Remove-Item -Recurse`) empty the main checkout's copy, so links go before that.

Fill in:
- `<wt>`, `<main>`: absolute paths of the worktree and the main checkout.
- `<reg>`: the decisions register, relative to the repo root with `/` (the one `AGENTS.md`/`CLAUDE.md` names, nearest wins as in `grill-docs`; else `docs/decisions.md`; else `skilleddocs/decisions.md`).
- `<more>`: each other doc folder `AGENTS.md`/`CLAUDE.md` names (handoffs, decisions), quoted, relative to the root; empty when none.
- `<hand>`: the handoff folder (`AGENTS.md`/`CLAUDE.md`'s, else `skilleddocs/handoffs`), relative to the root.

## Register rows

The one format for an assumed decision (`A-n`) that any agent writes; others point here. One table row per decision, never a heading, prose or list item. Its cells are main's register header, in order: the brief passes that header as `register header:` (a worktree can't see main's untracked register). No register yet → `grill-docs`' header `| # | Date | Decision | Why | Source |`, and the row:

```markdown
| A-<k> | <local date> | <what> (open; would change it: <…>; undo cost: <…>) | <why> | #<issue> |
```

Another header → the same facts in its cells, same cell count; no `|` inside a cell. Ids: the brief's `first A-id`, counting up (`A-<k>`, or `A-<lane>-<k>` with parallel lanes, per `meta-orchestrator` §4).

## 1. Records into main

Every untracked or ignored file under `skilleddocs/` and `<more>` (dated handoffs, `HANDOFF.md`, the register, anything else) goes to the same subpath in main:
- main lacks it → moved (`mv -n` / `Move-Item`, never overwriting).
- `skilleddocs/HANDOFF.md` → moved to `<hand>/<YYYY-MM-DD>-<worktree folder>-handoff.md` (`-2`, `-3`… if taken), so it has an owner (`update-progress` treats it as a dated handoff) and no later `HANDOFF.md` clashes with it.
- it is `<reg>` and main has one → line by line, trailing `\r` ignored: blank lines, table separators and lines main already has are covered; a row ([Register rows](#register-rows): first cell a capital letter first, a digit last) whose id main lacks and whose cell count matches main's header is appended with an LF ending. Anything else stays: a row whose id main holds with other text (`CLASH`), a row with the wrong cell count, a heading, prose, a list item, a header that differs. The worktree copy is deleted only when nothing stays; else it is kept and `STOP` lists the lines left. Fix them (as rows) and rerun.
- any other file main already has → `CLASH`, left in the worktree. Never overwrite: report both copies to the user.

A file left behind makes step 3 stop. In main, `update-progress` finds the dated handoffs and commits them per [TRACKING.md](../handoff-auto/TRACKING.md).

Git Bash or mac/linux:

```sh
wt="<wt>"; main="<main>"; reg="<reg>"; hand="<hand>"
git -C "$wt" ls-files -o -z -- skilleddocs <more> | while IFS= read -r -d '' f; do
  if [ "$f" = "$reg" ] && [ -f "$main/$f" ]; then
    m="$main/$f"; left=""; [ -n "$(tail -c1 "$m")" ] && printf '\n' >> "$m"
    ncol=$(tr -d '\r' < "$m" | grep -m1 '^|' | tr -cd '|' | wc -c)
    while IFS= read -r l || [ -n "$l" ]; do
      l=${l%$'\r'}
      [ -z "${l//[[:space:]]/}" ] && continue
      tr -d '\r' < "$m" | grep -qxF -- "$l" && continue
      printf '%s\n' "$l" | grep -qE '^\|[-:| ]*\|$' && continue
      id=$(printf '%s\n' "$l" | sed -nE 's/^\| *([A-Z][A-Za-z0-9-]*[0-9]) *\|.*/\1/p')
      if [ -z "$id" ]; then left="$left$l"$'\n'
      elif tr -d '\r' < "$m" | grep -qE "^\| *$id *\|"; then left="$left$l   <- CLASH: $id differs in main"$'\n'
      elif [ $(printf '%s' "$l" | tr -cd '|' | wc -c) -ne $ncol ]; then left="$left$l   <- cell count differs from main's header"$'\n'
      else printf '%s\n' "$l" >> "$m"; echo "appended $id"; fi
    done < "$wt/$f"
    if [ -z "$left" ]; then rm "$wt/$f"; else echo "STOP: $f kept, lines not in main:"; printf '%s' "$left"; fi
  elif [ "$f" = skilleddocs/HANDOFF.md ]; then
    b="$main/$hand/$(date +%F)-$(basename "$wt")-handoff"; t="$b.md"; k=1
    while [ -e "$t" ]; do k=$((k+1)); t="$b-$k.md"; done
    mkdir -p "$main/$hand" && mv -n "$wt/$f" "$t" && echo "moved $f -> $t"
  elif [ -e "$main/$f" ]; then echo "CLASH: $f exists in main"
  else mkdir -p "$(dirname "$main/$f")" && mv -n "$wt/$f" "$main/$f" && echo "moved $f"; fi
done
```

PowerShell (writes UTF-8 without BOM and LF only):

```powershell
$wt = '<wt>'; $main = '<main>'; $reg = '<reg>'; $hand = '<hand>'
$enc = New-Object Text.UTF8Encoding $false
git -C $wt -c core.quotepath=off ls-files -o -- skilleddocs <more> | ForEach-Object {
  $f = $_; $src = Join-Path $wt $f; $dst = Join-Path $main $f
  if ($f -eq $reg -and (Test-Path $dst)) {
    $have = @([IO.File]::ReadAllLines($dst)); $left = @()
    $raw = [IO.File]::ReadAllText($dst); if ($raw -and -not $raw.EndsWith("`n")) { [IO.File]::AppendAllText($dst, "`n", $enc) }
    $ncol = (@($have | Where-Object { $_ -like '|*' })[0] -replace '[^|]').Length
    foreach ($l in [IO.File]::ReadAllLines($src)) {
      if ($l.Trim() -eq '' -or $have -ccontains $l -or $l -match '^\|[-:| ]*\|$') { continue }
      if ($l -cmatch '^\| *([A-Z][A-Za-z0-9-]*[0-9]) *\|') {
        $id = $Matches[1]
        if ($have -cmatch "^\| *$([regex]::Escape($id)) *\|") { $left += "$l   <- CLASH: $id differs in main" }
        elseif (($l -replace '[^|]').Length -ne $ncol) { $left += "$l   <- cell count differs from main's header" }
        else { [IO.File]::AppendAllText($dst, "$l`n", $enc); $have += $l; "appended $id" }
      } else { $left += $l }
    }
    if ($left.Count -eq 0) { Remove-Item $src } else { "STOP: $f kept, lines not in main:"; $left }
  } elseif ($f -eq 'skilleddocs/HANDOFF.md') {
    $d = Join-Path $main $hand; New-Item -ItemType Directory -Force $d | Out-Null
    $b = "$(Get-Date -Format yyyy-MM-dd)-$(Split-Path -Leaf $wt)-handoff"; $t = Join-Path $d "$b.md"; $k = 1
    while (Test-Path $t) { $k++; $t = Join-Path $d "$b-$k.md" }
    Move-Item $src $t; "moved $f -> $t"
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

STOP → leave the worktree and report what is left (link, `CLASH` file, register lines step 1 listed). `git worktree remove` refuses (untracked or modified files elsewhere) → stop and report `git -C "<wt>" status --short`. Never `--force`.
