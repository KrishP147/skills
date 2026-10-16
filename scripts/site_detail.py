"""Detail-page (/<name>) rendering for scripts/build_site.py. Stdlib only.

Sources: a skill's README.md (split on "## " headings), or an agent's
"## <name>" section of agents/README.md (split on its "- **Label:**"
bullets) plus agents/<name>.md frontmatter, or a hook's "## `<file>.py`"
section of hooks/README.md (split on paragraphs led by a "Label:" that maps,
e.g. "How it works:", "Install into a repo:"). Headings are mapped onto the
canonical SECTIONS with tolerant matching; sections that don't map render
after the mapped ones, before Source. Missing sections are simply absent.

The Example section renders as a Claude Code transcript (example_html); an
entry without one gets a WARN line on stderr.
"""
import html
import json
import os
import posixpath
import re
import sys

import site_workflows
from flow_svg import FlowError
from md_render import Renderer, safe_url, strip_inline, tx_prompt, tx_reply, tx_wrap

REPO_URL = "https://github.com/KrishP147/skills"
SITE_URL = "https://www.krishpunjabi.com/skills"

SECTIONS = (
    ("what", "What it does"),
    ("when", "When to use"),
    ("invoke", "How to invoke"),
    ("how", "How it works"),
    ("flow", "Flow"),
    ("design", "Design principles"),
    ("usecases", "Use cases"),
    ("tips", "Tips"),
    ("example", "Example"),
    ("related", "Related"),
    ("prereqs", "Prereqs"),
)
# Normalised heading (or its leading words) -> section key.
ALIASES = {
    "what": ("what it does", "what", "overview", "summary", "role"),
    "when": ("when to use", "when to use it", "when"),
    "invoke": ("how to invoke", "invoke", "invocation", "usage", "you pass", "install"),
    "how": ("how it works",),
    "flow": ("flow", "flow diagram", "flowchart", "diagram", "the loop"),
    "design": ("design principles", "principles", "design"),
    "usecases": ("use cases", "use case"),
    "tips": ("tips", "gotchas", "tips and gotchas"),
    "example": ("example", "examples", "worked example"),
    "related": ("related", "see also", "related skills"),
    "prereqs": ("prereqs", "prereq", "prerequisites", "prerequisite", "requirements"),
}
# The "*... `SKILL.md` is the prompt Claude follows; this file is for you.*"
# note at the top of each README is meant for repo readers, not the site.
_README_NOTE_RE = re.compile(r"^\*.*`SKILL\.md` is the prompt Claude follows")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_TRANSCRIPT_FENCE_RE = re.compile(r"^ {0,3}(```|~~~)\s*transcript\s*$", re.M)


def esc(s):
    return html.escape(s, quote=True)


def norm_heading(text):
    t = strip_inline(text).lower()
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return " ".join(t.split())


def section_key(heading):
    h = norm_heading(heading)
    best = None
    for key, aliases in ALIASES.items():
        for a in aliases:
            if (h == a or h.startswith(a + " ")) and (best is None or len(a) > best[1]):
                best = (key, len(a))
    return best[0] if best else None


def split_h2(md):
    """(preamble, [(heading, body), ...]) split on '## ' outside fences.
    A leading '# ' title line is dropped."""
    pre, secs, cur, in_fence = [], [], None, False
    for line in md.replace("\r\n", "\n").split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        if not in_fence and re.match(r"^## +\S", line):
            cur = [line[3:].strip(), []]
            secs.append(cur)
            continue
        if not in_fence and cur is None and re.match(r"^# +\S", line):
            continue
        (cur[1] if cur else pre).append(line)
    pre_text = "\n".join(l for l in pre if not _README_NOTE_RE.match(l.strip())).strip()
    return pre_text, [(h, "\n".join(b).strip()) for h, b in secs]


def split_label_bullets(md):
    """Split '- **Label:** text' top-level bullets into (label, body)."""
    out, cur, rest = [], None, []
    for line in md.split("\n"):
        m = re.match(r"^- \*\*(.+?):?\*\*:?\s*(.*)$", line)
        if m:
            text = m.group(2)
            cur = [m.group(1).rstrip(":"), [text[:1].upper() + text[1:]]]
            out.append(cur)
        elif cur is not None and (line.startswith("  ") or not line.strip()):
            cur[1].append(line[2:] if line.startswith("  ") else line)
        else:
            cur = None
            rest.append(line)
    return "\n".join(rest).strip(), [(l, "\n".join(b).strip()) for l, b in out]


_LABEL_RE = re.compile(r"^([A-Z][^:`\[]*?):(?:\s+(.*))?$")


def split_label_paragraphs(md):
    """Split prose on paragraphs whose first line starts with a 'Label:' that
    maps to a section ('How it works: ...', 'Related: ...'). Other paragraphs
    stay with the block above them. A bare short label line (<= 4 words,
    'Install into a repo:') is dropped; a longer one ('Example output once
    ...:') is kept as text."""
    pre, out, cur = [], [], None
    in_fence, para_start = False, True
    for line in md.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        m = _LABEL_RE.match(line) if para_start and not in_fence and not _FENCE_RE.match(line) else None
        key = section_key(m.group(1)) if m else None
        if key:
            rest = (m.group(2) or "").strip()
            cur = [m.group(1), []]
            out.append(cur)
            if rest:
                cur[1].append(rest[:1].upper() + rest[1:])
            elif len(norm_heading(m.group(1)).split()) > 4:
                cur[1].append(line)
        else:
            (cur[1] if cur else pre).append(line)
        para_start = not in_fence and not line.strip()
    return "\n".join(pre).strip(), [(l, "\n".join(b).strip()) for l, b in out]


def organise(pre, pairs):
    """Map (heading, body) pairs onto SECTIONS. Returns (ordered, extras)."""
    mapped, extras = {}, []
    for heading, body in pairs:
        if not body.strip():
            continue
        key = section_key(heading)
        if key:
            mapped.setdefault(key, []).append(body)
        else:
            extras.append((heading, body))
    if pre:
        mapped.setdefault("what", []).insert(0, pre)
    ordered = [(key, title, "\n\n".join(mapped[key])) for key, title in SECTIONS if key in mapped]
    return ordered, extras


# ---- links ------------------------------------------------------------------

class LinkIndex:
    """Knows every page name, and which repo paths map onto which page."""

    def __init__(self, root, entries, base=""):
        self.root = root
        self.base = base
        self.names = {e["name"] for e in entries}
        self.agents = {e["name"] for e in entries if e["group"] == "agents"}
        self.dir_to_name = {}
        self.hook_anchors = {}  # hooks/README.md#<slug> -> hook name
        for e in entries:
            self.dir_to_name[e["source"]] = e["name"]  # skill dir, agents/<name>.md, hooks/<name>.py
            if e["group"] == "hooks":
                self.hook_anchors[hook_anchor(e["_x"]["heading"])] = e["name"]
            elif e["group"] != "agents":
                self.dir_to_name[e["source"] + "/README.md"] = e["name"]

    def rewriter(self, base_dir, on_page_link=None, agents_readme=False):
        def rewrite(url):
            if url.startswith(("http://", "https://", "mailto:", "/")):
                return url
            path, _, frag = url.partition("#")
            if not path:
                if agents_readme and frag in self.agents:
                    return self._page(frag, on_page_link)
                if agents_readme:
                    return "%s/blob/master/agents/README.md#%s" % (REPO_URL, frag)
                return url  # in-page anchor
            resolved = posixpath.normpath(posixpath.join(base_dir, path))
            if resolved.startswith("..") or resolved == ".":
                return REPO_URL
            key = resolved.rstrip("/")
            if key in self.dir_to_name:
                return self._page(self.dir_to_name[key], on_page_link)
            if key == "agents/README.md" and frag in self.agents:
                return self._page(frag, on_page_link)
            if key == "hooks/README.md" and frag in self.hook_anchors:
                return self._page(self.hook_anchors[frag], on_page_link)
            kind = "tree" if os.path.isdir(os.path.join(self.root, *key.split("/"))) else "blob"
            return "%s/%s/master/%s%s" % (REPO_URL, kind, key, "#" + frag if frag else "")
        return rewrite

    def _page(self, name, on_page_link):
        if on_page_link:
            on_page_link(name)
        return self.base + "/" + name


# ---- sources ------------------------------------------------------------------

def agent_section(agents_readme, name):
    _pre, secs = split_h2(agents_readme)
    for heading, body in secs:
        if heading.strip() == name:
            return body
    return ""


def hook_section(hooks_readme, filename):
    """(heading, body) of the '## `<filename>` ...' section, else ("", "")."""
    _pre, secs = split_h2(hooks_readme)
    for heading, body in secs:
        if heading.startswith("`%s`" % filename):
            return heading, body
    return "", ""


def hook_anchor(heading):
    """GitHub anchor of a hooks/README.md heading."""
    from md_render import slugify
    return slugify(strip_inline(heading))


def first_paragraph_text(md):
    """Plain text of the first paragraph (one line, inline markup dropped)."""
    para = []
    for line in md.strip().split("\n"):
        if not line.strip():
            break
        para.append(line.strip())
    return strip_inline(" ".join(para))


def shared_agent_example(agents_readme):
    _pre, secs = split_h2(agents_readme)
    for heading, body in secs:
        if section_key(heading) == "example":
            return body
    return ""


# Sections a grouped skill (kanban/<name>) inherits from its group README
# when its own README lacks them.
INHERITED = ("flow", "prereqs")


def parent_section(root, source, key):
    """(heading, body) of the `key` section in a skill's parent-group README
    (e.g. kanban/README.md for kanban/next), else None."""
    parent = posixpath.dirname(source)
    if not parent:
        return None
    path = os.path.join(root, *parent.split("/"), "README.md")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8-sig") as f:
        _pre, secs = split_h2(f.read())
    for heading, body in secs:
        if section_key(heading) == key:
            return heading, body
    return None


def prereq_hint(pairs):
    """Short chip text from a heading like 'Prerequisite: the `project` scope'."""
    for heading, _body in pairs:
        if section_key(heading) == "prereqs" and ":" in heading:
            return strip_inline(heading.split(":", 1)[1])
    return ""


def raw_sections(root, e, agents_readme):
    """[(heading, markdown body)] + preamble for one entry, plus link base dir."""
    if e["group"] == "agents":
        rest, bullets = split_label_bullets(agent_section(agents_readme, e["name"]))
        name = e["name"]
        invoke = '```\nAgent(subagent_type="%s", prompt=…)\n```' % name
        pairs = []
        seen_invoke = False
        for label, body in bullets:
            if section_key(label) == "invoke":
                body = invoke + "\n\n**You pass:** " + body
                seen_invoke = True
            pairs.append((label, body))
        if not seen_invoke:
            pairs.append(("How to invoke", invoke))
        ex = shared_agent_example(agents_readme)
        if ex:
            pairs.append(("Example", ex))
        return rest, pairs, "agents"
    if e["group"] == "hooks":
        pre, pairs = split_label_paragraphs(e["readme"])
        return pre, pairs, "hooks"
    pre, pairs = split_h2(e["readme"])
    for key in INHERITED:
        if any(section_key(h) == key for h, _b in pairs):
            continue  # the skill's own section wins
        pp = parent_section(root, e["source"], key)
        if pp:
            # Relative links in the parent README resolve from the parent dir.
            heading, body = pp
            pairs.append((heading, _rebase_links(body, posixpath.dirname(e["source"]), e["source"])))
    return pre, pairs, e["source"]


def _rebase_links(md, from_dir, to_dir):
    def fix(m):
        url = m.group(2)
        if re.match(r"^[a-z]+:|^/|^#", url):
            return m.group(0)
        target = posixpath.normpath(posixpath.join(from_dir, url))
        return "%s%s)" % (m.group(1), posixpath.relpath(target, to_dir) + ("/" if url.endswith("/") else ""))
    return re.sub(r"(\]\()([^)\s]+)\)", lambda m: fix(m), md)


# ---- chips ------------------------------------------------------------------

def level_of(meta, name):
    for level, names in meta.get("levels", {}).items():
        if name in names:
            return level
    return "new"


def author_of(meta, name):
    return meta.get("authors", {}).get(name, meta.get("default_author", "Krish"))


def first_line_text(md, limit=70):
    for line in md.split("\n"):
        s = line.strip()
        if not s or s.startswith(("```", "~~~", "|")):
            continue
        s = re.sub(r"^([-*+]|\d+[.)])\s+", "", s)
        s = re.sub(r"^prereqs?:\s*", "", strip_inline(s), flags=re.I)
        return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"
    return ""


def chips(meta, e, prereq_md, hint=""):
    x = e["_x"]
    fm = x["fm"]
    out = [("author", author_of(meta, e["name"]), None)]
    if e["group"] == "agents":
        out.append(("invocation", "subagent (Agent tool)", None))
        if fm.get("model"):
            out.append(("model", fm["model"], None))
        if fm.get("tools"):
            out.append(("tools", _as_text(fm["tools"]), None))
        if fm.get("disallowedTools"):
            out.append(("tools", "all except " + _as_text(fm["disallowedTools"]), None))
        skills = fm.get("skills") or []
        if isinstance(skills, list) and skills:
            out.append(("preloads", ", ".join("/" + s for s in skills), None))
        if "guard-git" in x.get("fm_raw", ""):
            out.append(("guard", "guard-git.py hook", None))
    elif e["group"] == "hooks":
        m = re.match(r"(\w+) hook\b", x.get("lead", ""))  # "PreToolUse hook for ..."
        out.append(("invocation", (m.group(1) + " hook") if m else "hook", None))
        out.append(("source", e["source"], "%s/blob/master/%s" % (REPO_URL, e["source"])))
    else:
        user_only = str(fm.get("disable-model-invocation", "")).strip().lower() == "true"
        out.append(("invocation", "user only" if user_only else "model + user", None))
    if prereq_md:
        out.append(("prereqs", hint or first_line_text(prereq_md, 48), "#prereqs"))
    level = level_of(meta, e["name"])
    label = meta.get("level_labels", {}).get(level, level)
    out.append(("tested", label, None))
    items = []
    for k, v, href in out:
        val = '<a href="%s">%s</a>' % (esc(href), esc(v)) if href else esc(v)
        items.append('        <li class="chip chip-%s"><span class="k">%s</span> %s</li>' % (esc(k), esc(k), val))
    return "\n".join(items), level


def _as_text(v):
    return ", ".join(v) if isinstance(v, list) else str(v)


# ---- page -------------------------------------------------------------------

def build_pages(root, entries, meta, template, data_json, site_base="", workflows=None):
    """Return {name: html}. Two passes: render, then compose (for backlinks).
    workflows: {name: [workflow, ...]} (site_workflows.by_name); each page
    lists only its own, generated here (never inherited from a group README)."""
    agents_readme = ""
    p = os.path.join(root, "agents", "README.md")
    if os.path.isfile(p):
        with open(p, encoding="utf-8-sig") as f:
            agents_readme = f.read()
    index = LinkIndex(root, entries, site_base)
    video = contributing_video(root)

    rendered = {}
    backlinks = {e["name"]: set() for e in entries}
    for e in entries:
        pre, pairs, base = raw_sections(root, e, agents_readme)
        ordered, extras = organise(pre, pairs)
        if e["group"] == "agents":
            base_dir, agents_md = "agents", True
        elif e["group"] == "hooks":
            base_dir, agents_md = "hooks", False
        else:
            base_dir, agents_md = e["source"], False
        targets = set()
        rw = index.rewriter(base_dir, targets.add, agents_readme=agents_md)
        rendered[e["name"]] = (ordered, extras, rw, prereq_hint(pairs))
        if missing_example(ordered):
            sys.stderr.write("WARN: %s: no Example section (its page has no transcript)\n" % e["name"])
        # Pre-render to collect outgoing page links (for backlinks).
        # A ```mermaid fence outside the flow_svg subset fails the build here.
        probe = Renderer(rw)
        try:
            for _k, _t, body in ordered:
                probe.render(body)
            for _h, body in extras:
                probe.render(body)
        except FlowError as err:
            raise FlowError("%s: %s" % (e["name"], err)) from err
        for t in targets:
            if t != e["name"] and t in backlinks:
                backlinks[t].add(e["name"])

    pages = {}
    names = [e["name"] for e in entries]
    for i, e in enumerate(entries):
        ordered, extras, rw, hint = rendered[e["name"]]
        ordered = list(ordered)
        if e["group"] == "agents":
            ordered = _with_agent_related(ordered, e, backlinks[e["name"]], site_base)
        if video:
            ordered = [(k, t, b + "\n\nShared context for these principles: [Matt Pocock's video](%s)." % video
                        if k == "design" else b) for k, t, b in ordered]
        prereq_md = next((b for k, _t, b in ordered if k == "prereqs"), "")
        rd = Renderer(rw)
        # Reserve ids the page itself uses.
        for fixed in ("term", "cmd", "menu", "echo", "hint", "status", "prompt-box",
                      "comments", "skill-data", "source"):
            rd.unique_id(fixed)
        body = []
        for key, title, md in ordered:
            body.append(_section(rd, title, md, example=key == "example"))
        for heading, md in extras:
            body.append(_section(rd, heading, md, extra=True))
        wfs = (workflows or {}).get(e["name"])
        if wfs:
            body.append(site_workflows.detail_section(wfs, site_base, rd.unique_id("sample-workflows")))
        body.append(_source_section(e))
        chip_html, _level = chips(meta, e, prereq_md, hint)
        prev_e = entries[i - 1] if i > 0 else None
        next_e = entries[i + 1] if i + 1 < len(entries) else None
        url = "%s/%s" % (SITE_URL, e["name"])
        # Single pass, so README text containing "{{NAME}}" etc. stays literal.
        values = {
            "CHIPS": chip_html,
            "BODY": "\n".join(body),
            "PREVNEXT": _prevnext(prev_e, next_e, site_base),
            "BASE": esc(site_base),
            "DATA": data_json,
            "URL": esc(url),
            "NAME": esc(e["name"]),
            "GROUP": esc(e["group"]),
            "DESCRIPTION": esc(e["description"]),
        }
        pages[e["name"]] = re.sub(r"\{\{([A-Z]+)\}\}",
                                  lambda m: values.get(m.group(1), m.group(0)), template)
    assert len(pages) == len(names)
    return pages


def _with_agent_related(ordered, e, backlinks, base=""):
    fm = e["_x"]["fm"]
    lines = []
    skills = fm.get("skills") or []
    if isinstance(skills, list) and skills:
        lines.append("- Preloads: " + ", ".join("[`%s`](%s/%s)" % (s, base, s) for s in skills))
    if backlinks:
        lines.append("- Linked from: " + ", ".join("[`%s`](%s/%s)" % (s, base, s) for s in sorted(backlinks)))
    if not lines:
        return ordered
    md = "\n".join(lines)
    out, done = [], False
    for k, t, b in ordered:
        if k == "related":
            b, done = b + "\n\n" + md, True
        out.append((k, t, b))
    if not done:
        out.append(("related", "Related", md))
        order = [k for k, _ in SECTIONS]
        out.sort(key=lambda s: order.index(s[0]))
    return out


def _section(rd, title, md, extra=False, example=False):
    from md_render import slugify
    sid = rd.unique_id(slugify(title))
    cls = "sec sec-extra" if extra else "sec"
    inner = example_html(rd, md) if example else rd.render(md, heading_offset=1)
    return ('<section class="%s" aria-labelledby="%s">\n<h2 id="%s">%s</h2>\n%s\n</section>'
            % (cls, esc(sid), esc(sid), rd.inline(title), inner))


def split_example(md):
    """(prompt, rest) of an Example section: prompt is the text of a leading
    code fence (the '/cmd args' line), else None; rest is the markdown after."""
    lines = md.strip("\n").split("\n")
    if not lines or not _FENCE_RE.match(lines[0]):
        return None, md.strip()
    marker = lines[0].strip()[:3]
    for j in range(1, len(lines)):
        if lines[j].strip().startswith(marker):
            prompt = "\n".join(l.strip() for l in lines[1:j] if l.strip())
            return prompt or None, "\n".join(lines[j + 1:]).strip()
    return None, md.strip()


def example_html(rd, md):
    """Example section as a transcript. With a ```transcript fence, md_render
    draws the fence and prose around it stays prose; otherwise the leading
    fence becomes the '> /cmd args' prompt and the rest one reply block."""
    if _TRANSCRIPT_FENCE_RE.search(md):
        return rd.render(md, heading_offset=1)
    prompt, rest = split_example(md)
    parts = [tx_prompt(prompt)] if prompt else []
    if rest:
        parts.append(tx_reply(rd.render(rest, heading_offset=1), block=True))
    return tx_wrap(parts)


def missing_example(ordered):
    return not any(k == "example" for k, _t, _b in ordered)


def _source_section(e):
    links = []
    if e["group"] == "agents":
        links.append((e["source"], "%s/blob/master/%s" % (REPO_URL, e["source"])))
        links.append(("agents/README.md#%s" % e["name"],
                      "%s/blob/master/agents/README.md#%s" % (REPO_URL, e["name"])))
    elif e["group"] == "hooks":
        anchor = hook_anchor(e["_x"]["heading"])
        links.append((e["source"], "%s/blob/master/%s" % (REPO_URL, e["source"])))
        links.append(("hooks/README.md#%s" % anchor,
                      "%s/blob/master/hooks/README.md#%s" % (REPO_URL, anchor)))
    else:
        links.append((e["source"] + "/SKILL.md", "%s/blob/master/%s/SKILL.md" % (REPO_URL, e["source"])))
        if e["readme"]:
            links.append((e["source"] + "/README.md", "%s/blob/master/%s/README.md" % (REPO_URL, e["source"])))
    items = "\n".join('<li><a href="%s">%s</a></li>' % (esc(u), esc(t)) for t, u in links)
    return ('<section class="sec" aria-labelledby="source">\n<h2 id="source">Source</h2>\n'
            "<ul>\n%s\n</ul>\n</section>" % items)


def _prevnext(prev_e, next_e, base=""):
    parts = []
    if prev_e:
        parts.append('    <a class="prev" href="%s/%s" rel="prev">&larr; /%s</a>' % (esc(base), esc(prev_e["name"]), esc(prev_e["name"])))
    else:
        parts.append('    <span class="prev"></span>')
    if next_e:
        parts.append('    <a class="next" href="%s/%s" rel="next">/%s &rarr;</a>' % (esc(base), esc(next_e["name"]), esc(next_e["name"])))
    return "\n".join(parts)


def contributing_video(root):
    p = os.path.join(root, "CONTRIBUTING.md")
    if not os.path.isfile(p):
        return ""
    with open(p, encoding="utf-8-sig") as f:
        m = re.search(r"\]\((https://(?:www\.)?youtube\.com/[^)\s]+)\)", f.read())
    return m.group(1) if m and safe_url(m.group(1)) else ""


def load_meta(root):
    with open(os.path.join(root, "site", "data", "meta.json"), encoding="utf-8") as f:
        return json.load(f)


def credited_third_party(root):
    """Names listed in '## a, b, c' headings of THIRD_PARTY_LICENSES.md."""
    p = os.path.join(root, "THIRD_PARTY_LICENSES.md")
    names = set()
    if os.path.isfile(p):
        with open(p, encoding="utf-8-sig") as f:
            for line in f:
                if line.startswith("## "):
                    names.update(n.strip().strip("`") for n in line[3:].split(",") if n.strip())
    return names
