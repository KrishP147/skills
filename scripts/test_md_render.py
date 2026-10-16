"""Tests for scripts/md_render.py. Run: python -m unittest discover -s scripts -p "test_*.py" """
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from md_render import Renderer, parse_transcript, safe_url, slugify  # noqa: E402


def r(md, **kw):
    return Renderer(**kw).render(md)


class BlockTest(unittest.TestCase):
    def test_headings_with_ids(self):
        out = r("# Hello World\n\n## What it *does*\n\n### `x` & y")
        self.assertIn('<h1 id="hello-world">Hello World</h1>', out)
        self.assertIn('<h2 id="what-it-does">What it <em>does</em></h2>', out)
        self.assertIn('<h3 id="x--y"><code>x</code> &amp; y</h3>', out)

    def test_heading_ids_unique_and_offset(self):
        rd = Renderer()
        a = rd.render("## Tips\n\n## Tips", heading_offset=1)
        self.assertIn('<h3 id="tips">', a)
        self.assertIn('<h3 id="tips-1">', a)
        self.assertIn('id="tips-2"', rd.render("# Tips"))

    def test_paragraphs(self):
        out = r("one\ntwo\n\nthree")
        self.assertEqual(out, "<p>one\ntwo</p>\n<p>three</p>")

    def test_nested_lists(self):
        md = "- a\n- b\n  1. x\n  2. y\n- c"
        out = r(md)
        self.assertEqual(out.count("<ul>"), 1)
        self.assertEqual(out.count("<ol>"), 1)
        self.assertIn("<li>b\n<ol>\n<li>x</li>\n<li>y</li>\n</ol></li>", out)
        self.assertNotIn("<p>", out)

    def test_ordered_start_and_loose(self):
        out = r("3. a\n\n4. b")
        self.assertIn('<ol start="3">', out)
        self.assertIn("<li><p>a</p></li>", out)

    def test_list_item_continuation(self):
        out = r("1. **Step.** first line\n   more text\n2. next")
        self.assertIn("<li><strong>Step.</strong> first line\nmore text</li>", out)

    def test_code_fence(self):
        out = r("```sh\n<b>&x\n  indented\n```\nafter")
        self.assertIn('<pre><code class="language-sh">&lt;b&gt;&amp;x\n  indented\n</code></pre>', out)
        self.assertIn("<p>after</p>", out)
        self.assertIn("<code>**not bold**\n</code>", r("~~~\n**not bold**\n~~~"))

    def test_unclosed_fence_runs_to_end(self):
        self.assertIn("<pre><code>a\nb\n</code></pre>", r("```\na\nb"))

    def test_table(self):
        md = "| A | B |\n|---|:-:|\n| `x|y` | [l](http://e.com) |\n| 1 |"
        out = r(md)
        self.assertIn('<div class="table-wrap"><table>', out)
        self.assertIn("<th>A</th>", out)
        self.assertIn('<th style="text-align:center">B</th>', out)
        self.assertIn("<td><code>x|y</code></td>", out)
        self.assertIn('<a href="http://e.com">l</a>', out)
        self.assertIn("<tr><td>1</td><td style=\"text-align:center\"></td></tr>", out)

    def test_blockquote(self):
        out = r("> quoted **x**\n> - item")
        self.assertIn("<blockquote>", out)
        self.assertIn("<p>quoted <strong>x</strong></p>", out)
        self.assertIn("<li>item</li>", out)

    def test_hr(self):
        self.assertIn("<hr>", r("a\n\n---\n\nb"))


class TranscriptTest(unittest.TestCase):
    SRC = ("> /pair 42 --push\n"
           "⏺ Bash(gh issue view 42)\n"
           "  ⎿ title: fix <date> parsing\n"
           "      indented detail\n"
           "⏺ Reading the **issue** and `x`.\n"
           "  second line\n"
           "\n"
           "loose line\n")

    def test_parse(self):
        self.assertEqual(parse_transcript(self.SRC), [
            ("prompt", "/pair 42 --push", []),
            ("tool", ("Bash", "gh issue view 42"), ["title: fix <date> parsing", "  indented detail"]),
            ("reply", "Reading the **issue** and `x`.", ["second line"]),
            ("text", "loose line", []),
        ])

    def test_reply_without_parens_is_not_a_tool(self):
        self.assertEqual(parse_transcript("⏺ Done (3 commits).")[0][0], "reply")
        self.assertEqual(parse_transcript('⏺ Agent(subagent_type="x", prompt=...)')[0][:2],
                         ("tool", ("Agent", 'subagent_type="x", prompt=...')))

    def test_fence_renders_transcript(self):
        h = r("```transcript\n" + self.SRC + "```\n")
        self.assertTrue(h.startswith('<div class="tx" role="group" aria-label="Example session">'))
        self.assertNotIn("<pre>", h)
        self.assertIn('<span class="tx-text">/pair 42 --push</span>', h)
        self.assertIn('<details class="tx-tool"><summary><span class="tx-dot" aria-hidden="true">⏺</span>'
                      '<span class="tx-name">Bash</span>(<span class="tx-args">gh issue view 42</span>) '
                      '<span class="tx-more">(+2 lines)</span></summary>', h)
        self.assertIn("title: fix &lt;date&gt; parsing\n  indented detail</span>", h)
        self.assertIn("Reading the <strong>issue</strong> and <code>x</code>.\nsecond line", h)
        self.assertIn('<div class="tx-line">loose line</div>', h)

    def test_transcript_escapes_html(self):
        h = r("```transcript\n> <script>x</script>\n⏺ T(<b>)\n  ⎿ <img src=x>\n⏺ <i>hi</i>\n```")
        for tag in ("<script>", "<b>", "<img", "<i>"):
            self.assertNotIn(tag, h)

    def test_other_fences_unchanged(self):
        self.assertIn('<pre><code class="language-bash">', r("```bash\nls\n```"))


class InlineTest(unittest.TestCase):
    def test_emphasis(self):
        out = r("**bold** and *it* and _it2_ and snake_case_name")
        self.assertIn("<strong>bold</strong>", out)
        self.assertIn("<em>it</em>", out)
        self.assertIn("<em>it2</em>", out)
        self.assertIn("snake_case_name", out)

    def test_inline_code_is_literal(self):
        out = r("use `<script>**x**</script>` here")
        self.assertIn("<code>&lt;script&gt;**x**&lt;/script&gt;</code>", out)

    def test_double_backtick_code(self):
        self.assertIn("<code>a ` b</code>", r("``a ` b``"))

    def test_links(self):
        out = r('[`pair`](../pair/ "T") and <https://x.io/a>')
        self.assertIn('<a href="../pair/" title="T"><code>pair</code></a>', out)
        self.assertIn('<a href="https://x.io/a">https://x.io/a</a>', out)

    def test_link_rewriter(self):
        out = r("[a](x.md#h) [b](https://ok)", link_rewriter=lambda u: "/R" if u.startswith("x") else u)
        self.assertIn('<a href="/R">a</a>', out)
        self.assertIn('<a href="https://ok">b</a>', out)
        dropped = r("[a](x)", link_rewriter=lambda u: None)
        self.assertEqual(dropped, "<p>a</p>")

    def test_backslash_escape(self):
        self.assertIn("*not em*", r(r"\*not em\*"))


class SafetyTest(unittest.TestCase):
    def test_raw_html_escaped(self):
        out = r('<script>alert(1)</script>\n\n<img src=x onerror="alert(1)">')
        self.assertNotIn("<script", out)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", out)

    def test_html_in_every_context(self):
        md = ("# <b>h</b>\n\n- <i>li</i>\n\n> <u>q</u>\n\n| <s>t</s> |\n|---|\n| <em>c</em> |\n\n"
              "[<b>x</b>](http://a) **<b>y</b>**")
        out = r(md)
        for tag in ("<b>", "<i>", "<u>", "<s>", "<em>c"):
            self.assertNotIn(tag, out)

    def test_javascript_urls_rejected(self):
        for url in ("javascript:alert(1)", "JaVaScRiPt:alert(1)", "java\tscript:alert(1)",
                    "data:text/html,x", "vbscript:x", "&#106;avascript:alert(1)"):
            out = r("[click](%s)" % url)
            self.assertNotIn("href", out, url)
            self.assertIn("click", out)
        self.assertNotIn("href", r("[x](javascript:alert(1))", link_rewriter=lambda u: u))
        # A rewriter can't smuggle one in either.
        self.assertNotIn("href", r("[x](a)", link_rewriter=lambda u: "javascript:x"))

    def test_attribute_quote_escaped(self):
        out = r('[x](http://a/"onmouseover=alert(1))')
        self.assertNotIn('"onmouseover', out)

    def test_safe_url(self):
        self.assertEqual(safe_url("https://a"), "https://a")
        self.assertEqual(safe_url("../pair/"), "../pair/")
        self.assertEqual(safe_url("mailto:a@b.c"), "mailto:a@b.c")
        self.assertIsNone(safe_url(" javascript:x"))

    def test_nul_stripped(self):
        self.assertNotIn("\x00", r("a\x00b `c\x00`"))

    def test_slugify(self):
        self.assertEqual(slugify("How it works"), "how-it-works")
        self.assertEqual(slugify("hooks/guard-git.py"), "hooksguard-gitpy")


if __name__ == "__main__":
    unittest.main()
