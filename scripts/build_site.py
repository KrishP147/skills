#!/usr/bin/env python3
"""Builds the static skills site into site/dist/. Stdlib only.

Reuses scripts/lint.py discovery + frontmatter parsing so the site lists
exactly what lint counts. Output (wiped + recreated every run):

  site/dist/index.html          terminal home + server-rendered skill list
  site/dist/skills.json         full data (name, description, summary,
                                group, source, readme)
  site/dist/<name>/index.html   detail page per skill/agent (site_detail.py)
  site/dist/404.html
  site/dist/*.css|*.js          copied from site/src/
  site/dist/*.png               copied byte-for-byte from site/src/

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

GROUPS = ("core", "kanban", "agents")
STATIC_EXTS = (".css", ".js")
BINARY_EXTS = (".png",)  # copied as bytes, no text IO
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


def posix_rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def collect(root):
    """Return entries sorted by group order then name."""
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
    entries.sort(key=lambda e: (GROUPS.index(e["group"]), e["name"]))
    return entries


def _entry(fm, fallback_name, group, source, readme, text):
    description = fm.get("description") or ""
    if not isinstance(description, str):
        description = ""
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
    agents = sum(1 for e in entries if e["group"] == "agents")
    return len(entries) - agents, agents


def count_line(entries):
    skills, agents = counts(entries)
    return "%d skill%s · %d agent%s" % (
        skills, "" if skills == 1 else "s", agents, "" if agents == 1 else "s")


def esc(s):
    return html.escape(s, quote=True)


def normalize_base(base):
    """"/skills", "/skills/", "skills" -> "/skills"; "/" or "" -> ""."""
    base = (base or "").strip().strip("/")
    return "/" + base if base else ""


def render_list(entries, base=""):
    out = []
    for group in GROUPS:
        items = [e for e in entries if e["group"] == group]
        if not items:
            continue
        out.append('<section class="group" aria-labelledby="g-%s">' % group)
        out.append('<h2 id="g-%s">%s <span class="n">(%d)</span></h2>' % (group, group, len(items)))
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


def nav_data(entries):
    return embed_json([{"name": e["name"], "summary": e["summary"], "group": e["group"]} for e in entries])


def render_index(template, entries, base=""):
    return (template.replace("{{BASE}}", esc(base))
            .replace("{{COUNT}}", esc(count_line(entries)))
            .replace("{{LIST}}", render_list(entries, base))
            .replace("{{DATA}}", nav_data(entries)))


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
        raise SystemExit("duplicate skill/agent names: %s" % sorted(n for n in names if names.count(n) > 1))

    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)

    write(os.path.join(out, "index.html"), render_index(read_text(os.path.join(src, "index.html")), entries, base))
    pages = site_detail.build_pages(root, entries, site_detail.load_meta(root),
                                    read_text(os.path.join(src, "detail.html")), nav_data(entries), base)
    for e in entries:
        write(os.path.join(out, e["name"], "index.html"), pages[e["name"]])
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
    skills, agents = counts(entries)
    print("Built %s: %d skills, %d agents" % (display_path(out, root), skills, agents))


if __name__ == "__main__":
    main(sys.argv[1:])
