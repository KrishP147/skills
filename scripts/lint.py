#!/usr/bin/env python3
"""Lints SKILL.md and agents/*.md files in this repo, plus a repo-wide
forbidden-word check over every tracked text file. Stdlib only.

Checks: frontmatter present; name matches parent dir (skills) or file stem
(agents); description present and <=1024 chars; body non-empty; every skill
an agent preloads exists as a skill dir in the repo; no agent preloads a
skill marked disable-model-invocation: true; no configured forbidden word
(case-insensitive) appears in any tracked file in the repo.

Forbidden words are never hard-coded here (this file is public). Configure
them locally via an untracked repo-root file `.lint-forbidden.txt` (one
word per line; `#` comments and blank lines ignored) and/or the
comma-separated env var SKILLS_LINT_FORBIDDEN. If neither yields any
words, the forbidden-word check is silently skipped. See CONTRIBUTING.md.

Also warns (to stderr, non-fatal) when a skill's README.md is missing one
of the required "## " section headings from templates/skill/README.md.
"templates/" itself is excluded from every check and from install.

Usage: python scripts/lint.py
Exit 0 + "OK: N skills, M agents" on success (last stdout line). Exit 1
with one line per failure otherwise. WARN lines never affect exit code.
"""
import glob
import os
import re
import subprocess
import sys

SKIP_DIRS = {".git", "node_modules", "templates"}
FORBIDDEN_WORDS_FILE = ".lint-forbidden.txt"

REQUIRED_README_SECTIONS = [
    "What it does",
    "When to use",
    "How to invoke",
    "How it works",
    "Design principles",
    "Use cases",
    "Tips",
    "Example",
    "Related",
    "Prereqs",
]


def repo_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def find_skill_files(root):
    found = set()
    for pattern in ("*/SKILL.md", "*/*/SKILL.md"):
        for path in glob.glob(os.path.join(root, pattern)):
            rel = os.path.relpath(path, root)
            parts = rel.split(os.sep)
            if any(p in SKIP_DIRS for p in parts):
                continue
            found.add(os.path.normpath(path))
    return sorted(found)


def find_agent_files(root):
    # README.md is human docs, not an agent definition.
    return sorted(
        p for p in glob.glob(os.path.join(root, "agents", "*.md"))
        if os.path.basename(p).lower() != "readme.md"
    )


# Group 1 is the bare header; an optional trailing `# comment` (preceded by
# whitespace) is allowed after it.
BLOCK_SCALAR_RE = re.compile(r"^([>|](?:[+-]\d?|\d[+-]?)?)(?:\s+#.*)?$")


def _block_scalar(header, block):
    """Value of a YAML block scalar (`>` folded, `|` literal; optional
    chomping `-`/`+`, optional indent digit). Clip keeps one trailing
    newline. Folded: single newlines become spaces, blank lines become
    newlines. Lines indented deeper than the block's base indent keep their
    line breaks (YAML 1.2 8.1.3): no folding into or out of them."""
    folded = header[0] == ">"
    chomp = "-" if "-" in header else "+" if "+" in header else ""
    digit = re.search(r"\d", header)
    nonblank = [l for l in block if l.strip()]
    if not nonblank:
        return "" if chomp != "+" else "\n" * len(block)
    if digit:
        indent = int(digit.group())
    else:
        indent = min(len(l) - len(l.lstrip()) for l in nonblank)
    lines = [l[indent:].rstrip() if l.strip() else "" for l in block]
    trailing = 0
    while lines and lines[-1] == "":
        lines.pop()
        trailing += 1
    if folded:
        text = ""
        breaks = 0
        prev_more = False
        for l in lines:
            if l == "":
                breaks += 1
                continue
            more = l[0] in " \t"
            if text:
                if more or prev_more:
                    text += "\n" * (breaks + 1)
                else:
                    text += "\n" * breaks if breaks else " "
            text += l
            breaks = 0
            prev_more = more
    else:
        text = "\n".join(lines)
    if chomp == "-":
        return text
    if chomp == "+":
        return text + "\n" * (1 + trailing)
    return text + "\n"


def parse_frontmatter(text):
    """Minimal '---' delimited frontmatter parser. Top-level `key: value`
    lines are captured. A key with an empty value followed by indented
    `- item` lines becomes a list. Deeper nested blocks are skipped."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None, text
    fm_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1:])

    data = {}
    current_key = None
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        i += 1
        if not line.strip():
            continue
        if not line[0].isspace():
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip()
                val = val.strip()
                if val == "":
                    data[key] = []
                    current_key = key
                elif BLOCK_SCALAR_RE.match(val):
                    header = BLOCK_SCALAR_RE.match(val).group(1)
                    block = []
                    while i < len(fm_lines):
                        nxt = fm_lines[i]
                        if nxt.strip() and not nxt[0].isspace():
                            break
                        block.append(nxt)
                        i += 1
                    data[key] = _block_scalar(header, block)
                    current_key = None
                else:
                    data[key] = val
                    current_key = None
            else:
                current_key = None
        else:
            stripped = line.strip()
            if stripped.startswith("- ") and isinstance(data.get(current_key), list):
                data[current_key].append(stripped[2:].strip())
            # else: nested block content - not needed for these checks, skip.
    return data, body


def lint_common(path, fm, body, expected_name, failures):
    if fm is None:
        failures.append("%s: missing frontmatter" % path)
        return
    name = fm.get("name")
    if not name:
        failures.append("%s: missing 'name' in frontmatter" % path)
    elif name != expected_name:
        failures.append("%s: name '%s' != expected '%s'" % (path, name, expected_name))

    description = fm.get("description")
    if isinstance(description, str) and BLOCK_SCALAR_RE.match(description.strip()):
        failures.append("%s: description is an unparsed block scalar '%s'" % (path, description.strip()))
    elif not description:
        failures.append("%s: missing 'description' in frontmatter" % path)
    elif len(description) > 1024:
        failures.append("%s: description exceeds 1024 chars (%d)" % (path, len(description)))

    if not body.strip():
        failures.append("%s: empty body" % path)


def load_forbidden_words(root):
    """Forbidden words from the untracked .lint-forbidden.txt (one per
    line, '#' comments and blank lines ignored) plus the comma-separated
    SKILLS_LINT_FORBIDDEN env var. All compared case-insensitively."""
    words = set()
    words_path = os.path.join(root, FORBIDDEN_WORDS_FILE)
    if os.path.isfile(words_path):
        with open(words_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line:
                    words.add(line.lower())
    for word in os.environ.get("SKILLS_LINT_FORBIDDEN", "").split(","):
        word = word.strip()
        if word:
            words.add(word.lower())
    return words


def list_tracked_files(root):
    """Paths git tracks, or None if git isn't available/this isn't a repo."""
    try:
        out = subprocess.check_output(
            ["git", "ls-files"], cwd=root, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return [
        os.path.join(root, rel)
        for rel in out.decode("utf-8", "replace").splitlines()
        if rel
    ]


def walk_all_files(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
        for name in filenames:
            found.append(os.path.join(dirpath, name))
    return found


def check_forbidden_words(root, failures):
    words = load_forbidden_words(root)
    if not words:
        return
    files = list_tracked_files(root)
    if files is None:
        files = walk_all_files(root)
    for path in sorted(files):
        if not os.path.isfile(path):
            continue
        if os.path.basename(path) == FORBIDDEN_WORDS_FILE:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        lowered = text.lower()
        rel = os.path.relpath(path, root)
        for word in sorted(words):
            if word in lowered:
                failures.append("%s: contains forbidden word '%s'" % (rel, word))


def readme_headings(text):
    headings = set()
    fence = None  # (char, length) of the open fenced code block
    for line in text.splitlines():
        stripped = line.strip()
        lead = line.lstrip()
        if lead[:3] in ("```", "~~~"):
            ch = lead[0]
            n = len(lead) - len(lead.lstrip(ch))
            if fence is None:
                fence = (ch, n)
                continue
            if ch == fence[0] and n >= fence[1] and not lead[n:].strip():
                fence = None
                continue
        if fence is not None:
            continue
        if stripped.startswith("## "):
            headings.add(stripped[3:].strip())
    return headings


def warn_missing_readme_sections(skill_md_path):
    """If a README.md sits next to this SKILL.md, print one WARN line to
    stderr naming any required section headings it's missing. "## Invoke"
    counts as "## How to invoke". Never affects the exit code."""
    readme_path = os.path.join(os.path.dirname(skill_md_path), "README.md")
    if not os.path.isfile(readme_path):
        return
    with open(readme_path, "r", encoding="utf-8") as f:
        headings = readme_headings(f.read())
    if "Invoke" in headings:
        headings.add("How to invoke")
    missing = [h for h in REQUIRED_README_SECTIONS if h not in headings]
    if missing:
        sys.stderr.write(
            "WARN: %s: missing sections: %s\n" % (readme_path, ", ".join(missing))
        )


LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


def check_relative_links(path, failures):
    """Every relative Markdown link in a skill/agent prompt file must resolve,
    so disclosed reference files (BOARD.md, SETUP.md, ...) can't go missing."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    for target in LINK_RE.findall(text):
        if re.match(r"^[a-z][a-z0-9+.-]*:|^#|^~|^/", target, re.I):
            continue
        rel = target.split("#", 1)[0]
        if rel and not os.path.exists(os.path.join(os.path.dirname(path), rel)):
            failures.append("%s: broken relative link '%s'" % (path, target))


def prompt_files(skill_files):
    """SKILL.md plus every sibling .md except the human README."""
    out = []
    for sp in skill_files:
        d = os.path.dirname(sp)
        out += [p for p in glob.glob(os.path.join(d, "*.md"))
                if os.path.basename(p).lower() != "readme.md"]
    return sorted(set(out))


def main():
    root = repo_root()
    failures = []

    check_forbidden_words(root, failures)

    skill_files = find_skill_files(root)
    agent_files = find_agent_files(root)

    skill_names = set()
    disabled_skills = set()

    for path in skill_files:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        fm, body = parse_frontmatter(text)
        parent_dir = os.path.basename(os.path.dirname(path))
        skill_names.add(parent_dir)
        lint_common(path, fm, body, parent_dir, failures)
        if fm and str(fm.get("disable-model-invocation", "")).strip().lower() == "true":
            disabled_skills.add(parent_dir)
        warn_missing_readme_sections(path)

    for path in prompt_files(skill_files) + agent_files:
        check_relative_links(path, failures)

    agent_skill_lists = {}
    for path in agent_files:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        fm, body = parse_frontmatter(text)
        stem = os.path.splitext(os.path.basename(path))[0]
        lint_common(path, fm, body, stem, failures)
        if fm:
            skills_list = fm.get("skills")
            if isinstance(skills_list, list):
                agent_skill_lists[path] = skills_list

    for path, skills_list in agent_skill_lists.items():
        for entry in skills_list:
            if entry not in skill_names:
                failures.append("%s: preloads unknown skill '%s' (no such skill dir)" % (path, entry))
            if entry in disabled_skills:
                failures.append(
                    "%s: preloads '%s', which has disable-model-invocation: true (unsupported)" % (path, entry)
                )

    if failures:
        for f in failures:
            print(f)
        sys.exit(1)

    print("OK: %d skills, %d agents" % (len(skill_files), len(agent_files)))


if __name__ == "__main__":
    main()
