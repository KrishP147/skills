"""Flowchart -> inline SVG for the skills site. Stdlib only.

Renders a strict subset of mermaid flowchart syntax, so the same fence also
renders on GitHub:

    flowchart TD            (or LR; first non-blank line)
    %% comment
    A[label]                node; the label is optional (defaults to the id)
    A[label] --> B[label]   edge; one edge per line
    A -->|label| B          labelled edge
    A -.-> B                dotted edge (also -.->|label|)

Ids are [A-Za-z][A-Za-z0-9_]* (not a mermaid keyword). Labels can't hold
[]{}()<>|"#;` or start with / or \\. Anything else raises FlowError, so a
typo fails the site build instead of shipping a broken picture.

Layout is a small layered (Sugiyama-style) one, fully deterministic: same
text -> byte-identical SVG.
  1. Back edges: depth-first search from nodes in declaration order,
     following edges in declaration order; an edge into a node still on the
     stack is a back edge (a loop). Back edges are laid out reversed.
  2. Ranks: longest path over the resulting DAG; a labelled forward edge
     spans at least two ranks so its label gets a slot of its own.
  3. Edges spanning several ranks get a dummy point per rank in between, so
     they run in their own lane instead of through nodes; a chain's dummies
     are straightened into one lane when nothing is in the way. A loop's
     return edge therefore climbs beside the nodes it skips.
  4. Order within a rank: declaration order, then barycenter sweeps (stable
     sorts, ties keep the current order); the order with fewest crossings
     wins, earliest on a tie.
  5. Positions: packed with fixed gaps, then nudged toward neighbours.
Edges are cubic curves between ports. Forward edges share the middle of a
node side, long back edges take its corner, and a one-rank back edge (a
retry between neighbours) leaves and re-enters the far side of the nodes
instead, so no back edge runs along a forward one.

API:
    g = parse(text)            # Graph; FlowError outside the subset
    lay = layout(g)            # Layout
    s = svg(lay, title)        # '<svg ...>'; colours via CSS classes only
    title_for(g)               # default accessible name: every edge in words
    render(text, title=None)   # all three
"""
import html
import re
from collections import namedtuple

__all__ = ["FlowError", "Graph", "Edge", "parse", "layout", "svg", "title_for", "render"]


class FlowError(ValueError):
    """Text outside the supported flowchart subset."""


Edge = namedtuple("Edge", "src dst label dotted")


class Graph:
    def __init__(self, direction):
        self.direction = direction  # "TD" or "LR"
        self.nodes = {}  # id -> label, declaration order
        self.edges = []  # [Edge], declaration order


# ---- parse ------------------------------------------------------------------

_HEADER_RE = re.compile(r"^flowchart\s+(TD|LR)$")
_ID = r"[A-Za-z][A-Za-z0-9_]*"
_REF = r"(%s)(?:\[([^\[\]]*)\])?" % _ID
_NODE_RE = re.compile(r"^%s$" % _REF)
_EDGE_RE = re.compile(r"^%s\s+(-->|-\.->)(?:\|([^|]*)\|)?\s+%s$" % (_REF, _REF))
_BAD_LABEL_RE = re.compile(r"[\[\]{}()<>|\"#;`]")
_KEYWORDS = {"end", "subgraph", "graph", "flowchart", "style", "class", "classdef",
             "click", "linkstyle", "direction", "default", "call", "href"}


def _label(text, lineno, what):
    t = " ".join(text.split())
    if not t:
        raise FlowError("line %d: empty %s" % (lineno, what))
    if _BAD_LABEL_RE.search(t) or t[0] in "/\\":
        raise FlowError("line %d: unsupported character in %s %r" % (lineno, what, t))
    return t


def parse(text):
    """Parse flowchart text into a Graph. Raises FlowError."""
    lines = text.replace("\r\n", "\n").split("\n")
    g = None
    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        if g is None:
            m = _HEADER_RE.match(line)
            if not m:
                raise FlowError("line %d: expected 'flowchart TD' or 'flowchart LR', got %r" % (lineno, line))
            g = Graph(m.group(1))
            continue
        m = _EDGE_RE.match(line)
        if m:
            sid, slabel, arrow, elabel, did, dlabel = m.groups()
            src = _node(g, sid, slabel, lineno)
            dst = _node(g, did, dlabel, lineno)
            if src == dst:
                raise FlowError("line %d: self-loop on %r is unsupported" % (lineno, src))
            if any(e.src == src and e.dst == dst for e in g.edges):
                raise FlowError("line %d: duplicate edge %s --> %s" % (lineno, src, dst))
            lab = _label(elabel, lineno, "edge label") if elabel is not None else ""
            g.edges.append(Edge(src, dst, lab, arrow == "-.->"))
            continue
        m = _NODE_RE.match(line)
        if m:
            _node(g, m.group(1), m.group(2), lineno)
            continue
        raise FlowError("line %d: unsupported syntax %r" % (lineno, line))
    if g is None:
        raise FlowError("empty flowchart")
    if not g.nodes:
        raise FlowError("flowchart has no nodes")
    return g


def _node(g, nid, label, lineno):
    if nid.lower() in _KEYWORDS:
        raise FlowError("line %d: %r is a reserved word, not a node id" % (lineno, nid))
    if label is not None:
        label = _label(label, lineno, "node label")
        if nid in g.nodes and g.nodes[nid] != label and g.nodes[nid] != nid:
            raise FlowError("line %d: node %r relabelled" % (lineno, nid))
        g.nodes[nid] = label
    elif nid not in g.nodes:
        g.nodes[nid] = nid
    return nid


# ---- layout -----------------------------------------------------------------

FONT = 13          # px, matches .flow-svg text in style.css
CHAR_W = 8.0       # monospace advance at FONT, rounded up
LINE_H = 17
PAD_X, PAD_Y = 12, 8
WRAP = 22          # chars per label line
NODE_GAP = 28      # between neighbours in a rank
RANK_GAP = {"TD": 48, "LR": 56}
MARGIN = 10
ARROW = 8          # arrowhead length

Box = namedtuple("Box", "x y w h")
Route = namedtuple("Route", "points label label_at dotted back loop")


class Layout:
    def __init__(self, direction, width, height, nodes, edges):
        self.direction = direction
        self.width, self.height = width, height
        self.nodes = nodes  # [(id, label lines, Box)]
        # [Route]: points in drawing order, arrow at the end. loop=False:
        # curves through the points, tangent along the rank axis; loop=True:
        # points are one cubic (start, control, control, end).
        self.edges = edges


def _wrap(text):
    lines, cur = [], ""
    for word in text.split(" "):
        if cur and len(cur) + 1 + len(word) > WRAP:
            lines.append(cur)
            cur = word
        else:
            cur = (cur + " " + word) if cur else word
    lines.append(cur)
    return lines


def _text_size(lines):
    return max(len(l) for l in lines) * CHAR_W, len(lines) * LINE_H


def _back_edges(g):
    out = {n: [] for n in g.nodes}
    for k, e in enumerate(g.edges):
        out[e.src].append(k)
    state, back = {}, set()
    for root in g.nodes:
        if root in state:
            continue
        state[root] = 1
        stack = [(root, iter(out[root]))]
        while stack:
            n, it = stack[-1]
            k = next(it, None)
            if k is None:
                state[n] = 2
                stack.pop()
                continue
            d = g.edges[k].dst
            if state.get(d) == 1:
                back.add(k)
            elif d not in state:
                state[d] = 1
                stack.append((d, iter(out[d])))
    return back


def _ranks(g, oriented, minlen):
    order = list(g.nodes)
    indeg = {n: 0 for n in order}
    succ = {n: [] for n in order}
    for (a, b), m in zip(oriented, minlen):
        succ[a].append((b, m))
        indeg[b] += 1
    rank = {n: 0 for n in order}
    ready = [n for n in order if indeg[n] == 0]
    pos = {n: i for i, n in enumerate(order)}
    while ready:
        ready.sort(key=pos.get)
        n = ready.pop(0)
        for b, m in succ[n]:
            rank[b] = max(rank[b], rank[n] + m)
            indeg[b] -= 1
            if indeg[b] == 0:
                ready.append(b)
    return rank


def _crossings(layers, segs_between):
    total = 0
    for r in range(len(layers) - 1):
        pos_a = {v: i for i, v in enumerate(layers[r])}
        pos_b = {v: i for i, v in enumerate(layers[r + 1])}
        segs = [(pos_a[a], pos_b[b]) for a, b, _w in segs_between[r]]
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                (a1, b1), (a2, b2) = segs[i], segs[j]
                if (a1 - a2) * (b1 - b2) < 0:
                    total += 1
    return total


def layout(g):
    """Place nodes and route edges. Deterministic for a given Graph."""
    td = g.direction == "TD"
    back = _back_edges(g)
    oriented = [(e.dst, e.src) if k in back else (e.src, e.dst) for k, e in enumerate(g.edges)]
    # A labelled forward edge spans >= 2 ranks, so its label gets a slot of
    # its own (a dummy) and never collides with a sibling's label.
    minlen = [2 if e.label and k not in back else 1 for k, e in enumerate(g.edges)]
    rank = _ranks(g, oriented, minlen)

    # Vertices: real nodes, then dummies (k, j). size = (order axis, rank axis).
    labels = {n: _wrap(g.nodes[n]) for n in g.nodes}
    size = {}
    for n in g.nodes:
        w, h = _text_size(labels[n])
        w, h = max(w + 2 * PAD_X, 64), h + 2 * PAD_Y
        size[n] = (w, h) if td else (h, w)
    nranks = max(rank.values()) + 1
    layers = [[] for _ in range(nranks)]
    for n in g.nodes:
        layers[rank[n]].append(n)
    chains, elabels, label_vertex, lsizes = [], {}, {}, {}
    for k, (a, b) in enumerate(oriented):
        e = g.edges[k]
        chain = [a]
        span = rank[b] - rank[a]
        if e.label:
            elabels[k] = _wrap(e.label)
            lw, lh = _text_size(elabels[k])
            lsize = (lw + 8, lh + 4) if td else (lh + 4, lw + 8)
            lsizes[k] = lsize
        for j in range(1, span):
            d = ("d", k, j)
            rank[d] = rank[a] + j
            chain.append(d)
            layers[rank[a] + j].append(d)
            if e.label and j == span // 2:
                size[d] = lsize
                label_vertex[k] = d
            else:
                size[d] = (0, 0)
        chain.append(b)
        chains.append(chain)

    # Segments between layer r and r+1, weight 1 for forward, 0 for back.
    segs = [[] for _ in range(nranks)]
    for k, chain in enumerate(chains):
        w = 0 if k in back else 1
        for u, v in zip(chain, chain[1:]):
            segs[rank[u]].append((u, v, w))

    # Crossing reduction.
    best, best_c = [list(l) for l in layers], _crossings(layers, segs)
    for _sweep in range(6):
        for r in range(1, nranks):
            _reorder(layers, r, [(v, u) for u, v, _w in segs[r - 1]], r - 1)
        for r in range(nranks - 2, -1, -1):
            _reorder(layers, r, [(u, v) for u, v, _w in segs[r]], r + 1)
        c = _crossings(layers, segs)
        if c < best_c:
            best, best_c = [list(l) for l in layers], c
    layers = best

    # One-rank loops swing out past the far side of both nodes; keep that
    # room (and the loop's label) clear of the next vertex in each rank.
    pad = {}
    for k, chain in enumerate(chains):
        if k in back and len(chain) == 2:
            extra = NODE_GAP / 2 + (6 + lsizes[k][0] if k in lsizes else 0)
            for v in chain:
                pad[v] = max(pad.get(v, 0), extra)

    # Order-axis positions (centres).
    x = {}
    for layer in layers:
        _pack(layer, size, pad, {v: 0 for v in layer}, x, initial=True)
    nbr_up, nbr_down = {}, {}
    for r in range(nranks):
        for u, v, w in segs[r]:
            nbr_down.setdefault(u, []).append((v, w))
            nbr_up.setdefault(v, []).append((u, w))
    for passes in (range(1, nranks), range(nranks - 2, -1, -1), range(1, nranks)):
        for r in passes:
            nb = nbr_up if passes.step == 1 else nbr_down
            want = {}
            for v in layers[r]:
                ps = nb.get(v, [])
                fw = [x[u] for u, w in ps if w]
                pts = fw or [x[u] for u, _w in ps]
                want[v] = sum(pts) / len(pts) if pts else x[v]
            _pack(layers[r], size, pad, want, x)

    # Straighten long edges: a chain's dummies share one lane (its outermost
    # x) when no neighbour in their ranks is in the way.
    where = {v: (r, i) for r, layer in enumerate(layers) for i, v in enumerate(layer)}
    for chain in chains:
        ds = chain[1:-1]
        if len(ds) < 2:
            continue
        for lane, step in ((max(x[d] for d in ds), 1), (min(x[d] for d in ds), -1)):
            ok = True
            for d in ds:
                r, i = where[d]
                j = i + step
                if 0 <= j < len(layers[r]):
                    u = layers[r][j]
                    room = (size[u][0] + size[d][0]) / 2 + NODE_GAP / 2 + (pad.get(d if step > 0 else u, 0))
                    if (x[u] - lane) * step < room:
                        ok = False
            if ok:
                for d in ds:
                    x[d] = lane
                break

    # Rank-axis positions: layer start, thickness.
    thick = [max([size[v][1] for v in layer] or [0]) for layer in layers]
    start, y = [], 0.0
    for r in range(nranks):
        start.append(y)
        # Full gap between two ranks of nodes; half beside a rank that only
        # carries edges through (its labels already have their own slot).
        both_real = r + 1 < nranks and all(
            any(not isinstance(v, tuple) for v in layers[q]) for q in (r, r + 1))
        y += thick[r] + RANK_GAP[g.direction] * (1 if both_real else 0.5)
    mid = [start[r] + thick[r] / 2 for r in range(nranks)]

    # Ports: forward segments share the middle of a side (spread by the other
    # end's position); back segments sit near the corner on their own side.
    ports = {}
    for side, nb in (("lo", nbr_down), ("hi", nbr_up)):
        for v, ps in nb.items():
            if isinstance(v, tuple):
                continue
            # Back segments between two real nodes are one-rank loops, drawn
            # off the far side instead (below); they take no port here.
            ps = [(u, w) for u, w in ps if w or isinstance(u, tuple)]
            ps = sorted(ps, key=lambda p: x[p[0]])  # stable: ties keep segment order
            fw = [u for u, w in ps if w]
            for slot, u in enumerate(fw):
                off = 0.0 if len(fw) == 1 else (slot / (len(fw) - 1) - 0.5) * 0.5
                ports[(v, side, u)] = x[v] + off * size[v][0]
            for sign, group in ((-1, [u for u, w in ps if not w and x[u] < x[v]][::-1]),
                                (1, [u for u, w in ps if not w and x[u] >= x[v]])):
                for slot, u in enumerate(group):
                    off = 0.28 + 0.12 * slot / (len(group) - 1) if len(group) > 1 else 0.4
                    ports[(v, side, u)] = x[v] + sign * off * size[v][0]

    routes = []
    for k, chain in enumerate(chains):
        e = g.edges[k]
        a, b = chain[0], chain[-1]
        pts = [(ports[(a, "lo", chain[1])], mid[rank[a]] + size[a][1] / 2)]
        for d in chain[1:-1]:
            r = rank[d]
            pts.append((x[d], start[r]))
            pts.append((x[d], start[r] + thick[r]))
        pts.append((ports[(b, "hi", chain[-2])], mid[rank[b]] - size[b][1] / 2))
        loop = k in back and len(chain) == 2
        if loop:
            # A one-rank loop would sit on its forward twin: leave the far
            # side of one node, swing out by half a node gap (so it never
            # reaches a neighbour), come back into the far side of the
            # other.
            side = max(x[a] + size[a][0] / 2, x[b] + size[b][0] / 2) + NODE_GAP / 2
            pts = [(x[a] + size[a][0] / 2, mid[rank[a]]), (side, mid[rank[a]]),
                   (side, mid[rank[b]]), (x[b] + size[b][0] / 2, mid[rank[b]])]
        if loop and e.label:
            # Beside the loop at the source's rank, where `pad` kept room;
            # the gap above is where other edges cross.
            at = (side + 6 + lsizes[k][0] / 2, mid[rank[b]])
        elif k in label_vertex:
            d = label_vertex[k]
            at = (x[d], mid[rank[d]])
        elif e.label:
            (o1, r1), (o2, r2) = pts[0], pts[-1]
            at = ((o1 + o2) / 2, (r1 + r2) / 2)
        else:
            at = None
        if k in back:
            pts.reverse()
        routes.append((k, pts, at, loop))

    # Map (order, rank) -> (x, y) and normalise to a margin.
    def xy(p):
        return (p[0], p[1]) if td else (p[1], p[0])

    boxes = []
    for n in g.nodes:
        c = xy((x[n], mid[rank[n]]))
        w, h = size[n] if td else (size[n][1], size[n][0])
        boxes.append((n, labels[n], c, w, h))
    out_routes = []
    for k, pts, at, loop in routes:
        out_routes.append((k, [xy(p) for p in pts], at and xy(at), loop))
    xs, ys = [], []
    for _n, _l, (cx, cy), w, h in boxes:
        xs += [cx - w / 2, cx + w / 2]
        ys += [cy - h / 2, cy + h / 2]
    for k, pts, at, _b in out_routes:
        xs += [p[0] for p in pts]
        ys += [p[1] for p in pts]
        if at:
            lw, lh = _text_size(elabels[k])
            xs += [at[0] - lw / 2 - 4, at[0] + lw / 2 + 4]
            ys += [at[1] - lh / 2 - 2, at[1] + lh / 2 + 2]
    dx, dy = MARGIN - min(xs), MARGIN - min(ys)
    nodes = [(n, l, Box(cx + dx - w / 2, cy + dy - h / 2, w, h)) for n, l, (cx, cy), w, h in boxes]
    edges = []
    for k, pts, at, loop in out_routes:
        edges.append(Route([(p[0] + dx, p[1] + dy) for p in pts], elabels.get(k, []),
                           at and (at[0] + dx, at[1] + dy), g.edges[k].dotted, k in back, loop))
    return Layout(g.direction, max(xs) + dx + MARGIN, max(ys) + dy + MARGIN, nodes, edges)


def _reorder(layers, r, pairs, other):
    """Stable barycenter sort of layers[r] by positions in layers[other]."""
    pos = {v: i for i, v in enumerate(layers[other])}
    cur = {v: i for i, v in enumerate(layers[r])}
    acc = {}
    for v, u in pairs:
        acc.setdefault(v, []).append(pos[u])
    key = {v: (sum(acc[v]) / len(acc[v]) if v in acc else cur[v]) for v in layers[r]}
    layers[r].sort(key=lambda v: (key[v], cur[v]))


def _pack(layer, size, pad, want, x, initial=False):
    """Place a layer's vertices in order, >= NODE_GAP apart (plus pad[] on a
    vertex's far side), near `want`.
    Real nodes pull the layer; dummies only when alone."""
    if not layer:
        return
    pos = []
    for i, v in enumerate(layer):
        p = want[v]
        if i:
            u = layer[i - 1]
            sep = NODE_GAP if size[u][0] and size[v][0] else NODE_GAP / 2
            p = max(p, pos[-1] + (size[u][0] + size[v][0]) / 2 + pad.get(u, 0) + sep)
        pos.append(p)
    weights = [0.0 if isinstance(v, tuple) else 1.0 for v in layer]
    if not any(weights):
        weights = [1.0] * len(layer)
    shift = sum((p - want[v]) * w for p, v, w in zip(pos, layer, weights)) / sum(weights)
    if initial:
        shift = (pos[0] - size[layer[0]][0] / 2 + pos[-1] + size[layer[-1]][0] / 2) / 2
    for p, v in zip(pos, layer):
        x[v] = p - shift


# ---- svg --------------------------------------------------------------------

def _f(v):
    s = "%.1f" % v
    s = s[:-2] if s.endswith(".0") else s
    return "0" if s == "-0" else s


def _path(pts, td, loop=False):
    """Cubic curves through pts, tangent along the rank axis at each point
    (loop: pts are one cubic). Returns (d, the control point before the end)."""
    d = ["M%s %s" % (_f(pts[0][0]), _f(pts[0][1]))]
    if loop:
        d.append("C%s" % " ".join(_f(v) for p in pts[1:] for v in p))
        return " ".join(d), pts[2]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if td:
            m = (y1 + y2) / 2
            c = (x1, m, x2, m, x2, y2)
        else:
            m = (x1 + x2) / 2
            c = (m, y1, m, y2, x2, y2)
        d.append("C%s" % " ".join(_f(v) for v in c))
    return " ".join(d), (c[2], c[3])


def _arrow(tip, toward):
    """Arrowhead at tip, pointing away from the control point `toward`."""
    (x2, y2), (x1, y1) = tip, toward
    dx, dy = x2 - x1, y2 - y1
    n = (dx * dx + dy * dy) ** 0.5 or 1.0
    ux, uy = dx / n, dy / n
    bx, by = x2 - ux * ARROW, y2 - uy * ARROW
    p = [(x2, y2), (bx - uy * ARROW / 2, by + ux * ARROW / 2), (bx + uy * ARROW / 2, by - ux * ARROW / 2)]
    return " ".join("%s,%s" % (_f(a), _f(b)) for a, b in p)


def _text(lines, cx, cy, cls):
    top = cy - (len(lines) - 1) * LINE_H / 2
    spans = "".join('<tspan x="%s" y="%s">%s</tspan>' % (_f(cx), _f(top + i * LINE_H), html.escape(l))
                    for i, l in enumerate(lines))
    return '<text class="%s" text-anchor="middle" dominant-baseline="central">%s</text>' % (cls, spans)


def svg(lay, title):
    """Inline SVG for a Layout. `title` is the accessible name (required)."""
    td = lay.direction == "TD"
    w, h = lay.width, lay.height
    out = ['<svg class="flow-svg" xmlns="http://www.w3.org/2000/svg" role="img" '
           'viewBox="0 0 %s %s" width="%s" height="%s">' % (_f(w), _f(h), _f(w), _f(h)),
           "<title>%s</title>" % html.escape(title)]
    for r in lay.edges:
        cls = "flow-edge" + (" flow-dotted" if r.dotted else "") + (" flow-back" if r.back else "")
        d, toward = _path(r.points, td, r.loop)
        out.append('<g class="%s"><path d="%s"/><polygon points="%s"/></g>'
                   % (cls, d, _arrow(r.points[-1], toward)))
    for nid, lines, b in lay.nodes:
        out.append('<g class="flow-node"><rect x="%s" y="%s" width="%s" height="%s" rx="6"/>%s</g>'
                   % (_f(b.x), _f(b.y), _f(b.w), _f(b.h), _text(lines, b.x + b.w / 2, b.y + b.h / 2, "flow-label")))
    for r in lay.edges:
        if r.label_at:
            lw, lh = _text_size(r.label)
            cx, cy = r.label_at
            out.append('<g class="flow-elabel"><rect x="%s" y="%s" width="%s" height="%s" rx="3"/>%s</g>'
                       % (_f(cx - lw / 2 - 4), _f(cy - lh / 2 - 2), _f(lw + 8), _f(lh + 4),
                          _text(r.label, cx, cy, "flow-etext")))
    out.append("</svg>")
    return "".join(out)


def title_for(g):
    """Accessible name: every edge in declaration order, in words."""
    parts = []
    for e in g.edges:
        s = "%s to %s" % (g.nodes[e.src], g.nodes[e.dst])
        if e.label:
            s += " (%s)" % e.label
        parts.append(s)
    lone = [g.nodes[n] for n in g.nodes if not any(n in (e.src, e.dst) for e in g.edges)]
    parts += lone
    return "Flowchart: " + "; ".join(parts) + "."


def render(text, title=None):
    g = parse(text)
    return svg(layout(g), title or title_for(g))
