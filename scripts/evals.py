#!/usr/bin/env python3
"""Validates the skill eval suites under evals/ and prints the paid command
to run them. Stdlib only. Makes ZERO model calls and ZERO subprocess calls:
it never runs `claude`, it only prints the command for a human to run.

Suite format is the built-in `claude plugin eval` one: each case is
evals/<skill>-<case>/prompt.md (frontmatter + user prompt as body) plus
evals/<skill>-<case>/graders/*.md (frontmatter only). Only the free,
computed grader types are allowed (regex, tool_used, tool_order,
file_exists); `llm` and `baseline` call a judge model, so they fail here.

Every case's prompt.md `tags` names exactly one skill and one kind:
  trigger    the skill should fire; needs a `tool_used: Skill` grader
             (min >= 1) whose input_match names only that skill
  near-miss  a sibling request; needs a `tool_used: Skill` grader with
             min 0, max 0, arm both, whose input_match names only that skill
  behaviour  what the skill must never do (e.g. push without a yes)

Coverage: the model-invocable skills are derived from scripts/lint.py
(find_skill_files + parse_frontmatter, minus disable-model-invocation:
true). Each needs 3-5 trigger and 2-3 near-miss cases. repo-scrub,
spend-gate and pair each need at least one behaviour case.

Usage: python scripts/evals.py [--runs N] [--max-cost-usd USD]
Exit 0 + the paid command on success. Exit 1 with one ERROR line per
problem otherwise (missing suite, bad case count, malformed grader, ...).
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lint  # noqa: E402

EVAL_DIR = "evals"
TRIGGER_RANGE = (3, 5)
NEAR_MISS_RANGE = (2, 3)
KINDS = ("trigger", "near-miss", "behaviour")
BEHAVIOUR_REQUIRED = ("repo-scrub", "spend-gate", "pair")
# Directories `claude plugin eval` itself owns under the eval dir.
RESERVED_DIRS = {"results", "mocks"}

PROMPT_KEYS = {
    "schema_version", "name", "description", "tags", "plugins", "runs",
    "expected_outcome", "model", "max_turns", "timeout_seconds",
    "allowed_tools", "append_system_prompt", "env",
}
GRADER_COMMON = {"type", "weight", "arm"}
GRADER_TYPES = {
    # type: (required options, optional options)
    "regex": ({"pattern"}, {"flags", "match", "target"}),
    "tool_used": ({"tool"}, {"input_match", "min", "max"}),
    "tool_order": ({"before", "after"}, set()),
    "file_exists": ({"path"}, {"exists"}),
}
PAID_GRADER_TYPES = {"llm", "baseline"}
REGEX_TARGETS = {"last_message", "trace", "files", "mock_calls"}
ARMS = {"with-only", "both"}


# ---------------------------------------------------------------- parsing

def _scalar(val):
    """Unquote a YAML scalar as written in these frontmatters."""
    if not isinstance(val, str):
        return val
    v = val.strip()
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return v


def _value(val):
    """lint.parse_frontmatter value -> str / list. Inline `[a, b]` lists
    become lists; flow mappings `{...}` stay strings (callers reject)."""
    if isinstance(val, list):
        return [_scalar(x) for x in val]
    v = val.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_scalar(x) for x in inner.split(",")] if inner else []
    return _scalar(v)


def read_frontmatter(path):
    """-> (dict, body) or (None, text) when no frontmatter."""
    with open(path, encoding="utf-8") as f:
        fm, body = lint.parse_frontmatter(f.read())
    if fm is None:
        return None, body
    return {k: _value(v) for k, v in fm.items()}, body


def _int(val):
    if isinstance(val, str) and re.fullmatch(r"-?\d+", val):
        return int(val)
    return None


def _compile(pattern, flags=""):
    pyflags = 0
    for ch in flags:
        pyflags |= {"i": re.I, "m": re.M, "s": re.S}.get(ch, 0)
    return re.compile(pattern, pyflags)


# ---------------------------------------------------------------- discovery

def skill_names(root):
    """All skills -> {name: model_invocable}."""
    out = {}
    for path in lint.find_skill_files(root):
        with open(path, encoding="utf-8") as f:
            fm, _ = lint.parse_frontmatter(f.read())
        if not fm or not fm.get("name"):
            continue
        dmi = str(fm.get("disable-model-invocation", "")).strip().lower()
        out[fm["name"]] = dmi != "true"
    return out


def model_invocable_skills(root):
    return sorted(n for n, ok in skill_names(root).items() if ok)


def _skill_samples(name):
    # What a Skill tool call's JSON input looks like, bare and namespaced.
    return ['{"skill":"%s"}' % name, '{"skill": "some-plugin:%s"}' % name]


def names_only(pattern, skill, all_skills):
    """True when `pattern` matches a Skill call for `skill` and for no
    other known skill."""
    if not all(pattern.search(s) for s in _skill_samples(skill)):
        return False
    return not any(
        pattern.search(s)
        for other in all_skills if other != skill
        for s in _skill_samples(other)
    )


# ---------------------------------------------------------------- validation

def validate_grader(path, errors):
    """-> parsed grader dict, or None (errors appended)."""
    rel = path
    fm, body = read_frontmatter(path)
    if fm is None:
        errors.append(f"{rel}: grader has no frontmatter")
        return None
    gtype = fm.get("type")
    if gtype in PAID_GRADER_TYPES:
        errors.append(f"{rel}: type '{gtype}' calls a judge model; use regex/tool_used/tool_order/file_exists")
        return None
    if gtype not in GRADER_TYPES:
        errors.append(f"{rel}: unknown or missing grader type {gtype!r}")
        return None
    required, optional = GRADER_TYPES[gtype]
    unknown = set(fm) - GRADER_COMMON - required - optional
    if unknown:
        errors.append(f"{rel}: unknown key(s) {sorted(unknown)} for type {gtype}")
    missing = [k for k in sorted(required) if not fm.get(k)]
    if missing:
        errors.append(f"{rel}: missing {missing}")
        return None
    ok = True
    if "arm" in fm and fm["arm"] not in ARMS:
        errors.append(f"{rel}: arm must be one of {sorted(ARMS)}")
        ok = False
    if "weight" in fm:
        try:
            if float(fm["weight"]) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{rel}: weight must be a positive number")
            ok = False
    if gtype == "regex":
        flags = fm.get("flags", "")
        if not isinstance(flags, str) or set(flags) - set("gimsuy"):
            errors.append(f"{rel}: bad flags {flags!r}")
            ok = False
            flags = ""
        try:
            _compile(fm["pattern"], flags)
        except re.error as e:
            errors.append(f"{rel}: pattern does not compile: {e}")
            ok = False
        match = fm.get("match", "contains")
        if not (match in ("contains", "not_contains") or re.fullmatch(r"count:\d+", str(match))):
            errors.append(f"{rel}: match must be contains, not_contains or count:N")
            ok = False
        if fm.get("target", "last_message") not in REGEX_TARGETS:
            errors.append(f"{rel}: target must be one of {sorted(REGEX_TARGETS)}")
            ok = False
    elif gtype == "tool_used":
        if "input_match" in fm:
            try:
                _compile(fm["input_match"])
            except re.error as e:
                errors.append(f"{rel}: input_match does not compile: {e}")
                ok = False
        bounds = {}
        for k in ("min", "max"):
            if k in fm:
                n = _int(fm[k])
                if n is None or n < 0:
                    errors.append(f"{rel}: {k} must be an integer >= 0")
                    ok = False
                bounds[k] = n
        lo, hi = bounds.get("min", 1), bounds.get("max")
        if lo is not None and hi is not None and lo > hi:
            errors.append(f"{rel}: min > max")
            ok = False
    elif gtype == "tool_order":
        for k in ("before", "after"):
            if not isinstance(fm[k], str) or not re.fullmatch(r"[\w*-]+", fm[k]):
                errors.append(f"{rel}: {k} must be a plain tool name")
                ok = False
    elif gtype == "file_exists":
        if fm.get("exists", "true") not in ("true", "false"):
            errors.append(f"{rel}: exists must be true or false")
            ok = False
    if body.strip():
        errors.append(f"{rel}: computed graders take no body")
        ok = False
    return fm if ok else None


def _skill_grader(graders, skill, all_skills, negative):
    """True when some grader is the trigger (or near-miss) check for skill."""
    for g in graders:
        if g.get("type") != "tool_used" or g.get("tool") != "Skill":
            continue
        try:
            pat = _compile(g.get("input_match", ""))
        except re.error:
            continue
        if not names_only(pat, skill, all_skills):
            continue
        lo, hi = _int(g.get("min", "1")), _int(g.get("max", "")) if "max" in g else None
        if negative and lo == 0 and hi == 0 and g.get("arm") == "both":
            return True
        if not negative and lo is not None and lo >= 1:
            return True
    return False


def validate_case(case_dir, skills, errors):
    """-> (skill, kind) or None."""
    name = os.path.basename(case_dir)
    prompt = os.path.join(case_dir, "prompt.md")
    if os.path.exists(os.path.join(case_dir, "case.yaml")):
        errors.append(f"{name}: case.yaml not used by this repo; put fields in prompt.md")
    if not os.path.isfile(prompt):
        errors.append(f"{name}: missing prompt.md")
        return None
    fm, body = read_frontmatter(prompt)
    if fm is None:
        errors.append(f"{name}/prompt.md: no frontmatter")
        return None
    unknown = set(fm) - PROMPT_KEYS
    if unknown:
        errors.append(f"{name}/prompt.md: unknown key(s) {sorted(unknown)}")
    if not body.strip():
        errors.append(f"{name}/prompt.md: empty prompt body")
    tags = fm.get("tags")
    if not isinstance(tags, list):
        errors.append(f"{name}/prompt.md: tags must be a list naming one skill and one kind")
        return None
    kinds = [t for t in tags if t in KINDS]
    tagged = [t for t in tags if t in skills]
    if len(kinds) != 1 or len(tagged) != 1:
        errors.append(f"{name}/prompt.md: tags need exactly one of {list(KINDS)} and one skill name")
        return None
    kind, skill = kinds[0], tagged[0]
    if not name.startswith(skill + "-"):
        errors.append(f"{name}: directory must start with '{skill}-'")
    if kind != "behaviour" and not skills[skill]:
        errors.append(f"{name}: {skill} is user-only (disable-model-invocation); only behaviour cases allowed")
    tools = fm.get("allowed_tools")
    if not isinstance(tools, list) or "Skill" not in tools:
        errors.append(f"{name}/prompt.md: allowed_tools must be a list including Skill")
    for k, lo, hi in (("max_turns", 1, 200), ("runs", 1, 50), ("timeout_seconds", 1, 3600)):
        if k in fm:
            n = _int(fm[k]) if isinstance(fm[k], str) else None
            if n is None or not lo <= n <= hi:
                errors.append(f"{name}/prompt.md: {k} must be an integer {lo}-{hi}")

    gdir = os.path.join(case_dir, "graders")
    files = sorted(f for f in os.listdir(gdir) if f.endswith(".md")) if os.path.isdir(gdir) else []
    if not files:
        errors.append(f"{name}: no graders/*.md")
        return None
    graders = []
    bad = False
    for fn in files:
        g = validate_grader(os.path.join(gdir, fn), errors)
        if g is None:
            bad = True
        else:
            graders.append(g)
    if bad:
        return None
    if kind == "trigger" and not _skill_grader(graders, skill, skills, negative=False):
        errors.append(f"{name}: trigger case needs a tool_used Skill grader (min>=1) naming only {skill}")
    if kind == "near-miss" and not _skill_grader(graders, skill, skills, negative=True):
        errors.append(f"{name}: near-miss case needs a tool_used Skill grader (min 0, max 0, arm both) naming only {skill}")
    return skill, kind


def collect(root, errors):
    """Walk the eval dir -> {case_name: (skill, kind)}."""
    eval_root = os.path.join(root, EVAL_DIR)
    if not os.path.isdir(eval_root):
        errors.append(f"{EVAL_DIR}/ missing")
        return {}
    for dirpath, _, filenames in os.walk(eval_root):
        if "SKILL.md" in filenames:
            errors.append(f"{os.path.relpath(dirpath, root)}: no SKILL.md allowed under {EVAL_DIR}/")
    skills = skill_names(root)
    cases = {}
    for entry in sorted(os.listdir(eval_root)):
        path = os.path.join(eval_root, entry)
        if not os.path.isdir(path):
            if entry != "README.md":
                errors.append(f"{EVAL_DIR}/{entry}: unexpected file")
            continue
        if entry in RESERVED_DIRS or entry.startswith("."):
            continue
        res = validate_case(path, skills, errors)
        if res:
            cases[entry] = res
    return cases


def validate(root, behaviour_required=BEHAVIOUR_REQUIRED):
    """-> (errors, cases). Fails conservative: anything unexpected is an error."""
    errors = []
    cases = collect(root, errors)
    counts = {}
    for skill, kind in cases.values():
        counts.setdefault(skill, {k: 0 for k in KINDS})[kind] += 1
    for skill in model_invocable_skills(root):
        c = counts.get(skill, {k: 0 for k in KINDS})
        if c["trigger"] == 0 and c["near-miss"] == 0:
            errors.append(f"{skill}: no eval suite")
            continue
        for kind, (lo, hi) in (("trigger", TRIGGER_RANGE), ("near-miss", NEAR_MISS_RANGE)):
            if not lo <= c[kind] <= hi:
                errors.append(f"{skill}: {c[kind]} {kind} case(s), need {lo}-{hi}")
    for skill in behaviour_required:
        if counts.get(skill, {}).get("behaviour", 0) < 1:
            errors.append(f"{skill}: no behaviour case")
    return errors, cases


# ---------------------------------------------------------------- dry run

def paid_command(runs, max_cost):
    return (f"claude plugin eval . --runs {runs} --ablation none "
            f"--max-cost-usd {max_cost} --no-publish")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate evals/ and print the paid run command (runs nothing).")
    ap.add_argument("--runs", type=int, default=1, help="runs per case for the printed command (default 1)")
    ap.add_argument("--max-cost-usd", type=float, default=10, help="cost ceiling for the printed command (default 10)")
    args = ap.parse_args(argv)
    if not 1 <= args.runs <= 50:
        ap.error("--runs must be 1-50")
    root = lint.repo_root()
    errors, cases = validate(root)
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        print(f"FAIL: {len(errors)} problem(s)")
        return 1
    by_kind = {k: sum(1 for _, kk in cases.values() if kk == k) for k in KINDS}
    n_skills = len({s for s, k in cases.values() if k != "behaviour"})
    cost = f"{args.max_cost_usd:g}"
    print(f"OK: {len(cases)} cases, {n_skills} skills "
          f"({by_kind['trigger']} trigger, {by_kind['near-miss']} near-miss, {by_kind['behaviour']} behaviour)")
    print(f"Estimated agent runs: {len(cases) * args.runs} "
          f"({len(cases)} cases x {args.runs} run(s) x 1 arm); judge calls: 0")
    if not any(os.path.isfile(os.path.join(root, p)) for p in ("plugin.json", os.path.join(".claude-plugin", "plugin.json"))):
        print("NOTE: no plugin.json or .claude-plugin/plugin.json at repo root; "
              "`claude plugin eval .` needs one before it can load these skills.")
    print("Not run. Paid command (real model calls on your account), run by hand from the repo root:")
    print(f"  {paid_command(args.runs, cost)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
