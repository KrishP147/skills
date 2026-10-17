#!/usr/bin/env python3
"""Builds the static skills site into site/dist/. Stdlib only.

Reuses scripts/lint.py discovery + frontmatter parsing so the site lists
exactly what lint counts. Output (wiped + recreated every run):

  site/dist/index.html          terminal home + server-rendered skill list
                                (one section per meta.json category)
  site/dist/skills.json         full data (name, description, summary,
                                group, category, source, readme)
  site/dist/<name>/index.html   detail page per skill/agent/hook (site_detail.py)
  site/dist/workflows/index.html  sample workflows from site/data/workflows.json
                                (site_workflows.py; validated, every skill covered)
  site/dist/map/index.html      skills map: categories from meta.json "categories",
                                edges generated from the docs (site_map.py)
  site/dist/404.html
  site/dist/*.css|*.js|*.svg    copied as text from site/src/
  site/dist/*.webp|*.png|*.jpg  copied byte for byte (rocky.webp, favicon-32.png, apple-touch-icon.png)

Usage: python scripts/build_site.py [--base /prefix] [--out DIR]
  --base  URL prefix the site is served under (default env SITE_BASE, else "/")
  --out   output dir, relative to cwd (default <repo>/site/dist)
"""
import argparse
import html
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lint  # noqa: E402
import site_detail  # noqa: E402
import site_map  # noqa: E402
import site_workflows  # noqa: E402

GROUPS = ("core", "kanban", "agents", "hooks")
KINDS = {"agents": "agent", "hooks": "hook"}  # nav kind per group, else "skill"
STATIC_EXTS = (".css", ".js", ".svg")
BINARY_EXTS = (".webp", ".png", ".jpg")  # copied byte for byte
# Abbreviations that end in '.' but don't end a sentence.
_ABBREV = ("e.g.", "i.e.", "etc.", "vs.")


def read_text(path):
    # utf-8-sig drops a BOM; text mode normalises CRLF to LF.
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def first_sentence(text):
    text = " ".join(text.split())
    for m in re.finditer(r"[.!?](?=\s|$)", text):
        end = m.end()
        if any(text[:end].lower().endswith(a) for a in _ABBREV):
            continue
        return text[:end]
    return text


def apply_categories(entries, cats):
    """Set e["category"] from meta.json categories ([(category, [name, ...])],
    already validated) and sort entries by category order, then name."""
    cat = {n: (i, c) for i, (c, members) in enumerate(cats) for n in members}
    for e in entries:
        e["category"] = cat[e["name"]][1]
    entries.sort(key=lambda e: (cat[e["name"]][0], e["name"]))


def posix_rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def collect(root):
    """Return entries sorted by group order then name. The build re-sorts
    them by category (apply_categories)."""
    entries = []
    for path in lint.find_skill_files(root):
        text = read_text(path)
        fm, _body = lint.parse_frontmatter(text)
        fm = fm or {}
        skill_dir = os.path.dirname(path)
        rel_dir = posix_rel(skill_dir, root)
        group = "kanban" if rel_dir.startswith("kanban/") else "core"
        readme_path = os.path.join(skill_dir, "README.md")
        readme = read_text(readme_path) if os.path.isfile(readme_path) else ""
        entries.append(_entry(fm, os.path.basename(skill_dir), group, rel_dir, readme, text))
    for path in lint.find_agent_files(root):
        text = read_text(path)
        fm, body = lint.parse_frontmatter(text)
        fm = fm or {}
        stem = os.path.splitext(os.path.basename(path))[0]
        entries.append(_entry(fm, stem, "agents", posix_rel(path, root), body.strip("\n") + "\n", text))
    entries.extend(collect_hooks(root))
    entries.sort(key=lambda e: (GROUPS.index(e["group"]), e["name"]))
    return entries


def hook_files(root):
    """hooks/*.py, sorted. Agent hooks (agents/hooks/) are not listed."""
    d = os.path.join(root, "hooks")
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, fn) for fn in sorted(os.listdir(d)) if fn.endswith(".py")]


def collect_hooks(root):
    """One entry per hooks/<stem>.py. Its page text is the "## `<stem>.py`"
    section of hooks/README.md. Its summary is the heading tagline (text after
    the em dash), capitalized and ending in a period like skill summaries; its
    description is that summary plus the section's first paragraph."""
    files = hook_files(root)
    if not files:
        return []
    readme = read_text(os.path.join(root, "hooks", "README.md"))
    out = []
    for path in files:
        fn = os.path.basename(path)
        heading, body = site_detail.hook_section(readme, fn)
        if not body:
            raise SystemExit("hooks/README.md: no '## `%s`' section" % fn)
        e = _entry({}, os.path.splitext(fn)[0], "hooks", posix_rel(path, root), body + "\n", "")
        lead = site_detail.first_paragraph_text(body)
        e["summary"] = hook_tagline(heading) or first_sentence(lead)
        e["description"] = e["summary"] + " " + lead if lead else e["summary"]
        e["_x"]["lead"] = lead
        e["_x"]["heading"] = heading
        out.append(e)
    return out


def hook_tagline(heading):
    """"`x.py` — block foo" -> "Block foo." ("" without an em dash)."""
    _, sep, tail = heading.partition("—")
    tail = site_detail.strip_inline(tail).strip()
    if not sep or not tail:
        return ""
    i = next((k for k, c in enumerate(tail) if c.isalpha()), 0)
    tail = tail[:i] + tail[i:i + 1].upper() + tail[i + 1:]
    return tail if tail[-1] in ".!?" else tail + "."


def _entry(fm, fallback_name, group, source, readme, text):
    description = fm.get("description") or ""
    if not isinstance(description, str):
        description = ""
    description = description.strip()  # block scalars keep a trailing newline
    return {
        "name": fm.get("name") or fallback_name,
        "description": description,
        "summary": first_sentence(description),
        "group": group,
        "source": source,
        "readme": readme,
        # Build-only extras (stripped from skills.json).
        "_x": {"fm": fm, "fm_raw": _frontmatter_raw(text)},
    }


def _frontmatter_raw(text):
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    return m.group(1) if m else ""


def public(entries):
    return [{k: v for k, v in e.items() if not k.startswith("_")} for e in entries]


def counts(entries):
    """(skills, agents, hooks)."""
    agents = sum(1 for e in entries if e["group"] == "agents")
    hooks = sum(1 for e in entries if e["group"] == "hooks")
    return len(entries) - agents - hooks, agents, hooks


def count_line(entries):
    return " · ".join("%d %s%s" % (n, word, "" if n == 1 else "s")
                      for n, word in zip(counts(entries), ("skill", "agent", "hook")))


def esc(s):
    return html.escape(s, quote=True)


def normalize_base(base):
    """"/skills", "/skills/", "skills" -> "/skills"; "/" or "" -> ""."""
    base = (base or "").strip().strip("/")
    return "/" + base if base else ""


def render_list(entries, base=""):
    out = []
    for cat in dict.fromkeys(e["category"] for e in entries):  # entries are in category order
        items = [e for e in entries if e["category"] == cat]
        out.append('<section class="group" aria-labelledby="g-%s">' % esc(cat))
        out.append('<h2 id="g-%s">%s <span class="n">(%d)</span></h2>'
                   % (esc(cat), esc(site_map.group_title(cat)), len(items)))
        out.append('<ul class="skill-list">')
        for e in items:
            out.append(
                '<li><a href="%s/%s"><span class="nm">/%s</span>'
                '<span class="ds">%s</span></a></li>'
                % (esc(base), esc(e["name"]), esc(e["name"]), esc(e["summary"])))
        out.append("</ul>")
        out.append("</section>")
    return "\n".join(out)


def embed_json(obj):
    # Safe inside <script type="application/json">: no '</script>' or '<!--'.
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def aliases_of(meta, entries):
    """meta.json "aliases": {name: [alias, ...]}, validated against entries."""
    raw = (meta or {}).get("aliases") or {}
    names = {e["name"] for e in entries}
    out = {}
    for name, als in raw.items():
        if name not in names:
            raise SystemExit("meta.json aliases: unknown name %r" % name)
        if not isinstance(als, list) or not all(isinstance(a, str) and ALIAS_RE.match(a) for a in als):
            raise SystemExit("meta.json aliases[%r]: need a list of lowercase words (a-z, 0-9, -)" % name)
        clash = sorted(set(als) & names)
        if clash:
            raise SystemExit("meta.json aliases[%r]: %s already a skill/agent/hook name" % (name, clash))
        out[name] = list(als)
    return out


def nav_entry(e, aliases):
    d = {"name": e["name"], "kind": KINDS.get(e["group"], "skill"),
         "group": e["group"], "summary": e["summary"]}
    if aliases.get(e["name"]):
        d["aliases"] = aliases[e["name"]]
    return d


# Site pages the slash prompt can open besides entries: /<name> -> <base>/<name>.
PAGES = ({"name": site_map.SLUG, "kind": "page", "group": "pages",
          "summary": "Map of every skill, agent and hook, grouped by purpose, and how they connect."},
         {"name": site_workflows.SLUG, "kind": "page", "group": "pages",
          "summary": "Common workflows, step by step: which skills, agents and hooks to chain and why."})


def nav_data(entries, meta=None):
    aliases = aliases_of(meta, entries)
    return embed_json([nav_entry(e, aliases) for e in entries] + [dict(p) for p in PAGES])


def render_index(template, entries, base="", meta=None):
    return (template.replace("{{BASE}}", esc(base))
            .replace("{{COUNT}}", esc(count_line(entries)))
            .replace("{{LIST}}", render_list(entries, base))
            .replace("{{DATA}}", nav_data(entries, meta)))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def build(root, out, base=""):
    base = normalize_base(base)
    src = os.path.join(root, "site", "src")
    entries = collect(root)
    names = [e["name"] for e in entries]
    if len(set(names)) != len(names):
        raise SystemExit("duplicate skill/agent/hook names: %s" % sorted(n for n in names if names.count(n) > 1))
    site_workflows.check_slug(entries)
    site_map.check_slug(entries)  # before validate: a clashing name is the clearer error
    workflows = site_workflows.validate(site_workflows.load(root), entries)
    meta = site_detail.load_meta(root)
    map_groups, map_edges = site_map.build(root, entries, meta, workflows)
    apply_categories(entries, map_groups)
    site_detail.model_effort(meta, entries)
    site_detail.validate_levels(root, meta, entries)

    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)

    write(os.path.join(out, "index.html"),
          render_index(read_text(os.path.join(src, "index.html")), entries, base, meta))
    data = nav_data(entries, meta)
    pages = site_detail.build_pages(root, entries, meta, read_text(os.path.join(src, "detail.html")), data, base,
                                    workflows=site_workflows.by_name(workflows))
    for e in entries:
        write(os.path.join(out, e["name"], "index.html"), pages[e["name"]])
    write(os.path.join(out, site_workflows.SLUG, "index.html"),
          site_workflows.render_index(read_text(os.path.join(src, "workflows.html")), workflows, base, data))
    write(os.path.join(out, site_map.SLUG, "index.html"),
          site_map.render_index(read_text(os.path.join(src, "map.html")), map_groups, map_edges, entries, base, data))
    write(os.path.join(out, "404.html"),
          read_text(os.path.join(src, "404.html")).replace("{{BASE}}", esc(base)))
    write(os.path.join(out, "skills.json"),
          json.dumps(public(entries), ensure_ascii=False, indent=2) + "\n")
    for fn in sorted(os.listdir(src)):
        if fn.endswith(STATIC_EXTS):
            write(os.path.join(out, fn), read_text(os.path.join(src, fn)))
        elif fn.endswith(BINARY_EXTS):
            shutil.copyfile(os.path.join(src, fn), os.path.join(out, fn))
    return entries


def display_path(path, root):
    try:
        return posix_rel(path, root)
    except ValueError:  # different drive on Windows
        return path.replace(os.sep, "/")


def main(argv):
    ap = argparse.ArgumentParser(description="Build the static skills site.")
    ap.add_argument("--base", default=os.environ.get("SITE_BASE", "/"),
                    help='URL prefix to serve under, e.g. /skills (default: $SITE_BASE or "/")')
    ap.add_argument("--out", default=None, help="output dir, relative to cwd (default: <repo>/site/dist)")
    args = ap.parse_args(argv)
    root = lint.repo_root()
    out = os.path.abspath(args.out) if args.out else os.path.join(root, "site", "dist")
    entries = build(root, out, args.base)
    print("Built %s: %s" % (display_path(out, root), count_line(entries).replace(" · ", ", ")))


if __name__ == "__main__":
    main(sys.argv[1:])
