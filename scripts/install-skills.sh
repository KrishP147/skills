#!/usr/bin/env bash
# Installs every skill in this repo into ~/.claude/skills/ (personal, global
# across all repos/terminals). Safe to re-run - each of our own skill dirs is
# replaced fresh; a same-named dir NOT installed by this repo (no marker
# file) is left alone unless --force. Also copies agents/*.md and
# agents/hooks/ over ~/.claude/agents/; agents there that aren't in this
# repo are warned about, never deleted. Same for skill dirs in the target
# that carry the marker but are no longer in this repo (stale skills).
#
# Flags:
#   --no-lint  proceed even if no working python 3 is found (skips lint)
#   --force    replace foreign skill dirs (no marker file) instead of
#              skipping them
#   --no-sh-check  proceed even if no POSIX `sh` is on PATH. The guard-git
#              hook command in agents/*.md is POSIX sh; without sh, Claude
#              Code can't run it, so the hook blocks nothing (fails open).
#   --workflow <name>  install only what that sample workflow
#              (site/data/workflows.json) needs: its skills, agents and
#              hooks plus their dependencies (scripts/workflow_deps.py).
#              Repeatable, or comma-separated. Nothing outside the
#              selection is touched or warned about. Hooks are copied to
#              $CLAUDE_HOOKS_DIR (default: hooks/ next to the skills dir)
#              and their settings.json snippet printed, never wired.
#              Needs python 3, even with --no-lint.
#   --list-workflows  print the workflow names and exit
set -euo pipefail

MARKER=".from-krishp147-skills"

no_lint=0
force=0
no_sh_check=0
list_workflows=0
workflows=()
usage() {
  echo "Usage: $0 [--no-lint] [--force] [--no-sh-check] [--workflow <name>]... [--list-workflows]" >&2
  exit 1
}
while (( $# )); do
  case "$1" in
    --no-lint) no_lint=1 ;;
    --force) force=1 ;;
    --no-sh-check) no_sh_check=1 ;;
    --list-workflows) list_workflows=1 ;;
    --workflow)
      (( $# >= 2 )) || usage
      workflows+=("$2")
      shift
      ;;
    --workflow=*) workflows+=("${1#--workflow=}") ;;
    *) usage ;;
  esac
  shift
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
agents_target="${CLAUDE_AGENTS_DIR:-$HOME/.claude/agents}"

# first candidate that actually runs Python 3 (skips e.g. the Windows Store
# python/python3 stub, which exists on PATH but refuses to run code)
pybin=""
pyargs=()
try_py() {
  local cmd="$1"; shift
  command -v "$cmd" >/dev/null 2>&1 || return 1
  "$cmd" "$@" -c 'import sys; sys.exit(sys.version_info[0] != 3)' >/dev/null 2>&1
}
if try_py python3; then
  pybin="python3"
elif try_py python; then
  pybin="python"
elif try_py py -3; then
  pybin="py"
  pyargs=(-3)
fi

deps=("$repo_root/scripts/workflow_deps.py")
if (( list_workflows )); then
  if [[ -z "$pybin" ]]; then
    echo "error: --list-workflows needs python 3 (checked python3, python, py -3)." >&2
    exit 1
  fi
  "$pybin" ${pyargs[@]+"${pyargs[@]}"} "${deps[@]}" list
  exit 0
fi

# guard-git's hook command (agents/*.md frontmatter) is POSIX sh. Without
# sh, Claude Code can't run the hook and nothing gets blocked, so check
# before copying anything.
if ! command -v sh >/dev/null 2>&1; then
  if (( no_sh_check )); then
    echo "warning: no POSIX sh on PATH - guard-git hook won't run and blocks nothing (--no-sh-check)" >&2
  else
    echo "error: no POSIX sh found on PATH." >&2
    echo "The guard-git hook command is POSIX sh; without it Claude Code can't run" >&2
    echo "the hook, which then fails open (blocks nothing). Install sh (on Windows:" >&2
    echo "Git for Windows / Git Bash), or pass --no-sh-check to install anyway." >&2
    exit 1
  fi
fi

if [[ -n "$pybin" ]]; then
  # ${arr[@]+...}: empty-array expansion under set -u breaks bash < 4.4 (macOS)
  if ! "$pybin" ${pyargs[@]+"${pyargs[@]}"} "$repo_root/scripts/lint.py"; then
    echo "lint failed - aborting install" >&2
    exit 1
  fi
elif (( no_lint )); then
  echo "warning: no working python 3 found, skipping lint (--no-lint)" >&2
else
  echo "error: no working python 3 found on PATH (checked python3, python, py -3)." >&2
  echo "Install Python 3, or pass --no-lint to skip the lint step." >&2
  exit 1
fi

# --workflow: resolve before creating or copying anything; an unknown name
# makes the resolver list the workflows and exit non-zero.
partial=0
sel_skills=()
sel_agents=()
sel_hooks=()
agent_hooks=0
if (( ${#workflows[@]} )); then
  partial=1
  if [[ -z "$pybin" ]]; then
    echo "error: --workflow needs python 3 to resolve the workflow (checked python3, python, py -3)." >&2
    echo "Install Python 3; --no-lint does not skip this step." >&2
    exit 1
  fi
  resolved="$("$pybin" ${pyargs[@]+"${pyargs[@]}"} "${deps[@]}" resolve "${workflows[@]}")" || exit $?
  while IFS= read -r line; do
    line="${line%$'\r'}"
    case "$line" in
      "skill "*) sel_skills+=("${line#skill }") ;;
      "agent "*) sel_agents+=("${line#agent }") ;;
      "hook "*) sel_hooks+=("${line#hook }") ;;
      agent-hooks) agent_hooks=1 ;;
      "") ;;
      *) echo "error: unexpected resolver output: $line" >&2; exit 1 ;;
    esac
  done <<< "$resolved"
fi

if (( partial )); then
  mkdir -p "$target"
  (( ${#sel_agents[@]} )) && mkdir -p "$agents_target"
else
  mkdir -p "$target"
  mkdir -p "$agents_target"
fi

installed=()
skipped_foreign=()
repo_skills=" "
install_skill() {
  local skill_dir="$1" name dest
  name="$(basename "$skill_dir")"
  dest="$target/$name"
  repo_skills+="$name "
  if [[ -e "$dest" && ! -f "$dest/$MARKER" && $force -eq 0 ]]; then
    echo "warning: $dest exists and wasn't installed by this repo, skipping (use --force to replace)" >&2
    skipped_foreign+=("$name")
    return 0
  fi
  rm -rf "$dest"
  cp -r "$skill_dir" "$dest"
  find "$dest" -depth -name "__pycache__" -type d -exec rm -rf {} +
  : > "$dest/$MARKER"
  installed+=("$name")
}
installed_agents=()
install_agent() {
  local name
  name="$(basename "$1")"
  cp "$1" "$agents_target/$name"
  installed_agents+=("${name%.md}")
}
install_agent_hooks() {
  mkdir -p "$agents_target/hooks"
  if [[ -d "$repo_root/agents/hooks" ]]; then
    cp -rf "$repo_root/agents/hooks/." "$agents_target/hooks/"
    find "$agents_target/hooks" -depth -name "__pycache__" -type d -exec rm -rf {} +
  fi
}

if (( partial )); then
  for d in ${sel_skills[@]+"${sel_skills[@]}"}; do
    install_skill "$repo_root/$d"
  done
  for a in ${sel_agents[@]+"${sel_agents[@]}"}; do
    install_agent "$repo_root/agents/$a.md"
  done
  (( agent_hooks )) && install_agent_hooks

  # hooks/<name>.py: copied, never wired into settings.json. A different
  # file already there is left alone unless --force.
  hooks_target="${CLAUDE_HOOKS_DIR:-$(dirname "$target")/hooks}"
  copied_hooks=()
  skipped_hooks=()
  for h in ${sel_hooks[@]+"${sel_hooks[@]}"}; do
    src="$repo_root/hooks/$h.py"
    dest="$hooks_target/$h.py"
    if [[ -e "$dest" ]] && ! cmp -s "$src" "$dest" && (( force == 0 )); then
      echo "warning: $dest exists and differs from this repo's copy, skipping (use --force to replace)" >&2
      skipped_hooks+=("$h")
      continue
    fi
    mkdir -p "$hooks_target"
    cp "$src" "$dest"
    copied_hooks+=("$h")
  done

  printf 'Workflow(s): %s\n' "${workflows[*]}"
  printf 'Installed %d skill(s) to %s:\n' "${#installed[@]}" "$target"
  (( ${#installed[@]} )) && printf '  - %s\n' "${installed[@]}"
  if (( ${#skipped_foreign[@]} )); then
    printf 'warning: skipped %d foreign skill dir(s) without marker (use --force): %s\n' \
      "${#skipped_foreign[@]}" "${skipped_foreign[*]}" >&2
  fi
  if (( ${#installed_agents[@]} )); then
    printf 'Installed %d agent(s) to %s (with the guard-git hook in hooks/):\n' "${#installed_agents[@]}" "$agents_target"
    printf '  - %s\n' "${installed_agents[@]}"
  fi
  if (( ${#copied_hooks[@]} )); then
    printf 'Copied %d hook(s) to %s, NOT wired. To enable, add this to the "hooks" block of ~/.claude/settings.json (see hooks/README.md):\n' \
      "${#copied_hooks[@]}" "$hooks_target"
    "$pybin" ${pyargs[@]+"${pyargs[@]}"} "${deps[@]}" snippet "$hooks_target" "${copied_hooks[@]}"
  fi
  if (( ${#skipped_foreign[@]} || ${#skipped_hooks[@]} )); then
    exit 1
  fi
  exit 0
fi

while IFS= read -r -d '' skill_md; do
  install_skill "$(dirname "$skill_md")"
done < <(find "$repo_root" -mindepth 2 -maxdepth 3 -name "SKILL.md" -not -path "$repo_root/templates/*" -print0)

while IFS= read -r -d '' agent_md; do
  install_agent "$agent_md"
done < <(find "$repo_root/agents" -maxdepth 1 -name "*.md" ! -name "README.md" -print0)

install_agent_hooks

printf 'Installed %d skill(s) to %s:\n' "${#installed[@]}" "$target"
printf '  - %s\n' "${installed[@]}"

if (( ${#skipped_foreign[@]} )); then
  printf 'warning: skipped %d foreign skill dir(s) without marker (use --force): %s\n' \
    "${#skipped_foreign[@]}" "${skipped_foreign[*]}" >&2
fi

printf 'Installed %d agent(s) to %s:\n' "${#installed_agents[@]}" "$agents_target"
printf '  - %s\n' "${installed_agents[@]}"

stale=()
while IFS= read -r -d '' existing; do
  name="$(basename "$existing")"
  [[ -f "$repo_root/agents/$name" ]] || stale+=("$name")
done < <(find "$agents_target" -maxdepth 1 -type f -name "*.md" ! -name "README.md" -print0)
if (( ${#stale[@]} )); then
  printf 'warning: stale agent(s) not in repo, remove manually: %s\n' "${stale[*]}" >&2
fi

stale_skills=()
while IFS= read -r -d '' existing; do
  name="$(basename "$existing")"
  [[ -f "$existing/$MARKER" && "$repo_skills" != *" $name "* ]] && stale_skills+=("$name")
done < <(find "$target" -mindepth 1 -maxdepth 1 -type d -print0)
if (( ${#stale_skills[@]} )); then
  # comma-joined: dir names may contain spaces (matches the .ps1 output)
  joined="$(printf ', %s' "${stale_skills[@]}")"
  printf 'warning: stale skill(s) not in repo, remove manually: %s\n' "${joined:2}" >&2
fi

if (( ${#skipped_foreign[@]} )); then
  exit 1
fi
