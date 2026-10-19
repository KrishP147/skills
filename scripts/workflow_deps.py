#!/usr/bin/env python3
"""Resolve sample workflows (site/data/workflows.json) or single skills,
agents and hooks to what to install. Stdlib only; used by install-skills.sh
and install-skills.ps1.

  workflow_deps.py list                     name<TAB>title per workflow
  workflow_deps.py list-names               name<TAB>kind per skill/agent/hook
  workflow_deps.py resolve [WF ...] [--skill NAME ...]
  workflow_deps.py resolve-names NAME [NAME ...]
                                            one "<kind> <value>" line each:
      skill <repo-relative dir>   e.g. "skill kanban/next"
      agent <name>                agents/<name>.md
      hook <name>                 hooks/<name>.py (copied, never wired)
      agent-hooks                 agents/hooks/ (guard-git), once if any agent
                                  or guard-git itself is selected
  workflow_deps.py snippet HOOKS_DIR HOOK [HOOK ...]
                                            settings.json snippet for hooks
                                            copied into HOOKS_DIR

Names may be comma-separated. --skill takes any skill, agent or hook name.
Unknown name: the valid names go to stderr and the exit code is 2.

Closure, starting from every skill/agent/hook a workflow's steps name (and
each --skill name):
  preloads  an agent's frontmatter `skills:` (site_map preloads edges)
  calls     a site_map related edge whose target the source also names in
            its own SKILL.md (agent: its .md) as `name`, /name or name/.
            Related links alone pull in most of the repo; this keeps the
            ones the source actually calls.
  spawns    an agent the source's own SKILL.md (agent: its .md) passes as
            subagent_type="name" or "krish:name" (manager -> implementer).
  files     a relative link in any non-README .md of a selected skill that
            points into another skill's dir (e.g. ../next/BOARD.md), so
            no installed skill links to a file that isn't there.
Hooks come only from workflow steps or --skill, never from edges.
OPTIONAL lists "calls"/"spawns" edges whose source works without the target (it
only suggests it, or has a fallback); they are not followed.
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
_SPAWN_RE = re.compile(r'subagent_type="(?:krish:)?([\w-]+)"')

# hooks/<name>.py -> (event, matcher or None, command suffix); per hooks/README.md
HOOK_WIRING = {
    "smartzone": ("UserPromptSubmit", None, " || exit 0"),
    "spend-guard": ("PreToolUse", "Bash|PowerShell|mcp__.*", ""),
}


# src -> targets it names but works without; see each source's SKILL.md
OPTIONAL = {
    "find-me-a-skill": {"implementer", "manager", "meta-orchestrator", "next", "pair", "planner",
                        "verifier"},  # suggests, runs nothing
    "gap-scan": {"divide", "grill-docs", "kanban-setup"},  # offers, doesn't run
    "handoff-auto": {"handoff"},  # credit line only
    "pr-watch": {"pair"},  # fixes inline without it
    "repo-scrub": {"repo-showcase"},  # either order, either alone
    "repo-showcase": {"repo-scrub"},
    "score-loop": {"sitrep"},  # pointer only
    "smartzone": {"divide", "session-handoff"},  # hook text suggests them
    "wayfinder": {"divide", "meta-orchestrator"},  # offered at the end
}


class UnknownWorkflow(Exception):
    pass


class UnknownName(Exception):
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
                if _names(texts[src], dst) and dst not in OPTIONAL.get(src, ()):
                    self.deps[src].append(dst)
        for e in self.entries:
            n, k = e["name"], self.kinds[e["name"]]
            if k == "skill":
                self.deps[n].extend(_file_links(root, e, by_dir))
            if k in ("skill", "agent"):
                if n not in texts:
                    texts[n] = _read(_source_md(root, e, k))
                for a in _SPAWN_RE.findall(texts[n]):
                    if self.kinds.get(a) == "agent" and a != n and a not in OPTIONAL.get(n, ()):
                        self.deps[n].append(a)

    def names(self):
        return [wf["name"] for wf in self.workflows]

    def resolve(self, wf_names=(), names=()):
        """{"skill": [...], "agent": [...], "hook": [...]} sorted names, for
        the union of workflows wf_names and skill/agent/hook names."""
        known = {wf["name"]: wf for wf in self.workflows}
        bad = [n for n in wf_names if n not in known]
        if bad or not (wf_names or names):
            raise UnknownWorkflow(", ".join(bad))
        bad = [n for n in names if n not in self.kinds]
        if bad:
            raise UnknownName(", ".join(bad))
        seeds = [s["name"] for n in wf_names for s in known[n]["steps"] if s["kind"] != "human"]
        seeds += list(names)
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

    def lines(self, wf_names=(), names=()):
        r = self.resolve(wf_names, names)
        out = ["skill " + self.by_name[n]["source"] for n in r["skill"]]
        out += ["agent " + n for n in r["agent"]]
        agent_hooks = [n for n in r["hook"] if self.by_name[n]["source"].startswith("agents/")]
        out += ["hook " + n for n in r["hook"] if n not in agent_hooks]
        if r["agent"] or agent_hooks:
            out.append("agent-hooks")
        return out


def split_names(args):
    """['a,b', 'c'] -> ['a', 'b', 'c']; blanks dropped."""
    return [p.strip() for a in args for p in a.split(",") if p.strip()]


def listing(g):
    return ["%s\t%s" % (wf["name"], wf["title"]) for wf in g.workflows]


def needs_line(g, name):
    """The README line saying what installing `name` alone brings along."""
    r = g.resolve(names=[name])
    others = ["`%s`" % n for k in ("skill", "agent", "hook") for n in r[k] if n != name]
    if r["agent"]:  # any agent install also copies agents/hooks/guard-git.py
        others.append("the `guard-git` hook")
    if not others:
        return "Works on its own."
    return "Needs: %s (installed with it)." % ", ".join(others)


def name_listing(g):
    return ["%s\t%s" % (e["name"], g.kinds[e["name"]]) for e in g.entries]


def parse_resolve(args):
    """['a', '--skill', 'x,y', 'b'] -> (['a', 'b'], ['x', 'y'])."""
    wfs, names, it = [], [], iter(args)
    for a in it:
        if a == "--skill":
            names.append(next(it, ""))
        elif a.startswith("--skill="):
            names.append(a[len("--skill="):])
        else:
            wfs.append(a)
    return split_names(wfs), split_names(names)


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
    if not argv or argv[0] not in ("list", "list-names", "resolve", "resolve-names", "snippet"):
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
    if cmd == "list-names":
        out.write("\n".join(name_listing(g)) + "\n")
        return 0
    if cmd == "resolve-names":
        wfs, names = [], split_names(rest)
        if not names:
            sys.stderr.write("error: no skill, agent or hook name given\n")
            return 2
    else:
        wfs, names = parse_resolve(rest)
    try:
        lines = g.lines(wfs, names)
    except UnknownWorkflow as e:
        msg = "unknown workflow(s): %s" % e if str(e) else "no workflow name given"
        sys.stderr.write("error: %s\nWorkflows:\n" % msg)
        sys.stderr.write("".join("  %s\n" % ln for ln in listing(g)))
        return 2
    except UnknownName as e:
        sys.stderr.write("error: unknown skill, agent or hook name(s): %s\nNames:\n" % e)
        sys.stderr.write("".join("  %s\n" % ln for ln in name_listing(g)))
        return 2
    out.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
