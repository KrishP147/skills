// Dependency-free: node --test site/test/filter.test.mjs
// The "every real name" tests load nav data from scripts/build_site.py (same
// code the build embeds), so they cannot drift from the real catalog.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const F = require("../src/filter.js");
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

const e = (name, summary = "", extra = {}) => ({
  name, kind: extra.kind || "skill", group: extra.group || "core", summary, ...extra,
});
const FIX = [
  e("pair", "Run one task in a worktree."),
  e("planner", "Picks the next issue.", { kind: "agent", group: "agents" }),
  e("pr-watch", "Watch open PRs: read bot and human review threads."),
  e("progress-report", "Write a short progress report."),
  e("grilling", "Grill the user."),
  e("grill-me", "A relentless interview."),
  e("handoff", "Compact the conversation.", { aliases: ["compact"] }),
  e("handoff-auto", "Write a handoff document."),
  e("session-handoff", "End a session."),
  e("next", "Show the next task.", { group: "kanban" }),
  e("sitrep", "Live status.", { aliases: ["status"] }),
];
const names = (list) => list.map((x) => x.name);
const opts = (buf, data = FIX) => names(F.search(buf, data).options);

function loadReal() {
  const code = [
    "import sys, os",
    "sys.path.insert(0, os.path.join(os.getcwd(), 'scripts'))",
    "import build_site, lint, site_detail",
    "r = lint.repo_root()",
    "sys.stdout.buffer.write(build_site.nav_data(build_site.collect(r), site_detail.load_meta(r)).encode('utf-8'))",
  ].join("\n");
  for (const py of ["python3", "python"]) {
    try {
      const out = execFileSync(py, ["-c", code], { cwd: ROOT, encoding: "utf-8", stdio: ["ignore", "pipe", "pipe"] });
      return JSON.parse(out);
    } catch (err) {
      if (err.code !== "ENOENT" && !/not found|was not found|9009/i.test(String(err.message))) throw err;
    }
  }
  throw new Error("python not found: needed to load real nav data");
}
const REAL = loadReal();

test("buffer always starts with exactly one '/'", () => {
  assert.equal(F.normalize(""), "/");
  assert.equal(F.normalize("/"), "/");
  assert.equal(F.normalize("pair"), "/pair");
  assert.equal(F.normalize("//pair"), "/pair");
  assert.equal(F.normalize(null), "/");
  assert.equal(F.queryOf("/Pair "), "pair");
  assert.equal(F.queryOf("/pr watch"), "pr-watch");
});

test("free typing: any text is a valid buffer (no rejection)", () => {
  for (const b of ["/zzzz", "/x", "/!!", "/pairx"]) {
    const s = F.search(b, FIX);
    assert.ok(["results", "desc", "suggest", "none"].includes(s.mode), b);
  }
});

test("bare '/' lists everything A-Z with the first highlighted (D2)", () => {
  const s = F.search("/", FIX);
  assert.equal(s.mode, "all");
  assert.deepEqual(names(s.options), names(FIX).slice().sort());
  assert.equal(F.resolve(s, -1), names(s.options)[0]);
  assert.equal(F.complete("/", s, -1), "/" + names(s.options)[0]);
  assert.equal(F.resolve(s, 2), names(s.options)[2]);
});

test("tiers: exact > prefix > word-boundary prefix > substring > alias", () => {
  assert.deepEqual(opts("/handoff"), ["handoff", "handoff-auto", "session-handoff"]);
  // prefixes A-Z, then substring (sitrep); aliases never match mid-word
  assert.deepEqual(opts("/p"), ["pair", "planner", "pr-watch", "progress-report", "sitrep"]);
  assert.deepEqual(opts("/pact"), []);
  // word-boundary prefix before plain substring
  assert.deepEqual(opts("/re"), ["progress-report", "sitrep"]);
  assert.deepEqual(opts("/report"), ["progress-report"]);
  assert.deepEqual(opts("/ill"), ["grill-me", "grilling"]);
  // alias last, after any name hit
  assert.deepEqual(opts("/stat"), ["sitrep"]);
  assert.deepEqual(opts("/comp"), ["handoff"]);
});

test("ties sort A-Z inside a tier", () => {
  assert.deepEqual(opts("/gri"), ["grill-me", "grilling"]);
  assert.deepEqual(opts("/h"), ["handoff", "handoff-auto", "session-handoff", "pr-watch"]);
});

test("exact match is flagged for the '↵ to open' hint", () => {
  assert.equal(F.search("/pair", FIX).exact.name, "pair");
  assert.equal(F.search("/pai", FIX).exact, null);
  assert.match(F.statusText(F.search("/pair", FIX)), /Enter opens \/pair/);
});

test("osa distance", () => {
  assert.equal(F.osa("", ""), 0);
  assert.equal(F.osa("abc", ""), 3);
  assert.equal(F.osa("nxet", "next"), 1);
  assert.equal(F.osa("pair", "piar"), 1);
  assert.equal(F.osa("kitten", "sitting"), 3);
  assert.equal(F.osa("ca", "abc"), 3); // OSA, not full Damerau
});

test("typos and transpositions suggest the right name", () => {
  const s = F.search("/nxet", FIX);
  assert.equal(s.mode, "suggest");
  assert.equal(s.options[0].name, "next");
  assert.equal(F.search("/hnadoff", FIX).options[0].name, "handoff");
  assert.equal(F.search("/grilign", FIX).options[0].name, "grilling");
  assert.equal(F.search("/sitrpe", FIX).options[0].name, "sitrep");
  assert.equal(F.search("/sesion-handof", FIX).options[0].name, "session-handoff");
});

test("description fallback: /review -> /pr-watch", () => {
  const s = F.search("/review", FIX);
  assert.equal(s.mode, "desc");
  assert.deepEqual(names(s.options), ["pr-watch"]);
  assert.equal(F.noMatchText(s), 'No command name matches "/review". Matched descriptions:');
  assert.equal(F.statusText(s), "1 command matches by description");
  assert.equal(F.resolve(s, -1), "pr-watch");
  assert.equal(F.complete("/review", s, -1), "/pr-watch");
});

test("description fallback: /run one task -> pair first (FIX and REAL)", () => {
  for (const data of [FIX, REAL]) {
    const s = F.search("/run one task", data);
    assert.equal(s.mode, "desc");
    assert.equal(s.options[0].name, "pair");
    assert.equal(F.noMatchText(s), 'No command name matches "/run one task". Matched descriptions:');
    assert.match(F.statusText(s), /^\d+ commands? match(es)? by description$/);
  }
  assert.equal(F.search("/task one run", FIX).options[0].name, "pair");
  assert.equal(F.search("/task one run", REAL).options[0].name, "pair");
});

test("description fallback: real summary phrases surface their entry", () => {
  let checked = 0;
  const picked = REAL.filter((x) => !x.aliases && tokensOf(x.summary).length >= 4).slice(0, 5);
  assert.ok(picked.length >= 3);
  for (const x of picked) {
    const tk = tokensOf(x.summary);
    const phrase = tk.slice(1, 4).join(" ");
    const s = F.search("/" + phrase, REAL);
    if (s.mode === "results") continue; // phrase also hit a name: tiers win
    assert.equal(s.mode, "desc", phrase);
    assert.ok(names(s.options).includes(x.name), phrase + " -> " + x.name);
    checked++;
  }
  assert.ok(checked >= 3, "checked " + checked);
});

test("description ranking: phrase > all words > most words, ties A-Z", () => {
  const data = [e("zed", "Alpha beta gamma delta."), e("aaa", "Gamma alpha beta delta."),
    e("bbb", "Gamma beta delta."), e("ccc", "Alpha beta only.")];
  // phrase only in zed; aaa/bbb hold both words apart; A-Z would put aaa first
  assert.deepEqual(names(F.describe("gamma delta", data)), ["zed", "aaa", "bbb"]);
  // zed phrase; aaa all 4 words; bbb 3; ccc 2 (half is enough for 4 words)
  assert.deepEqual(names(F.describe("alpha beta gamma delta", data)), ["zed", "aaa", "bbb", "ccc"]);
});
function tokensOf(t) { return t.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean); }

test("name matches never become description results", () => {
  for (const b of ["/pair", "/watch", "/handoff", "/status", "/pr watch"]) {
    assert.notEqual(F.search(b, FIX).mode, "desc", b);
  }
  // "next" is a name and a summary word (planner): the name tier wins alone.
  const s = F.search("/next", FIX);
  assert.equal(s.mode, "results");
  assert.deepEqual(names(s.options), ["next"]);
  assert.equal(F.search("/pr watch", FIX).options[0].name, "pr-watch");
});

test("description search ignores stopwords and short words", () => {
  for (const b of ["/the", "/a b", "/and the", "/in of"]) {
    assert.notEqual(F.search(b, FIX).mode, "desc", b);
    assert.deepEqual(F.describe(b.slice(1), FIX), [], b);
  }
});

test("did-you-mean caps at 3, lists them, Tab/Enter take first", () => {
  const data = ["aaab", "aaac", "aaad", "aaae"].map((n) => e(n));
  const s = F.search("/aaaz", data);
  assert.equal(s.mode, "suggest");
  assert.equal(s.options.length, F.MAX_SUGGESTIONS);
  assert.deepEqual(names(s.options), ["aaab", "aaac", "aaad"]);
  assert.equal(F.noMatchText(s), 'No command matches "/aaaz". Did you mean /aaab, /aaac or /aaad?');
  assert.equal(F.resolve(s, -1), "aaab");
  assert.equal(F.complete("/aaaz", s, -1), "/aaab");
  assert.equal(F.resolve(s, 2), "aaad");
});

test("nonsense and empty", () => {
  for (const b of ["/zzzz", "/qwxv", "/zq", "/!!"]) {
    const s = F.search(b, FIX);
    assert.equal(s.mode, "none", b);
    assert.deepEqual(s.options, [], b);
    assert.equal(F.noMatchText(s), "No matches. Type / to see all.", b);
    assert.equal(F.resolve(s, -1), null, b);
    assert.equal(F.complete(b, s, -1), null, b);
  }
  assert.equal(F.search("/", []).options.length, 0);
  assert.equal(F.search("/zzzz", REAL).mode, "none");
  for (const b of ["/qwxv", "/zq", "/!!"]) assert.equal(F.search(b, REAL).mode, "none", b);
  assert.equal(F.search("/nxet", REAL).options[0].name, "next");
  assert.equal(F.search("/nxet", REAL).mode, "suggest");
});

test("tab fills the highlighted name; null when nothing changes", () => {
  const s = F.search("/pa", FIX);
  assert.equal(F.complete("/pa", s, 0), "/pair");
  assert.equal(F.complete("/pair", F.search("/pair", FIX), 0), null);
  const h = F.search("/handoff", FIX);
  assert.equal(F.complete("/handoff", h, 2), "/session-handoff");
  assert.equal(F.resolve(h, 1), "handoff-auto");
  assert.equal(F.resolve(h, 99), null);
});

// ---- Menu keyboard reducer (F.key). Spec: site/README.md "Keys" + "Back home".
const menu = (buffer, extra = {}) => {
  const state = F.search(buffer, FIX);
  return { buffer, state, active: F.firstRow(state), open: false, ...extra };
};
const press = (m, key, ev = {}) => F.key(m, { key, home: true, collapsed: true, ...ev });

test("menu: firstRow is 0 with options, -1 without", () => {
  assert.equal(F.firstRow(F.search("/", FIX)), 0);
  assert.equal(F.firstRow(F.search("/zzzzzz", FIX)), -1);
});

test("menu: openMenu highlights row 0, returns same object when already open", () => {
  const m = menu("/", { active: 5 });
  const o = F.openMenu(m);
  assert.deepEqual([o.open, o.active], [true, 0]);
  assert.equal(m.open, false, "no mutation");
  const again = F.openMenu(o);
  assert.equal(again, o);
  const none = F.openMenu(menu("/zzzzzz"));
  assert.deepEqual([none.open, none.active], [true, -1]);
});

test("menu: move wraps both ways; no highlight -> first/last; no options -> same", () => {
  const n = FIX.length;
  const m = menu("/", { open: true });
  assert.equal(F.move(m, 1).active, 1);
  assert.equal(F.move(m, -1).active, n - 1, "up from 0 wraps to last");
  assert.equal(F.move({ ...m, active: n - 1 }, 1).active, 0, "down from last wraps to 0");
  assert.equal(F.move({ ...m, active: -1 }, 1).active, 0);
  assert.equal(F.move({ ...m, active: -1 }, -1).active, n - 1);
  const empty = menu("/zzzzzz", { open: true });
  assert.equal(F.move(empty, 1), empty);
});

test("key: every open path (/, Enter, Down, Up) highlights row 0 (#76, D2, #48)", () => {
  for (const k of ["/", "Enter", "ArrowDown", "ArrowUp"]) {
    const r = press(menu("/", { active: 3 }), k);
    assert.equal(r.action, "open", k);
    assert.equal(r.preventDefault, true, k);
    assert.deepEqual([r.menu.open, r.menu.active], [true, 0], k);
  }
  // Typed text, closed menu: Enter and arrows open on row 0 too.
  for (const k of ["Enter", "ArrowDown", "ArrowUp"]) {
    const r = press(menu("/gri", { active: 1 }), k);
    assert.deepEqual([r.action, r.menu.open, r.menu.active], ["open", true, 0], k);
  }
});

test("key: arrows on an open menu move with wraparound", () => {
  const m = menu("/gri", { open: true }); // grill-me, grilling
  let r = press(m, "ArrowDown");
  assert.deepEqual([r.action, r.preventDefault, r.menu.active, r.menu.open], ["move", true, 1, true]);
  r = press(r.menu, "ArrowDown");
  assert.equal(r.menu.active, 0, "wraps to first");
  r = press(r.menu, "ArrowUp");
  assert.equal(r.menu.active, 1, "wraps to last");
});

test("key: arrows with no options do nothing, no preventDefault", () => {
  for (const open of [false, true]) {
    const m = menu("/zzzzzz", { open });
    for (const k of ["ArrowDown", "ArrowUp"]) {
      const r = press(m, k);
      assert.deepEqual([r.action, r.preventDefault, r.menu], [null, false, m], k);
    }
  }
});

test("key: Tab completes the highlighted name", () => {
  const r = press(menu("/pa", { open: true }), "Tab");
  assert.deepEqual([r.action, r.buffer, r.preventDefault], ["complete", "/pair", true]);
  const h = press(menu("/handoff", { open: true, active: 2 }), "Tab");
  assert.equal(h.buffer, "/session-handoff");
});

test("key: Tab with nothing to fill, closed menu or a modifier: no trap", () => {
  const cases = [
    [menu("/pair", { open: true }), {}],
    [menu("/zzzzzz", { open: true }), {}],
    [menu("/pa"), {}],
    [menu("/pa", { open: true }), { shift: true }],
    [menu("/pa", { open: true }), { alt: true }],
    [menu("/pa", { open: true }), { ctrl: true }],
    [menu("/pa", { open: true }), { meta: true }],
  ];
  for (const [m, ev] of cases) {
    const r = press(m, "Tab", ev);
    assert.deepEqual([r.action, r.preventDefault, r.menu], [null, false, m], m.buffer + JSON.stringify(ev));
  }
});

test("key: Enter on an open menu goes to the highlighted name", () => {
  const r = press(menu("/handoff", { open: true, active: 1 }), "Enter");
  assert.deepEqual([r.action, r.name, r.preventDefault], ["go", "handoff-auto", true]);
  const first = press(menu("/", { open: true }), "Enter");
  assert.deepEqual([first.action, first.name], ["go", "grill-me"]);
});

test("key: Enter with nothing to open still prevents default", () => {
  const m = menu("/zzzzzz", { open: true });
  const r = press(m, "Enter");
  assert.deepEqual([r.action, r.preventDefault, r.menu], [null, true, m]);
  const closed = press(menu("/zzzzzz"), "Enter");
  assert.deepEqual([closed.action, closed.preventDefault, closed.menu.open], ["open", true, true]);
});

test("key: Esc with text clears to '/' and closes (home and detail)", () => {
  for (const home of [true, false]) {
    const r = press(menu("/gri", { open: true }), "Escape", { home });
    assert.deepEqual([r.action, r.preventDefault, r.menu.open], ["clear", true, false]);
  }
});

test("key: Esc on bare '/': detail goes home in one press, open or not", () => {
  for (const open of [false, true]) {
    const r = press(menu("/", { open }), "Escape", { home: false });
    assert.deepEqual([r.action, r.preventDefault], ["home", true]);
  }
});

test("key: Esc on bare '/' at home closes an open menu, never navigates", () => {
  const r = press(menu("/", { open: true }), "Escape", { home: true });
  assert.deepEqual([r.action, r.preventDefault, r.menu.open], ["close", true, false]);
  const m = menu("/");
  const idle = press(m, "Escape", { home: true });
  assert.deepEqual([idle.action, idle.preventDefault, idle.menu], [null, false, m]);
});

test("key: Backspace blocked only on bare '/' with a collapsed selection", () => {
  assert.equal(press(menu("/"), "Backspace", { collapsed: true }).preventDefault, true);
  assert.equal(press(menu("/"), "Backspace", { collapsed: false }).preventDefault, false);
  assert.equal(press(menu("/pa"), "Backspace", { collapsed: true }).preventDefault, false);
  assert.equal(press(menu("/"), "Backspace").action, null);
});

test("key: '/' opens only on the bare prompt; already open does nothing more", () => {
  const typed = press(menu("/pa"), "/");
  assert.deepEqual([typed.action, typed.preventDefault, typed.menu.open], [null, false, false]);
  const m = menu("/", { open: true, active: 4 });
  const r = press(m, "/");
  assert.deepEqual([r.action, r.preventDefault, r.menu], [null, true, m]);
});

test("key: ArrowLeft/Home keep the caret at the end; other keys pass through", () => {
  for (const k of ["ArrowLeft", "Home"]) {
    const r = press(menu("/pa"), k);
    assert.deepEqual([r.action, r.preventDefault], [null, true], k);
  }
  for (const k of ["a", "ArrowRight", "End", "Delete"]) {
    const m = menu("/pa");
    const r = press(m, k);
    assert.deepEqual([r.action, r.preventDefault, r.menu], [null, false, m], k);
  }
});

test("status text counts matches", () => {
  assert.equal(F.statusText(F.search("/gri", FIX)), "2 matching commands");
  assert.equal(F.statusText(F.search("/sitr", FIX)), "1 matching command");
});

test("real nav data shape: kind derived from group, aliases optional", () => {
  assert.ok(REAL.length > 10);
  for (const x of REAL) {
    assert.deepEqual(Object.keys(x).filter((k) => k !== "aliases"), ["name", "kind", "group", "summary"], x.name);
    assert.equal(x.kind, { agents: "agent", hooks: "hook", pages: "page" }[x.group] || "skill", x.name);
    if ("aliases" in x) assert.ok(Array.isArray(x.aliases) && x.aliases.length, x.name);
  }
  assert.ok(F.search("/review", REAL).options.some((x) => x.name === "pr-watch"));
});

test("hooks are in the real nav data and searchable", () => {
  const hooks = REAL.filter((x) => x.kind === "hook").map((x) => x.name).sort();
  assert.deepEqual(hooks, ["smartzone", "spend-guard"]);
  assert.ok(!REAL.some((x) => x.name === "guard-git"), "agent hook stays out");
  // prefix, mid-word fragment, 1-2 char typos (the per-name loop below covers more)
  for (const [buf, name] of [["/smart", "smartzone"], ["/spend-gu", "spend-guard"], ["/artzon", "smartzone"],
    ["/end-gua", "spend-guard"], ["/smratzone", "smartzone"], ["/spend-gaurd", "spend-guard"],
    ["/smartzn", "smartzone"], ["/spnd-gurd", "spend-guard"], ["/smart-zone", "smartzone"]]) {
    assert.ok(names(F.search(buf, REAL).options).includes(name), buf + " -> " + name);
  }
});

test("site pages in the real nav data: /map and /workflows open", () => {
  const pages = REAL.filter((x) => x.kind === "page");
  assert.deepEqual(names(pages), ["map", "workflows"]);
  assert.equal(pages[0].group, "pages");
  const st = F.search("/map", REAL);
  assert.equal(st.exact && st.exact.name, "map");
  assert.equal(F.resolve(st), "map");
  assert.equal(F.complete("/ma", F.search("/ma", REAL)), "/manager", "prefix A-Z keeps entries first");
  assert.ok(names(F.search("/ma", REAL).options).includes("map"));
  for (const typo of ["/mpa", "/amp", "/mqp"]) assert.equal(F.search(typo, REAL).options[0].name, "map", typo);
  const wf = F.search("/workflows", REAL);
  assert.equal(wf.exact && wf.exact.name, "workflows");
  assert.equal(F.resolve(wf), "workflows");
  assert.ok(names(F.search("/workf", REAL).options).includes("workflows"));
  for (const typo of ["/wrokflows", "/workflow", "/worklfows"]) {
    assert.ok(names(F.search(typo, REAL).options).includes("workflows"), typo);
  }
});

function surfaces(buf, name) {
  return names(F.search(buf, REAL).options).includes(name);
}
function swap(s, i) {
  return s.slice(0, i) + s[i + 1] + s[i] + s.slice(i + 2);
}

// Entries only: a 3-letter page name ("map") has no room for the deletion
// typo ("mp" is inside "implementer"); its own test above covers it.
for (const { name } of REAL.filter((x) => x.kind !== "page")) {
  test(`every name surfaces: /${name}`, () => {
    assert.equal(opts("/" + name, REAL)[0], name, "exact first");
    const pre = name.slice(0, Math.max(2, Math.ceil(name.length / 2)));
    assert.ok(surfaces("/" + pre, name), "prefix " + pre);
    const mid = name.slice(1, -1);
    assert.ok(surfaces("/" + mid, name), "mid fragment " + mid);
    // 1-char typos: adjacent transposition and deletion inside the name.
    const i = Math.floor(name.length / 2) - 1;
    const t1 = name[i] === name[i + 1] ? swap(name, i - 1) : swap(name, i);
    assert.ok(surfaces("/" + t1, name), "transposition " + t1);
    const del = name.slice(0, i + 1) + name.slice(i + 2);
    assert.ok(surfaces("/" + del, name), "deletion " + del);
    const sub = name.slice(0, i + 1) + "q" + name.slice(i + 2);
    assert.ok(surfaces("/" + sub, name), "substitution " + sub);
    // 2-char typo on longer names.
    if (name.length >= 7) {
      const two = swap(name, 0).slice(0, -1);
      assert.ok(surfaces("/" + two, name), "two edits " + two);
    }
  });
}
