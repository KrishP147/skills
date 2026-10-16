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

# (pattern, replacement) pairs, applied in order. Every token prefix is
# anchored on a word boundary so "task-notification" never reads as "sk-...".
R = "[REDACTED]"
SECRETS = [(re.compile(p), r) for p, r in (
    # PEM private key: header through END, else header plus the body that follows.
    (r"(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----"
     r"(?:.*?-----END [A-Z ]*PRIVATE KEY-----|[A-Za-z0-9+/=\s\\]*)", R),
    (r"\bsk-[A-Za-z0-9_-]{8,}", R),
    (r"\bgh[pousr]_[A-Za-z0-9]{8,}", R),
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}", R),
    (r"\bAKIA[0-9A-Z]{12,}", R),
    (r"\brpa_[A-Za-z0-9]{16,}", R),                    # Runpod
    (r"\bxox[abprs]-[A-Za-z0-9-]{10,}", R),            # Slack
    (r"\bhf_[A-Za-z0-9]{20,}", R),                     # Hugging Face
    (r"\bAIza[A-Za-z0-9_-]{30,}", R),                  # Google API key
    (r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*", R),  # JWT
    (r"\bglpat-[A-Za-z0-9_-]{20,}", R),                # GitLab
    (r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{10,}", R),    # Stripe secret/restricted
    (r"\bnpm_[A-Za-z0-9]{36}\b", R),                   # npm
    (r"\bya29\.[A-Za-z0-9_-]{20,}", R),                # Google OAuth
    (r"\bdop_v1_[a-f0-9]{64}", R),                     # DigitalOcean
    (r"\bSK[0-9a-f]{32}\b", R),                        # Twilio
    (r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}", R),  # SendGrid
    # Discord bot token: 3 dot-separated parts, first starts M/N/O.
    (r"\b[MNO][A-Za-z0-9_-]{23,25}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,38}", R),
    # .npmrc: //registry/:_authToken=X, _auth=X, _password=X
    (r"(_auth(?:Token|Password)?\s*=\s*)[^\s'\"]+", r"\1" + R),
    # Password in a connection URL; keep scheme, user, host. Before the email rule.
    (r"((?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|rediss?|amqps?)://"
     r"[^\s:/@]*:)[^\s@/]+(?=@)", r"\1" + R),
    # curl basic-auth flag with user:secret (a bare "-u root" has no colon).
    (r"(\bcurl\b[^\n|;&]*?\s(?:-u|--user)(?:\s+|=)['\"]?[^\s:'\"]+:)[^\s'\"]+",
     r"\1" + R),
    # mysql -psecret (attached; "-p 8080", "ssh -p 22", "mkdir -p d" are not).
    (r"(\b(?:mysql|mysqldump|mysqladmin|mariadb)\b[^\n|;&]*?\s-p)(?=[^\s-])\S+",
     r"\1" + R),
    # AWS secret key: 40 base64 chars of mixed case, only within 40 chars after
    # "aws" or "secret", so bare git SHAs and hashes are left alone.
    (r"((?i:\baws|secret)[^\n]{0,40}?)(?<![A-Za-z0-9/+])"
     r"(?=[A-Za-z0-9/+]{0,39}[a-z])(?=[A-Za-z0-9/+]{0,39}[A-Z])"
     r"[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+])", r"\1" + R),
    # --password X / --token=X; "--password-file x" is a path, not a secret.
    (r"((?<![\w-])--?(?i:password|passwd|token|secret|api[-_]?key)(?:\s+|=))(?!-)\S+",
     r"\1" + R),
    (r"((?i:\bauthorization)\s*[:=]\s*(?i:basic|digest|token)\s+)\S+", r"\1" + R),
    (r"\b[Bb]earer\s+\S+", R),
    (r"(?i:(?:api[_-]?key|token|secret|password)\S*\s*[:=]\s*)\S+", R),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", R),
)]


def red(text):
    for pat, rep in SECRETS:
        text = pat.sub(rep, text)
    return text


def one_line(text, limit):
    """Redact, then fold whitespace so each item stays on one line, then cut."""
    return " ".join(red(text).split())[:limit]


def blocks(entry):
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


INJECTED = re.compile(
    r"<(system-reminder|local-command-stdout|local-command-stderr"
    r"|local-command-caveat|command-message|agent-message|task-notification)\b[^>]*>.*?</\1>"
    r"|<(?:system-reminder|agent-message|task-notification)\b[^>]*>.*\Z", re.S)
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
    # A Windows pipe defaults to the locale codepage (cp1252): one non-ASCII
    # char in a transcript would crash print, so replace what can't encode.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    entries = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):  # a list/str/number line is not an entry
                entries.append(obj)

    asks = [t for e in entries if e.get("type") == "user" for t in [user_text(e)] if t]
    print("LAST USER ASK:", one_line(asks[-1], 500) if asks else "(none found)")

    # Only assistant entries: other entry types (e.g. API request blobs) repeat
    # the same tool calls. Dedupe by tool_use id when one is present.
    actions, seen = [], set()
    for e in entries:
        if e.get("type") != "assistant":
            continue
        for b in blocks(e):
            if isinstance(b, dict) and b.get("type") == "tool_use":
                tid = b.get("id")
                if isinstance(tid, str) and tid:
                    if tid in seen:
                        continue
                    seen.add(tid)
                what = action_text(b.get("name"), b.get("input"))
                actions.append((e.get("timestamp", "?"), b.get("name"), one_line(str(what), 160)))
    print(f"LAST {n} ACTIONS:")
    for ts, name, what in actions[-n:]:
        print("-", ts, name, what)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
