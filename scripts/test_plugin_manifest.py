"""Shape and path checks for .claude-plugin/{plugin,marketplace}.json.

Stdlib only; runs in CI via `python -m unittest discover -s scripts`.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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

    def test_find_me_a_skill_catalog_shipped(self):
        # The skill reads its sibling CATALOG.md; the whole folder ships under a skills dir.
        scanned = {resolve(rel) for rel in as_list(self.plugin["skills"])}
        catalog = resolve("./find-me-a-skill/CATALOG.md")
        self.assertTrue(os.path.isfile(catalog))
        self.assertIn(os.path.dirname(os.path.dirname(catalog)), scanned)
        with open(resolve("./find-me-a-skill/SKILL.md"), encoding="utf-8") as f:
            self.assertIn("](CATALOG.md)", f.read())

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
        # No Python: fail closed only for guarded agents; the main session must pass.
        self.assertIn("(implementer|manager)", cmd)
        self.assertIn("exit 2; }", cmd)
        self.assertTrue(cmd.rstrip().endswith("exit 0"), "no-Python fallback must allow non-agent sessions")

    def test_guard_hook_no_python(self):
        # Run the real command with python3/python/py shadowed by stubs that fail the probe.
        sh = shutil.which("sh")
        if not sh:
            self.skipTest("sh not on PATH")
        entries = self.plugin["hooks"]["PreToolUse"]
        cmd = [h["command"] for e in entries for h in e["hooks"]][0]
        with tempfile.TemporaryDirectory() as stub:
            for name in ("python3", "python", "py"):
                path = os.path.join(stub, name)
                with open(path, "w", newline="\n") as f:
                    f.write("#!/bin/sh\nexit 1\n")
                os.chmod(path, 0o755)
            env = dict(os.environ, PATH=stub + os.pathsep + os.environ.get("PATH", ""),
                       CLAUDE_PLUGIN_ROOT=ROOT)
            for agent_type, expect in ((None, 0), ("krish:implementer", 2), ("implementer", 2),
                                       ("manager", 2), ("krish:manager", 2), ("krish:verifier", 0),
                                       ("planner", 0), ("implementer-x", 0)):
                # Harmless command: a real guard-git run would allow it, so 2 proves the no-Python path.
                payload = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
                if agent_type is not None:
                    payload["agent_type"] = agent_type
                rc = subprocess.run([sh, "-c", cmd], input=json.dumps(payload), env=env,
                                    capture_output=True, text=True, timeout=30).returncode
                self.assertEqual(rc, expect, "agent_type=%r" % agent_type)

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
