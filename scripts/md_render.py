"""Tiny Markdown -> HTML renderer for the skills site. Stdlib only.

Supports what the repo's READMEs use: ATX headings (with id slugs),
paragraphs, nested lists (ordered/unordered), fenced code, inline code,
links, bold/italic, pipe tables, blockquotes, horizontal rules.

A ```transcript fence renders as a Claude Code style session (line grammar:
parse_transcript); the tx_* helpers build the same markup for callers that
assemble a transcript themselves.

Safety: every piece of source text is HTML-escaped. Raw HTML in the
markdown is escaped, never passed through. Link URLs with a scheme other
than http/https/mailto (javascript:, data:, vbscript:, ...) are dropped and
only the link text is rendered.

Usage:
    r = Renderer(link_rewriter=fn)   # fn(url) -> href str, or None to drop
    html = r.render(markdown_text, heading_offset=0)
Share one Renderer across a page so heading ids stay unique.
"""
import html
import re

SAFE_SCHEMES = ("http", "https", "mailto")
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")
_FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([^`\s]*)[^`]*$")
_HEADING_RE = re.compile(r"^(#{1,6})(?:[ \t]+(.*?))?[ \t]*#*[ \t]*$")
_HR_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_LIST_RE = re.compile(r"^( *)([-*+]|\d{1,9}[.)])( +|$)(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_TX_TOOL_RE = re.compile(r"^⏺\s*([A-Za-z_][\w.:-]*)\((.*)\)\s*$")
_ESCAPABLE ="\\`*_{}[]()#+-.!|>~<\"'"


def esc(s):
    return html.escape(s, quote=True)


def safe_url(url):
    """Return url if its scheme is safe (or it has none), else None."""
    # Browsers ignore control chars and whitespace inside a scheme.
    probe = re.sub(r"[\x00-\x20\x7f]", "", html.unescape(url))
    m = _SCHEME_RE.match(probe)
    if m and m.group(1).lower() not in SAFE_SCHEMES:
        return None
    return url


def parse_transcript(text):
    """Line grammar of a ```transcript fence -> [(kind, head, lines)].

    '> text'          user prompt (kind "prompt", head = text)
    '⏺ Tool(args)'    tool call (kind "tool", head = (Tool, args)); the
                      indented '⎿ ...' line under it, and any further
                      indented lines, are its result
    '⏺ text'          reply (kind "reply")
    Indented lines continue the turn above; blank lines inside a turn are
    kept, trailing ones dropped. Any other unindented line is a plain
    "text" turn. Never raises."""
    turns = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        s = line.lstrip(" ")
        indent = len(line) - len(s)
        if not s:
            if turns:
                turns[-1][2].append("")
            continue
        if indent == 0 and (s == ">" or s.startswith("> ")):
            turns.append(["prompt", s[2:], []])
        elif indent == 0 and s.startswith("⏺"):
            m = _TX_TOOL_RE.match(s)
            if m:
                turns.append(["tool", (m.group(1), m.group(2)), []])
            else:
                turns.append(["reply", s[1:].strip(), []])
        elif indent > 0 and turns:
            if turns[-1][0] == "tool":
                # '⎿' marks the result; deeper lines keep their indent past it
                s = s[1:].strip() if s.startswith("⎿") else line[min(indent, 4):]
            turns[-1][2].append(s)
        else:
            turns.append(["text", s, []])
    out = []
    for kind, head, lines in turns:
        while lines and not lines[-1]:
            lines.pop()
        out.append((kind, head, lines))
    return out


def tx_prompt(text):
    return ('<div class="tx-prompt"><span class="tx-gt" aria-hidden="true">&gt;</span>'
            '<span class="tx-text">%s</span></div>' % esc(text))


def tx_reply(inner_html, block=False):
    """A reply row; inner_html is already rendered (escaped) markup."""
    return ('<div class="tx-reply%s"><span class="tx-dot" aria-hidden="true">⏺</span>'
            '<div class="tx-text">%s</div></div>' % (" tx-md" if block else "", inner_html))


def tx_tool(name, args, result_lines):
    """A collapsed tool call; result lines are literal text."""
    more = res = ""
    if result_lines:
        n = len(result_lines)
        more = ' <span class="tx-more">(+%d line%s)</span>' % (n, "" if n == 1 else "s")
        res = ('<div class="tx-res"><span class="tx-elbow" aria-hidden="true">⎿</span>'
               '<span class="tx-text">%s</span></div>' % esc("\n".join(result_lines)))
    return ('<details class="tx-tool"><summary><span class="tx-dot" aria-hidden="true">⏺</span>'
            '<span class="tx-name">%s</span>(<span class="tx-args">%s</span>)%s</summary>%s</details>'
            % (esc(name), esc(args), more, res))


def tx_wrap(parts):
    return '<div class="tx" role="group" aria-label="Example session">\n%s\n</div>' % "\n".join(parts)


def slugify(text):
    """GitHub-style heading slug: lowercase, drop punctuation, spaces -> '-'."""
    s = text.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def strip_inline(text):
    """Plain text of an inline markdown string (for slugs / descriptions)."""
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    t = re.sub(r"[`*]|(?<!\w)_|_(?!\w)", "", t)
    return t.strip()


class Renderer:
    def __init__(self, link_rewriter=None):
        self.link_rewriter = link_rewriter
        self.used_ids = {}

    # ---- ids -------------------------------------------------------------
    def unique_id(self, base):
        base = base or "section"
        n = self.used_ids.get(base)
        if n is None:
            self.used_ids[base] = 0
            return base
        n += 1
        while "%s-%d" % (base, n) in self.used_ids:
            n += 1
        self.used_ids[base] = n
        self.used_ids["%s-%d" % (base, n)] = 0
        return "%s-%d" % (base, n)

    # ---- blocks ----------------------------------------------------------
    def render(self, text, heading_offset=0):
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
        text = text.expandtabs(4)
        return "\n".join(self._blocks(text.split("\n"), heading_offset))

    def _blocks(self, lines, hoff):
        out = []
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            m = _FENCE_RE.match(line)
            if m and len(m.group(1)) <= 3:
                i = self._fence(lines, i, m, out)
                continue
            m = _HEADING_RE.match(line.lstrip(" ")) if len(line) - len(line.lstrip(" ")) <= 3 else None
            if m:
                level = min(6, len(m.group(1)) + hoff)
                content = m.group(2) or ""
                hid = self.unique_id(slugify(strip_inline(content)))
                out.append('<h%d id="%s">%s</h%d>' % (level, esc(hid), self.inline(content), level))
                i += 1
                continue
            if _HR_RE.match(line):
                out.append("<hr>")
                i += 1
                continue
            if line.lstrip(" ").startswith(">") and len(line) - len(line.lstrip(" ")) <= 3:
                i = self._blockquote(lines, i, hoff, out)
                continue
            if _LIST_RE.match(line) and len(_LIST_RE.match(line).group(1)) <= 3:
                i = self._list(lines, i, hoff, out)
                continue
            if "|" in line and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]) and "-" in lines[i + 1]:
                i = self._table(lines, i, out)
                continue
            i = self._paragraph(lines, i, out)
        return out

    def _fence(self, lines, i, m, out):
        indent, marker, lang = len(m.group(1)), m.group(2), m.group(3)
        body = []
        i += 1
        while i < len(lines):
            s = lines[i]
            stripped = s.strip()
            if stripped.startswith(marker[0] * len(marker)) and set(stripped) == {marker[0]}:
                i += 1
                break
            # Drop up to `indent` leading spaces, like CommonMark.
            k = 0
            while k < indent and k < len(s) and s[k] == " ":
                k += 1
            body.append(s[k:])
            i += 1
        if lang == "transcript":
            out.append(self.transcript("\n".join(body)))
            return i
        cls = ' class="language-%s"' % esc(lang) if lang else ""
        code = "\n".join(body)
        out.append("<pre><code%s>%s</code></pre>" % (cls, esc(code + ("\n" if body else ""))))
        return i

    def transcript(self, text):
        """HTML for a ```transcript fence body (grammar: parse_transcript).
        Prompts and tool output stay literal; replies get inline markdown."""
        parts = []
        for kind, head, lines in parse_transcript(text):
            if kind == "prompt":
                parts.append(tx_prompt("\n".join([head] + lines)))
            elif kind == "tool":
                parts.append(tx_tool(head[0], head[1], lines))
            elif kind == "reply":
                parts.append(tx_reply("\n".join(self.inline(l) for l in [head] + lines)))
            else:
                parts.append('<div class="tx-line">%s</div>' % esc("\n".join([head] + lines)))
        return tx_wrap(parts)

    def _blockquote(self, lines, i, hoff, out):
        inner = []
        while i < len(lines):
            s = lines[i].lstrip(" ")
            if s.startswith(">"):
                s = s[1:]
                inner.append(s[1:] if s.startswith(" ") else s)
                i += 1
            elif lines[i].strip() and inner and inner[-1].strip():
                inner.append(lines[i])  # lazy continuation
                i += 1
            else:
                break
        out.append("<blockquote>\n%s\n</blockquote>" % "\n".join(self._blocks(inner, hoff)))
        return i

    def _list(self, lines, i, hoff, out):
        first = _LIST_RE.match(lines[i])
        ordered = first.group(2)[-1] in ".)"
        base_indent = len(first.group(1))
        items = []
        loose = False
        n = len(lines)
        while i < n:
            m = _LIST_RE.match(lines[i])
            if not m or len(m.group(1)) != base_indent or (m.group(2)[-1] in ".)") != ordered:
                break
            content_indent = len(m.group(1)) + len(m.group(2)) + max(1, min(len(m.group(3)), 4))
            item = [m.group(4)]
            i += 1
            blank_run = False
            while i < n:
                s = lines[i]
                if not s.strip():
                    blank_run = True
                    item.append("")
                    i += 1
                    continue
                ind = len(s) - len(s.lstrip(" "))
                if ind >= content_indent or (ind > base_indent and not blank_run):
                    item.append(s[min(ind, content_indent):])
                    blank_run = False
                    i += 1
                    continue
                if not blank_run and not _LIST_RE.match(s) and ind > base_indent - 1 and not self._starts_block(s):
                    item.append(s.lstrip(" "))  # lazy paragraph continuation
                    i += 1
                    continue
                break
            while item and not item[-1].strip():
                item.pop()
            if blank_run and i < n and _LIST_RE.match(lines[i]):
                loose = True
            items.append(item)
        tag = "ol" if ordered else "ul"
        start = ""
        if ordered:
            num = int(first.group(2)[:-1])
            if num != 1:
                start = ' start="%d"' % num
        parts = ["<%s%s>" % (tag, start)]
        for item in items:
            blocks = self._blocks(item, hoff)
            if not loose and blocks and blocks[0].startswith("<p>"):
                blocks[0] = blocks[0][3:-4]
            parts.append("<li>%s</li>" % "\n".join(blocks))
        parts.append("</%s>" % tag)
        out.append("\n".join(parts))
        return i

    @staticmethod
    def _starts_block(s):
        t = s.lstrip(" ")
        return t.startswith(("#", ">", "```", "~~~")) or bool(_HR_RE.match(s))

    def _table(self, lines, i, out):
        header = self._cells(lines[i])
        aligns = []
        for c in self._cells(lines[i + 1]):
            c = c.strip()
            if c.startswith(":") and c.endswith(":"):
                aligns.append("center")
            elif c.endswith(":"):
                aligns.append("right")
            elif c.startswith(":"):
                aligns.append("left")
            else:
                aligns.append(None)
        i += 2
        rows = []
        while i < len(lines) and lines[i].strip() and "|" in lines[i]:
            rows.append(self._cells(lines[i]))
            i += 1
        ncol = len(header)

        def cell(tag, text, k):
            a = aligns[k] if k < len(aligns) else None
            style = ' style="text-align:%s"' % a if a else ""
            return "<%s%s>%s</%s>" % (tag, style, self.inline(text.strip()), tag)

        parts = ['<div class="table-wrap"><table>', "<thead><tr>"]
        parts += [cell("th", h, k) for k, h in enumerate(header)]
        parts.append("</tr></thead>")
        if rows:
            parts.append("<tbody>")
            for r in rows:
                r = (r + [""] * ncol)[:ncol]
                parts.append("<tr>%s</tr>" % "".join(cell("td", c, k) for k, c in enumerate(r)))
            parts.append("</tbody>")
        parts.append("</table></div>")
        out.append("".join(parts))
        return i

    @staticmethod
    def _cells(line):
        s = line.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|") and not s.endswith("\\|"):
            s = s[:-1]
        cells, cur, in_code, k = [], [], False, 0
        while k < len(s):
            ch = s[k]
            if ch == "\\" and k + 1 < len(s) and s[k + 1] == "|":
                cur.append("|")
                k += 2
                continue
            if ch == "`":
                in_code = not in_code
            if ch == "|" and not in_code:
                cells.append("".join(cur))
                cur = []
            else:
                cur.append(ch)
            k += 1
        cells.append("".join(cur))
        return cells

    def _paragraph(self, lines, i, out):
        buf = []
        while i < len(lines):
            s = lines[i]
            if not s.strip():
                break
            if buf and (self._starts_block(s) or (_LIST_RE.match(s) and len(_LIST_RE.match(s).group(1)) <= 3)):
                break
            buf.append(s.strip())
            i += 1
        out.append("<p>%s</p>" % self.inline("\n".join(buf)))
        return i

    # ---- inline ----------------------------------------------------------
    def inline(self, text):
        slots = []

        def hold(fragment):
            slots.append(fragment)
            return "\x00%d\x00" % (len(slots) - 1)

        out = []
        k = 0
        n = len(text)
        while k < n:
            ch = text[k]
            if ch == "\\" and k + 1 < n and text[k + 1] in _ESCAPABLE:
                out.append(hold(esc(text[k + 1])))
                k += 2
                continue
            if ch == "`":
                run = 1
                while k + run < n and text[k + run] == "`":
                    run += 1
                close = text.find("`" * run, k + run)
                while close != -1 and close + run < n and text[close + run] == "`":
                    close = text.find("`" * run, close + run + 1)
                if close != -1:
                    code = text[k + run:close].replace("\n", " ")
                    if code.startswith(" ") and code.endswith(" ") and code.strip():
                        code = code[1:-1]
                    out.append(hold("<code>%s</code>" % esc(code)))
                    k = close + run
                    continue
                out.append("`" * run)
                k += run
                continue
            if ch == "<":
                m = re.match(r"<((?:https?|mailto):[^\s<>]+)>", text[k:])
                if m:
                    url = m.group(1)
                    out.append(hold('<a href="%s">%s</a>' % (esc(self._href(url) or url), esc(url))))
                    k += m.end()
                    continue
            if ch == "[" or (ch == "!" and k + 1 < n and text[k + 1] == "["):
                res = self._link(text, k + (1 if ch == "!" else 0))
                if res:
                    label, url, title, end = res
                    inner = self.inline(label)
                    href = self._href(url)
                    if href is None:
                        out.append(hold(inner))
                    else:
                        t = ' title="%s"' % esc(title) if title else ""
                        out.append(hold('<a href="%s"%s>%s</a>' % (esc(href), t, inner)))
                    k = end
                    continue
            out.append(ch)
            k += 1
        s = esc("".join(out))
        s = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)", r"<em>\1</em>", s)
        s = re.sub(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])", r"<em>\1</em>", s)
        # Slots can nest (link label holding code): restore until stable.
        for _ in range(4):
            s2 = re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], s)
            if s2 == s:
                break
            s = s2
        return s

    def _href(self, url):
        url = url.strip()
        if safe_url(url) is None:
            return None
        if self.link_rewriter is not None:
            url = self.link_rewriter(url)
            if url is None or safe_url(url) is None:
                return None
        return url

    @staticmethod
    def _link(text, k):
        """Parse [label](url "title") starting at text[k] == '['."""
        depth = 0
        j = k
        n = len(text)
        while j < n:
            c = text[j]
            if c == "\\":
                j += 2
                continue
            if c == "`":
                close = text.find("`", j + 1)
                j = close + 1 if close != -1 else j + 1
                continue
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= n or j + 1 >= n or text[j + 1] != "(":
            return None
        label = text[k + 1:j]
        p = j + 2
        depth = 1
        q = p
        while q < n:
            c = text[q]
            if c == "\\":
                q += 2
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            q += 1
        if q >= n:
            return None
        dest = text[p:q].strip()
        title = ""
        m = re.match(r'^(\S+)\s+"(.*)"$', dest) or re.match(r"^(\S+)\s+'(.*)'$", dest)
        if m:
            dest, title = m.group(1), m.group(2)
        if dest.startswith("<") and dest.endswith(">"):
            dest = dest[1:-1]
        if " " in dest:
            return None
        return label, dest, title, q + 1
