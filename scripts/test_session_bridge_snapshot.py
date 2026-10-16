#!/usr/bin/env python3
"""Stdlib unittest coverage for session-bridge/scripts/snapshot.py. Run with:

    python -m unittest discover -s scripts -p "test_*.py"

Synthetic transcripts built in temp files; no real sessions.
"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "session-bridge" / "scripts" / "snapshot.py"
_spec = importlib.util.spec_from_file_location("session_bridge_snapshot", MODULE_PATH)
snap = importlib.util.module_from_spec(_spec)
sys.modules["session_bridge_snapshot"] = snap
_spec.loader.exec_module(snap)


def user(content, **kw):
    return dict({"type": "user", "message": {"content": content}}, **kw)


def tool(name, inp, ts="t1"):
    return {"type": "assistant", "timestamp": ts,
            "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def run(entries, n=10, raw=()):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.jsonl"
        lines = [json.dumps(e) for e in entries] + list(raw)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = snap.main(["snapshot.py", str(p), str(n)])
    assert rc == 0
    return out.getvalue()


def ask(out):
    return out.split("\n")[0]


class UserAsk(unittest.TestCase):
    def test_plain_str_and_list(self):
        self.assertEqual(ask(run([user("hello there")])), "LAST USER ASK: hello there")
        out = run([user([{"type": "text", "text": "list form"}])])
        self.assertEqual(ask(out), "LAST USER ASK: list form")

    def test_meta_skipped(self):
        out = run([user("real ask"), user("meta text", isMeta=True)])
        self.assertEqual(ask(out), "LAST USER ASK: real ask")

    def test_agent_message_relay_skipped(self):
        relay = '<agent-message from="worker">done, all good</agent-message>'
        out = run([user("real ask"), user(relay)])
        self.assertEqual(ask(out), "LAST USER ASK: real ask")

    def test_injected_blocks_skipped(self):
        for tag in ("system-reminder", "local-command-stdout", "local-command-caveat"):
            out = run([user("real ask"), user(f"<{tag}>noise</{tag}>")])
            self.assertEqual(ask(out), "LAST USER ASK: real ask", tag)

    def test_appended_reminder_stripped(self):
        c = [{"type": "text", "text": "fix the thing"},
             {"type": "text", "text": "<system-reminder>ctx</system-reminder>"}]
        self.assertEqual(ask(run([user(c)])), "LAST USER ASK: fix the thing")
        s = "fix it <system-reminder>ctx\nmore</system-reminder>"
        self.assertEqual(ask(run([user(s)])), "LAST USER ASK: fix it")

    def test_tool_result_only_skipped(self):
        tr = [{"type": "tool_result", "tool_use_id": "x", "content": "output"}]
        out = run([user("real ask"), user(tr)])
        self.assertEqual(ask(out), "LAST USER ASK: real ask")
        self.assertEqual(ask(run([user(tr)])), "LAST USER ASK: (none found)")

    def test_slash_command_shown(self):
        s = ("<command-message>x</command-message><command-name>/x</command-name>"
             "<command-args>one two</command-args>")
        self.assertEqual(ask(run([user(s)])), "LAST USER ASK: /x one two")
        s2 = "<command-message>y</command-message><command-name>/y</command-name>"
        self.assertEqual(ask(run([user(s2)])), "LAST USER ASK: /y")

    def test_secret_straddling_500(self):
        secret = "sk-" + "A" * 20
        out = run([user("a" * 490 + " " + secret)])
        self.assertNotIn("sk-", out)
        self.assertNotIn("AAAA", out)


class Actions(unittest.TestCase):
    def acts(self, name, inp):
        return run([tool(name, inp)]).split("\n")[2]

    def test_agent(self):
        self.assertEqual(self.acts("Agent", {"description": "d", "subagent_type": "s", "prompt": "p"}), "- t1 Agent d")
        self.assertEqual(self.acts("Agent", {"subagent_type": "s", "prompt": "p"}), "- t1 Agent s")
        self.assertEqual(self.acts("Agent", {"prompt": "p"}), "- t1 Agent p")

    def test_skill(self):
        self.assertEqual(self.acts("Skill", {"skill": "next", "args": "foo"}), "- t1 Skill next foo")
        self.assertEqual(self.acts("Skill", {"skill": "next"}), "- t1 Skill next")

    def test_other_fields(self):
        self.assertEqual(self.acts("Bash", {"command": "ls"}), "- t1 Bash ls")
        self.assertEqual(self.acts("Read", {"file_path": "/a/b"}), "- t1 Read /a/b")
        self.assertEqual(self.acts("Grep", {"pattern": "zz"}), "- t1 Grep zz")
        self.assertEqual(self.acts("WebFetch", {"url": "http://e.test", "prompt": "q"}), "- t1 WebFetch http://e.test")
        self.assertEqual(self.acts("WebSearch", {"query": "qq"}), "- t1 WebSearch qq")

    def test_fallback(self):
        self.assertEqual(self.acts("Custom", {"n": 1, "z": "first"}), "- t1 Custom first")
        self.assertEqual(self.acts("Custom", {"n": 1}), "- t1 Custom ")

    def test_secret_straddling_160(self):
        secret = "sk-" + "B" * 20
        out = run([tool("Bash", {"command": "x" * 150 + " " + secret})])
        self.assertNotIn("sk-", out)
        self.assertNotIn("BBBB", out)

    def test_limit_and_malformed(self):
        out = run([tool("Bash", {"command": "c1"}, "a"), tool("Bash", {"command": "c2"}, "b")],
                  n=1, raw=["{not json"])
        self.assertIn("LAST 1 ACTIONS:", out)
        self.assertIn("c2", out)
        self.assertNotIn("c1", out)


if __name__ == "__main__":
    unittest.main()
