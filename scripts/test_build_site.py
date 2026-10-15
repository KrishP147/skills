"""Tests for scripts/build_site.py. Run: python -m unittest discover -s scripts -p "test_*.py" """
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_site  # noqa: E402
import lint  # noqa: E402

ROOT = lint.repo_root()


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
        skills, agents = build_site.counts(self.entries)
        self.assertEqual(skills, len(lint.find_skill_files(ROOT)))
        self.assertEqual(agents, len(lint.find_agent_files(ROOT)))
        self.assertIn(build_site.esc(build_site.count_line(self.entries)), self.index)

    def test_groups(self):
        by = {e["name"]: e["group"] for e in self.data}
        self.assertEqual(by["pair"], "core")
        self.assertEqual(by["next"], "kanban")
        self.assertEqual(by["implementer"], "agents")
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
        for fn in ("404.html", "style.css", "filter.js", "app.js", "favicon.svg"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, fn)), fn)

    def test_favicon_svg_copied(self):
        with open(os.path.join(ROOT, "site", "src", "favicon.svg"), encoding="utf-8") as f:
            src = f.read()
        with open(os.path.join(self.out, "favicon.svg"), encoding="utf-8") as f:
            out = f.read()
        self.assertEqual(out, src)
        self.assertTrue(out.lstrip().startswith("<svg"))
        self.assertFalse([fn for fn in os.listdir(self.out) if fn.endswith(".png")])

    def test_icons_and_robots_default_base(self):
        for fn in ["index.html", "404.html"] + [os.path.join(e["name"], "index.html") for e in self.data]:
            with open(os.path.join(self.out, fn), encoding="utf-8") as f:
                page = f.read()
            self.assertIn('<link rel="icon" type="image/svg+xml" href="/favicon.svg">', page, fn)
            self.assertNotIn("apple-touch-icon", page, fn)
            self.assertNotIn(".png", page, fn)
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
            self.assertIn('data-term="%s"' % n, page, n)
            self.assertIn('data-strict="1"', page, n)
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
        with open(os.path.join(self.out, "style.css"), encoding="utf-8") as f:
            css = f.read()
        self.assertIn("100dvh", css)
        self.assertIn("100vh", css)
        self.assertIn("prefers-reduced-motion", css)

    def test_github_link(self):
        link = re.compile(r'<a class="gh[^"]*" href="https://github.com/KrishP147/skills" aria-label="[^"]+"><svg ')
        self.assertRegex(self.index, link)
        self.assertIn('class="gh gh-fixed"', self.index)
        for fn in ["404.html", os.path.join("pair", "index.html")]:
            with open(os.path.join(self.out, fn), encoding="utf-8") as f:
                self.assertRegex(f.read(), link, fn)

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
                self.assertIn('data-term="%s"' % label, page, label)
                self.assertIn('data-strict="1"', page, label)

    def test_icons_and_robots_prefixed_base(self):
        for label, page in self.pages():
            self.assertIn('<link rel="icon" type="image/svg+xml" href="/skills/favicon.svg">', page, label)
            self.assertNotIn("apple-touch-icon", page, label)
            self.assertEqual('<meta name="robots" content="noindex">' in page, label == "404.html", label)

    def test_displayed_names_unchanged(self):
        self.assertIn('<span class="nm">/pair</span>', self.read("index.html"))


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
