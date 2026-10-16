import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evals  # noqa: E402
import lint  # noqa: E402

ROOT = lint.repo_root()

PROMPT = """---
description: test case
tags: [{skill}, {kind}]
max_turns: 5
allowed_tools: [Read, Glob, Grep, Skill]
---

{body}
"""


def skill_grader(skill, negative):
    lines = ["---", "type: tool_used", "tool: Skill",
             "input_match: '\"skill\"\\s*:\\s*\"(?:[\\w-]+:)?%s\"'" % skill]
    if negative:
        lines += ["min: 0", "max: 0", "arm: both"]
    return "\n".join(lines + ["---", ""])


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class RepoSuite(unittest.TestCase):
    """The real evals/ in this repo."""

    @classmethod
    def setUpClass(cls):
        cls.errors, cls.cases = evals.validate(ROOT)

    def test_valid(self):
        self.assertEqual(self.errors, [])

    def test_skill_list_derived_from_lint(self):
        expected = []
        for path in lint.find_skill_files(ROOT):
            with open(path, encoding="utf-8") as f:
                fm, _ = lint.parse_frontmatter(f.read())
            if str(fm.get("disable-model-invocation", "")).lower() != "true":
                expected.append(fm["name"])
        self.assertEqual(evals.model_invocable_skills(ROOT), sorted(expected))
        self.assertNotIn("repo-scrub", expected)

    def test_coverage_and_counts(self):
        for skill in evals.model_invocable_skills(ROOT):
            kinds = [k for s, k in self.cases.values() if s == skill]
            with self.subTest(skill=skill):
                self.assertTrue(3 <= kinds.count("trigger") <= 5)
                self.assertTrue(2 <= kinds.count("near-miss") <= 3)

    def test_behaviour_suites(self):
        got = {s for s, k in self.cases.values() if k == "behaviour"}
        self.assertTrue(set(evals.BEHAVIOUR_REQUIRED) <= got)

    def test_every_grader_frontmatter_free_type(self):
        ev = os.path.join(ROOT, evals.EVAL_DIR)
        n = 0
        for case in self.cases:
            gdir = os.path.join(ev, case, "graders")
            for fn in os.listdir(gdir):
                fm, _ = evals.read_frontmatter(os.path.join(gdir, fn))
                with self.subTest(grader=f"{case}/{fn}"):
                    self.assertIn(fm["type"], evals.GRADER_TYPES)
                    errs = []
                    self.assertIsNotNone(evals.validate_grader(os.path.join(gdir, fn), errs), errs)
                n += 1
        self.assertGreater(n, 0)

    def test_no_skill_md_under_evals(self):
        for _, _, files in os.walk(os.path.join(ROOT, evals.EVAL_DIR)):
            self.assertNotIn("SKILL.md", files)


class DryRun(unittest.TestCase):
    def test_no_subprocess_or_system_call(self):
        patches = [mock.patch.object(subprocess, n) for n in
                   ("run", "Popen", "call", "check_call", "check_output")]
        patches += [mock.patch.object(os, n) for n in ("system", "popen")]
        with contextlib.ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = evals.main([])
        self.assertEqual(rc, 0, out.getvalue())
        for m in mocks:
            m.assert_not_called()
        text = out.getvalue()
        self.assertIn("claude plugin eval . --runs 1", text)
        self.assertIn("--max-cost-usd", text)
        self.assertIn("--no-publish", text)
        self.assertIn("Estimated agent runs:", text)

    def test_module_never_imports_subprocess(self):
        with open(evals.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("import subprocess", src)
        self.assertNotIn("os.system", src)

    def test_main_fails_on_errors(self):
        with mock.patch.object(evals, "validate", return_value=(["x: broken"], {})):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(evals.main([]), 1)
        self.assertIn("ERROR: x: broken", out.getvalue())
        self.assertNotIn("claude plugin eval", out.getvalue())


class Fixture(unittest.TestCase):
    """Temp repo: alpha, beta model-invocable; gamma user-only."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        for name, dmi in (("alpha", False), ("beta", False), ("gamma", True)):
            extra = "disable-model-invocation: true\n" if dmi else ""
            write(os.path.join(self.root, name, "SKILL.md"),
                  f"---\nname: {name}\ndescription: d\n{extra}---\n\nbody\n")
        for skill in ("alpha", "beta"):
            for i in range(3):
                self.case(f"{skill}-trigger-{i}", skill, "trigger", {"fired": skill_grader(skill, False)})
            for i in range(2):
                self.case(f"{skill}-near-{i}", skill, "near-miss", {f"not-{skill}": skill_grader(skill, True)})
        self.case("gamma-no-push", "gamma", "behaviour",
                  {"no-push": "---\ntype: tool_used\ntool: Bash\ninput_match: 'git\\s+push'\nmin: 0\nmax: 0\narm: both\n---\n"})

    def case(self, name, skill, kind, graders, body="do the thing"):
        d = os.path.join(self.root, "evals", name)
        write(os.path.join(d, "prompt.md"), PROMPT.format(skill=skill, kind=kind, body=body))
        for g, text in graders.items():
            write(os.path.join(d, "graders", g + ".md"), text)
        return d

    def errors(self):
        return evals.validate(self.root, behaviour_required=("gamma",))[0]

    def assertFails(self, needle):
        errs = self.errors()
        self.assertTrue(any(needle in e for e in errs), errs)

    def test_valid_fixture(self):
        self.assertEqual(self.errors(), [])

    def test_missing_suite(self):
        shutil.rmtree(os.path.join(self.root, "evals"))
        self.assertFails("evals/ missing")

    def test_skill_without_suite(self):
        write(os.path.join(self.root, "delta", "SKILL.md"), "---\nname: delta\ndescription: d\n---\n\nb\n")
        self.assertFails("delta: no eval suite")

    def test_too_few_triggers(self):
        shutil.rmtree(os.path.join(self.root, "evals", "alpha-trigger-0"))
        self.assertFails("alpha: 2 trigger case(s)")

    def test_too_many_near_misses(self):
        for i in (2, 3):
            self.case(f"alpha-near-{i}", "alpha", "near-miss", {"n": skill_grader("alpha", True)})
        self.assertFails("alpha: 4 near-miss case(s)")

    def test_missing_behaviour(self):
        shutil.rmtree(os.path.join(self.root, "evals", "gamma-no-push"))
        self.assertFails("gamma: no behaviour case")

    def test_user_only_skill_cannot_have_trigger(self):
        self.case("gamma-trigger-0", "gamma", "trigger", {"fired": skill_grader("gamma", False)})
        self.assertFails("user-only")

    def test_paid_grader_rejected(self):
        self.case("alpha-trigger-0", "alpha", "trigger", {"judge": "---\ntype: llm\n---\n\nPASS if good.\n"})
        self.assertFails("calls a judge model")

    def test_unknown_grader_type(self):
        self.case("alpha-trigger-0", "alpha", "trigger", {"x": "---\ntype: magic\n---\n"})
        self.assertFails("unknown or missing grader type")

    def test_grader_without_frontmatter(self):
        self.case("alpha-trigger-0", "alpha", "trigger", {"x": "just text\n"})
        self.assertFails("grader has no frontmatter")

    def test_grader_bad_regex(self):
        self.case("alpha-trigger-0", "alpha", "trigger", {"x": "---\ntype: regex\npattern: '(unclosed'\n---\n"})
        self.assertFails("does not compile")

    def test_grader_missing_required(self):
        self.case("alpha-trigger-0", "alpha", "trigger", {"x": "---\ntype: tool_order\nbefore: Read\n---\n"})
        self.assertFails("missing ['after']")

    def test_grader_unknown_key(self):
        self.case("alpha-trigger-0", "alpha", "trigger", {"x": "---\ntype: file_exists\npath: a.txt\ncolour: red\n---\n"})
        self.assertFails("unknown key(s) ['colour']")

    def test_grader_min_gt_max(self):
        self.case("alpha-trigger-0", "alpha", "trigger",
                  {"x": "---\ntype: tool_used\ntool: Read\nmin: 2\nmax: 1\n---\n"})
        self.assertFails("min > max")

    def test_no_graders(self):
        d = self.case("alpha-trigger-0", "alpha", "trigger", {})
        shutil.rmtree(os.path.join(d, "graders"))
        self.assertFails("no graders/*.md")

    def test_trigger_needs_specific_skill_grader(self):
        # Matches any skill, so it is not specific to alpha.
        loose = "---\ntype: tool_used\ntool: Skill\n---\n"
        shutil.rmtree(os.path.join(self.root, "evals", "alpha-trigger-0"))
        self.case("alpha-trigger-0", "alpha", "trigger", {"fired": loose})
        self.assertFails("trigger case needs")

    def test_near_miss_must_name_the_skill(self):
        shutil.rmtree(os.path.join(self.root, "evals", "alpha-near-0"))
        self.case("alpha-near-0", "alpha", "near-miss", {"none": "---\ntype: tool_used\ntool: Skill\nmin: 0\nmax: 0\narm: both\n---\n"})
        self.assertFails("near-miss case needs")

    def test_near_miss_needs_arm_both(self):
        shutil.rmtree(os.path.join(self.root, "evals", "alpha-near-0"))
        g = skill_grader("alpha", True).replace("arm: both\n", "")
        self.case("alpha-near-0", "alpha", "near-miss", {"not-alpha": g})
        self.assertFails("near-miss case needs")

    def test_prompt_unknown_key(self):
        d = self.case("alpha-trigger-0", "alpha", "trigger", {"fired": skill_grader("alpha", False)})
        write(os.path.join(d, "prompt.md"), "---\ntags: [alpha, trigger]\nallowed_tools: [Skill]\nbogus: 1\n---\n\nhi\n")
        self.assertFails("unknown key(s) ['bogus']")

    def test_prompt_empty_body(self):
        self.case("alpha-trigger-0", "alpha", "trigger", {"fired": skill_grader("alpha", False)}, body="")
        self.assertFails("empty prompt body")

    def test_prompt_tags_need_kind(self):
        d = self.case("alpha-trigger-0", "alpha", "trigger", {"fired": skill_grader("alpha", False)})
        write(os.path.join(d, "prompt.md"), "---\ntags: [alpha]\nallowed_tools: [Skill]\n---\n\nhi\n")
        self.assertFails("tags need exactly one")

    def test_dir_name_must_match_skill(self):
        self.case("wrong-name", "alpha", "trigger", {"fired": skill_grader("alpha", False)})
        self.assertFails("directory must start with 'alpha-'")

    def test_skill_md_under_evals(self):
        write(os.path.join(self.root, "evals", "alpha-trigger-0", "SKILL.md"), "x")
        self.assertFails("no SKILL.md allowed")

    def test_stray_file(self):
        write(os.path.join(self.root, "evals", "notes.txt"), "x")
        self.assertFails("unexpected file")

    def test_results_dir_ignored(self):
        write(os.path.join(self.root, "evals", "results", "run", "report.html"), "x")
        self.assertEqual(self.errors(), [])


class NamesOnly(unittest.TestCase):
    def test_prefix_collision(self):
        pat = evals._compile('"skill"\\s*:\\s*"(?:[\\w-]+:)?handoff-auto"')
        self.assertTrue(evals.names_only(pat, "handoff-auto", ["handoff-auto", "session-handoff", "handoff"]))
        loose = evals._compile("handoff")
        self.assertFalse(evals.names_only(loose, "handoff-auto", ["handoff-auto", "session-handoff"]))


if __name__ == "__main__":
    unittest.main()
