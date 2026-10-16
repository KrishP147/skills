/* Pure slash-input logic. Shared by the browser (window.SkillFilter) and
   node tests (CommonJS module.exports). No DOM access here.

   Entries: {name, kind, group, summary, aliases?}. The buffer always starts
   with "/"; everything after it is the free-typed query. */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SkillFilter = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var MAX_SUGGESTIONS = 3;
  // Tiers, best first. Ties inside a tier sort A-Z.
  var EXACT = 0, PREFIX = 1, WORD = 2, SUBSTRING = 3, ALIAS = 4;

  // Any raw input value -> a buffer that starts with exactly one "/".
  // Extra leading slashes are dropped, so typing "/pair" from "/" works.
  function normalize(value) {
    return "/" + String(value == null ? "" : value).replace(/^\/+/, "");
  }

  // The part after "/", lowercased, inner whitespace as "-".
  function queryOf(buffer) {
    return normalize(buffer).slice(1).trim().toLowerCase().replace(/\s+/g, "-");
  }

  function byName(a, b) {
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  }

  function tierOf(q, e) {
    var n = e.name;
    if (n === q) return EXACT;
    if (n.indexOf(q) === 0) return PREFIX;
    var parts = n.split("-");
    for (var i = 1; i < parts.length; i++) {
      if (parts.slice(i).join("-").indexOf(q) === 0) return WORD;
    }
    if (n.indexOf(q) !== -1) return SUBSTRING;
    // Aliases match from the start of the alias or one of its words, never
    // mid-word ("board" must not hit "onboarding").
    var al = e.aliases || [];
    for (var j = 0; j < al.length; j++) {
      if (("-" + al[j]).indexOf("-" + q) !== -1) return ALIAS;
    }
    return -1;
  }

  // Matching entries, best tier first, ties A-Z. Empty query: all, A-Z.
  function rank(query, entries) {
    var q = String(query || "");
    var hits = [];
    for (var i = 0; i < entries.length; i++) {
      var t = q === "" ? EXACT : tierOf(q, entries[i]);
      if (t >= 0) hits.push({ e: entries[i], t: t });
    }
    hits.sort(function (a, b) { return a.t - b.t || byName(a.e, b.e); });
    return hits.map(function (h) { return h.e; });
  }

  // Optimal string alignment distance (Damerau-Levenshtein, adjacent
  // transpositions, no substring edited twice).
  function osa(a, b) {
    var m = a.length, n = b.length, d = [], i, j;
    for (i = 0; i <= m; i++) { d[i] = [i]; }
    for (j = 1; j <= n; j++) d[0][j] = j;
    for (i = 1; i <= m; i++) {
      for (j = 1; j <= n; j++) {
        var cost = a.charAt(i - 1) === b.charAt(j - 1) ? 0 : 1;
        var v = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
        if (i > 1 && j > 1 && a.charAt(i - 1) === b.charAt(j - 2) && a.charAt(i - 2) === b.charAt(j - 1)) {
          v = Math.min(v, d[i - 2][j - 2] + 1);
        }
        d[i][j] = v;
      }
    }
    return d[m][n];
  }

  // Edit score against one term, 0 (same) .. 1+: the whole term, or (for a
  // partial query) the term's start. Normalized by length.
  function termScore(q, term) {
    var best = osa(q, term) / Math.max(q.length, term.length);
    if (term.length > q.length) {
      for (var k = q.length - 1; k <= q.length + 1; k++) {
        if (k < 3 || k > term.length) continue;
        var s = osa(q, term.slice(0, k)) / Math.max(q.length, k) + 0.05;
        if (s < best) best = s;
      }
    }
    return best;
  }

  var EDIT_LIMIT = 0.34;   // about 1 edit in 3 chars
  var SUMMARY_SCORE = 0.45;

  function tokens(text) {
    return String(text || "").toLowerCase().split(/[^a-z0-9]+/).filter(function (t) { return t.length >= 3; });
  }

  // Best (lowest) score for one entry, or Infinity when it is not a plausible
  // "did you mean". Terms: name, its dash parts, aliases. Then summary words.
  function suggestScore(q, e) {
    if (q.length < 2) return Infinity;
    var terms = [e.name].concat(e.name.split("-").filter(function (p) { return p.length >= 3; }), e.aliases || []);
    var best = Infinity;
    for (var i = 0; i < terms.length; i++) {
      var s = termScore(q, terms[i]);
      var d = osa(q, terms[i]);
      // One edit always counts once the query has 3+ chars.
      if (s <= EDIT_LIMIT || (d === 1 && q.length >= 3)) best = Math.min(best, s);
    }
    if (best === Infinity && q.length >= 3) {
      var tk = tokens(e.summary);
      for (var j = 0; j < tk.length; j++) {
        var t = tk[j];
        if (t === q || (q.length >= 4 && t.indexOf(q) === 0) ||
            (q.length >= 5 && osa(q, t) === 1)) {
          return SUMMARY_SCORE;
        }
      }
    }
    return best;
  }

  // Up to `max` closest entries, best first, ties A-Z.
  function suggest(query, entries, max) {
    var q = String(query || "");
    var lim = typeof max === "number" ? max : MAX_SUGGESTIONS;
    var scored = [];
    for (var i = 0; i < entries.length; i++) {
      var s = suggestScore(q, entries[i]);
      if (s !== Infinity) scored.push({ e: entries[i], s: s });
    }
    scored.sort(function (a, b) { return a.s - b.s || byName(a.e, b.e); });
    return scored.slice(0, lim).map(function (x) { return x.e; });
  }

  // Description search: the query's words against summary words. A word
  // matches a summary word exactly, or (4+ chars) as its prefix.
  var STOP = {};
  ("the and for with from that this into over are was can you your its not but all any how "
    + "what when use used").split(" ").forEach(function (w) { STOP[w] = 1; });

  function words(q) {
    return q.split(/[\s-]+/).filter(function (w) { return w; });
  }
  function hasWord(w, t) {
    return t === w || (w.length >= 4 && t.indexOf(w) === 0);
  }
  function summaryTokens(text) {
    return String(text || "").toLowerCase().split(/[^a-z0-9]+/).filter(function (t) { return t; });
  }
  // Content words count toward the threshold; short words and stopwords don't.
  function contentWords(ws) {
    return ws.filter(function (w) { return w.length >= 3 && !STOP[w]; });
  }
  // Words that must match: all of 1-2 content words, else at least half.
  function needed(n) { return n <= 2 ? n : Math.ceil(n / 2); }

  // Query words as a consecutive run of summary words (prefix rules apply).
  function hasPhrase(ws, tk) {
    for (var i = 0; i + ws.length <= tk.length; i++) {
      var ok = true;
      for (var j = 0; j < ws.length; j++) {
        if (!hasWord(ws[j], tk[i + j])) { ok = false; break; }
      }
      if (ok) return true;
    }
    return false;
  }

  // Entries whose summary matches enough query words. Best first: phrase,
  // then all content words, then most words; ties A-Z.
  function describe(query, entries) {
    var ws = words(String(query || ""));
    var cw = contentWords(ws);
    if (!cw.length) return [];
    var need = needed(cw.length);
    var hits = [];
    for (var i = 0; i < entries.length; i++) {
      var tk = summaryTokens(entries[i].summary);
      var n = 0;
      for (var k = 0; k < cw.length; k++) {
        for (var m = 0; m < tk.length; m++) {
          if (hasWord(cw[k], tk[m])) { n++; break; }
        }
      }
      if (n < need) continue;
      hits.push({ e: entries[i], p: ws.length > 1 && hasPhrase(ws, tk) ? 1 : 0, n: n });
    }
    hits.sort(function (a, b) { return b.p - a.p || b.n - a.n || byName(a.e, b.e); });
    return hits.map(function (h) { return h.e; });
  }

  // Everything the UI needs for one buffer.
  //   options: what the menu lists (results, else suggestions)
  //   exact:   the entry named exactly by the query, or null
  //   mode:    "all" | "results" | "desc" | "suggest" | "none"
  function search(buffer, entries) {
    var q = queryOf(buffer);
    var results = rank(q, entries);
    var exact = null;
    if (results.length && results[0].name === q) exact = results[0];
    if (q === "") return { query: q, mode: "all", options: results, exact: null, suggestions: [] };
    if (results.length) return { query: q, mode: "results", options: results, exact: exact, suggestions: [] };
    var sug = suggest(q, entries);
    // A close name typo ("gril-me") beats a description hit; summary-only
    // suggestions (score SUMMARY_SCORE) do not.
    var nameTypo = sug.length && suggestScore(q, sug[0]) < SUMMARY_SCORE;
    var found = nameTypo ? [] : describe(q, entries);
    if (found.length) return { query: q, mode: "desc", options: found, exact: null, suggestions: [] };
    return { query: q, mode: sug.length ? "suggest" : "none", options: sug, exact: null, suggestions: sug };
  }

  function listNames(list) {
    var n = list.map(function (e) { return "/" + e.name; });
    if (n.length <= 1) return n.join("");
    return n.slice(0, -1).join(", ") + " or " + n[n.length - 1];
  }

  // The line shown above suggestions (and announced) when nothing matches.
  function noMatchText(state) {
    if (state.mode === "desc") {
      return 'No command name matches "/' + words(state.query).join(" ") + '". Matched descriptions:';
    }
    if (state.mode === "suggest") {
      return 'No command matches "/' + state.query + '". Did you mean ' + listNames(state.suggestions) + "?";
    }
    if (state.mode === "none") return "No matches. Type / to see all.";
    return "";
  }

  // Screen-reader status for a state.
  function statusText(state) {
    if (state.mode === "suggest" || state.mode === "none") return noMatchText(state);
    var n = state.options.length;
    if (state.mode === "desc") return n + (n === 1 ? " command matches" : " commands match") + " by description";
    var s = n + (n === 1 ? " matching command" : " matching commands");
    return state.exact ? s + ". Enter opens /" + state.exact.name : s;
  }

  // Index Tab/Enter act on: the highlighted option, else the first one.
  // app.js highlights the first row whenever a list opens (bare "/" too), so
  // the fallback only covers callers that pass no index.
  function pick(state, active) {
    if (typeof active === "number" && active >= 0) return active;
    return state.options.length ? 0 : -1;
  }

  // Tab: fill the highlighted option. Returns the new buffer, or null when
  // that changes nothing (the caller then lets Tab move focus: no trap).
  function complete(buffer, state, active) {
    var e = state.options[pick(state, active)];
    if (!e) return null;
    var next = "/" + e.name;
    return next === normalize(buffer) ? null : next;
  }

  // Enter / click: the name to open, or null.
  function resolve(state, active) {
    var e = state.options[pick(state, active)];
    return e ? e.name : null;
  }

  // ---- Menu keyboard state (app.js applies the result to the DOM) ----
  // Menu: {buffer, state (from search), active (row index or -1), open}.
  // Functions return a new menu object, never mutate.

  // Row highlighted whenever a list is (re)shown: the first, bare "/" included,
  // so Enter/Tab always act on a visible highlight.
  function firstRow(state) { return state.options.length ? 0 : -1; }

  function withMenu(m, open, active) {
    return { buffer: m.buffer, state: m.state, active: active, open: open };
  }

  // Every path that opens a closed menu (click, "/", Enter, arrows) highlights
  // the first row. Already open: returns m itself (caller: nothing to do).
  function openMenu(m) {
    return m.open ? m : withMenu(m, true, firstRow(m.state));
  }

  // Up/Down on an open menu: wrap around; no highlight yet -> first or last.
  function move(m, delta) {
    var n = m.state.options.length;
    if (!n) return m;
    var a = m.active < 0 ? (delta > 0 ? 0 : n - 1) : (m.active + delta + n) % n;
    return withMenu(m, m.open, a);
  }

  // One keydown on the prompt. ev: {key, shift, alt, ctrl, meta, home
  // (home page, not detail), collapsed (selectionStart === selectionEnd)}.
  // IME composition is filtered by the caller. Returns {menu, preventDefault,
  // action, buffer?, name?}; action:
  //   null       nothing beyond preventDefault
  //   "complete" set the buffer to r.buffer (engaged)
  //   "clear"    set the buffer to "/" and close the menu
  //   "go"       open the page for r.name
  //   "home"     navigate to the home page
  //   "open" / "close"  menu shown / hidden: render and announce
  //   "move"     highlight moved: render, scroll it into view
  function key(m, ev) {
    var r = { menu: m, preventDefault: false, action: null };
    var opened;
    switch (ev.key) {
      case "Tab": {
        if (ev.shift || ev.alt || ev.ctrl || ev.meta || !m.open) return r;
        var c = complete(m.buffer, m.state, m.active);
        // Nothing to fill: let Tab move focus (no keyboard trap).
        if (c !== null) { r.preventDefault = true; r.action = "complete"; r.buffer = c; }
        return r;
      }
      case "ArrowDown":
      case "ArrowUp":
        if (!m.state.options.length) return r;
        r.preventDefault = true;
        opened = openMenu(m);
        // First press on a closed menu only opens it (row 0), no move.
        if (opened !== m) { r.menu = opened; r.action = "open"; }
        else { r.menu = move(m, ev.key === "ArrowDown" ? 1 : -1); r.action = "move"; }
        return r;
      case "Enter": {
        r.preventDefault = true;
        var name = m.open ? resolve(m.state, m.active) : null;
        if (name) { r.action = "go"; r.name = name; return r; }
        opened = openMenu(m);
        if (opened !== m) { r.menu = opened; r.action = "open"; }
        return r;
      }
      case "Escape":
        if (m.buffer !== "/") {
          r.preventDefault = true; r.action = "clear"; r.menu = withMenu(m, false, m.active);
        } else if (!ev.home) {
          // Detail page: Esc on a bare "/" goes home in one press.
          r.preventDefault = true; r.action = "home";
        } else if (m.open) {
          r.preventDefault = true; r.action = "close"; r.menu = withMenu(m, false, m.active);
        }
        return r;
      case "Backspace":
        // The leading "/" is undeletable.
        r.preventDefault = m.buffer === "/" && !!ev.collapsed;
        return r;
      case "/":
        // "/" on the bare prompt shows everything (nothing to type: it is there).
        if (m.buffer !== "/") return r;
        r.preventDefault = true;
        opened = openMenu(m);
        if (opened !== m) { r.menu = opened; r.action = "open"; }
        return r;
      case "ArrowLeft":
      case "Home":
        r.preventDefault = true; // caret stays at the end
        return r;
    }
    return r;
  }

  return {
    firstRow: firstRow,
    openMenu: openMenu,
    move: move,
    key: key,
    normalize: normalize,
    queryOf: queryOf,
    rank: rank,
    osa: osa,
    describe: describe,
    suggest: suggest,
    search: search,
    noMatchText: noMatchText,
    statusText: statusText,
    complete: complete,
    resolve: resolve,
    MAX_SUGGESTIONS: MAX_SUGGESTIONS
  };
});
