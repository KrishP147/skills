"""Tests for scripts/flow_svg.py. Run: python -m unittest discover -s scripts -p "test_*.py" """
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flow_svg  # noqa: E402
from flow_svg import FlowError, layout, parse, render, svg  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

LOOP = """flowchart TD
    next[next: top tasks] --> impl[You implement]
    impl --> handoff[session-handoff]
    handoff --> update[update-progress]
    update -->|finishes with next| next
    update -.->|deviations| consult[consult-plan]
"""
BRANCH = """flowchart LR
    %% a comment
    plan[planner] -->|pair| man[manager]
    plan -->|flat| imp[implementer]
    man --> gate[merge gate]
    imp --> gate
    gate --> ver[verifier]
    ver --> plan
"""


def _boxes(lay):
    return {nid: b for nid, _l, b in lay.nodes}


def _overlap(a, b, pad=0):
    return (a.x < b.x + b.w + pad and b.x < a.x + a.w + pad
            and a.y < b.y + b.h + pad and b.y < a.y + a.h + pad)


def _samples(pts, loop, td, n=24):
    """Points along a route's drawn curve (same maths as flow_svg._path)."""
    segs = []
    if loop:
        segs.append(pts)
    else:
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if td:
                m = (y1 + y2) / 2
                segs.append([(x1, y1), (x1, m), (x2, m), (x2, y2)])
            else:
                m = (x1 + x2) / 2
                segs.append([(x1, y1), (m, y1), (m, y2), (x2, y2)])
    out = []
    for p0, p1, p2, p3 in segs:
        for i in range(1, n):
            t = i / n
            u = 1 - t
            out.append(tuple(u ** 3 * p0[k] + 3 * u * u * t * p1[k] + 3 * u * t * t * p2[k] + t ** 3 * p3[k]
                             for k in (0, 1)))
    return out


class ParseTest(unittest.TestCase):
    def test_nodes_edges_in_declaration_order(self):
        g = parse(LOOP)
        self.assertEqual(g.direction, "TD")
        self.assertEqual(list(g.nodes), ["next", "impl", "handoff", "update", "consult"])
        self.assertEqual(g.nodes["next"], "next: top tasks")
        self.assertEqual(g.edges[3], flow_svg.Edge("update", "next", "finishes with next", False))
        self.assertTrue(g.edges[4].dotted)
        self.assertEqual(g.edges[4].label, "deviations")

    def test_bare_ids_comments_and_lone_nodes(self):
        g = parse("\n%% hi\nflowchart LR\n  A\n  A --> B\n  C[see]\n")
        self.assertEqual(g.direction, "LR")
        self.assertEqual(g.nodes, {"A": "A", "B": "B", "C": "see"})
        self.assertEqual(len(g.edges), 1)

    def test_label_defined_on_later_reference(self):
        g = parse("flowchart TD\n  A --> B\n  B[bee] --> C")
        self.assertEqual(g.nodes["B"], "bee")

    def test_unsupported_syntax_raises(self):
        bad = [
            "",                                          # empty
            "graph TD\n  A --> B",                       # old keyword
            "flowchart TB\n  A --> B",                   # other direction
            "flowchart TD\n  A(round) --> B",            # other shape
            "flowchart TD\n  A{choice}",                 # rhombus
            "flowchart TD\n  A --- B",                   # open link
            "flowchart TD\n  A ==> B",                   # thick link
            "flowchart TD\n  A --> B --> C",             # chain
            "flowchart TD\n  A & B --> C",               # fan
            "flowchart TD\n  A -- text --> B",           # inline label
            "flowchart TD\n  A-->B",                     # no spaces
            "flowchart TD\n  subgraph x\n  A\n  end",    # subgraph
            "flowchart TD\n  classDef x fill:#f00",      # styling
            "flowchart TD\n  style A fill:#f00",
            "flowchart TD\n  click A href",
            "flowchart TD\n  A --> B;",                  # statement separator
            "flowchart TD\n  A[a (b)] --> B",            # parens in label
            'flowchart TD\n  A["quoted"]',               # quotes
            "flowchart TD\n  A[#35;]",                   # entity
            "flowchart TD\n  A[/slant/]",                # parallelogram
            "flowchart TD\n  A[]",                       # empty label
            "flowchart TD\n  A -->|| B",                 # empty edge label
            "flowchart TD\n  end --> B",                 # keyword id
            "flowchart TD\n  A --> A",                   # self-loop
            "flowchart TD\n  A --> B\n  A --> B",        # duplicate edge
            "flowchart TD\n  A[x]\n  A[y]",              # relabel
            "flowchart TD",                              # no nodes
        ]
        for text in bad:
            with self.subTest(text=text):
                with self.assertRaises(FlowError):
                    parse(text)

    def test_error_names_line(self):
        with self.assertRaisesRegex(FlowError, "line 3"):
            parse("flowchart TD\n  A --> B\n  B ==> C")


class LayoutTest(unittest.TestCase):
    def test_same_input_byte_identical(self):
        for text in (LOOP, BRANCH):
            self.assertEqual(render(text), render(text))

    def test_identical_across_processes(self):
        # Hash seeds differ per process; output must not depend on them.
        code = "import sys; sys.path.insert(0, %r); import flow_svg, test_flow_svg as t; print(flow_svg.render(t.LOOP))" % os.path.dirname(os.path.abspath(__file__))
        outs = set()
        for seed in ("1", "2", "3"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            outs.add(subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                                    text=True, encoding="utf-8", check=True).stdout)
        self.assertEqual(len(outs), 1)
        self.assertEqual(outs.pop().strip(), render(LOOP))

    def test_formatting_independent(self):
        # Whitespace, comments and where a label is first given don't matter.
        a = "flowchart TD\nA[a] --> B[b]\nB --> C[c]\nC --> A"
        b = "%% x\nflowchart   TD\n\n   A[a]   -->   B\n  %% y\n  B[b] --> C[c]\n\tC --> A\n"
        self.assertEqual(render(a), render(b))

    def test_lone_node_position_independent(self):
        # Edges decide ranks; a lone node line moving doesn't move the graph.
        base = "flowchart TD\n  A[a] --> B[b]\n  B --> C[c]\n"
        lay1 = layout(parse("flowchart TD\n  A[a]\n  B[b]\n  C[c]\n  A --> B\n  B --> C"))
        lay2 = layout(parse(base))
        self.assertEqual(_boxes(lay1), _boxes(lay2))

    def test_back_edge_broken_by_declaration_order(self):
        lay = layout(parse(LOOP))
        boxes = _boxes(lay)
        ys = [boxes[n].y for n in ("next", "impl", "handoff", "update", "consult")]
        self.assertEqual(ys, sorted(ys))
        self.assertEqual(len(set(ys)), 5)
        back = [r for r in lay.edges if r.back]
        self.assertEqual(len(back), 1)
        # Drawn from update up to next: arrow ends at next's bottom side.
        end = back[0].points[-1]
        b = boxes["next"]
        self.assertAlmostEqual(end[1], b.y + b.h)
        # Declaration order decides which edge is the back edge.
        rev = parse("flowchart TD\n  A --> B\n  B --> A")
        self.assertEqual([r.back for r in layout(rev).edges], [False, True])
        rev2 = parse("flowchart TD\n  B --> A\n  A --> B")
        self.assertEqual([r.back for r in layout(rev2).edges], [False, True])

    def test_routes_clear_nodes(self):
        """No edge passes through a node it doesn't touch, and back edges
        never run on top of a forward edge."""
        cases = [LOOP, BRANCH,
                 "flowchart TD\n  A --> B\n  B --> C\n  C -->|again| B\n  C --> D\n  D -.->|retry| A",
                 "flowchart LR\n  A --> B\n  B -->|loop| A\n  B --> C"]
        for text in cases:
            g = parse(text)
            lay = layout(g)
            td = g.direction == "TD"
            boxes = _boxes(lay)
            for e, r in zip(g.edges, lay.edges):
                pts = _samples(r.points, r.loop, td)
                for nid, b in boxes.items():
                    if nid in (e.src, e.dst):
                        continue
                    for px, py in pts:
                        inside = b.x + 1 < px < b.x + b.w - 1 and b.y + 1 < py < b.y + b.h - 1
                        self.assertFalse(inside, "%s: %s->%s crosses %s" % (text[:20], e.src, e.dst, nid))
            fw = [set((round(x), round(y)) for x, y in _samples(r.points, r.loop, td)) for r in lay.edges if not r.back]
            for r in lay.edges:
                if r.back:
                    pts = set((round(x), round(y)) for x, y in _samples(r.points, r.loop, td))
                    for f in fw:
                        self.assertLess(len(pts & f), 3, text)

    def test_nodes_and_labels_do_not_overlap(self):
        for text in (LOOP, BRANCH, "flowchart TD\n  A -->|one| B\n  A -->|two| C\n  A -->|three| D"):
            lay = layout(parse(text))
            rects = [b for _n, _l, b in lay.nodes]
            for r in lay.edges:
                if r.label_at:
                    lw, lh = flow_svg._text_size(r.label)
                    rects.append(flow_svg.Box(r.label_at[0] - lw / 2 - 4, r.label_at[1] - lh / 2 - 2, lw + 8, lh + 4))
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    self.assertFalse(_overlap(rects[i], rects[j]), (text, rects[i], rects[j]))
            for b in rects:
                self.assertGreaterEqual(b.x, 0)
                self.assertGreaterEqual(b.y, 0)
                self.assertLessEqual(b.x + b.w, lay.width)
                self.assertLessEqual(b.y + b.h, lay.height)

    def test_lr_runs_left_to_right(self):
        lay = layout(parse(BRANCH))
        b = _boxes(lay)
        self.assertLess(b["plan"].x, b["man"].x)
        self.assertLess(b["man"].x, b["gate"].x)
        self.assertLess(b["gate"].x, b["ver"].x)


class SvgTest(unittest.TestCase):
    def test_tokens_only_no_colours(self):
        for text in (LOOP, BRANCH):
            out = render(text)
            self.assertNotIn("#", out)
            self.assertNotRegex(out.lower(), r"rgba?\(|hsla?\(|fill=|stroke=|style=")
            for cls in re.findall(r'class="([^"]+)"', out):
                for c in cls.split():
                    self.assertTrue(c.startswith("flow-"), c)

    def test_classes_styled_in_css(self):
        with open(os.path.join(ROOT, "site", "src", "style.css"), encoding="utf-8") as f:
            css = f.read()
        out = render(LOOP)
        for c in set(c for cls in re.findall(r'class="([^"]+)"', out) for c in cls.split()):
            if c != "flow-back":
                self.assertIn("." + c, css)
        rules = re.findall(r"\.flow[^{]*\{[^}]*\}", css)
        self.assertTrue(rules)
        for rule in rules:
            self.assertNotRegex(rule, r"#[0-9a-fA-F]{3,8}\b|rgba?\(", rule)

    def test_accessible_name(self):
        out = render(LOOP)
        self.assertIn('role="img"', out)
        m = re.search(r"<title>(.*?)</title>", out)
        self.assertTrue(m)
        self.assertIn("update-progress to next: top tasks (finishes with next)", m.group(1))
        self.assertTrue(out.index("<title>") < out.index("<g"))
        self.assertIn("<title>Custom</title>", svg(layout(parse(LOOP)), "Custom"))

    def test_escapes_text(self):
        out = render("flowchart TD\n  A[a & b] --> B[c's]")
        self.assertIn("a &amp; b", out)
        self.assertIn("c&#x27;s", out)

    def test_size_attributes_match_viewbox(self):
        out = render(LOOP)
        m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)" width="([\d.]+)" height="([\d.]+)"', out)
        self.assertTrue(m)
        self.assertEqual(m.group(1), m.group(3))
        self.assertEqual(m.group(2), m.group(4))


if __name__ == "__main__":
    unittest.main()
