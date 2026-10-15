"""Tests for detail pages (scripts/site_detail.py via build_site.build).
Run: python -m unittest discover -s scripts -p "test_*.py" """
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_site  # noqa: E402
import lint  # noqa: E402
import site_detail  # noqa: E402

ROOT = lint.repo_root()


class DetailPagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp(prefix="site-detail-")
        cls.entries = build_site.build(ROOT, cls.out)
        cls.by = {e["name"]: e for e in cls.entries}
        cls.pages = {}
        for e in cls.entries:
            with open(os.path.join(cls.out, e["name"], "index.html"), encoding="utf-8") as f:
                cls.pages[e["name"]] = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_every_page_has_description_and_meta(self):
        for e in self.entries:
            page = self.pages[e["name"]]
            desc = build_site.esc(e["description"])
            self.assertIn('<p class="detail-desc">%s</p>' % desc, page, e["name"])
            self.assertIn('<meta name="description" content="%s">' % desc, page)
            self.assertIn("<title>/%s · " % e["name"], page)
            self.assertIn('<meta property="og:url" content="https://www.krishpunjabi.com/skills/%s">'
                          % e["name"], page)
            for prop in ("og:title", "og:description", "og:type"):
                self.assertIn('property="%s"' % prop, page)
            self.assertIn('<section id="comments"', page)
            self.assertIn("&gt;</span> /%s</p>" % e["name"], page)  # echoed command
            self.assertIn('id="cmd"', page)  # sticky slash input
            self.assertNotIn("{{", page)

    def test_links_rewritten(self):
        href = re.compile(r'href="([^"]*)"')
        for name, page in self.pages.items():
            for h in href.findall(page):
                self.assertTrue(h.startswith(("/", "#", "https://", "http://", "mailto:")), (name, h))
                if h.endswith(".md") or ".md#" in h:
                    self.assertTrue(h.startswith("https://github.com/"), (name, h))
        pair = self.pages["pair"]
        self.assertIn('<a href="/meta-orchestrator">', pair)  # ../meta-orchestrator/
        self.assertIn('<a href="/manager">', pair)  # ../agents/README.md#manager
        self.assertIn("https://github.com/KrishP147/skills/blob/master/pair/SKILL.md", pair)

    def test_no_script_from_markdown(self):
        for name, page in self.pages.items():
            # data + filter.js + app.js + giscus
            self.assertEqual(page.count("<script"), 4, name)
            self.assertEqual(page.count("<script src="), 3, name)

    def test_giscus_embed(self):
        for name, page in self.pages.items():
            self.assertIn('<script src="https://giscus.app/client.js"', page, name)
            self.assertIn('data-term="%s"' % build_site.esc(name), page, name)
            self.assertEqual(page.count("data-term="), 1, name)
            self.assertIn('data-strict="1"', page, name)
            self.assertIn('data-mapping="specific"', page, name)
            self.assertIn("Use cases &amp; tips from the community", page, name)

    def test_sections_ordered_none_empty(self):
        titles = [t for _k, t in site_detail.SECTIONS] + ["Source"]
        h2 = re.compile(r'<h2 id="[^"]*">(.*?)</h2>')
        for name, page in self.pages.items():
            found = h2.findall(page)
            mapped = [t for t in found if t in titles]
            self.assertEqual(mapped, sorted(mapped, key=titles.index), name)
            self.assertEqual(found[-1], "Source", name)
            self.assertNotRegex(page, r"</h2>\s*</section>", name)
        for name, e in self.by.items():
            if e["group"] != "agents" and "## Tips" not in e["readme"]:
                self.assertNotIn(">Tips</h2>", self.pages[name], name)

    def test_chips(self):
        grill_me = self.pages["grill-me"]
        self.assertIn("Matt Pocock", grill_me)
        self.assertIn("user only", grill_me)
        self.assertIn("derived from Matt Pocock", self.pages["handoff-auto"])
        self.assertIn("model + user", self.pages["pair"])
        self.assertIn("lightly used", self.pages["pair"])
        planner = self.pages["planner"]
        self.assertIn('<span class="k">model</span> opus', planner)
        self.assertIn("/next, /divide", planner)
        self.assertIn("all except Edit, Write, NotebookEdit", planner)
        self.assertIn("used in anger", planner)

    def test_agent_page_from_readme_section(self):
        mgr = self.pages["manager"]
        self.assertIn("Owns one task end to end", mgr)
        self.assertIn("Agent(subagent_type=&quot;manager&quot;", mgr)
        self.assertIn('Linked from: <a href="/pair">', mgr)  # backlink from pair's README
        self.assertIn('Preloads: <a href="/handoff-auto">', mgr)
        self.assertIn("https://github.com/KrishP147/skills/blob/master/agents/manager.md", mgr)
        article = mgr.split("<article", 1)[1].split("</article>", 1)[0]
        self.assertNotIn("Role:", article)  # labels became section headings
        self.assertNotIn("Picks the next single unit", article)  # planner's section

    def test_hook_pages(self):
        sz, sg = self.pages["smartzone"], self.pages["spend-guard"]
        for name, page in (("smartzone", sz), ("spend-guard", sg)):
            src = "https://github.com/KrishP147/skills/blob/master/hooks/%s.py" % name
            self.assertIn('<span class="k">source</span> <a href="%s">hooks/%s.py</a>' % (src, name), page)
            self.assertIn('<span class="tag">hooks</span>', page)
            for title in ("What it does", "How to invoke", "How it works", "Related"):
                self.assertIn(">%s</h2>" % title, page, (name, title))
            article = page.split("<article", 1)[1].split("</article>", 1)[0]
            self.assertNotIn("Install into a repo:", article)  # bare label dropped
            self.assertNotIn("How it works:", article)
            self.assertNotIn("guard-git.py` lives in", article)  # README preamble is not a hook's
        self.assertIn('<span class="k">invocation</span> UserPromptSubmit hook', sz)
        self.assertIn('<span class="k">invocation</span> PreToolUse hook', sg)
        self.assertIn(">Example</h2>", sz)
        self.assertIn("Example output once a long session", sz)  # long label kept as text
        self.assertIn('<a href="/divide">', sz)  # ../kanban/divide/
        self.assertIn('<a href="/spend-gate">', sg)
        self.assertNotIn("SPEND_GUARD_PATTERNS", sz)  # spend-guard's section stays out
        self.assertIn("hooks/README.md#spend-guardpy--block-billable-commands-without-an-approval", sg)

    def test_links_to_hooks_become_pages(self):
        self.assertIn('<a href="/smartzone">', self.pages["meta-orchestrator"])
        self.assertIn('<a href="/spend-guard">', self.pages["spend-gate"])  # ../hooks/spend-guard.py
        idx = site_detail.LinkIndex(ROOT, self.entries)
        rw = idx.rewriter("spend-gate")
        self.assertEqual(rw("../hooks/README.md#spend-guardpy--block-billable-commands-without-an-approval"),
                         "/spend-guard")
        self.assertEqual(rw("../hooks/README.md"),
                         "https://github.com/KrishP147/skills/blob/master/hooks/README.md")
        self.assertEqual(rw("../hooks/"), "https://github.com/KrishP147/skills/tree/master/hooks")

    def test_prev_next_build_order(self):
        names = [e["name"] for e in self.entries]
        for i, n in enumerate(names):
            page = self.pages[n]
            if i:
                self.assertIn('href="/%s" rel="prev"' % names[i - 1], page)
            else:
                self.assertNotIn('rel="prev"', page)
            if i + 1 < len(names):
                self.assertIn('href="/%s" rel="next"' % names[i + 1], page)
            else:
                self.assertNotIn('rel="next"', page)

    def test_deterministic(self):
        out2 = tempfile.mkdtemp(prefix="site-detail2-")
        try:
            build_site.build(ROOT, out2)
            for name, page in self.pages.items():
                with open(os.path.join(out2, name, "index.html"), encoding="utf-8") as f:
                    self.assertEqual(f.read(), page, name)
        finally:
            shutil.rmtree(out2, ignore_errors=True)


class MetaTest(unittest.TestCase):
    def test_authors_match_third_party_licenses(self):
        meta = site_detail.load_meta(ROOT)
        credited = site_detail.credited_third_party(ROOT)
        names = {e["name"] for e in build_site.collect(ROOT)}
        third_party = {n for n, a in meta["authors"].items() if a != meta["default_author"]}
        self.assertEqual(third_party, credited & names)

    def test_levels(self):
        meta = site_detail.load_meta(ROOT)
        seen = [n for ns in meta["levels"].values() for n in ns]
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(site_detail.level_of(meta, "does-not-exist"), "new")
        self.assertEqual(site_detail.level_of(meta, "planner"), "in-anger")
        self.assertEqual(meta["levels_source"], "usage in the author's sessions, Sep 2026")


class SectionMappingTest(unittest.TestCase):
    def test_tolerant_headings(self):
        k = site_detail.section_key
        self.assertEqual(k("What it does"), "what")
        self.assertEqual(k("Invoke"), "invoke")
        self.assertEqual(k("How to invoke it"), "invoke")
        self.assertEqual(k("Prerequisite: the `project` OAuth scope"), "prereqs")
        self.assertEqual(k("Examples"), "example")
        self.assertEqual(k("Tips & gotchas"), "tips")
        self.assertEqual(k("How it works"), "how")
        self.assertIsNone(k("You get back (40 lines)"))

    def test_organise_drops_missing_and_orders(self):
        md = ("# x\n\n*`SKILL.md` is the prompt Claude follows; this file is for you.*\n\n"
              "## Example\nex\n## Odd one\nodd\n## What it does\nw\n## Tips\n\n"
              "## How it works\n```\n## not a heading\n```\n")
        pre, pairs = site_detail.split_h2(md)
        self.assertEqual(pre, "")
        ordered, extras = site_detail.organise(pre, pairs)
        self.assertEqual([t for _k, t, _b in ordered], ["What it does", "How it works", "Example"])
        self.assertEqual(extras, [("Odd one", "odd")])
        self.assertIn("## not a heading", ordered[1][2])  # fenced '##' is not a split

    def test_placeholders_in_readme_stay_literal(self):
        e = dict(build_site.collect(ROOT)[0], readme="## What it does\n\nUse `{{NAME}}` and {{DATA}}.\n")
        pages = site_detail.build_pages(ROOT, [e], {}, "{{BODY}}|{{NAME}}", "[]")
        self.assertIn("<code>{{NAME}}</code> and {{DATA}}", pages[e["name"]])
        self.assertTrue(pages[e["name"]].endswith("|" + e["name"]))

    def test_install_heading_maps_to_invoke(self):
        self.assertEqual(site_detail.section_key("Install into a repo"), "invoke")

    def test_label_paragraphs(self):
        md = ("`X` hook. Does y.\n\nMore of what.\n\n"
              "How it works: reads stdin,\nthen exits.\n\nThis is a note: kept here.\n\n"
              "Install into a repo:\n\n```bash\nRelated: not a label in a fence\n```\n\n"
              "Example output once it fires:\n\n```\nout\n```\n\nRelated: [a](../a/).")
        pre, pairs = site_detail.split_label_paragraphs(md)
        self.assertEqual(pre, "`X` hook. Does y.\n\nMore of what.")
        self.assertEqual([l for l, _b in pairs],
                         ["How it works", "Install into a repo", "Example output once it fires", "Related"])
        how = pairs[0][1]
        self.assertTrue(how.startswith("Reads stdin,\nthen exits."))
        self.assertIn("This is a note: kept here.", how)
        self.assertTrue(pairs[1][1].startswith("```bash"))
        self.assertIn("Related: not a label in a fence", pairs[1][1])
        self.assertTrue(pairs[2][1].startswith("Example output once it fires:"))
        self.assertEqual(pairs[3][1], "[a](../a/).")

    def test_label_bullets(self):
        rest, pairs = site_detail.split_label_bullets(
            "- **Role:** does x.\n- **How it works:**\n  1. a\n  2. b\nTrailing.")
        self.assertEqual(pairs[0], ("Role", "Does x."))
        self.assertEqual(pairs[1][0], "How it works")
        self.assertIn("1. a\n2. b", pairs[1][1])
        self.assertEqual(rest, "Trailing.")


if __name__ == "__main__":
    unittest.main()
