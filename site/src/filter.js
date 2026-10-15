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

  // Everything the UI needs for one buffer.
  //   options: what the menu lists (results, else suggestions)
  //   exact:   the entry named exactly by the query, or null
  //   mode:    "all" | "results" | "suggest" | "none"
  function search(buffer, entries) {
    var q = queryOf(buffer);
    var results = rank(q, entries);
    var exact = null;
    if (results.length && results[0].name === q) exact = results[0];
    if (q === "") return { query: q, mode: "all", options: results, exact: null, suggestions: [] };
    if (results.length) return { query: q, mode: "results", options: results, exact: exact, suggestions: [] };
    var sug = suggest(q, entries);
    return { query: q, mode: sug.length ? "suggest" : "none", options: sug, exact: null, suggestions: sug };
  }

  function listNames(list) {
    var n = list.map(function (e) { return "/" + e.name; });
    if (n.length <= 1) return n.join("");
    return n.slice(0, -1).join(", ") + " or " + n[n.length - 1];
  }

  // The line shown above suggestions (and announced) when nothing matches.
  function noMatchText(state) {
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
    var s = n + (n === 1 ? " matching command" : " matching commands");
    return state.exact ? s + ". Enter opens /" + state.exact.name : s;
  }

  // Index Tab/Enter act on: the highlighted option, else the first one
  // (never for the bare "/" list, where nothing is chosen yet).
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

  return {
    normalize: normalize,
    queryOf: queryOf,
    rank: rank,
    osa: osa,
    suggest: suggest,
    search: search,
    noMatchText: noMatchText,
    statusText: statusText,
    complete: complete,
    resolve: resolve,
    MAX_SUGGESTIONS: MAX_SUGGESTIONS
  };
});
