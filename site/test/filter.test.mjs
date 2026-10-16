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

test("status text counts matches", () => {
  assert.equal(F.statusText(F.search("/gri", FIX)), "2 matching commands");
  assert.equal(F.statusText(F.search("/sitr", FIX)), "1 matching command");
});

test("real nav data shape: kind derived from group, aliases optional", () => {
  assert.ok(REAL.length > 10);
  for (const x of REAL) {
    assert.deepEqual(Object.keys(x).filter((k) => k !== "aliases"), ["name", "kind", "group", "summary"], x.name);
    assert.equal(x.kind, { agents: "agent", hooks: "hook" }[x.group] || "skill", x.name);
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

function surfaces(buf, name) {
  return names(F.search(buf, REAL).options).includes(name);
}
function swap(s, i) {
  return s.slice(0, i) + s[i + 1] + s[i] + s.slice(i + 2);
}

for (const { name } of REAL) {
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
