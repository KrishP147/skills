"""Sample workflows for the skills site. Stdlib only.

Content lives in site/data/workflows.json; this module only loads, validates
and renders it, so other readers (e.g. a catalog generator) can reuse
load() + validate() and get the same checks the site build runs.

Format: [{name, title, steps: [{kind, name?, why}]}]
  kind  skill | agent | hook | human (human steps have no name)
  name  an existing skill / agent / hook of that kind
  why   one line
Rules (SystemExit on any break): unknown keys or names, a workflow with
fewer than 2 skill/agent steps or no human step, duplicate workflow names,
a name that clashes with an id on the workflows page, and any skill that
appears in no workflow. Agents and hooks are optional.
"""
import html
import json
import os
import re

SLUG = "workflows"  # index page: <out>/workflows/index.html, URL <base>/workflows
DATA_PATH = ("site", "data", "workflows.json")
STEP_KINDS = ("skill", "agent", "hook", "human")
GROUP_KIND = {"core": "skill", "kanban": "skill", "agents": "agent", "hooks": "hook"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# Ids the workflows page uses itself; a workflow's anchor can't take one.
PAGE_IDS = {"term", "cmd", "menu", "echo", "hint", "status", "prompt-box", "skill-data", "wf-toc"}


def esc(s):
    return html.escape(s, quote=True)


def kind_of(entry):
    return GROUP_KIND.get(entry["group"], "skill")


def load(root):
    with open(os.path.join(root, *DATA_PATH), encoding="utf-8") as f:
        return json.load(f)


def _fail(msg):
    raise SystemExit("workflows.json: " + msg)


def _one_line(v):
    return isinstance(v, str) and v.strip() and "\n" not in v


def validate(raw, entries):
    """Check raw workflows against entries (from build_site.collect).
    Returns them unchanged; raises SystemExit on the first problem."""
    kinds = {e["name"]: kind_of(e) for e in entries}
    if not isinstance(raw, list) or not raw:
        _fail("need a non-empty list of workflows")
    seen = set()
    for i, wf in enumerate(raw):
        where = "workflow %d" % i
        if not isinstance(wf, dict):
            _fail("%s: need an object" % where)
        extra = set(wf) - {"name", "title", "steps"}
        if extra:
            _fail("%s: unknown keys %s" % (where, sorted(extra)))
        name = wf.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            _fail("%s: name must be lowercase a-z, 0-9, -" % where)
        where = "workflow %r" % name
        if name in seen:
            _fail("%s: duplicate name" % where)
        if name in PAGE_IDS:
            _fail("%s: name clashes with an id on the workflows page" % where)
        seen.add(name)
        if not _one_line(wf.get("title")):
            _fail("%s: title must be one non-empty line" % where)
        steps = wf.get("steps")
        if not isinstance(steps, list):
            _fail("%s: steps must be a list" % where)
        for j, st in enumerate(steps):
            _check_step(st, "%s step %d" % (where, j + 1), kinds)
        actors = [s for s in steps if s["kind"] in ("skill", "agent")]
        if len(actors) < 2:
            _fail("%s: needs 2+ skill/agent steps" % where)
        if not any(s["kind"] == "human" for s in steps):
            _fail("%s: needs a human step" % where)
    used = {s["name"] for wf in raw for s in wf["steps"] if s["kind"] != "human"}
    missing = sorted(n for n, k in kinds.items() if k == "skill" and n not in used)
    if missing:
        _fail("skills in no workflow: %s" % ", ".join(missing))
    return raw


def _check_step(st, where, kinds):
    if not isinstance(st, dict):
        _fail("%s: need an object" % where)
    extra = set(st) - {"kind", "name", "why"}
    if extra:
        _fail("%s: unknown keys %s" % (where, sorted(extra)))
    kind = st.get("kind")
    if kind not in STEP_KINDS:
        _fail("%s: kind must be one of %s" % (where, ", ".join(STEP_KINDS)))
    if kind == "human":
        if "name" in st:
            _fail("%s: a human step has no name" % where)
    else:
        name = st.get("name")
        if not isinstance(name, str) or name not in kinds:
            _fail("%s: unknown %s %r" % (where, kind, name))
        if kinds[name] != kind:
            _fail("%s: %r is a %s, not a %s" % (where, name, kinds[name], kind))
    if not _one_line(st.get("why")):
        _fail("%s: why must be one non-empty line" % where)


def check_slug(entries):
    """The index page owns <out>/workflows/; no entry may take that name."""
    if any(e["name"] == SLUG for e in entries):
        raise SystemExit("%r is reserved for the workflows index page; rename that skill/agent/hook" % SLUG)


def by_name(workflows):
    """{entry name: [workflow, ...]} in file order, each workflow once."""
    out = {}
    for wf in workflows:
        for st in wf["steps"]:
            if st["kind"] != "human":
                lst = out.setdefault(st["name"], [])
                if wf not in lst:
                    lst.append(wf)
    return out


def chain(wf):
    """'session-handoff → you → update-progress' (plain text)."""
    return " → ".join(st.get("name", "you") for st in wf["steps"])


def href(base, name=None):
    return "%s/%s%s" % (base, SLUG, "#" + name if name else "")


def detail_section(wfs, base, sid):
    """'Sample workflows' section for a detail page, linking each workflow."""
    if not wfs:
        return ""
    items = "\n".join(
        '<li><a href="%s">%s</a><br><span class="dim wf-chain">%s</span></li>'
        % (esc(href(base, wf["name"])), esc(wf["title"]), esc(chain(wf))) for wf in wfs)
    return ('<section class="sec" aria-labelledby="%s">\n<h2 id="%s">Sample workflows</h2>\n'
            '<ul class="wf-links">\n%s\n</ul>\n</section>' % (esc(sid), esc(sid), items))


def _step_html(st, base):
    if st["kind"] == "human":
        head = '<span class="wf-who wf-you">you</span>'
    else:
        kind = "" if st["kind"] == "skill" else ' <span class="tag">%s</span>' % esc(st["kind"])
        head = '<a class="wf-who" href="%s/%s">/%s</a>%s' % (esc(base), esc(st["name"]), esc(st["name"]), kind)
    cls = "wf-step wf-human" if st["kind"] == "human" else "wf-step"
    return '<li class="%s">%s <span class="wf-why">%s</span></li>' % (cls, head, esc(st["why"]))


def render_list(workflows, base):
    toc = "\n".join('<li><a href="#%s">%s</a></li>' % (esc(wf["name"]), esc(wf["title"])) for wf in workflows)
    out = ['<nav class="sec wf-toc" aria-labelledby="wf-toc">\n<h2 id="wf-toc">All workflows</h2>\n'
           '<ul>\n%s\n</ul>\n</nav>' % toc]
    for wf in workflows:
        steps = "\n".join(_step_html(st, base) for st in wf["steps"])
        out.append('<section class="sec wf" aria-labelledby="%s">\n<h2 id="%s">%s</h2>\n'
                   '<ol class="wf-steps">\n%s\n</ol>\n</section>'
                   % (esc(wf["name"]), esc(wf["name"]), esc(wf["title"]), steps))
    return "\n".join(out)


def render_index(template, workflows, base, data_json):
    values = {"BASE": esc(base), "COUNT": str(len(workflows)),
              "LIST": render_list(workflows, base), "DATA": data_json}
    return re.sub(r"\{\{([A-Z]+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template)
