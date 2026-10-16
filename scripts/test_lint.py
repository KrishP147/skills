import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lint  # noqa: E402


class ReadmeHeadings(unittest.TestCase):
    def test_fenced_heading_ignored(self):
        self.assertEqual(lint.readme_headings("```\n## Foo\n```\n"), set())

    def test_real_heading_counted(self):
        self.assertEqual(lint.readme_headings("## Foo\n```\n## Bar\n```\n## Baz\n"), {"Foo", "Baz"})

    def test_unclosed_fence(self):
        self.assertEqual(lint.readme_headings("## A\n```\n## B\n## C\n"), {"A"})

    def test_tilde_fence(self):
        self.assertEqual(lint.readme_headings("~~~\n## B\n~~~\n## C\n"), {"C"})

    def test_indented_opener(self):
        self.assertEqual(lint.readme_headings("  ```\n## B\n  ```\n## C\n"), {"C"})

    def test_mismatched_close(self):
        self.assertEqual(lint.readme_headings("```\n~~~\n## B\n```\n## C\n"), {"C"})

    def test_shorter_close_does_not_close(self):
        self.assertEqual(lint.readme_headings("````\n```\n## B\n````\n## C\n"), {"C"})

    def test_language_tag_opener(self):
        self.assertEqual(lint.readme_headings("```bash\n## B\n```\n## C\n"), {"C"})

    def test_close_with_trailing_text_does_not_close(self):
        self.assertEqual(lint.readme_headings("```\n``` x\n## B\n```\n## C\n"), {"C"})


class WarnMissing(unittest.TestCase):
    def test_fenced_invoke_warns(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "SKILL.md"), "w").write("x")
            open(os.path.join(d, "README.md"), "w").write("```\n## How to invoke\n```\n")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                lint.warn_missing_readme_sections(os.path.join(d, "SKILL.md"))
        out = err.getvalue()
        self.assertTrue(out.startswith("WARN:"))
        self.assertIn("How to invoke", out)

    def test_invoke_alias_still_works(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "SKILL.md"), "w").write("x")
            open(os.path.join(d, "README.md"), "w").write("## Invoke\n")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                lint.warn_missing_readme_sections(os.path.join(d, "SKILL.md"))
        self.assertNotIn("How to invoke", err.getvalue())


class BlockScalarFrontmatter(unittest.TestCase):
    def fm(self, body):
        data, _ = lint.parse_frontmatter("---\n" + body + "---\nbody\n")
        return data

    def test_folded_with_paragraph_break(self):
        d = self.fm("name: x\ndescription: >\n  Lazy senior dev mode.\n  Second line.\n\n  New para.\nnext: v\n")
        self.assertEqual(d["description"], "Lazy senior dev mode. Second line.\nNew para.\n")
        self.assertEqual(d["next"], "v")

    def test_literal_keeps_newlines(self):
        d = self.fm("description: |\n  a\n  b\nk: v\n")
        self.assertEqual(d["description"], "a\nb\n")
        self.assertEqual(d["k"], "v")

    def test_chomp_strip(self):
        self.assertEqual(self.fm("d: >-\n  a\n  b\n\n")["d"], "a b")
        self.assertEqual(self.fm("d: |-\n  a\n  b\n")["d"], "a\nb")

    def test_chomp_keep(self):
        self.assertEqual(self.fm("d: |+\n  a\n\n\nk: v\n")["d"], "a\n\n\n")
        self.assertEqual(self.fm("d: >+\n  a\n  b\n\nk: v\n")["d"], "a b\n\n")

    def test_indent_digit(self):
        self.assertEqual(self.fm("d: |2\n  a\n    b\n")["d"], "a\n  b\n")

    def test_header_comment(self):
        self.assertEqual(self.fm("d: > # c\n  a\n  b\nk: v\n")["d"], "a b\n")
        self.assertEqual(self.fm("d: | # c\n  a\n  b\n")["d"], "a\nb\n")
        self.assertEqual(self.fm("d: >- # c\n  a\n  b\n")["d"], "a b")
        self.assertEqual(self.fm("d: |2 # c\n  a\n    b\n")["d"], "a\n  b\n")

    def test_hash_without_space_not_block_scalar(self):
        self.assertEqual(self.fm("d: >#c\n  a\n")["d"], ">#c")

    def test_folded_more_indented(self):
        self.assertEqual(self.fm("d: >\n  a\n    b\n  c\n")["d"], "a\n  b\nc\n")

    def test_folded_more_indented_with_blank(self):
        self.assertEqual(self.fm("d: >\n  a\n\n    b\n  c\n")["d"], "a\n\n  b\nc\n")
        self.assertEqual(self.fm("d: >\n  a\n    b\n\n    c\n  d\n")["d"], "a\n  b\n\n  c\nd\n")

    def test_list_still_works(self):
        d = self.fm("tools:\n  - a\n  - b\nempty:\nk: v\n")
        self.assertEqual(d["tools"], ["a", "b"])
        self.assertEqual(d["empty"], [])
        self.assertEqual(d["k"], "v")

    def test_quoted_unchanged(self):
        d = self.fm('argument-hint: "[lite|full|ultra]"\n')
        self.assertEqual(d["argument-hint"], '"[lite|full|ultra]"')

    def test_lint_common_flags_raw_indicator(self):
        for raw in (">", "|", ">-", "|+", ">2"):
            failures = []
            lint.lint_common("p", {"name": "x", "description": raw}, "body", "x", failures)
            self.assertTrue(any("block scalar" in f for f in failures), raw)

    def test_real_ponytail(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "ponytail", "SKILL.md"), encoding="utf-8") as f:
            d, _ = lint.parse_frontmatter(f.read())
        self.assertTrue(d["description"].startswith("Lazy senior dev mode"))
        self.assertNotIn(">", d["description"])


class ChangelogVersion(unittest.TestCase):
    def _run(self, plugin_version, changelog):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".claude-plugin"))
            with open(os.path.join(root, ".claude-plugin", "plugin.json"), "w", encoding="utf-8") as f:
                f.write('{"name": "x", "version": "%s"}' % plugin_version)
            if changelog is not None:
                with open(os.path.join(root, "CHANGELOG.md"), "w", encoding="utf-8") as f:
                    f.write(changelog)
            failures = []
            lint.check_changelog_version(root, failures)
            return failures

    def test_top_version_forms(self):
        for heading in ("## [0.2.0] - 2026-01-01", "## 0.2.0", "## v0.2.0", "## [0.2.0]"):
            self.assertEqual(lint.changelog_top_version("# Changelog\n\n" + heading + "\n- x\n"), "0.2.0", heading)

    def test_first_heading_wins(self):
        self.assertEqual(lint.changelog_top_version("## [0.3.0]\n## [0.2.0]\n"), "0.3.0")

    def test_unversioned_top_heading(self):
        self.assertIsNone(lint.changelog_top_version("## Unreleased\n## [0.2.0]\n"))

    def test_match_passes(self):
        self.assertEqual(self._run("0.2.0", "# Changelog\n\n## [0.2.0] - 2026-01-01\n- x\n"), [])

    def test_mismatch_fails(self):
        failures = self._run("0.3.0", "## [0.2.0]\n- x\n")
        self.assertEqual(len(failures), 1)
        self.assertIn("0.3.0", failures[0])

    def test_missing_changelog_fails(self):
        self.assertEqual(len(self._run("0.2.0", None)), 1)

    def test_no_manifest_skips(self):
        with tempfile.TemporaryDirectory() as root:
            failures = []
            lint.check_changelog_version(root, failures)
            self.assertEqual(failures, [])

    def test_repo_changelog_matches(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        failures = []
        lint.check_changelog_version(root, failures)
        self.assertEqual(failures, [])

class GroupEscape(unittest.TestCase):
    def _run(self, rel, text):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, *rel.split("/"))
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            failures = []
            lint.check_group_escape(root, path, failures)
            return failures

    def test_escape_fails(self):
        f = self._run("kanban/x/SKILL.md", "see [T](../../handoff-auto/TRACKING.md)")
        self.assertEqual(len(f), 1)
        self.assertIn("leaves the group dir", f[0])

    def test_sibling_in_group_ok(self):
        self.assertEqual(self._run("kanban/x/SKILL.md", "[B](../next/BOARD.md)"), [])

    def test_own_dir_and_anchor_and_url_ok(self):
        self.assertEqual(self._run("kanban/x/SKILL.md", "[a](A.md) [b](#h) [c](https://e.com/../../x)"), [])

    def test_top_level_skill_ignored(self):
        self.assertEqual(self._run("x/SKILL.md", "[T](../handoff-auto/TRACKING.md)"), [])


if __name__ == "__main__":
    unittest.main()
