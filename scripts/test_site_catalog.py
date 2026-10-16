"""Tests for scripts/site_catalog.py (find-me-a-skill/CATALOG.md). Offline.
Run: python -m unittest discover -s scripts -p "test_*.py" """
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_site  # noqa: E402
import lint  # noqa: E402
import site_catalog  # noqa: E402
import site_detail  # noqa: E402
import site_workflows  # noqa: E402

ROOT = lint.repo_root()


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = build_site.collect(ROOT)
        cls.meta = site_detail.load_meta(ROOT)
        cls.workflows = site_workflows.validate(site_workflows.load(ROOT), cls.entries)
        cls.text = site_catalog.render(cls.entries, cls.meta, cls.workflows)

    def test_committed_catalog_not_stale(self):
        with open(site_catalog.catalog_path(ROOT), encoding="utf-8") as f:
            committed = f.read()
        self.assertEqual(committed, self.text, "CATALOG.md is stale; run: " + site_catalog.REGEN)

    def test_every_entry_one_row(self):
        rows = [l for l in self.text.split("\n## Workflows")[0].split("\n") if l.startswith("| ")][1:]
        self.assertEqual([r.split(" | ")[0][2:] for r in rows], [e["name"] for e in self.entries])
        for r in rows:
            self.assertEqual(r.count(" | "), 6, r)

    def test_row_fields(self):
        self.assertIn("| planner | agent | opus | medium | `Agent(subagent_type=\"planner\")` |", self.text)
        self.assertIn("| grill-me | skill (user only) |", self.text)
        self.assertIn("| smartzone | hook | haiku | low | install: hooks/README.md |", self.text)
        self.assertRegex(self.text, r"\| next \| skill \| haiku \| low \| `/next` \| [^|]+ \| [a-z-]+")

    def test_every_workflow_with_step_defaults(self):
        for wf in self.workflows:
            self.assertIn("### %s: %s" % (wf["name"], wf["title"]), self.text)
        self.assertIn("1. /session-handoff (skill, sonnet · medium): Writes the handoff", self.text)
        self.assertIn("2. you: Read the handoff", self.text)
        self.assertIn("planner (agent, opus · medium): ", self.text)

    def test_cell_escapes_pipes_and_newlines(self):
        self.assertEqual(site_catalog.cell("a | b\n c"), "a \\| b c")

    def test_render_validates_model_effort(self):
        meta = dict(self.meta, model_effort={})
        with self.assertRaises(SystemExit):
            site_catalog.render(self.entries, meta, self.workflows)

    def test_deterministic(self):
        self.assertEqual(site_catalog.render_repo(ROOT), self.text)


if __name__ == "__main__":
    unittest.main()
