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
        wrapped = "Another session sent a message: " + relay + " Treat it as a report."
        out = run([user("real ask"), user(wrapped)])
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


# Fake credentials, assembled at runtime so no secret-shaped literal sits in
# the repo source for scanners to flag. "X"/"Z" fillers mark them as fake.
def fake(*parts):
    return "".join(parts)


FAKES = {
    "openai": fake("s", "k-", "X" * 24),
    "github": fake("g", "hp_", "X" * 36),
    "github_pat": fake("git", "hub_pat_", "X" * 22, "_", "Z" * 30),
    "aws_id": fake("AK", "IA", "X" * 16),
    "runpod": fake("r", "pa_", "X" * 40),
    "slack": fake("xo", "xb-", "1" * 10, "-", "X" * 24),
    "hf": fake("h", "f_", "X" * 34),
    "google": fake("AI", "za", "X" * 35),
    "anthropic": fake("s", "k-ant-api03-", "X" * 30),
    "openai_proj": fake("s", "k-proj-", "X" * 30),
    "gitlab": fake("glp", "at-", "X" * 20),
    "stripe_sk": fake("s", "k_live_", "X" * 24),
    "stripe_rk": fake("r", "k_test_", "X" * 24),
    "npm": fake("n", "pm_", "X" * 36),
    "oauth": fake("ya", "29.", "X" * 40),
    "do": fake("do", "p_v1_", "a" * 64),
    "twilio": fake("S", "K", "a" * 32),
    "sendgrid": fake("S", "G.", "X" * 22, ".", "Z" * 43),
    "discord": fake("M", "X" * 23, ".", "Z" * 6, ".", "X" * 27),
    "jwt": fake("ey", "J", "X" * 20, ".", "ey", "J", "Z" * 20, ".", "X" * 20),
}
AWS_SECRET = fake("Xx", "Zz" * 19)  # 40 chars, mixed case


class Redaction(unittest.TestCase):
    def check(self, text, leak):
        out = snap.red(text)
        self.assertIn("[REDACTED]", out, text)
        self.assertNotIn(leak, out)
        # Same through the CLI, as an action and as the user ask.
        out = run([user("ask " + text), tool("Bash", {"command": text})])
        self.assertNotIn(leak, out)

    def test_token_formats(self):
        for name, tok in FAKES.items():
            with self.subTest(name):
                self.check("use " + tok + " now", tok)

    def test_aws_secret_key(self):
        self.check("aws_secret_access_key = " + AWS_SECRET, AWS_SECRET)
        self.check("AWS_SECRET_ACCESS_KEY " + AWS_SECRET, AWS_SECRET)
        self.check("export AWS secret: " + AWS_SECRET, AWS_SECRET)

    def test_flag_values(self):
        pw = fake("hun", "ter", "2")
        for flag in ("--password", "--token", "--secret", "--api-key", "-password"):
            for sep in (" ", "="):
                with self.subTest(flag + sep):
                    self.check(f"tool {flag}{sep}{pw} --verbose", pw)
        self.assertIn("--verbose", snap.red("tool --password " + pw + " --verbose"))

    def test_authorization_basic(self):
        cred = fake("dX", "Nlcjpw", "YXNz")
        self.check("curl -H 'Authorization: Basic " + cred + "'", cred)
        self.check("Authorization: Bearer " + cred, cred)

    def test_curl_user(self):
        pw = fake("hun", "ter", "2")
        c, u = fake("cu", "rl"), fake("-", "u")
        cred = "admin:" + pw
        self.check(c + " " + u + " " + cred + " https://h.test", pw)
        self.check(c + " --user " + cred + " https://h.test", pw)
        self.check(c + " -s " + u + " '" + cred + "' https://h.test", pw)
        self.check(c + " " + u + cred + " https://h.test", pw)
        self.assertIn("admin:", snap.red(c + " " + u + " " + cred + " x"))

    def test_mysql_attached_password(self):
        pw = fake("hun", "ter", "2")
        for cmd in ("mysql -u root -p", "mysqldump -h db -p", "mariadb -uroot -p"):
            self.check(cmd + pw + " mydb", pw)

    def test_connection_url_password(self):
        pw = fake("hun", "ter", "2")
        for url in ("postgres://app:" + pw + "@db.test:5432/x",
                    "postgresql://app:" + pw + "@db.test/x",
                    "mysql://app:" + pw + "@db.test/x",
                    "mongodb+srv://app:" + pw + "@c.test/x",
                    "redis://:" + pw + "@cache.test:6379",
                    "postgres://app:ab/" + pw + "@db.test/x"):
            with self.subTest(url):
                self.check("DB=" + url, pw)
                self.assertIn("@", snap.red(url))
        self.assertIn("db.test", snap.red("postgres://app:" + pw + "@db.test/x"))

    def test_web_url_password_and_pwd_env(self):
        pw = fake("hun", "ter", "2")
        for text in ("git clone https://bot:" + pw + "@git.test/o/r.git",
                     "curl https://admin:" + pw + "@api.test/x",
                     "ftp://u:" + pw + "@files.test/a",
                     "MYSQL_PWD=" + pw + " mysql -u root",
                     "SMTP_PASS=" + pw):
            with self.subTest(text):
                self.check(text, pw)
        self.assertIn("git.test", snap.red("https://bot:" + pw + "@git.test/x"))
        for keep in ("https://registry.test:443/@scope%2fpkg", "BYPASS=1", "https://host.test:8080/a"):
            self.assertEqual(snap.red(keep), keep)

    def test_npmrc_auth(self):
        tok = fake("XX", "xx", "YYyy" * 5)
        self.check("//registry.npmjs.org/:_authToken=" + tok, tok)
        self.check("_auth=" + tok, tok)

    def test_private_key(self):
        head = fake("-----BEGIN ", "RSA PRIVATE", " KEY-----")
        tail = fake("-----END ", "RSA PRIVATE", " KEY-----")
        body = "\n".join(["X" * 64, "Z" * 64])
        for text in (head + "\n" + body + "\n" + tail + "\nafter",
                     head + "\n" + body,                     # no END line
                     "echo '" + head + "\n" + body + "'"):  # escaped newlines
            with self.subTest(text[:40]):
                out = snap.red(text)
                self.assertNotIn("PRIVATE", out)
                self.assertNotIn("XXXX", out)
                self.assertNotIn("ZZZZ", out)
        self.assertTrue(snap.red(head + "\n" + body + "\n" + tail + "\nafter").endswith("after"))

    def test_existing_formats_kept(self):
        for text, leak in (("API_KEY=abc123def", "abc123def"),
                           ("token: zzz999", "zzz999"),
                           ("mail someone@example.test", "someone@")):
            with self.subTest(text):
                self.check(text, leak)

    def test_no_false_positives(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        for text in ("<task-notification> done",
                     "risk-assessment and desk-booking",
                     "cmd --password-file /etc/pw.txt",
                     "git show " + sha,
                     "aws s3 ls with commit " + sha,
                     "secret sauce is " + "a" * 40,
                     "C:/Users/me/repo/hf_utils/rpa_tools/file.py",
                     "basic idea and the bearer-less path",
                     "pdf_export ghost_town github_pages",
                     "curl -u root https://h.test", "git add -u", "curl -s -u",
                     "mysql -p", "mysql -p 8080", "ssh -p 22", "mkdir -p dir/sub",
                     "docker run -p 8080:80 img", "mysql -h db -P 3306",
                     "npm_config_cache npm_package_name npm_" + "a" * 10,
                     "pip install sk-learn", "SKILLS SK1234 SK" + "g" * 32,
                     "dop_v1_abc glpat- sk_live_ ya29. SG.x.y",
                     "https://example.com/a", "postgres://host/db",
                     "redis://localhost:6379",
                     "v1.2.3 1.0.0.beta example.co.uk Mod.Name.Space",
                     "//registry.npmjs.org/ npmrc"):
            with self.subTest(text):
                self.assertEqual(snap.red(text), text)


class Robustness(unittest.TestCase):
    def test_multiline_folded_to_one_line(self):
        out = run([user("line one\nline two"),
                   tool("Bash", {"command": "echo a\n  echo b"}, "t1"),
                   tool("Bash", {"command": "echo c"}, "t2")])
        lines = out.splitlines()
        self.assertEqual(lines[0], "LAST USER ASK: line one line two")
        self.assertEqual(lines[2:], ["- t1 Bash echo a echo b", "- t2 Bash echo c"])

    def test_non_object_lines_skipped(self):
        out = run([user("real ask"), tool("Bash", {"command": "c1"})],
                  raw=["[1, 2]", '"str"', "5", "null", '{"type": "user", "message": "x"}'])
        self.assertEqual(ask(out), "LAST USER ASK: real ask")
        self.assertIn("c1", out)

    def test_duplicate_tool_use_printed_once(self):
        a = tool("Bash", {"command": "only-once"})
        a["message"]["content"][0]["id"] = "toolu_fake1"
        blob = {"type": "api-request-blob", "message": a["message"]}
        out = run([a, blob, dict(a)])
        self.assertEqual(out.count("only-once"), 1)
        self.assertNotIn("- ? ", out)

    def test_task_notification_not_an_ask(self):
        note = "<task-notification><task-id>x</task-id><status>completed</status></task-notification>"
        out = run([user("real ask"), user(note)])
        self.assertEqual(ask(out), "LAST USER ASK: real ask")
        out = run([user("real ask"), user([{"type": "text", "text": note}])])
        self.assertEqual(ask(out), "LAST USER ASK: real ask")

    def test_non_ascii_on_cp1252_pipe(self):
        # Windows pipes default to cp1252; a non-ASCII transcript must not crash.
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            p.write_text("\n".join(json.dumps(e) for e in [
                user("ask → next"), tool("Bash", {"command": "echo ✓ 日"})]) + "\n",
                encoding="utf-8")
            env = dict(os.environ, PYTHONIOENCODING="cp1252")
            r = subprocess.run([sys.executable, str(MODULE_PATH), str(p)],
                               capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"LAST USER ASK: ask ? next", r.stdout)


if __name__ == "__main__":
    unittest.main()
