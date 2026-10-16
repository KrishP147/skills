"""Tests for scripts/build_site.py. Run: python -m unittest discover -s scripts -p "test_*.py" """
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from glob import glob
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_site  # noqa: E402
import lint  # noqa: E402
import site_workflows  # noqa: E402

ROOT = lint.repo_root()


def check_corner(tc, page, base, label):
    m = re.search(r'<a class="me[^"]*" href="https://www\.krishpunjabi\.com/" aria-label="([^"]+)">(.*?)</a>', page, re.S)
    tc.assertIsNotNone(m, label)
    tc.assertEqual(m.group(1), "Krish Punjabi — krishpunjabi.com", label)
    tc.assertIn('<img src="%s/rocky.webp"' % base, m.group(2), label)
    tc.assertIn(">krishpunjabi.com</span>", m.group(2), label)
    tc.assertNotIn("back", m.group(0).lower(), label)


def _palettes(css):
    """{"dark": tokens, "light": tokens} from style.css's two :root palettes
    (light inherits dark tokens it doesn't override)."""
    dark_src = re.search(r"^:root \{(.*?)^\}", css, re.S | re.M).group(1)
    light_src = re.search(r"@media \(prefers-color-scheme: light\) \{\s*:root \{(.*?)\}", css, re.S).group(1)

    def parse(src):
        return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", src))
    dark = parse(dark_src)
    return {"dark": dark, "light": dict(dark, **parse(light_src))}


def _rgba(v):
    v = v.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", v)
    if m:
        h = m.group(1)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (1.0,)
    m = re.fullmatch(r"rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\)", v)
    assert m, "unparsed color " + v
    return tuple(int(x) for x in m.groups()[:3]) + (float(m.group(4)),)


def _over(fg, bg):
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3)) + (1.0,)


def _contrast(a, b):
    def lum(c):
        def ch(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class PaletteContrastTest(unittest.TestCase):
    """WCAG AA (4.5:1) for token pairs, both palettes, rgba composited over --panel."""

    def test_selected_row_and_accent(self):
        with open(os.path.join(ROOT, "site", "src", "style.css"), encoding="utf-8") as f:
            css = f.read()
        css_rules = css.split("@media (prefers-color-scheme: light)", 1)[1]
        self.assertIn('.menu li[aria-selected="true"] .nm { color: var(--accent-sel); }', css_rules)
        self.assertIn("background: var(--sel-bg); }", css_rules)
        self.assertIn(".skill-list a:hover { background: var(--sel-bg); }", css_rules)
        self.assertIn(".skill-list a:hover .nm { color: var(--accent-sel); }", css_rules)
        for theme, t in _palettes(css).items():
            c = {k: _rgba(v) for k, v in t.items() if k not in ("--mono",)}
            panel, bg = c["--panel"], c["--bg"]
            sel = _over(c["--sel-bg"], panel)
            hov = _over(c["--sel-bg"], bg)
            pairs = {
                "selected name": (c["--accent-sel"], sel),
                "selected dim (.kd/.ds)": (c["--dim"], sel),
                "hover name on bg (.skill-list a:hover .nm)": (c["--accent-sel"], hov),
                "hover dim on bg (.skill-list a:hover .ds)": (c["--dim"], hov),
                "accent on bg": (c["--accent"], bg),
                "accent on panel": (c["--accent"], panel),
                "dim on panel (transcript .tx-res/.tx-more)": (c["--dim"], panel),
                "fg on panel (transcript text, flow node label)": (c["--fg"], panel),
                "dim on bg (flow edge label)": (c["--dim"], bg),
            }
            for label, (fg, back) in pairs.items():
                r = _contrast(_over(fg, back), back)
                self.assertGreaterEqual(r, 4.5, "%s %s: %.2f" % (theme, label, r))
            # Non-text graphics (WCAG 1.4.11): flow diagram lines and node borders.
            lines = {
                "dim on bg (flow edge, arrowhead)": (c["--dim"], bg),
                "accent-line on bg (flow node border)": (c["--accent-line"], bg),
            }
            for label, (fg, back) in lines.items():
                r = _contrast(_over(fg, back), back)
                self.assertGreaterEqual(r, 3.0, "%s %s: %.2f" % (theme, label, r))
        flow_rules = css.split("/* Flow diagram", 1)[1].split("\n\n", 1)[0]
        self.assertIn(".flow-edge path { fill: none; stroke: var(--dim);", flow_rules)
        self.assertIn(".flow-node rect { fill: var(--panel); stroke: var(--accent-line);", flow_rules)
        self.assertIn(".flow-label { fill: var(--fg); }", flow_rules)
        self.assertIn(".flow-etext { fill: var(--dim); }", flow_rules)
        self.assertIn(".flow-elabel rect { fill: var(--bg);", flow_rules)


class BuildSiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp(prefix="site-dist-")
        cls.entries = build_site.build(ROOT, cls.out)
        with open(os.path.join(cls.out, "skills.json"), encoding="utf-8") as f:
            cls.data = json.load(f)
        with open(os.path.join(cls.out, "index.html"), encoding="utf-8") as f:
            cls.index = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_counts_match_lint(self):
        skills, agents, hooks = build_site.counts(self.entries)
        self.assertEqual(skills, len(lint.find_skill_files(ROOT)))
        self.assertEqual(agents, len(lint.find_agent_files(ROOT)))
        self.assertEqual(hooks, len(glob(os.path.join(ROOT, "hooks", "*.py"))))
        self.assertEqual(hooks, 2)
        line = build_site.count_line(self.entries)
        self.assertEqual(line, "%d skills · %d agents · %d hooks" % (skills, agents, hooks))
        self.assertIn(build_site.esc(line), self.index)

    def test_hook_entries(self):
        by = {e["name"]: e for e in self.data}
        for name in ("smartzone", "spend-guard"):
            e = by[name]
            self.assertEqual(e["group"], "hooks")
            self.assertEqual(e["source"], "hooks/%s.py" % name)
            self.assertTrue(e["readme"].lstrip().startswith("`"), name)  # the README section, not the docstring
            self.assertNotIn("\n## ", e["readme"], name)
        # summary = heading tagline (after the em dash), capitalized like skill summaries
        self.assertEqual(by["smartzone"]["summary"], '"Your context has left the smart zone" warning.')
        self.assertEqual(by["spend-guard"]["summary"], "Block billable commands without an approval.")
        self.assertTrue(by["spend-guard"]["description"].startswith(
            "Block billable commands without an approval. PreToolUse hook for Bash"))
        with open(os.path.join(self.out, "spend-guard", "index.html"), encoding="utf-8") as f:
            self.assertIn('<span class="k">invocation</span> PreToolUse hook</li>', f.read())
        self.assertNotIn("guard-git", by)
        self.assertIn('href="/spend-guard"', self.index)

    def test_name_collision_fails(self):
        real = build_site.collect(ROOT)
        hook = next(e for e in real if e["group"] == "hooks")
        for other in ("pair", "planner"):
            dup = dict(hook, name=other)
            with mock.patch.object(build_site, "collect", return_value=real + [dup]):
                out = tempfile.mkdtemp(prefix="site-dup-")
                try:
                    with self.assertRaises(SystemExit) as cm:
                        build_site.build(ROOT, out)
                    self.assertIn(other, str(cm.exception))
                finally:
                    shutil.rmtree(out, ignore_errors=True)

    def test_groups(self):
        by = {e["name"]: e["group"] for e in self.data}
        self.assertEqual(by["pair"], "core")
        self.assertEqual(by["next"], "kanban")
        self.assertEqual(by["implementer"], "agents")
        self.assertEqual(by["spend-guard"], "hooks")
        self.assertNotIn("README", by)
        self.assertTrue(set(by.values()) <= set(build_site.GROUPS))
        order = [build_site.GROUPS.index(e["group"]) for e in self.data]
        self.assertEqual(order, sorted(order))

    def test_json_fields(self):
        for e in self.data:
            self.assertEqual(set(e), {"name", "description", "summary", "group", "source", "readme"})
            self.assertTrue(e["name"] and e["description"] and e["summary"])
            self.assertNotIn("\\", e["source"])
            self.assertNotIn("\r", e["readme"])
            self.assertTrue(e["description"].startswith(e["summary"].rstrip(".!?")[:20]))
        pair = next(e for e in self.data if e["name"] == "pair")
        self.assertEqual(pair["source"], "pair")
        self.assertTrue(pair["readme"])
        impl = next(e for e in self.data if e["name"] == "implementer")
        self.assertEqual(impl["source"], "agents/implementer.md")
        self.assertNotIn("name: implementer", impl["readme"])

    def test_placeholder_pages(self):
        for e in self.data:
            path = os.path.join(self.out, e["name"], "index.html")
            self.assertTrue(os.path.isfile(path), path)
        with open(os.path.join(self.out, "pair", "index.html"), encoding="utf-8") as f:
            self.assertIn("/pair", f.read())
        for fn in ("404.html", "style.css", "filter.js", "app.js", "rocky.webp", "favicon-32.png", "apple-touch-icon.png"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, fn)), fn)

    def test_favicon_pngs_copied(self):
        for fn in ("favicon-32.png", "apple-touch-icon.png"):
            with open(os.path.join(ROOT, "site", "src", fn), "rb") as f:
                src = f.read()
            with open(os.path.join(self.out, fn), "rb") as f:
                self.assertEqual(f.read(), src, fn)
        self.assertFalse(os.path.exists(os.path.join(self.out, "favicon.svg")))

    def test_icons_and_robots_default_base(self):
        for fn in ["index.html", "404.html"] + [os.path.join(e["name"], "index.html") for e in self.data]:
            with open(os.path.join(self.out, fn), encoding="utf-8") as f:
                page = f.read()
            self.assertIn('<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">', page, fn)
            self.assertIn('<link rel="apple-touch-icon" href="/apple-touch-icon.png">', page, fn)
            self.assertNotIn("favicon.svg", page, fn)
            self.assertEqual('<meta name="robots" content="noindex">' in page, fn == "404.html", fn)

    def test_list_links_server_rendered(self):
        for e in self.data:
            self.assertIn('href="/%s"' % e["name"], self.index)
        self.assertNotIn("{{", self.index)

    def test_first_sentence(self):
        fs = build_site.first_sentence
        self.assertEqual(fs("One thing. Two things."), "One thing.")
        self.assertEqual(fs("Use e.g. this. Then that."), "Use e.g. this.")
        self.assertEqual(fs("No period"), "No period")
        self.assertEqual(fs("Line\r\nwrap. Next."), "Line wrap.")
        self.assertEqual(fs("v1.2 is out. Yes."), "v1.2 is out.")

    def test_escaping(self):
        e = {"name": "x", "summary": '<b>"a" & b</b>', "group": "core"}
        html = build_site.render_list([e])
        self.assertIn("&lt;b&gt;&quot;a&quot; &amp; b&lt;/b&gt;", html)
        self.assertNotIn("<b>", html)
        embedded = build_site.embed_json([{"summary": "</script><!--"}])
        self.assertNotIn("<", embedded)
        self.assertEqual(json.loads(embedded)[0]["summary"], "</script><!--")

    def test_deterministic_and_wipes(self):
        stale = os.path.join(self.out, "stale.txt")
        with open(stale, "w") as f:
            f.write("x")
        out2 = tempfile.mkdtemp(prefix="site-dist2-")
        try:
            build_site.build(ROOT, self.out)
            build_site.build(ROOT, out2)
            self.assertFalse(os.path.exists(stale))
            for rel in ("index.html", "skills.json", os.path.join("pair", "index.html")):
                with open(os.path.join(self.out, rel), "rb") as a, open(os.path.join(out2, rel), "rb") as b:
                    self.assertEqual(a.read(), b.read(), rel)
        finally:
            shutil.rmtree(out2, ignore_errors=True)

    def test_no_skill_md_under_site(self):
        # lint globs */SKILL.md and */*/SKILL.md; the site must not add any.
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "site")):
            self.assertNotIn("SKILL.md", files, dirpath)


    def test_default_base(self):
        self.assertIn('href="/pair"', self.index)
        self.assertIn('href="/style.css"', self.index)
        self.assertIn('data-base=""', self.index)
        self.assertNotIn("{{BASE}}", self.index)

    def test_giscus_only_on_detail_pages(self):
        for n in (e["name"] for e in self.entries):
            with open(os.path.join(self.out, n, "index.html"), encoding="utf-8") as f:
                page = f.read()
            self.assertIn("giscus.app/client.js", page, n)
            self.assertIn('"data-term": "%s"' % n, page, n)
            self.assertIn('"data-strict": "1"', page, n)
        with open(os.path.join(self.out, "404.html"), encoding="utf-8") as f:
            nf = f.read()
        for page in (self.index, nf):
            self.assertNotIn("giscus", page)

    def test_home_layout_markers(self):
        idx = self.index
        # Catalog scrolls in .feed; the prompt dock comes after it (pinned bottom).
        feed, dock = idx.index('<main class="feed">'), idx.index('<div class="dock term" id="term">')
        self.assertLess(idx.index('class="catalog"'), dock)
        self.assertLess(feed, dock)
        self.assertLess(dock, idx.index('id="cmd"'))
        # Menu sits above the prompt so it opens upward.
        self.assertLess(idx.index('id="menu"'), idx.index('id="prompt-box"'))
        for marker in ('id="echo"', 'id="hint"', 'role="combobox"', 'aria-controls="menu"'):
            self.assertIn(marker, idx)
        # Intro hidden state only via a class JS adds; never hard-coded.
        self.assertIn('classList.add("intro")', idx)
        self.assertNotRegex(idx, r'<html[^>]*class="[^"]*intro')
        # .home styles the detail-page ~/skills link; page wrappers must not reuse it.
        self.assertNotRegex(idx, r'<(html|body)[^>]*class="[^"]*home')
        with open(os.path.join(self.out, "style.css"), encoding="utf-8") as f:
            css = f.read()
        self.assertIn("100dvh", css)
        self.assertIn("100vh", css)
        self.assertIn("prefers-reduced-motion", css)

    def test_color_scheme_meta_both(self):
        for n in ("index.html", "404.html", os.path.join("pair", "index.html")):
            with open(os.path.join(self.out, n), encoding="utf-8") as f:
                self.assertIn('<meta name="color-scheme" content="light dark">', f.read(), n)
        with open(os.path.join(self.out, "style.css"), encoding="utf-8") as f:
            css = f.read()
        self.assertIn("@media (prefers-color-scheme: light)", css)
        # colors live in :root tokens only (the two palettes at the top)
        body = css.split("@media (prefers-color-scheme: light)", 1)[1].split("}\n}\n", 1)[1]
        self.assertNotRegex(body, r"#[0-9a-fA-F]{3,8}\b|rgba?\(")

    def test_github_link(self):
        link = re.compile(r'<a class="gh[^"]*" href="https://github.com/KrishP147/skills" aria-label="[^"]+"><svg ')
        self.assertRegex(self.index, link)
        self.assertIn('class="gh gh-fixed"', self.index)
        for fn in ["404.html", os.path.join("pair", "index.html")]:
            with open(os.path.join(self.out, fn), encoding="utf-8") as f:
                self.assertRegex(f.read(), link, fn)

    def test_rocky_link_all_pages_default_base(self):
        pages = [("index", self.index)]
        for fn in ["404.html", os.path.join("pair", "index.html")]:
            with open(os.path.join(self.out, fn), encoding="utf-8") as f:
                pages.append((fn, f.read()))
        for label, page in pages:
            check_corner(self, page, "", label)

    def test_mobile_corner_band(self):
        with open(os.path.join(self.out, "style.css"), encoding="utf-8") as f:
            css = f.read()
        mobile = css[css.index("@media (max-width: 600px)"):]
        self.assertIn("body:not(.detail)::before", mobile)
        self.assertIn("position: fixed", mobile.split("body:not(.detail)::before", 1)[1].split("}", 1)[0])

    def test_rocky_bytes_copied(self):
        with open(os.path.join(ROOT, "site", "src", "rocky.webp"), "rb") as f:
            src = f.read()
        with open(os.path.join(self.out, "rocky.webp"), "rb") as f:
            self.assertEqual(f.read(), src)
        self.assertFalse(os.path.exists(os.path.join(self.out, "avatar.webp")))

    def embedded(self, page):
        m = re.search(r'<script type="application/json" id="skill-data">(.*?)</script>', page, re.S)
        self.assertIsNotNone(m)
        return json.loads(m.group(1))

    def test_nav_data_kind_and_aliases(self):
        nav = self.embedded(self.index)
        pages = [n for n in nav if n["kind"] == "page"]
        self.assertEqual([n["name"] for n in pages], ["map", "workflows"])
        nav = [n for n in nav if n["kind"] != "page"]
        self.assertEqual([n["name"] for n in nav], [e["name"] for e in self.data])
        with open(os.path.join(ROOT, "site", "data", "meta.json"), encoding="utf-8") as f:
            aliases = json.load(f).get("aliases", {})
        self.assertIn("review", aliases.get("pr-watch", []))
        for n in nav:
            self.assertEqual(list(n)[:4], ["name", "kind", "group", "summary"], n["name"])
            self.assertEqual(n["kind"], {"agents": "agent", "hooks": "hook"}.get(n["group"], "skill"), n["name"])
            if n["name"] in aliases:
                self.assertEqual(n["aliases"], aliases[n["name"]])
            else:
                self.assertNotIn("aliases", n)
        with open(os.path.join(self.out, "pair", "index.html"), encoding="utf-8") as f:
            self.assertEqual(self.embedded(f.read()), nav + pages)

    def test_aliases_validated(self):
        entries = [{"name": "pair", "group": "core", "summary": "s"},
                   {"name": "planner", "group": "agents", "summary": "s"},
                   {"name": "smartzone", "group": "hooks", "summary": "s"}]
        ok = build_site.aliases_of({"aliases": {"pair": ["worktree", "run-1"], "smartzone": ["context"]}}, entries)
        self.assertEqual(ok, {"pair": ["worktree", "run-1"], "smartzone": ["context"]})
        self.assertEqual(build_site.aliases_of({}, entries), {})
        self.assertEqual(build_site.aliases_of(None, entries), {})
        for bad in ({"nope": ["x"]}, {"pair": "worktree"}, {"pair": ["Work Tree"]},
                    {"pair": [""]}, {"pair": ["planner"]}, {"pair": ["smartzone"]}):
            with self.assertRaises(SystemExit, msg=bad):
                build_site.aliases_of({"aliases": bad}, entries)

    def test_normalize_base(self):
        for raw in ("/skills", "/skills/", "skills", " /skills/ "):
            self.assertEqual(build_site.normalize_base(raw), "/skills")
        for raw in ("/", "", None):
            self.assertEqual(build_site.normalize_base(raw), "")


class BaseBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp(prefix="site-base-")
        cls.entries = build_site.build(ROOT, cls.out, "skills/")
        cls.names = [e["name"] for e in cls.entries]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def read(self, *parts):
        with open(os.path.join(self.out, *parts), encoding="utf-8") as f:
            return f.read()

    def pages(self):
        yield "index.html", self.read("index.html")
        yield "404.html", self.read("404.html")
        for n in self.names:
            yield n, self.read(n, "index.html")

    def test_root_relative_urls_prefixed(self):
        for label, page in self.pages():
            urls = re.findall(r'(?:href|src)="(/[^"]*)"', page)
            self.assertTrue(urls, label)
            for u in urls:
                self.assertTrue(u.startswith("/skills/"), (label, u))
            self.assertNotIn("{{BASE}}", page)

    def test_assets_home_and_data_base(self):
        idx = self.read("index.html")
        self.assertIn('href="/skills/style.css"', idx)
        self.assertIn('src="/skills/app.js"', idx)
        self.assertIn('href="/skills/pair"', idx)
        self.assertIn('data-base="/skills"', idx)
        nf = self.read("404.html")
        self.assertIn('href="/skills/"', nf)
        self.assertIn('href="/skills/style.css"', nf)
        page = self.read(self.names[1], "index.html")
        self.assertIn('data-base="/skills"', page)
        self.assertIn('href="/skills/" aria-label', page)

    def test_rocky_link_prefixed_base(self):
        for label, page in self.pages():
            check_corner(self, page, "/skills", label)
        with open(os.path.join(ROOT, "site", "src", "rocky.webp"), "rb") as f:
            src = f.read()
        with open(os.path.join(self.out, "rocky.webp"), "rb") as f:
            self.assertEqual(f.read(), src)
        self.assertFalse(os.path.exists(os.path.join(self.out, "avatar.webp")))

    def test_prev_next_and_canonical(self):
        page = self.read(self.names[1], "index.html")
        self.assertIn('href="/skills/%s" rel="prev"' % self.names[0], page)
        self.assertIn('href="/skills/%s" rel="next"' % self.names[2], page)
        url = "https://www.krishpunjabi.com/skills/%s" % self.names[1]
        self.assertIn('<link rel="canonical" href="%s">' % url, page)
        self.assertNotIn("/skills/skills", page)

    def test_giscus_only_on_detail_pages(self):
        for label, page in self.pages():
            if label in ("index.html", "404.html"):
                self.assertNotIn("giscus", page, label)
            else:
                self.assertIn("giscus.app/client.js", page, label)
                self.assertIn('"data-term": "%s"' % label, page, label)
                self.assertIn('"data-strict": "1"', page, label)

    def test_icons_and_robots_prefixed_base(self):
        for label, page in self.pages():
            self.assertIn('<link rel="icon" type="image/png" sizes="32x32" href="/skills/favicon-32.png">', page, label)
            self.assertIn('<link rel="apple-touch-icon" href="/skills/apple-touch-icon.png">', page, label)
            self.assertNotIn("favicon.svg", page, label)
            self.assertEqual('<meta name="robots" content="noindex">' in page, label == "404.html", label)

    def test_displayed_names_unchanged(self):
        self.assertIn('<span class="nm">/pair</span>', self.read("index.html"))


class EntryDescriptionTest(unittest.TestCase):
    def test_block_scalar_description_stripped(self):
        fm = lint.parse_frontmatter("---\nname: x\ndescription: >\n  Does a thing.\n  More.\n---\n")[0]
        e = build_site._entry(fm, "x", "skill", "", "", "")
        self.assertEqual(e["description"], "Does a thing. More.")


class WorkflowsValidationTest(unittest.TestCase):
    """site/data/workflows.json: format, names, coverage (site_workflows.validate)."""

    @classmethod
    def setUpClass(cls):
        cls.entries = build_site.collect(ROOT)
        cls.raw = site_workflows.load(ROOT)

    def fails(self, raw, needle, entries=None):
        with self.assertRaises(SystemExit) as cm:
            site_workflows.validate(raw, entries or self.entries)
        self.assertIn(needle, str(cm.exception))

    def copy(self):
        return json.loads(json.dumps(self.raw))

    def test_real_data_valid(self):
        self.assertIs(site_workflows.validate(self.raw, self.entries), self.raw)

    def test_every_skill_covered(self):
        skills = [e["name"] for e in self.entries if e["group"] in ("core", "kanban")]
        self.assertEqual(len(skills), 26)
        used = {s.get("name") for wf in self.raw for s in wf["steps"]}
        self.assertEqual([n for n in skills if n not in used], [])

    def test_issue_example_chain(self):
        # The issue's example, step for step (each traces to its SKILL.md).
        wf = next(w for w in self.raw if w["name"] == "close-the-loop")
        self.assertEqual([(s["kind"], s.get("name")) for s in wf["steps"]],
                         [("skill", "session-handoff"), ("human", None), ("skill", "update-progress"),
                          ("skill", "next"), ("human", None)])
        self.assertIn('"go"', wf["steps"][-1]["why"])

    def test_human_steps_everywhere_and_no_model_fields(self):
        for wf in self.raw:
            self.assertTrue(any(s["kind"] == "human" for s in wf["steps"]), wf["name"])
            for s in wf["steps"]:
                self.assertLessEqual(set(s), {"kind", "name", "why"})

    def test_unknown_names_fail(self):
        for kind, name in (("skill", "no-such-skill"), ("agent", "no-such-agent"), ("hook", "no-such-hook")):
            raw = self.copy()
            raw[0]["steps"].append({"kind": kind, "name": name, "why": "x"})
            self.fails(raw, name)

    def test_wrong_kind_fails(self):
        raw = self.copy()
        raw[0]["steps"].append({"kind": "skill", "name": "planner", "why": "x"})
        self.fails(raw, "is a agent, not a skill")

    def test_uncovered_skill_fails(self):
        raw = [wf for wf in self.copy() if wf["name"] != "go-public"]
        self.fails(raw, "skills in no workflow: repo-scrub, repo-showcase")

    def test_bad_steps_fail(self):
        cases = [
            ({"kind": "human", "name": "pair", "why": "x"}, "human step has no name"),
            ({"kind": "skill", "name": "pair", "why": "x", "model": "opus"}, "unknown keys ['model']"),
            ({"kind": "robot", "why": "x"}, "kind must be one of"),
            ({"kind": "skill", "name": "pair", "why": ""}, "why must be one"),
            ({"kind": "skill", "name": "pair", "why": "two\nlines"}, "why must be one"),
        ]
        for step, needle in cases:
            raw = self.copy()
            raw[0]["steps"].append(step)
            self.fails(raw, needle)

    def test_bad_workflows_fail(self):
        raw = self.copy()
        raw[1]["name"] = raw[0]["name"]
        self.fails(raw, "duplicate name")
        raw = self.copy()
        raw[0]["name"] = "menu"
        self.fails(raw, "clashes with an id")
        raw = self.copy()
        raw[0]["name"] = "Bad Name"
        self.fails(raw, "lowercase")
        raw = self.copy()
        raw[0]["effort"] = "high"
        self.fails(raw, "unknown keys ['effort']")
        raw = self.copy()
        raw[0]["steps"] = [s for s in raw[0]["steps"] if s["kind"] != "human"]
        self.fails(raw, "needs a human step")
        raw = self.copy()
        raw.append({"name": "solo", "title": "Solo", "steps": [
            {"kind": "skill", "name": "pair", "why": "x"}, {"kind": "hook", "name": "smartzone", "why": "x"},
            {"kind": "human", "why": "x"}]})
        self.fails(raw, "needs 2+ skill/agent steps")
        self.fails([], "non-empty list")

    def test_entry_named_like_index_slug_fails_build(self):
        real = build_site.collect(ROOT)
        clash = dict(next(e for e in real if e["group"] == "hooks"), name=site_workflows.SLUG)
        with mock.patch.object(build_site, "collect", return_value=real + [clash]):
            out = tempfile.mkdtemp(prefix="site-slug-")
            try:
                with self.assertRaises(SystemExit) as cm:
                    build_site.build(ROOT, out)
                self.assertIn("reserved for the workflows index", str(cm.exception))
            finally:
                shutil.rmtree(out, ignore_errors=True)


class WorkflowsPageTest(unittest.TestCase):
    """dist/workflows/index.html, built under a base prefix."""

    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp(prefix="site-wf-")
        cls.entries = build_site.build(ROOT, cls.out, "/skills")
        cls.raw = site_workflows.load(ROOT)
        with open(os.path.join(cls.out, "workflows", "index.html"), encoding="utf-8") as f:
            cls.page = f.read()
        with open(os.path.join(cls.out, "index.html"), encoding="utf-8") as f:
            cls.index = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_home_links_index(self):
        self.assertIn('href="/skills/workflows"', self.index)

    def test_every_workflow_and_step_rendered(self):
        self.assertNotIn("{{", self.page)
        self.assertIn("<title>Sample workflows", self.page)
        for wf in self.raw:
            self.assertIn('<a href="#%s">' % wf["name"], self.page)
            m = re.search(r'<h2 id="%s">(.*?)</h2>\n<ol class="wf-steps">\n(.*?)\n</ol>' % wf["name"], self.page, re.S)
            self.assertIsNotNone(m, wf["name"])
            self.assertEqual(m.group(1), build_site.esc(wf["title"]))
            items = re.findall(r"<li class=\"wf-step[^\"]*\">(.*?)</li>", m.group(2))
            self.assertEqual(len(items), len(wf["steps"]), wf["name"])
            for li, st in zip(items, wf["steps"]):
                self.assertIn(build_site.esc(st["why"]), li)
                if st["kind"] == "human":
                    self.assertIn(">you</span>", li)
                else:
                    self.assertIn('href="/skills/%s">/%s</a>' % (st["name"], st["name"]), li)
                    self.assertTrue(os.path.isfile(os.path.join(self.out, st["name"], "index.html")))

    def test_page_shell(self):
        # Same chrome as a detail page: slash prompt, nav data, back link, one h1.
        self.assertIn('id="skill-data"', self.page)
        self.assertIn('data-autofocus="false"', self.page)
        self.assertIn('<a class="back" href="/skills/">', self.page)
        self.assertEqual(self.page.count("<h1"), 1)
        self.assertIn('<meta name="color-scheme" content="light dark">', self.page)
        self.assertIn('<link rel="canonical" href="https://www.krishpunjabi.com/skills/workflows">', self.page)


class CliTest(unittest.TestCase):
    def test_out_outside_repo_other_cwd(self):
        with tempfile.TemporaryDirectory(prefix="site-cwd-") as cwd:
            r = subprocess.run(
                [sys.executable, os.path.join(ROOT, "scripts", "build_site.py"),
                 "--base", "/skills", "--out", "public/skills"],
                cwd=cwd, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.isfile(os.path.join(cwd, "public", "skills", "index.html")))
            self.assertIn("Built ", r.stdout)


if __name__ == "__main__":
    unittest.main()
