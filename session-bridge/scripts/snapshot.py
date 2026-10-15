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


def user_text(entry):
    return " ".join(b.get("text", "") for b in blocks(entry)
                    if isinstance(b, dict) and b.get("type") == "text")


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
    print("LAST USER ASK:", red(asks[-1][:500]) if asks else "(none found)")

    actions = []
    for e in entries:
        for b in blocks(e):
            if isinstance(b, dict) and b.get("type") == "tool_use":
                i = b.get("input") or {}
                what = i.get("command") or i.get("file_path") or i.get("pattern") or ""
                actions.append((e.get("timestamp", "?"), b.get("name"), str(what)[:160]))
    print(f"LAST {n} ACTIONS:")
    for ts, name, what in actions[-n:]:
        print("-", ts, name, red(what))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
