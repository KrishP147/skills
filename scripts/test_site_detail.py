"""Tests for detail pages (scripts/site_detail.py via build_site.build).
Run: python -m unittest discover -s scripts -p "test_*.py" """
import contextlib
import io
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
import site_workflows  # noqa: E402

ROOT = lint.repo_root()


class DetailPagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp(prefix="site-detail-")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            cls.entries = build_site.build(ROOT, cls.out)
        cls.stderr = err.getvalue()
        cls.by = {e["name"]: e for e in cls.entries}
        cls.pages = {}
        for e in cls.entries:
            with open(os.path.join(cls.out, e["name"], "index.html"), encoding="utf-8") as f:
                cls.pages[e["name"]] = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_sample_workflows_section(self):
        # Every page lists exactly the workflows it appears in, in file order, just before Source.
        mapping = site_workflows.by_name(site_workflows.load(ROOT))
        for e in self.entries:
            page = self.pages[e["name"]]
            m = re.search(r'<h2 id="sample-workflows">Sample workflows</h2>\n<ul class="wf-links">\n(.*?)\n</ul>\n</section>\n'
                          r'<section class="sec" aria-labelledby="source">', page, re.S)
            want = [wf["name"] for wf in mapping.get(e["name"], [])]
            if e["group"] in ("core", "kanban"):
                self.assertTrue(want, e["name"])  # coverage: every skill is in a workflow
            if not want:
                self.assertNotIn("Sample workflows", page, e["name"])
                continue
            self.assertIsNotNone(m, e["name"])
            self.assertEqual(re.findall(r'<a href="/workflows#([a-z0-9-]+)">', m.group(1)), want, e["name"])
        self.assertIn("session-handoff → you → update-progress → next → you", self.pages["next"])

    def test_sample_workflows_not_inherited(self):
        # Generated per entry: a kanban sibling never picks up another's section (D8/D76).
        wf = {"name": "only-divide", "title": "Only divide", "steps": []}
        meta = site_detail.load_meta(ROOT)
        with open(os.path.join(ROOT, "site", "src", "detail.html"), encoding="utf-8") as f:
            template = f.read()
        with contextlib.redirect_stderr(io.StringIO()):
            pages = site_detail.build_pages(ROOT, self.entries, meta, template, "[]", "/b",
                                            workflows={"divide": [wf]})
        self.assertIn('<a href="/b/workflows#only-divide">Only divide</a>', pages["divide"])
        for name in ("next", "session-handoff", "kanban-setup", "pair"):
            self.assertNotIn("Sample workflows", pages[name], name)
        with contextlib.redirect_stderr(io.StringIO()):
            bare = site_detail.build_pages(ROOT, self.entries, meta, template, "[]")
        self.assertFalse(any("Sample workflows" in p for p in bare.values()))

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
            # data + filter.js + app.js + inline giscus loader
            self.assertEqual(page.count("<script"), 4, name)
            self.assertEqual(page.count("<script src="), 2, name)

    def test_giscus_embed(self):
        for name, page in self.pages.items():
            self.assertIn('"src": "https://giscus.app/client.js"', page, name)
            self.assertIn('"data-term": "%s"' % build_site.esc(name), page, name)
            self.assertEqual(page.count('"data-term"'), 1, name)
            self.assertIn('"data-strict": "1"', page, name)
            self.assertIn('"data-mapping": "specific"', page, name)
            # theme from the OS scheme before load, live updates via postMessage, no external CSS
            self.assertIn('"data-theme": theme()', page, name)
            self.assertIn('matchMedia("(prefers-color-scheme: light)")', page, name)
            self.assertIn("setConfig: { theme: theme() }", page, name)
            self.assertNotRegex(page, r'theme[^,;]*https?://', name)
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

    def test_flow_diagrams(self):
        def flow(name):
            m = re.search(r'<h2 id="flow">Flow</h2>\n(.*?)</section>', self.pages[name], re.S)
            return m and m.group(1)
        for name in ("pair", "pr-watch", "meta-orchestrator"):
            sec = flow(name)
            self.assertTrue(sec, name)
            self.assertIn('<div class="flow" tabindex="0"><svg class="flow-svg"', sec)
            page = self.pages[name]
            # Flow sits after How it works, before Example.
            self.assertLess(page.index(">How it works</h2>"), page.index(">Flow</h2>"))
            self.assertLess(page.index(">Flow</h2>"), page.index(">Example</h2>"))
        # Every kanban skill inherits the group's loop (and its prose links
        # are rebased to the child dir).
        kanban = [e["name"] for e in self.entries if e["source"].startswith("kanban/")]
        self.assertEqual(len(kanban), 6)
        loop = flow("next")
        self.assertIn("update-progress: verify, docs, board", loop)
        for name in kanban:
            self.assertEqual(flow(name), loop, name)
        self.assertIn('href="https://github.com/KrishP147/skills/blob/master/kanban/next/BOARD.md"', loop)
        self.assertNotIn("The loop", self.pages["next"])
        self.assertNotIn("language-mermaid", "".join(self.pages.values()))

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
        self.assertIn('<li class="chip chip-suggested"><span class="k">suggested model · effort</span> opus · medium</li>',
                      planner)
        for name, page in self.pages.items():
            self.assertIn("chip-suggested", page, name)

    def test_model_effort_validated(self):
        meta = site_detail.load_meta(ROOT)
        self.assertEqual(set(site_detail.model_effort(meta, self.entries)), set(self.by))
        good = meta["model_effort"]
        first = next(iter(good))
        bads = [
            ({**good, "no-such-entry": {"model": "haiku", "effort": "low"}}, "unknown name"),
            ({k: v for k, v in good.items() if k != first}, "missing " + first),
            ({**good, first: {"model": "gpt", "effort": "low"}}, "model must be"),
            ({**good, first: {"model": "haiku", "effort": "huge"}}, "effort must be"),
            ({**good, first: {"model": "haiku"}}, "exactly {model, effort}"),
            ({**good, "planner": {"model": "haiku", "effort": "low"}}, "differs from its frontmatter"),
        ]
        for raw, needle in bads:
            with self.assertRaises(SystemExit) as cm:
                site_detail.model_effort({"model_effort": raw}, self.entries)
            self.assertIn(needle, str(cm.exception))
        with self.assertRaises(SystemExit):
            site_detail.model_effort({}, self.entries)

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
        """Two builds are byte-identical, every file (transcripts included)."""
        out2 = tempfile.mkdtemp(prefix="site-detail2-")
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                build_site.build(ROOT, out2)
            for name, page in self.pages.items():
                with open(os.path.join(out2, name, "index.html"), encoding="utf-8") as f:
                    self.assertEqual(f.read(), page, name)
            files = sorted(os.path.relpath(os.path.join(d, f), self.out)
                           for d, _s, fs in os.walk(self.out) for f in fs)
            files2 = sorted(os.path.relpath(os.path.join(d, f), out2)
                            for d, _s, fs in os.walk(out2) for f in fs)
            self.assertEqual(files, files2)
            for rel in files:
                with open(os.path.join(self.out, rel), "rb") as a, open(os.path.join(out2, rel), "rb") as b:
                    self.assertEqual(a.read(), b.read(), rel)
        finally:
            shutil.rmtree(out2, ignore_errors=True)

    def _example(self, name):
        m = re.search(r'aria-labelledby="example">(.*?)</section>', self.pages[name], re.S)
        self.assertIsNotNone(m, name)
        return m.group(1)

    def test_every_entry_has_example_no_warnings(self):
        self.assertEqual(len(self.entries), 32)  # 26 skills, 4 agents, 2 hooks
        self.assertEqual(build_site.counts(self.entries), (26, 4, 2))
        self.assertNotIn("WARN", self.stderr)
        for name in self.pages:
            self.assertIn('<div class="tx" role="group" aria-label="Example session">',
                          self._example(name), name)

    def test_default_example_render(self):
        # "```/cmd args```" + prose: the fence becomes the prompt, the prose one reply block
        sec = self._example("grilling")
        self.assertIn('<div class="tx-prompt"><span class="tx-gt" aria-hidden="true">&gt;</span>'
                      '<span class="tx-text">/grilling move auth from sessions to JWTs</span></div>', sec)
        self.assertIn('<div class="tx-reply tx-md"><span class="tx-dot" aria-hidden="true">⏺</span>', sec)
        self.assertIn("<p>Round 1 asks", sec)
        self.assertNotIn("<pre>", sec)
        # no leading fence (hook output example): reply only, no prompt
        sec = self._example("smartzone")
        self.assertNotIn("tx-prompt", sec)
        self.assertIn("[smart-zone] Session transcript", sec)

    def test_transcript_fence_pages(self):
        for name in ("meta-orchestrator", "pair", "pr-watch", "planner", "spend-guard"):
            sec = self._example(name)
            self.assertIn('<details class="tx-tool">', sec, name)
            self.assertNotIn("language-transcript", sec, name)

    def test_missing_example_warns(self):
        e = dict(self.by["grilling"])
        e["readme"] = "## What it does\n\nThings.\n"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            site_detail.build_pages(ROOT, [e], site_detail.load_meta(ROOT), "{{BODY}}", "[]")
        self.assertIn("WARN: grilling: no Example section", err.getvalue())

    def test_back_link_and_esc_home(self):
        self.assertIn('<a class="back" href="/">&larr; all commands</a>', self.pages["pair"])
        src = os.path.join(ROOT, "site", "src")
        with open(os.path.join(src, "filter.js"), encoding="utf-8") as f:
            fjs = f.read()
        with open(os.path.join(src, "app.js"), encoding="utf-8") as f:
            js = f.read()
        # Detail page: Esc on a bare "/" -> reducer action "home" -> goHome().
        self.assertIn('} else if (!ev.home) {', fjs)
        self.assertIn('r.preventDefault = true; r.action = "home";', fjs)
        self.assertIn('home: home,', js)
        self.assertIn('case "home": goHome(); break;', js)


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
        with contextlib.redirect_stderr(io.StringIO()):  # fixture README has no Example
            pages = site_detail.build_pages(ROOT, [e], {}, "{{BODY}}|{{NAME}}", "[]")
        self.assertIn("<code>{{NAME}}</code> and {{DATA}}", pages[e["name"]])
        self.assertTrue(pages[e["name"]].endswith("|" + e["name"]))

    def test_flow_aliases(self):
        k = site_detail.section_key
        for h in ("Flow", "The loop", "Diagram", "Flow diagram", "Flowchart"):
            self.assertEqual(k(h), "flow", h)
        keys = [key for key, _t in site_detail.SECTIONS]
        self.assertEqual(keys.index("flow"), keys.index("how") + 1)
        self.assertLess(keys.index("flow"), keys.index("example"))

    def test_group_sections_inherited_unless_own(self):
        root = tempfile.mkdtemp(prefix="site-inherit-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        os.makedirs(os.path.join(root, "grp", "a"))
        with open(os.path.join(root, "grp", "README.md"), "w", encoding="utf-8") as f:
            f.write("# grp\n\n## The loop\n\n```mermaid\nflowchart TD\n  P --> Q\n```\n\nSee [b](b/x.md).\n\n"
                    "## Prereqs\n\ngh\n")
        e = {"group": "skills", "name": "a", "source": "grp/a", "readme": "## What it does\n\nw\n"}
        _pre, pairs, _base = site_detail.raw_sections(root, e, "")
        got = dict((site_detail.section_key(h), b) for h, b in pairs)
        self.assertIn("P --> Q", got["flow"])
        self.assertIn("[b](../b/x.md)", got["flow"])  # rebased to the child dir
        self.assertEqual(got["prereqs"], "gh")
        own = dict(e, readme="## What it does\n\nw\n\n## Flow\n\n```mermaid\nflowchart LR\n  X --> Y\n```\n")
        _pre, pairs, _base = site_detail.raw_sections(root, own, "")
        flows = [b for h, b in pairs if site_detail.section_key(h) == "flow"]
        self.assertEqual(len(flows), 1)
        self.assertIn("X --> Y", flows[0])
        self.assertIn("prereqs", [site_detail.section_key(h) for h, _b in pairs])
        top = dict(e, source="a")  # no parent group: nothing inherited
        _pre, pairs, _base = site_detail.raw_sections(root, top, "")
        self.assertEqual([site_detail.section_key(h) for h, _b in pairs], ["what"])

    def test_bad_mermaid_fails_build(self):
        import flow_svg
        e = dict(build_site.collect(ROOT)[0], readme="## Flow\n\n```mermaid\nflowchart TD\n  A --- B\n```\n")
        with self.assertRaisesRegex(flow_svg.FlowError, "^%s: line 2" % re.escape(e["name"])), \
                contextlib.redirect_stderr(io.StringIO()):  # fixture README has no Example
            site_detail.build_pages(ROOT, [e], {}, "{{BODY}}", "[]")

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
