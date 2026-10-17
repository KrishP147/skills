"""meta.json "categories" is the one source: every skill/agent/hook is in exactly
one, and the README "What's here" tables match it (no drift). Offline.
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
ROW_RE = re.compile(r"^\| \[`([a-z0-9-]+)`\]\(", re.M)


def whats_here():
    """{heading text: section markdown} for each ### under README's "## What's here"."""
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
        text = f.read().replace("\r\n", "\n")
    body = text.split("\n## What's here\n", 1)[1].split("\n## ", 1)[0]
    parts = re.split(r"^### ", body, flags=re.M)[1:]
    return {p.split("\n", 1)[0]: p for p in parts}


class CategoriesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta = site_detail.load_meta(ROOT)
        cls.cats = cls.meta["categories"]
        cls.entries = build_site.collect(ROOT)
        cls.sections = whats_here()
        cls.out = tempfile.mkdtemp(prefix="site-cats-")
        cls.built = build_site.build(ROOT, cls.out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def read(self, *parts):
        with open(os.path.join(self.out, *parts), encoding="utf-8") as f:
            return f.read()

    def test_every_entry_in_exactly_one_category(self):
        flat = [n for members in self.cats.values() for n in members]
        self.assertEqual(len(flat), len(set(flat)), "a name is in two categories")
        self.assertEqual(sorted(flat), sorted(e["name"] for e in self.entries))

    def test_structural_categories_match_folders(self):
        by = {e["name"]: e["group"] for e in self.entries}
        self.assertEqual(sorted(self.cats["agents"]), sorted(n for n, g in by.items() if g == "agents"))
        self.assertEqual(sorted(self.cats["hooks"]), sorted(n for n, g in by.items() if g == "hooks"))
        self.assertEqual(sorted(self.cats["kanban-board"]),
                         sorted(n for n, g in by.items() if g == "kanban" and n != "consult-plan"))

    def test_readme_skill_tables_match_categories(self):
        skill_cats = [c for c in self.cats if c not in ("agents", "hooks")]
        headings = [h for h in self.sections if h.lower().replace(" ", "-") in skill_cats]
        self.assertEqual([h.lower().replace(" ", "-") for h in headings], skill_cats, "heading order")
        for h in headings:
            cat = h.lower().replace(" ", "-")
            self.assertEqual(sorted(ROW_RE.findall(self.sections[h])), sorted(self.cats[cat]), h)

    def test_readme_agents_table_matches_category(self):
        h = next(h for h in self.sections if "agents/" in h)
        self.assertEqual(sorted(ROW_RE.findall(self.sections[h])), sorted(self.cats["agents"]))

    def test_readme_hooks_prose_names_each_hook(self):
        h = next(h for h in self.sections if "hooks/" in h)
        for n in self.cats["hooks"]:
            self.assertIn("[`%s.py`]" % n, self.sections[h])

    def test_readme_has_every_skill_once(self):
        names = [n for h, s in self.sections.items() for n in ROW_RE.findall(s)]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(sorted(names), sorted(n for n in (e["name"] for e in self.entries)
                                               if n not in self.cats["hooks"]))  # hooks are prose

    def test_home_sections_follow_categories(self):
        ids = re.findall(r'<section class="group" aria-labelledby="g-([^"]+)">', self.read("index.html"))
        self.assertEqual(ids, list(self.cats))
        for cat, members in self.cats.items():
            sec = self.read("index.html").split('id="g-%s"' % cat, 1)[1].split("</section>", 1)[0]
            self.assertEqual(sorted(re.findall(r'<span class="nm">/([^<]+)</span>', sec)), sorted(members), cat)

    def test_detail_tag_is_category_title(self):
        for e in self.built:
            tag = re.search(r'<span class="tag">([^<]*)</span>', self.read(e["name"], "index.html")).group(1)
            self.assertEqual(tag, e["category"].replace("-", " "), e["name"])
        self.assertIn('class="tag">plan and decide<', self.read("consult-plan", "index.html"))


if __name__ == "__main__":
    unittest.main()
