"""UserPromptSubmit hook: warn when the session context nears the end of the
smart zone (quality tends to drop around 100-120k tokens; the default warns
earlier, at 75k, so there is room to wrap up).

Measures the last main-chain assistant usage (input + cache creation + cache
read tokens), read from the TAIL of the transcript only. /compact appends a
compact_boundary line and never truncates, so usage before the last boundary
is ignored; with no usable usage it falls back to bytes after the boundary
(~20 bytes per token). Threshold: SMARTZONE_TOKENS (default 75000; a whole
number, "1e5" and "100_000" accepted; anything else falls back to the default
with a note on stderr).

Stdout from this hook is injected into the conversation, so both the user and
Claude see the warning (/divide remaining work, then /session-handoff).
Never blocks, silent on any error. Stdlib only."""

import json
import os
import shutil
import sys
import tempfile

DEFAULT_TOKENS = 75000  # = old 1.5 MB threshold at ~20 bytes/token
BYTES_PER_TOKEN = 20
TAIL_START = 2 * 1024 * 1024
MAX_WINDOW = 32 * 1024 * 1024  # lower-bound estimate beyond this


def threshold(env=None):
    env = os.environ if env is None else env
    raw = str(env.get("SMARTZONE_TOKENS", "") or "").strip()
    if not raw:
        return DEFAULT_TOKENS
    try:
        f = float(raw)  # also takes "1e5", "100_000", "90000"
        v = int(f) if f == f and abs(f) != float("inf") and f == int(f) else 0
    except (ValueError, TypeError, OverflowError):
        v = 0
    if v > 0:
        return v
    print("smartzone: SMARTZONE_TOKENS=%r is not a positive whole number; "
          "using %d" % (raw, DEFAULT_TOKENS), file=sys.stderr)
    return DEFAULT_TOKENS


def _is_boundary(o):
    return o.get("type") == "system" and o.get("subtype") == "compact_boundary"


def _usage_tokens(o):
    if o.get("type") != "assistant" or o.get("isSidechain"):
        return None
    msg = o.get("message")
    u = msg.get("usage") if isinstance(msg, dict) else None
    if not isinstance(u, dict):
        return None
    total = 0
    for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        v = u.get(k)
        if isinstance(v, int) and not isinstance(v, bool):
            total += v
    return total or None  # synthetic entries (errors, interrupts) carry all-zero usage


def context_tokens(path):
    """Estimated live context tokens, or None if unknown."""
    size = os.path.getsize(path)
    window = TAIL_START
    with open(path, "rb") as f:
        while True:
            start = max(0, size - window)
            f.seek(start)
            data = f.read(size - start).decode("utf-8", errors="replace")
            lines = data.split("\n")
            if start > 0:
                lines = lines[1:]  # first line is probably partial
            # walk from the end
            usage = None
            boundary_found = False
            after_bytes = 0
            for line in reversed(lines):
                s = line.strip()
                if not s:
                    after_bytes += len(line.encode("utf-8", "replace")) + 1
                    continue
                try:
                    o = json.loads(s)
                except ValueError:
                    o = None
                if isinstance(o, dict):
                    if _is_boundary(o):
                        boundary_found = True
                        break
                    if usage is None:
                        usage = _usage_tokens(o)
                        if usage is not None:
                            return usage
                after_bytes += len(line.encode("utf-8", "replace")) + 1
            if boundary_found or start == 0:
                return after_bytes // BYTES_PER_TOKEN
            # no boundary and no usage in this window: grow it
            if window >= size or window >= MAX_WINDOW:
                return after_bytes // BYTES_PER_TOKEN
            window *= 4


def check(path, env=None):
    """Warning text or None."""
    if not path or not os.path.exists(path):
        return None
    tokens = context_tokens(path)
    limit = threshold(env)
    if tokens is None or tokens < limit:
        return None
    return (
        f"[smart-zone] Session transcript context is ~{tokens // 1000}k tokens, "
        f"past the {limit // 1000}k warning threshold; quality tends to drop around "
        "100-120k (a heuristic, verify with /context). Wrap up: run /divide on the "
        "remaining work, then /session-handoff, and continue in a fresh session."
    )


def main() -> None:
    data = json.load(sys.stdin)
    msg = check(data.get("transcript_path") or "")
    if msg:
        print(msg)


def run_self_test() -> int:
    passed = failed = 0
    d = tempfile.mkdtemp(prefix="smartzone-selftest-")

    def mk(name, lines):
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write((ln if isinstance(ln, str) else json.dumps(ln)) + "\n")
        return p

    def asst(inp=0, cc=0, cr=0, side=False):
        o = {"type": "assistant", "message": {"usage": {
            "input_tokens": inp, "cache_creation_input_tokens": cc,
            "cache_read_input_tokens": cr}}}
        if side:
            o["isSidechain"] = True
        return o

    boundary = {"type": "system", "subtype": "compact_boundary"}
    pad = {"type": "user", "message": {"content": "x" * 1000}}

    def rec(label, ok):
        nonlocal passed, failed
        if ok:
            passed += 1
        else:
            failed += 1
        print("%s: %s" % ("PASS" if ok else "FAIL", label))

    big_pre = [pad] * 3000 + [asst(cr=190000)]
    p = mk("a.jsonl", big_pre + [boundary, pad, asst(inp=5, cc=3000, cr=10000)])
    rec("big pre-compact + small post-compact: no warn", check(p, {}) is None)
    p = mk("b.jsonl", [pad, asst(inp=10, cc=2000, cr=82000)])
    m = check(p, {})
    rec("over threshold via usage: warn", bool(m) and "~84k tokens" in m)
    p = mk("c.jsonl", [asst(cr=190000), boundary] + [pad] * 3000)
    rec("no usage after boundary: byte fallback warns", check(p, {}) is not None)
    p = mk("c2.jsonl", [asst(cr=190000), boundary, pad])
    rec("post-compact, no new usage, small: no warn", check(p, {}) is None)
    p = mk("d.jsonl", [pad] * 3000)
    rec("no usage, no boundary: byte fallback warns", check(p, {}) is not None)
    rec("missing file: silent", check(os.path.join(d, "nope.jsonl"), {}) is None)
    p = mk("e.jsonl", ["{not json", asst(cr=90000), "also bad", "[1,2]"])
    rec("malformed lines tolerated", check(p, {}) is not None)
    p = mk("f.jsonl", [asst(cr=50000)])
    rec("env override lowers threshold", check(p, {"SMARTZONE_TOKENS": "40000"}) is not None)
    rec("env override raises threshold", check(mk("g.jsonl", [asst(cr=90000)]), {"SMARTZONE_TOKENS": "200000"}) is None)
    rec("bad env value uses default", threshold({"SMARTZONE_TOKENS": "abc"}) == DEFAULT_TOKENS)
    rec("1e5 / 100_000 accepted", threshold({"SMARTZONE_TOKENS": "1e5"}) == 100000
        and threshold({"SMARTZONE_TOKENS": "100_000"}) == 100000)
    rec("fractional / inf / nan / negative use default",
        all(threshold({"SMARTZONE_TOKENS": v}) == DEFAULT_TOKENS
            for v in ("90000.5", "inf", "nan", "-5", "0")))
    rec("warning names the threshold, not 100-120k as the trigger",
        "past the 40k warning threshold" in (check(mk("f2.jsonl", [asst(cr=50000)]),
                                                   {"SMARTZONE_TOKENS": "4e4"}) or ""))
    p = mk("h.jsonl", [asst(cr=10000), asst(cr=500000, side=True)])
    rec("sidechain entry ignored", check(p, {}) is None)
    p = mk("i.jsonl", [asst(cr=90000)] + [pad] * 3000)
    rec("usage beyond first 2 MB window found (grows)", check(p, {}) is not None)
    p = mk("j.jsonl", [asst(cr=90000)] + [pad] * 3000 + [asst(cr=1000)])
    rec("last usage wins over earlier big one", check(p, {}) is None)
    p = mk("k.jsonl", [asst(cr=90000), asst()])
    rec("all-zero synthetic usage skipped", check(p, {}) is not None)

    shutil.rmtree(d, ignore_errors=True)

    print("%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(run_self_test())
    try:
        main()
    except Exception:
        pass  # a broken heuristic must never break the session
    sys.exit(0)
