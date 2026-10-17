"""Tests for scripts/site_map.py (the /map page). Run: python -m unittest discover -s scripts -p "test_*.py" """
import copy
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_site  # noqa: E402
import lint  # noqa: E402
import site_detail  # noqa: E402
import site_map  # noqa: E402
import site_workflows  # noqa: E402

ROOT = lint.repo_root()


class MapPageTest(unittest.TestCase):
    """dist/map/index.html, built under a base prefix."""

    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp(prefix="site-map-")
        cls.entries = build_site.build(ROOT, cls.out, "/skills")
        with open(os.path.join(cls.out, "map", "index.html"), encoding="utf-8") as f:
            cls.page = f.read()
        with open(os.path.join(cls.out, "index.html"), encoding="utf-8") as f:
            cls.index = f.read()
        meta = site_detail.load_meta(ROOT)
        wfs = site_workflows.validate(site_workflows.load(ROOT), cls.entries)
        cls.groups, cls.edges = site_map.build(ROOT, cls.entries, meta, wfs)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def section(self, g):
        m = re.search(r'<section class="sec map-group" aria-labelledby="map-%s">(.*?)</section>' % g, self.page, re.S)
        self.assertIsNotNone(m, g)
        return m.group(1)

    def test_every_entry_on_the_map(self):
        self.assertNotIn("{{", self.page)
        kinds = {"skill": 0, "agent": 0, "hook": 0}
        for e in self.entries:
            kinds[site_workflows.kind_of(e)] += 1
            g = next(g for g, m in self.groups if e["name"] in m)
            sec = self.section(g)
            svg = sec[sec.index("<svg"):sec.index("</svg>")]
            self.assertIn(">%s</tspan>" % e["name"], svg, e["name"])
            self.assertIn('<li><a href="/skills/%s">%s</a>' % (e["name"], e["name"]), sec, e["name"])
        self.assertTrue(all(kinds.values()), kinds)  # core/kanban skills, agents and hooks all present
        self.assertTrue(any(e["group"] == "kanban" for e in self.entries))
        self.assertTrue(any(e["group"] == "core" for e in self.entries))

    def test_every_edge_drawn_once_and_listed(self):
        self.assertIn("with %d arrows" % len(self.edges), self.page)
        for s, d, kinds in self.edges:
            g = next(g for g, m in self.groups if s in m)
            sec = self.section(g)
            self.assertIn('<span class="dim">%s</span> <a href="/skills/%s">%s</a>' % (", ".join(kinds), d, d), sec)
        drawn = len(re.findall(r'<g class="flow-edge', self.page))
        self.assertEqual(drawn, len(self.edges))

    def test_edge_kinds_from_real_sources(self):
        by = {(s, d): k for s, d, k in self.edges}
        self.assertEqual(by[("planner", "next")], ["preloads"])           # agent frontmatter
        self.assertIn("related", by[("pair", "manager")])                 # ../agents/README.md#manager
        self.assertIn("related", by[("spend-guard", "spend-gate")])       # hook "Related:" paragraph
        self.assertIn("workflow", by[("manager", "implementer")])         # workflows.json chain
        self.assertIn("related", by[("meta-orchestrator", "verifier")])   # agents named in link text
        self.assertFalse(any(s == d for s, d, _k in self.edges))

    def test_flow_wrappers_scroll_and_titled(self):
        n = len(self.groups)
        self.assertEqual(self.page.count('<div class="flow" tabindex="0"'), n)
        self.assertEqual(len(re.findall(r"<svg[^>]*role=\"img\"[^>]*><title>Map of ", self.page)), n)

    def test_legend_and_groups_in_order(self):
        for kind in ("related", "preloads", "workflow"):
            self.assertIn("%s: " % kind, self.page)
        ids = re.findall(r'aria-labelledby="map-([a-z0-9-]+)"', self.page)
        self.assertEqual([i for i in ids if i not in ("toc", "key")], [g for g, _m in self.groups])

    def test_home_links_map_and_nav_resolves(self):
        self.assertIn('href="/skills/map"', self.index)
        self.assertIn('"name":"map","kind":"page"', self.index)
        self.assertIn('<link rel="canonical" href="https://www.krishpunjabi.com/skills/map">', self.page)

    def test_deterministic(self):
        out = tempfile.mkdtemp(prefix="site-map2-")
        try:
            build_site.build(ROOT, out, "/skills")
            with open(os.path.join(out, "map", "index.html"), encoding="utf-8") as f:
                self.assertEqual(f.read(), self.page)
        finally:
            shutil.rmtree(out, ignore_errors=True)


class MapValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = build_site.collect(ROOT)
        cls.meta = site_detail.load_meta(ROOT)

    def fails(self, meta, msg):
        with self.assertRaises(SystemExit) as cm:
            site_map.groups(meta, self.entries)
        self.assertIn(msg, str(cm.exception))

    def raw(self):
        return copy.deepcopy(self.meta[site_map.META_KEY])

    def test_real_groups_cover_everything_once(self):
        grps = site_map.groups(self.meta, self.entries)
        flat = [n for _g, m in grps for n in m]
        self.assertEqual(sorted(flat), sorted(e["name"] for e in self.entries))
        self.assertEqual([g for g, _m in grps][:6],
                         ["plan-and-decide", "build-and-orchestrate", "sessions-and-accounts",
                          "review-and-report", "repo-and-safety", "kanban-board"])

    def test_bad_groups_fail(self):
        r = self.raw()
        r["plan-and-decide"].append("nope")
        self.fails({site_map.META_KEY: r}, "unknown name 'nope'")
        r = self.raw()
        r["review-and-report"].append(r["plan-and-decide"][0])
        self.fails({site_map.META_KEY: r}, "is in both")
        r = self.raw()
        r["hooks"].remove("smartzone")
        self.fails({site_map.META_KEY: r}, "not in any group: smartzone")
        r = self.raw()
        r["toc"] = r.pop("hooks")
        self.fails({site_map.META_KEY: r}, "reserved")
        r = self.raw()
        r["Bad Name"] = r.pop("hooks")
        self.fails({site_map.META_KEY: r}, "lowercase")
        r = self.raw()
        r["empty"] = []
        self.fails({site_map.META_KEY: r}, "non-empty list")
        self.fails({}, "need an object")

    def targets(self, md, base_dir="pair"):
        return site_map.link_targets(ROOT, self.entries, "x", md, base_dir)

    def test_link_resolution(self):
        self.assertEqual(self.targets("[a](../agents/README.md#manager) [b](../grilling/) "
                                      "[c](../kanban/next/README.md) [d](../hooks/spend-guard.py) "
                                      "[e](https://example.com) [f](#local)"),
                         ["manager", "grilling", "next", "spend-guard"])
        self.assertEqual(self.targets("[`planner`, `pair`, `verifier`](../agents/README.md)"), ["planner", "verifier"])
        self.assertEqual(self.targets("[root](../README.md#third-party-skills)"), [])

    def test_dangling_link_fails(self):
        for md, msg in (("[x](../no-such-skill/)", "no such file"),
                        ("[x](../README.md#no-such-heading)", "no heading"),
                        ("[x](../../../outside)", "leaves the repo")):
            with self.assertRaises(SystemExit) as cm:
                self.targets(md)
            self.assertIn(msg, str(cm.exception))

    def test_entry_named_map_fails_build(self):
        real = build_site.collect(ROOT)
        clash = dict(next(e for e in real if e["group"] == "hooks"), name=site_map.SLUG)
        with mock.patch.object(build_site, "collect", return_value=real + [clash]):
            out = tempfile.mkdtemp(prefix="site-slug-")
            try:
                with self.assertRaises(SystemExit) as cm:
                    build_site.build(ROOT, out)
                self.assertIn("reserved for the map page", str(cm.exception))
            finally:
                shutil.rmtree(out, ignore_errors=True)

    def test_flowchart_is_flow_svg_subset(self):
        text = site_map.flowchart(["a-b", "c"], [("a-b", "d", ["related"]), ("c", "a-b", ["workflow"]),
                                                 ("c", "d", ["preloads"])])
        self.assertEqual(text.split("\n"), ["flowchart LR", "n0[a-b]", "n1[c]", "n2[d]",
                                            "n0 --> n2", "n1 -.-> n0", "n1 -->|preloads| n2"])
        self.assertIn("<svg", site_map.flow_svg.render(text, "t"))


if __name__ == "__main__":
    unittest.main()
