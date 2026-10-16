#!/usr/bin/env python3
"""Summarise another Claude Code session's transcript (.jsonl) without dumping it.

Prints the last real user prompt and the last N tool actions, with anything
credential- or email-shaped redacted. Field names follow Claude Code's
transcript format; unknown shapes are skipped, never fatal. Stdlib only.

Usage: python snapshot.py <transcript.jsonl> [N=10]
"""
import json
import re
import sys

SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{12,}"
    r"|[Bb]earer\s+\S+|(?i:(?:api[_-]?key|token|secret|password)\S*\s*[:=]\s*)\S+"
    r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def red(text):
    return SECRET.sub("[REDACTED]", text)


def blocks(entry):
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


INJECTED = re.compile(
    r"<(system-reminder|local-command-stdout|local-command-stderr"
    r"|local-command-caveat|command-message|agent-message)\b[^>]*>.*?</\1>"
    r"|<(?:system-reminder|agent-message)\b[^>]*>.*\Z", re.S)
CMD_NAME = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.S)
CMD_ARGS = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.S)


def user_text(entry):
    """Real prompt text of a user entry, or "" (meta, relays, injected, tool results)."""
    if entry.get("isMeta"):
        return ""
    # A relay from another agent is wrapped in harness preamble; skip it whole.
    if any(isinstance(b, dict) and b.get("type") == "text"
           and "<agent-message" in str(b.get("text", "")) for b in blocks(entry)):
        return ""
    parts = []
    for b in blocks(entry):
        if not (isinstance(b, dict) and b.get("type") == "text"):
            continue
        text = b.get("text")
        if not isinstance(text, str):
            continue
        m = CMD_NAME.search(text)
        if m:
            args = CMD_ARGS.search(text)
            name = m.group(1)
            name = name if name.startswith("/") else "/" + name
            parts.append((name + " " + (args.group(1) if args else "")).strip())
            continue
        text = INJECTED.sub("", text).strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def action_text(name, i):
    if not isinstance(i, dict):
        return ""
    keys = ("command", "file_path", "pattern", "url", "query")
    if name == "Agent":
        keys = ("description", "subagent_type", "prompt")
    elif name == "Skill":
        skill = i.get("skill")
        if isinstance(skill, str) and skill:
            args = i.get("args")
            return skill + (" " + args if isinstance(args, str) and args else "")
        keys = ()
    for k in keys:
        if isinstance(i.get(k), str) and i[k]:
            return i[k]
    for v in i.values():
        if isinstance(v, str) and v:
            return v
    return ""


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    path, n = argv[1], int(argv[2]) if len(argv) > 2 else 10
    entries = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue

    asks = [t for e in entries if e.get("type") == "user" for t in [user_text(e)] if t]
    print("LAST USER ASK:", red(asks[-1])[:500] if asks else "(none found)")

    actions = []
    for e in entries:
        for b in blocks(e):
            if isinstance(b, dict) and b.get("type") == "tool_use":
                what = action_text(b.get("name"), b.get("input"))
                actions.append((e.get("timestamp", "?"), b.get("name"), red(str(what))[:160]))
    print(f"LAST {n} ACTIONS:")
    for ts, name, what in actions[-n:]:
        print("-", ts, name, what)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
