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


if __name__ == "__main__":
    unittest.main()
