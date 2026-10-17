"""Skills map page (/map) for the skills site. Stdlib only.

Nodes are every skill, agent and hook. Groups come from site/data/meta.json
"categories" ({category: [name, ...]}, declaration order; the same list
drives the home catalog, page tags and README): every entry in
exactly one category; unknown, missing or duplicate names fail the build.

Edges are generated from real references, never hand-written:
  related   a markdown link in an entry's Related section (skill README
            "## Related", hook "Related:" paragraph) that resolves to
            another entry. A relative link whose file or anchor does not
            exist fails the build. A link to agents/README.md with no
            anchor counts for each agent named in `backticks` in its text.
  preloads  an agent's frontmatter `skills:` list.
  workflow  consecutive skill/agent/hook steps of a sample workflow
            (site/data/workflows.json), human steps skipped.
One edge per (from, to); its kinds are listed in first-seen order.

Rendering: one flow_svg graph per group (its members plus the targets of
their outgoing edges), so each edge is drawn once, in its source's group.
flow_svg has no subgraphs or styling, so groups are page sections. Edge
style: solid = related or preloads (preloads labelled), dotted = workflow
only. A list beside each graph links every node and names every edge.
"""
import html
import os
import posixpath
import re

import flow_svg
import site_detail
from md_render import slugify, strip_inline

SLUG = "map"  # index page: <out>/map/index.html, URL <base>/map
META_KEY = "categories"
GROUP_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
RESERVED_GROUPS = {"toc", "key"}  # section ids map-toc, map-key are the page's own
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_TICK_RE = re.compile(r"`([^`]+)`")
_HEAD_RE = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")


def esc(s):
    return html.escape(s, quote=True)


def _fail(msg):
    raise SystemExit("map: " + msg)


def check_slug(entries):
    """The map page owns <out>/map/; no entry may take that name."""
    if any(e["name"] == SLUG for e in entries):
        raise SystemExit("%r is reserved for the map page; rename that skill/agent/hook" % SLUG)


# ---- groups -----------------------------------------------------------------

def groups(meta, entries):
    """[(group, [name, ...])] from meta.json, validated against entries."""
    raw = (meta or {}).get(META_KEY)
    if not isinstance(raw, dict) or not raw:
        _fail("meta.json %s: need an object {group: [name, ...]}" % META_KEY)
    names = [e["name"] for e in entries]
    seen = {}
    out = []
    for g, members in raw.items():
        if not GROUP_RE.match(g):
            _fail("meta.json %s: group %r must be lowercase a-z, 0-9, -" % (META_KEY, g))
        if g in RESERVED_GROUPS:
            _fail("meta.json %s: group name %r is reserved" % (META_KEY, g))
        if not isinstance(members, list) or not members or not all(isinstance(n, str) for n in members):
            _fail("meta.json %s[%r]: need a non-empty list of names" % (META_KEY, g))
        for n in members:
            if n not in names:
                _fail("meta.json %s[%r]: unknown name %r" % (META_KEY, g, n))
            if n in seen:
                _fail("meta.json %s: %r is in both %r and %r" % (META_KEY, n, seen[n], g))
            seen[n] = g
        out.append((g, list(members)))
    missing = [n for n in names if n not in seen]
    if missing:
        _fail("meta.json %s: not in any group: %s" % (META_KEY, ", ".join(missing)))
    return out


# ---- edges ------------------------------------------------------------------

def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def _anchors(root, rel, cache):
    if rel not in cache:
        slugs = set()
        in_fence = False
        for line in _read(os.path.join(root, *rel.split("/"))).replace("\r\n", "\n").split("\n"):
            if line.lstrip().startswith(("```", "~~~")):
                in_fence = not in_fence
            m = None if in_fence else _HEAD_RE.match(line)
            if m:
                slugs.add(slugify(strip_inline(m.group(1))))
        cache[rel] = slugs
    return cache[rel]


def related_md(root, e, agents_readme):
    """Markdown body of an entry's Related section (\"\" if none), and the
    repo dir its relative links resolve from."""
    pre, pairs, _base = site_detail.raw_sections(root, e, agents_readme)
    ordered, _extras = site_detail.organise(pre, pairs)
    body = next((b for k, _t, b in ordered if k == "related"), "")
    base_dir = {"agents": "agents", "hooks": "hooks"}.get(e["group"], e["source"])
    return body, base_dir


def link_targets(root, entries, name, md, base_dir, cache=None):
    """Entry names the markdown links in `md` point at, in order. Raises
    SystemExit on a dangling relative link (missing file or anchor)."""
    cache = {} if cache is None else cache
    by_path, agents, hook_anchors = {}, [], {}
    for e in entries:
        by_path[e["source"]] = e["name"]
        if e["group"] == "agents":
            agents.append(e["name"])
        elif e["group"] == "hooks":
            hook_anchors[site_detail.hook_anchor(e["_x"]["heading"])] = e["name"]
        else:
            by_path[e["source"] + "/README.md"] = e["name"]
    out = []
    for text, url in _LINK_RE.findall(md):
        if re.match(r"^[a-z][a-z0-9+.-]*:|^/", url):
            continue
        path, _, frag = url.partition("#")
        if not path:
            continue  # in-page anchor
        key = posixpath.normpath(posixpath.join(base_dir, path)).rstrip("/")
        where = "%s: Related link %r" % (name, url)
        if key.startswith("..") or key == ".":
            _fail("%s leaves the repo" % where)
        if not os.path.exists(os.path.join(root, *key.split("/"))):
            _fail("%s: no such file" % where)
        if key == "agents/README.md" and frag in agents:
            out.append(frag)
        elif key == "agents/README.md" and not frag:
            out.extend(n for n in _TICK_RE.findall(text) if n in agents)
        elif key == "hooks/README.md" and frag in hook_anchors:
            out.append(hook_anchors[frag])
        else:
            if frag and key.endswith(".md") and frag not in _anchors(root, key, cache):
                _fail("%s: no heading #%s" % (where, frag))
            if key in by_path:
                out.append(by_path[key])
    return out


def edges(root, entries, workflows):
    """[(src, dst, [kind, ...])] in entry order; per source: related, then
    preloads, then workflow successors. No self-edges."""
    names = {e["name"] for e in entries}
    p = os.path.join(root, "agents", "README.md")
    agents_readme = _read(p) if os.path.isfile(p) else ""
    found = {e["name"]: [] for e in entries}  # src -> [(dst, kind)]
    cache = {}
    for e in entries:
        md, base_dir = related_md(root, e, agents_readme)
        for t in link_targets(root, entries, e["name"], md, base_dir, cache):
            found[e["name"]].append((t, "related"))
        if e["group"] == "agents":
            pre = e["_x"]["fm"].get("skills") or []
            for s in pre if isinstance(pre, list) else []:
                if s not in names:
                    _fail("%s: preloads unknown skill %r" % (e["name"], s))
                found[e["name"]].append((s, "preloads"))
    for wf in workflows:
        actors = [s["name"] for s in wf["steps"] if s["kind"] != "human"]
        for a, b in zip(actors, actors[1:]):
            found[a].append((b, "workflow"))
    out = []
    for e in entries:
        idx = {}
        for dst, kind in found[e["name"]]:
            if dst == e["name"]:
                continue
            if dst not in idx:
                idx[dst] = len(out)
                out.append((e["name"], dst, []))
            kinds = out[idx[dst]][2]
            if kind not in kinds:
                kinds.append(kind)
    return out


# ---- render -----------------------------------------------------------------

group_title = site_detail.category_title


def flowchart(members, group_edges):
    """Mermaid-subset text for one group: members first, then outside targets."""
    order = list(members)
    for _s, d, _k in group_edges:
        if d not in order:
            order.append(d)
    ids = {n: "n%d" % i for i, n in enumerate(order)}
    lines = ["flowchart LR"]
    lines += ["%s[%s]" % (ids[n], n) for n in order]
    for s, d, kinds in group_edges:
        arrow = "-.->" if kinds == ["workflow"] else "-->"
        label = "|preloads|" if "preloads" in kinds else ""
        lines.append("%s %s%s %s" % (ids[s], arrow, label, ids[d]))
    return "\n".join(lines)


def _title(g, members, group_edges):
    parts = ["%s to %s (%s)" % (s, d, ", ".join(k)) for s, d, k in group_edges]
    lone = [n for n in members if not any(n == s for s, _d, _k in group_edges)]
    if lone:
        parts.append("no outgoing links: " + ", ".join(lone))
    return "Map of %s: %s." % (group_title(g), "; ".join(parts))


def _a(base, n):
    return '<a href="%s/%s">%s</a>' % (esc(base), esc(n), esc(n))


def render_group(g, members, all_edges, summaries, base):
    ge = [x for x in all_edges if x[0] in members]
    svg = flow_svg.render(flowchart(members, ge), _title(g, members, ge))
    items = []
    for n in members:
        outs = [x for x in ge if x[0] == n]
        sub = ""
        if outs:
            sub = '<ul class="map-out">%s</ul>' % "".join(
                '<li><span class="dim">%s</span> %s</li>' % (esc(", ".join(k)), _a(base, d))
                for _s, d, k in outs)
        items.append('<li>%s <span class="dim">%s</span>%s</li>' % (_a(base, n), esc(summaries[n]), sub))
    gid = "map-" + g
    return ('<section class="sec map-group" aria-labelledby="%s">\n<h2 id="%s">%s <span class="n">(%d)</span></h2>\n'
            '<div class="flow" tabindex="0" role="group" aria-label="%s graph, scrolls sideways">%s</div>\n'
            '<ul class="map-list">\n%s\n</ul>\n</section>'
            % (esc(gid), esc(gid), esc(group_title(g)), len(members), esc(group_title(g)), svg, "\n".join(items)))


def legend():
    rows = [("solid arrow", "related: the source links to the target in its Related section"),
            ("solid arrow labelled preloads", "preloads: an agent loads that skill at start (its frontmatter)"),
            ("dotted arrow", "workflow: the target is the next step in a sample workflow")]
    items = "\n".join("<li><strong>%s</strong>. %s</li>" % (esc(a), esc(b)) for a, b in rows)
    return ('<section class="sec" aria-labelledby="map-key">\n<h2 id="map-key">How to read it</h2>\n'
            '<p>Each group draws its members and every arrow that leaves them, so each link shows once. '
            'A name from another group appears where a member points at it. Wide graphs scroll sideways; '
            'the list under each graph has the same links.</p>\n<ul class="map-legend">\n%s\n</ul>\n</section>' % items)


def render_list(grps, all_edges, entries, base):
    summaries = {e["name"]: e["summary"] for e in entries}
    toc = "\n".join('<li><a href="#map-%s">%s</a></li>' % (esc(g), esc(group_title(g))) for g, _m in grps)
    out = ['<nav class="sec wf-toc" aria-labelledby="map-toc">\n<h2 id="map-toc">Groups</h2>\n'
           '<ul>\n%s\n</ul>\n</nav>' % toc, legend()]
    out += [render_group(g, m, all_edges, summaries, base) for g, m in grps]
    return "\n".join(out)


def render_index(template, grps, all_edges, entries, base, data_json):
    values = {"BASE": esc(base), "COUNT": str(len(entries)), "EDGES": str(len(all_edges)),
              "LIST": render_list(grps, all_edges, entries, base), "DATA": data_json}
    return re.sub(r"\{\{([A-Z]+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template)


def build(root, entries, meta, workflows):
    """(groups, edges) validated; SystemExit on any problem."""
    check_slug(entries)
    return groups(meta, entries), edges(root, entries, workflows)
