#!/usr/bin/env python3
"""Resolve sample workflows (site/data/workflows.json) to what to install.
Stdlib only; used by install-skills.sh and install-skills.ps1.

  workflow_deps.py list                     name<TAB>title per workflow
  workflow_deps.py resolve NAME [NAME ...]  one "<kind> <value>" line each:
      skill <repo-relative dir>   e.g. "skill kanban/next"
      agent <name>                agents/<name>.md
      hook <name>                 hooks/<name>.py (copied, never wired)
      agent-hooks                 agents/hooks/ (guard-git), once if any agent
  workflow_deps.py snippet HOOKS_DIR HOOK [HOOK ...]
                                            settings.json snippet for hooks
                                            copied into HOOKS_DIR

Unknown workflow name: the list goes to stderr and the exit code is 2.

Closure, starting from every skill/agent/hook a workflow's steps name:
  preloads  an agent's frontmatter `skills:` (site_map preloads edges)
  calls     a site_map related edge whose target the source also names in
            its own SKILL.md (agent: its .md) as `name`, /name or name/.
            Related links alone pull in most of the repo; this keeps the
            ones the source actually calls.
  files     a relative link in any non-README .md of a selected skill that
            points into another skill's dir (e.g. ../next/BOARD.md), so
            no installed skill links to a file that isn't there.
Hooks come only from workflow steps, never from edges.
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_site  # noqa: E402
import site_map  # noqa: E402
import site_workflows  # noqa: E402

ROOT = os.path.dirname(HERE)
_FILE_LINK_RE = re.compile(r"\]\(((?:\.\./)+[^)\s#]*)")

# hooks/<name>.py -> (event, matcher or None, command suffix); per hooks/README.md
HOOK_WIRING = {
    "smartzone": ("UserPromptSubmit", None, " || exit 0"),
    "spend-guard": ("PreToolUse", "Bash|PowerShell|mcp__.*", ""),
}


class UnknownWorkflow(Exception):
    pass


def _source_md(root, e, kind):
    if kind == "skill":
        return os.path.join(root, *e["source"].split("/"), "SKILL.md")
    return os.path.join(root, *e["source"].split("/"))


def _read(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return f.read()
    except OSError:
        return ""


def _names(text, name):
    return re.search(r"(?:`/?|/)%s(?:`|/|(?![\w-]))" % re.escape(name), text) is not None


def _file_links(root, e, by_dir):
    """Skill names whose dirs this skill's own .md files link into."""
    base = os.path.join(root, *e["source"].split("/"))
    out = []
    for path in sorted(glob.glob(os.path.join(base, "**", "*.md"), recursive=True)):
        if os.path.basename(path) == "README.md":
            continue
        here = os.path.dirname(path)
        for url in _FILE_LINK_RE.findall(_read(path)):
            rel = os.path.relpath(os.path.normpath(os.path.join(here, url)), root).replace(os.sep, "/")
            for d, n in by_dir.items():
                if (rel == d or rel.startswith(d + "/")) and n != e["name"]:
                    out.append(n)
    return out


class Graph:
    def __init__(self, root=ROOT):
        self.root = root
        self.entries = build_site.collect(root)
        self.workflows = site_workflows.load(root)
        self.kinds = {e["name"]: site_workflows.kind_of(e) for e in self.entries}
        self.by_name = {e["name"]: e for e in self.entries}
        by_dir = {e["source"]: e["name"] for e in self.entries if self.kinds[e["name"]] == "skill"}
        self.deps = {n: [] for n in self.kinds}
        texts = {}
        for src, dst, kinds in site_map.edges(root, self.entries, self.workflows):
            if self.kinds[dst] == "hook":
                continue
            if "preloads" in kinds:
                self.deps[src].append(dst)
            elif "related" in kinds:
                if src not in texts:
                    texts[src] = _read(_source_md(root, self.by_name[src], self.kinds[src]))
                if _names(texts[src], dst):
                    self.deps[src].append(dst)
        for e in self.entries:
            if self.kinds[e["name"]] == "skill":
                self.deps[e["name"]].extend(_file_links(root, e, by_dir))

    def names(self):
        return [wf["name"] for wf in self.workflows]

    def resolve(self, wf_names):
        """{"skill": [...], "agent": [...], "hook": [...]} sorted names."""
        known = {wf["name"]: wf for wf in self.workflows}
        bad = [n for n in wf_names if n not in known]
        if bad or not wf_names:
            raise UnknownWorkflow(", ".join(bad))
        seeds = [s["name"] for n in wf_names for s in known[n]["steps"] if s["kind"] != "human"]
        seen, todo = set(seeds), list(seeds)
        while todo:
            for d in self.deps[todo.pop()]:
                if d not in seen:
                    seen.add(d)
                    todo.append(d)
        out = {"skill": [], "agent": [], "hook": []}
        for n in sorted(seen):
            out[self.kinds[n]].append(n)
        return out

    def lines(self, wf_names):
        r = self.resolve(wf_names)
        out = ["skill " + self.by_name[n]["source"] for n in r["skill"]]
        out += ["agent " + n for n in r["agent"]]
        out += ["hook " + n for n in r["hook"]]
        if r["agent"]:
            out.append("agent-hooks")
        return out


def split_names(args):
    """['a,b', 'c'] -> ['a', 'b', 'c']; blanks dropped."""
    return [p.strip() for a in args for p in a.split(",") if p.strip()]


def listing(g):
    return ["%s\t%s" % (wf["name"], wf["title"]) for wf in g.workflows]


def snippet(hooks_dir, hooks):
    """settings.json text wiring each hook at its path under hooks_dir."""
    block = {}
    for h in hooks:
        event, matcher, suffix = HOOK_WIRING.get(h, (None, None, ""))
        if not event:
            continue
        path = os.path.join(hooks_dir, h + ".py").replace("\\", "/")
        entry = {"hooks": [{"type": "command", "command": 'python "%s"%s' % (path, suffix)}]}
        if matcher:
            entry = {"matcher": matcher, **entry}
        block.setdefault(event, []).append(entry)
    return json.dumps({"hooks": block}, indent=2)


def main(argv):
    out = sys.stdout
    if hasattr(out, "reconfigure"):
        out.reconfigure(newline="\n")  # shells read these lines; no \r on Windows
    if not argv or argv[0] not in ("list", "resolve", "snippet"):
        sys.stderr.write(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    if cmd == "snippet":
        if len(rest) < 2:
            sys.stderr.write("usage: workflow_deps.py snippet HOOKS_DIR HOOK [HOOK ...]\n")
            return 1
        out.write(snippet(rest[0], rest[1:]) + "\n")
        return 0
    g = Graph()
    if cmd == "list":
        out.write("\n".join(listing(g)) + "\n")
        return 0
    names = split_names(rest)
    try:
        lines = g.lines(names)
    except UnknownWorkflow as e:
        msg = "unknown workflow(s): %s" % e if str(e) else "no workflow named"
        sys.stderr.write("error: %s\nWorkflows:\n" % msg)
        sys.stderr.write("".join("  %s\n" % ln for ln in listing(g)))
        return 2
    out.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
