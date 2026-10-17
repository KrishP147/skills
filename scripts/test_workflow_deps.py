"""Tests for scripts/workflow_deps.py and install-skills --workflow."""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import workflow_deps  # noqa: E402

MARKER = ".from-krishp147-skills"


class ResolveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = workflow_deps.Graph(ROOT)

    def test_every_workflow_closed_and_real(self):
        for wf in self.g.workflows:
            r = self.g.resolve([wf["name"]])
            got = set(r["skill"]) | set(r["agent"]) | set(r["hook"])
            seeds = {s["name"] for s in wf["steps"] if s["kind"] != "human"}
            self.assertLessEqual(seeds, got, wf["name"])
            for n in got:
                for d in self.g.deps[n]:
                    self.assertIn(d, got, "%s: %s needs %s" % (wf["name"], n, d))
            for n in r["skill"]:
                src = self.g.by_name[n]["source"]
                self.assertTrue(os.path.isfile(os.path.join(ROOT, src, "SKILL.md")), n)
            for n in r["agent"]:
                self.assertTrue(os.path.isfile(os.path.join(ROOT, "agents", n + ".md")), n)
            for n in r["hook"]:
                self.assertTrue(os.path.isfile(os.path.join(ROOT, "hooks", n + ".py")), n)
            # hooks only come from the workflow's own steps
            self.assertEqual(set(r["hook"]), {s["name"] for s in wf["steps"] if s["kind"] == "hook"}, wf["name"])
            lines = self.g.lines([wf["name"]])
            self.assertEqual("agent-hooks" in lines, bool(r["agent"]), wf["name"])

    def test_no_installed_skill_links_outside_selection(self):
        # every relative link from a selected skill's own files into another
        # skill dir lands on a selected skill
        dirs = {e["source"]: e["name"] for e in self.g.entries if self.g.kinds[e["name"]] == "skill"}
        for wf in self.g.workflows:
            sel = set(self.g.resolve([wf["name"]])["skill"])
            for n in sel:
                for t in workflow_deps._file_links(ROOT, self.g.by_name[n], dirs):
                    self.assertIn(t, sel, "%s: %s links into %s" % (wf["name"], n, t))

    def test_agent_preloads_included(self):
        r = self.g.resolve(["pair-to-pr"])
        for a in r["agent"]:
            for s in self.g.by_name[a]["_x"]["fm"].get("skills") or []:
                self.assertIn(s, r["skill"], a)

    def test_closure_is_not_the_whole_repo(self):
        n_skills = sum(1 for k in self.g.kinds.values() if k == "skill")
        r = self.g.resolve(["lazy-fix-handoff"])
        self.assertLess(len(r["skill"]), n_skills // 2)
        self.assertEqual(r["agent"], [])

    def test_union_of_two(self):
        a, b = self.g.resolve(["safe-to-close"]), self.g.resolve(["go-public"])
        both = self.g.resolve(["safe-to-close", "go-public"])
        self.assertEqual(set(both["skill"]), set(a["skill"]) | set(b["skill"]))

    def test_unknown_and_empty_raise(self):
        with self.assertRaises(workflow_deps.UnknownWorkflow):
            self.g.resolve(["no-such-workflow"])
        with self.assertRaises(workflow_deps.UnknownWorkflow):
            self.g.resolve(["pair-to-pr", "no-such-workflow"])
        with self.assertRaises(workflow_deps.UnknownWorkflow):
            self.g.resolve([])

    def test_split_names(self):
        self.assertEqual(workflow_deps.split_names(["a,b", " c ", "", ","]), ["a", "b", "c"])

    def test_snippet(self):
        data = json.loads(workflow_deps.snippet("/h", ["smartzone", "spend-guard"]))
        self.assertEqual(data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"],
                         'python "/h/smartzone.py" || exit 0')
        self.assertEqual(data["hooks"]["PreToolUse"][0]["matcher"], "Bash|PowerShell|mcp__.*")

    def test_every_hook_has_wiring(self):
        hooks = [n for n, k in self.g.kinds.items() if k == "hook"]
        self.assertEqual(sorted(hooks), sorted(workflow_deps.HOOK_WIRING))


LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


def copy_like_installer(g, r, dest):
    """Lay out a resolve() result as the installers do: flat skill dirs,
    agents/ (+ agents/hooks/ once any agent is in), hooks/."""
    for n in r["skill"]:
        shutil.copytree(os.path.join(ROOT, g.by_name[n]["source"]), os.path.join(dest, "skills", n),
                        ignore=shutil.ignore_patterns("__pycache__"))
    if r["agent"]:
        shutil.copytree(os.path.join(ROOT, "agents", "hooks"), os.path.join(dest, "agents", "hooks"),
                        ignore=shutil.ignore_patterns("__pycache__"))
    for n in r["agent"]:
        shutil.copy(os.path.join(ROOT, "agents", n + ".md"), os.path.join(dest, "agents"))
    for n in r["hook"]:
        os.makedirs(os.path.join(dest, "hooks"), exist_ok=True)
        shutil.copy(os.path.join(ROOT, "hooks", n + ".py"), os.path.join(dest, "hooks"))


def dangling_links(dest):
    """'file: link' for each relative .md link in an installed non-README
    file whose target is missing from the install."""
    out = []
    for base, _dirs, files in os.walk(dest):
        for f in files:
            if not f.endswith(".md") or f == "README.md":
                continue
            p = os.path.join(base, f)
            with open(p, encoding="utf-8-sig") as fh:
                text = fh.read()
            for url in LINK_RE.findall(text):
                path = url.split("#")[0]
                if not path or re.match(r"^[a-z][a-z0-9+.-]*:", path, re.I) or path.startswith("/"):
                    continue
                if not os.path.exists(os.path.normpath(os.path.join(base, path))):
                    out.append("%s: %s" % (os.path.relpath(p, dest).replace(os.sep, "/"), url))
    return out


class NamesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = workflow_deps.Graph(ROOT)

    def test_each_kind_alone(self):
        self.assertEqual(self.g.resolve(names=["switch"]), {"skill": ["switch"], "agent": [], "hook": []})
        r = self.g.resolve(names=["planner"])
        self.assertEqual(r["agent"], ["planner"])
        self.assertIn("next", r["skill"])
        self.assertIn("agent-hooks", self.g.lines(names=["planner"]))
        self.assertEqual(self.g.resolve(names=["spend-guard"]), {"skill": [], "agent": [], "hook": ["spend-guard"]})

    def test_unknown_name_raises(self):
        with self.assertRaises(workflow_deps.UnknownName):
            self.g.resolve(names=["switch", "no-such-thing"])

    def test_union_with_workflow(self):
        wf, one = self.g.resolve(["go-public"]), self.g.resolve(names=["switch"])
        both = self.g.resolve(["go-public"], ["switch"])
        for k in both:
            self.assertEqual(set(both[k]), set(wf[k]) | set(one[k]), k)

    def test_optional_edges_are_real_and_unfollowed(self):
        # each OPTIONAL entry names a real edge source/target, and none is followed
        for src, dsts in workflow_deps.OPTIONAL.items():
            self.assertIn(src, self.g.kinds)
            for d in dsts:
                self.assertIn(d, self.g.kinds, src)
                self.assertNotIn(d, self.g.deps[src], "%s still pulls %s" % (src, d))

    def test_dangling_links_detects(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "skills", "a"))
            with open(os.path.join(tmp, "skills", "a", "SKILL.md"), "w") as f:
                f.write("[ok](SKILL.md#x) [web](https://x.y) [bad](../b/BOARD.md)\n")
            with open(os.path.join(tmp, "skills", "a", "README.md"), "w") as f:
                f.write("[ignored](../../README.md)\n")
            self.assertEqual(dangling_links(tmp), ["skills/a/SKILL.md: ../b/BOARD.md"])

    def test_every_entry_standalone(self):
        # each skill, agent and hook installed alone (with what it needs)
        # links to nothing that isn't installed
        for n in self.g.kinds:
            with self.subTest(n), tempfile.TemporaryDirectory() as tmp:
                copy_like_installer(self.g, self.g.resolve(names=[n]), tmp)
                self.assertEqual(dangling_links(tmp), [])


class CliTest(unittest.TestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = workflow_deps.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_unknown_lists_workflows(self):
        rc, out, err = self.run_main("resolve", "nope")
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertIn("unknown workflow(s): nope", err)
        self.assertIn("pair-to-pr\t", err)

    def test_resolve_lines(self):
        rc, out, _ = self.run_main("resolve", "pair-to-pr")
        self.assertEqual(rc, 0)
        lines = out.splitlines()
        self.assertIn("skill pair", lines)
        self.assertIn("skill kanban/session-handoff", lines)
        self.assertIn("agent manager", lines)
        self.assertEqual(lines[-1], "agent-hooks")
        for ln in lines:
            self.assertRegex(ln, r"^(skill [a-z0-9/-]+|agent [a-z0-9-]+|hook [a-z0-9-]+|agent-hooks)$")

    def test_list(self):
        rc, out, _ = self.run_main("list")
        self.assertEqual(rc, 0)
        self.assertIn("usage-limit\t", out)


def find_bash():
    cands = [shutil.which("bash")]
    if os.name == "nt":
        cands += [r"C:\Program Files\Git\bin\bash.exe"]
    for c in cands:
        if c and os.path.isfile(c) and not re.search(r"\\(System32|SysWOW64|WindowsApps)\\", c, re.I):
            return c
    return None


def find_powershell():
    for c in ("powershell", "pwsh"):
        p = shutil.which(c)
        if p:
            return p
    return None


class InstallerMixin:
    """Runs one installer into temp dirs; subclasses define install()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wf-install-")
        self.skills = os.path.join(self.tmp, "skills")
        self.agents = os.path.join(self.tmp, "agents")
        self.hooks = os.path.join(self.tmp, "hooks")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self):
        env = dict(os.environ)
        env.update(CLAUDE_SKILLS_DIR=self.skills, CLAUDE_AGENTS_DIR=self.agents)
        env.pop("CLAUDE_HOOKS_DIR", None)
        return env

    def seed(self):
        os.makedirs(os.path.join(self.skills, "old-skill"))
        open(os.path.join(self.skills, "old-skill", MARKER), "w").close()
        os.makedirs(self.agents)
        with open(os.path.join(self.agents, "mine.md"), "w") as f:
            f.write("mine\n")

    def ls(self, d):
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def test_partial_leaves_others_untouched(self):
        self.seed()
        rc, out, err = self.install("pair-to-pr")
        self.assertEqual(rc, 0, out + err)
        want = workflow_deps.Graph(ROOT).resolve(["pair-to-pr"])
        self.assertEqual(self.ls(self.skills), sorted(want["skill"] + ["old-skill"]))
        self.assertEqual(self.ls(os.path.join(self.skills, "old-skill")), [MARKER])
        self.assertEqual(self.ls(self.agents), sorted([a + ".md" for a in want["agent"]] + ["hooks", "mine.md"]))
        with open(os.path.join(self.agents, "mine.md")) as f:
            self.assertEqual(f.read(), "mine\n")
        self.assertTrue(os.path.isfile(os.path.join(self.agents, "hooks", "guard-git.py")))
        self.assertNotIn("stale", (out + err).lower())
        for s in want["skill"]:
            self.assertTrue(os.path.isfile(os.path.join(self.skills, s, MARKER)), s)

    def test_partial_no_agents_no_agents_dir(self):
        rc, out, err = self.install("lazy-fix-handoff")
        self.assertEqual(rc, 0, out + err)
        self.assertFalse(os.path.exists(self.agents))
        self.assertFalse(os.path.exists(self.hooks))

    def test_hook_copied_not_wired(self):
        rc, out, err = self.install("paid-tests")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.ls(self.hooks), ["spend-guard.py"])
        self.assertIn('"PreToolUse"', out)
        self.assertIn("NOT wired", out)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "settings.json")))

    def test_differing_hook_kept_without_force(self):
        os.makedirs(self.hooks)
        p = os.path.join(self.hooks, "spend-guard.py")
        with open(p, "w") as f:
            f.write("# mine\n")
        rc, out, err = self.install("paid-tests")
        self.assertNotEqual(rc, 0)
        with open(p) as f:
            self.assertEqual(f.read(), "# mine\n")

    def test_foreign_selected_skill_skipped(self):
        os.makedirs(os.path.join(self.skills, "ponytail"))
        rc, out, err = self.install("lazy-fix-handoff")
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.ls(os.path.join(self.skills, "ponytail")), [])

    def test_unknown_installs_nothing(self):
        rc, out, err = self.install("no-such-workflow")
        self.assertNotEqual(rc, 0)
        self.assertIn("pair-to-pr", out + err)
        self.assertFalse(os.path.exists(self.tmp + "/skills"))
        self.assertFalse(os.path.exists(self.agents))

    def test_skill_alone(self):
        self.seed()
        rc, out, err = self.install(None, "switch")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.ls(self.skills), ["old-skill", "switch"])
        self.assertEqual(self.ls(self.agents), ["mine.md"])
        self.assertFalse(os.path.exists(self.hooks))
        self.assertNotIn("stale", (out + err).lower())

    def test_hook_alone_no_skills_dir(self):
        rc, out, err = self.install(None, "spend-guard")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.ls(self.hooks), ["spend-guard.py"])
        self.assertFalse(os.path.exists(self.skills))
        self.assertFalse(os.path.exists(self.agents))

    def test_skill_and_workflow_union(self):
        rc, out, err = self.install("lazy-fix-handoff", "switch,planner")
        self.assertEqual(rc, 0, out + err)
        want = workflow_deps.Graph(ROOT).resolve(["lazy-fix-handoff"], ["switch", "planner"])
        self.assertEqual(self.ls(self.skills), want["skill"])
        self.assertEqual(self.ls(self.agents), ["hooks", "planner.md"])

    def test_unknown_skill_installs_nothing(self):
        rc, out, err = self.install(None, "no-such-thing")
        self.assertEqual(rc, 2)
        self.assertIn("switch", out + err)
        self.assertFalse(os.path.exists(self.skills))
        self.assertFalse(os.path.exists(self.agents))
        self.assertFalse(os.path.exists(self.hooks))

    def test_full_install_unchanged(self):
        self.seed()
        rc, out, err = self.install(None)
        self.assertEqual(rc, 0, out + err)
        n_skills = sum(1 for k in workflow_deps.Graph(ROOT).kinds.values() if k == "skill")
        self.assertEqual(len(self.ls(self.skills)), n_skills + 1)
        self.assertIn("implementer.md", self.ls(self.agents))
        self.assertIn("stale agent(s) not in repo, remove manually: mine.md", out + err)
        self.assertIn("stale skill(s) not in repo, remove manually: old-skill", out + err)
        self.assertFalse(os.path.exists(self.hooks))


@unittest.skipUnless(find_bash(), "bash not available")
class BashInstallerTest(InstallerMixin, unittest.TestCase):
    def install(self, wf, skill=None):
        args = [find_bash(), os.path.join(ROOT, "scripts", "install-skills.sh").replace("\\", "/")]
        if wf:
            args += ["--workflow", wf]
        if skill:
            args += ["--skill", skill]
        p = subprocess.run(args, env=self.env(), capture_output=True, text=True, encoding="utf-8")
        return p.returncode, p.stdout, p.stderr

    def test_list_and_repeat_and_equals(self):
        p = subprocess.run([find_bash(), os.path.join(ROOT, "scripts", "install-skills.sh").replace("\\", "/"),
                            "--list-workflows"], env=self.env(), capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertIn("usage-limit\t", p.stdout)
        self.assertFalse(os.path.exists(self.skills))
        p = subprocess.run([find_bash(), os.path.join(ROOT, "scripts", "install-skills.sh").replace("\\", "/"),
                            "--workflow", "safe-to-close", "--workflow=go-public"],
                           env=self.env(), capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("repo-scrub", self.ls(self.skills))
        self.assertIn("sitrep", self.ls(self.skills))

    def test_list_skills_and_skill_equals(self):
        sh = os.path.join(ROOT, "scripts", "install-skills.sh").replace("\\", "/")
        p = subprocess.run([find_bash(), sh, "--list-skills"], env=self.env(), capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertIn("spend-guard\thook", p.stdout)
        self.assertFalse(os.path.exists(self.skills))
        p = subprocess.run([find_bash(), sh, "--skill=grilling,ponytail", "--skill", "switch"],
                           env=self.env(), capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.ls(self.skills), ["grilling", "ponytail", "switch"])


@unittest.skipUnless(os.name == "nt" and find_powershell(), "Windows PowerShell not available")
class PowerShellInstallerTest(InstallerMixin, unittest.TestCase):
    def install(self, wf, skill=None):
        args = [find_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                os.path.join(ROOT, "scripts", "install-skills.ps1")]
        if wf:
            args += ["-Workflow", wf]
        if skill:
            args += ["-Skill", skill]
        p = subprocess.run(args, env=self.env(), capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr


if __name__ == "__main__":
    unittest.main()
