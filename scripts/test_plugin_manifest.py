"""Shape and path checks for .claude-plugin/{plugin,marketplace}.json.

Stdlib only; runs in CI via `python -m unittest discover -s scripts`.
"""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lint  # noqa: E402

ROOT = lint.repo_root()
PLUGIN_DIR = os.path.join(ROOT, ".claude-plugin")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def load(name):
    with open(os.path.join(PLUGIN_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def as_list(value):
    return value if isinstance(value, list) else [value]


def resolve(rel):
    return os.path.normpath(os.path.join(ROOT, rel))


class PluginManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = load("plugin.json")

    def test_required_fields(self):
        self.assertRegex(self.plugin.get("name", ""), NAME_RE)
        self.assertRegex(self.plugin.get("version", ""), SEMVER_RE)
        self.assertIsInstance(self.plugin.get("description"), str)

    def test_paths_relative_and_exist(self):
        for key in ("skills", "agents"):
            for rel in as_list(self.plugin[key]):
                self.assertTrue(rel.startswith("./"), "%s path must start with ./: %s" % (key, rel))
                self.assertTrue(os.path.exists(resolve(rel)), "%s path missing: %s" % (key, rel))

    def test_every_skill_dir_covered(self):
        # A skills entry is a directory scanned one level deep for <name>/SKILL.md.
        scanned = {resolve(rel) for rel in as_list(self.plugin["skills"])}
        skills = lint.find_skill_files(ROOT)
        self.assertTrue(skills)
        for skill_md in skills:
            parent = os.path.dirname(os.path.dirname(skill_md))
            self.assertIn(parent, scanned, "skill not shipped by plugin.json: %s" % skill_md)

    def test_template_not_shipped(self):
        scanned = {resolve(rel) for rel in as_list(self.plugin["skills"])}
        self.assertNotIn(resolve("./templates/"), scanned)

    def test_agents_listed_exactly(self):
        # `agents` replaces the default scan; listing files keeps agents/README.md out.
        listed = sorted(resolve(rel) for rel in as_list(self.plugin["agents"]))
        expected = sorted(os.path.normpath(p) for p in lint.find_agent_files(ROOT))
        self.assertEqual(listed, expected)
        for path in listed:
            self.assertTrue(os.path.isfile(path) and path.endswith(".md"), path)

    def test_guard_hook(self):
        entries = self.plugin["hooks"]["PreToolUse"]
        commands = [h["command"] for e in entries if e.get("matcher") == "Bash|PowerShell"
                    for h in e["hooks"] if h.get("type") == "command"]
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIn('"${CLAUDE_PLUGIN_ROOT}/agents/hooks/guard-git.py" --plugin', cmd)
        self.assertTrue(os.path.isfile(resolve("./agents/hooks/guard-git.py")))
        self.assertTrue(cmd.rstrip().endswith("exit 2"), "must fail closed without Python")

    def test_no_autoloaded_hooks_file(self):
        # hooks/hooks.json would auto-load the opt-in smartzone/spend-guard hooks.
        self.assertFalse(os.path.exists(os.path.join(ROOT, "hooks", "hooks.json")))


class MarketplaceManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market = load("marketplace.json")
        cls.plugin = load("plugin.json")

    def test_required_fields(self):
        self.assertRegex(self.market.get("name", ""), NAME_RE)
        self.assertIsInstance(self.market.get("owner", {}).get("name"), str)
        self.assertIsInstance(self.market.get("plugins"), list)

    def test_entry_points_at_this_plugin(self):
        entries = [p for p in self.market["plugins"] if p.get("name") == self.plugin["name"]]
        self.assertEqual(len(entries), 1)
        source = entries[0]["source"]
        self.assertTrue(source.startswith("./"), source)
        self.assertTrue(os.path.isfile(os.path.join(resolve(source), ".claude-plugin", "plugin.json")))

    def test_no_version_drift(self):
        # plugin.json is the single version source; a marketplace version would shadow it.
        for entry in self.market["plugins"]:
            self.assertNotIn("version", entry)


if __name__ == "__main__":
    unittest.main()
