"""Tests for upstream_sync.py. Fake HTTP and fake git/gh only: no network."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import subprocess
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import upstream_sync as us  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "upstream_sync")
OLD = "1" * 40
MID = "3" * 40
HEAD = "2" * 40
REPO = "owner/upstream"
UP = "skills/demo/SKILL.md"


def slurp(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8", newline="") as f:
        return f.read()


class FakeUpstream:
    """Serves the handful of GitHub API routes upstream_sync uses."""

    def __init__(self, files, latest=HEAD, compare="ahead"):
        self.files = files          # sha -> text (absent = 404)
        self.latest = latest        # newest commit touching UP, or None
        self.compare = compare
        self.calls = []

    def fetch(self, url, headers):
        self.calls.append((url, headers))
        path = url[len(us.API):]
        base = "/repos/%s" % REPO
        if path == base + "/commits/main":
            return 200, json.dumps({"sha": HEAD}).encode()
        if path.startswith(base + "/contents/%s?ref=" % UP):
            sha = path.rsplit("=", 1)[1]
            if sha in self.files:
                return 200, self.files[sha].encode()
            return 404, b"{}"
        if path.startswith(base + "/commits?path=%s&sha=" % UP):
            return 200, json.dumps([{"sha": self.latest}] if self.latest else []).encode()
        if path.startswith(base + "/compare/"):
            return 200, json.dumps({"status": self.compare}).encode()
        raise AssertionError("unexpected URL " + url)

    def urls(self, part):
        return [u for u, _ in self.calls if part in u]


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        os.makedirs(os.path.join(self.root, "demo"))
        os.makedirs(os.path.join(self.root, "demo-local"))
        self.put("demo/SKILL.md", fixture("upstream_v1.md"))
        self.put("demo-local/SKILL.md", fixture("local_modified.md"))
        self.manifest = os.path.join(self.root, "upstream.json")
        shutil.copy(os.path.join(FIX, "manifest.json"), self.manifest)

    def put(self, rel, text):
        with open(os.path.join(self.root, rel), "wb") as f:
            f.write(text.encode("utf-8"))

    def raw(self, rel):
        with open(os.path.join(self.root, rel), "rb") as f:
            return f.read()

    def sync(self, fake, **kw):
        return us.run(us.GitHub(fetch=fake.fetch), self.root, self.manifest, **kw)

    def shas(self):
        return {e["local_path"]: e["upstream_sha"] for e in us.load_manifest(self.manifest)["entries"]}


class Verbatim(Base):
    def test_identical_is_unchanged(self):
        fake = FakeUpstream({HEAD: fixture("upstream_v1.md"), OLD: fixture("upstream_v1.md")},
                            latest=OLD)
        s = self.sync(fake)
        self.assertEqual(s["verbatim"], [])
        self.assertIn("demo/SKILL.md", s["unchanged"])
        self.assertEqual(self.shas()["demo/SKILL.md"], OLD)

    def test_crlf_only_difference_is_unchanged(self):
        self.put("demo/SKILL.md", fixture("upstream_v1.md").replace("\n", "\r\n"))
        fake = FakeUpstream({HEAD: fixture("upstream_v1.md")}, latest=OLD)
        self.assertEqual(self.sync(fake)["verbatim"], [])

    def test_differs_writes_lf_and_bumps_sha(self):
        fake = FakeUpstream({HEAD: fixture("upstream_v2.md").replace("\n", "\r\n")}, latest=OLD)
        s = self.sync(fake)
        self.assertEqual([i["local_path"] for i in s["verbatim"]], ["demo/SKILL.md"])
        self.assertEqual(self.raw("demo/SKILL.md"), fixture("upstream_v2.md").encode())
        shas = self.shas()
        self.assertEqual(shas["demo/SKILL.md"], HEAD)
        self.assertEqual(shas["demo-local/SKILL.md"], OLD)

    def test_dry_run_writes_nothing(self):
        before_manifest = slurp(self.manifest, "rb")
        before_file = self.raw("demo/SKILL.md")
        out = os.path.join(self.root, "out")
        fake = FakeUpstream({HEAD: fixture("upstream_v2.md"), OLD: fixture("upstream_v1.md")})
        s = self.sync(fake, dry_run=True, out_dir=out)
        self.assertEqual(len(s["verbatim"]), 1)
        self.assertEqual(len(s["modified"]), 1)
        self.assertEqual(slurp(self.manifest, "rb"), before_manifest)
        self.assertEqual(self.raw("demo/SKILL.md"), before_file)
        self.assertFalse(os.path.exists(out))
        self.assertIn("would update", us.report(s))


class Modified(Base):
    def files(self):
        return {OLD: fixture("upstream_v1.md"), HEAD: fixture("upstream_v2.md")}

    def test_latest_path_commit_is_recorded_sha(self):
        fake = FakeUpstream(self.files(), latest=OLD)
        s = self.sync(fake)
        self.assertEqual(s["modified"], [])
        self.assertEqual(fake.urls("/compare/"), [])

    def test_path_commit_already_in_recorded_sha(self):
        for status in ("behind", "identical"):
            fake = FakeUpstream(self.files(), latest=MID, compare=status)
            self.assertEqual(self.sync(fake)["modified"], [], status)
            self.assertTrue(fake.urls("/compare/%s...%s" % (OLD, MID)))

    def test_newer_path_commit_yields_upstream_diff(self):
        fake = FakeUpstream(self.files(), latest=HEAD, compare="ahead")
        s = self.sync(fake)
        [item] = s["modified"]
        self.assertEqual(item["title"], "upstream-sync: demo-local/SKILL.md")
        self.assertIn("+Recommend an answer for each question.", item["diff"])
        self.assertNotIn("save notes", item["diff"])  # never diffs our copy
        self.assertIn("--mark-synced demo-local/SKILL.md", item["body"])
        self.assertEqual(self.shas()["demo-local/SKILL.md"], OLD)  # human bumps

    def test_diverged_counts_as_changed(self):
        fake = FakeUpstream(self.files(), latest=MID, compare="diverged")
        self.assertEqual(len(self.sync(fake)["modified"]), 1)

    def test_upstream_file_deleted(self):
        fake = FakeUpstream({OLD: fixture("upstream_v1.md")}, latest=HEAD)
        self.put("demo/SKILL.md", fixture("upstream_v1.md"))
        # Verbatim entry would raise on a missing file; drop it for this case.
        m = us.load_manifest(self.manifest)
        m["entries"] = [e for e in m["entries"] if e["mode"] == "modified"]
        us.dump_manifest(self.manifest, m)
        [item] = self.sync(fake)["modified"]
        self.assertTrue(item["upstream_missing"])
        self.assertIn("-Ask one question at a time.", item["diff"])


class OutDir(Base):
    def test_summary_and_bodies(self):
        out = os.path.join(self.root, "out")
        fake = FakeUpstream({OLD: fixture("upstream_v1.md"), HEAD: fixture("upstream_v2.md")})
        self.sync(fake, out_dir=out)
        with open(os.path.join(out, "summary.json"), encoding="utf-8") as f:
            s = json.load(f)
        pr = slurp(s["pr_body_file"])
        self.assertIn(us.CI_NOTE, pr)
        self.assertNotIn("Allow GitHub Actions", pr)
        [item] = s["modified"]
        self.assertNotIn("diff", item)
        body = slurp(item["body_file"])
        self.assertIn("```diff\n", body)
        self.assertTrue(os.path.exists(item["diff_file"]))

    def test_fence_longer_than_backticks_in_diff(self):
        self.assertEqual(us.fence("a ```` b"), "`````")
        self.assertEqual(us.fence("plain"), "```")


class SubprocessRunErrors(unittest.TestCase):
    def run_failing(self, args):
        err = subprocess.CalledProcessError(3, args, output="out", stderr="boom")
        buf = io.StringIO()
        with mock.patch("subprocess.run", side_effect=err), contextlib.redirect_stderr(buf):
            with self.assertRaises(subprocess.CalledProcessError):
                us.subprocess_run(args)
        return buf.getvalue()

    def test_prints_command_stderr_stdout(self):
        out = self.run_failing(["git", "push", "origin", "x"])
        for want in ("git push origin x", "boom", "out", "3"):
            self.assertIn(want, out)
        self.assertNotIn("Allow GitHub Actions", out)

    def test_pr_create_notes_fallback_not_setting(self):
        out = self.run_failing(["gh", "pr", "create", "--title", "t"])
        self.assertIn("falling back to an issue", out)
        self.assertNotIn("Allow GitHub Actions", out)


class Publish(unittest.TestCase):
    summary = {
        "verbatim": [{"local_path": "demo/SKILL.md"}],
        "modified": [{"local_path": "demo-local/SKILL.md", "title": "upstream-sync: demo-local/SKILL.md",
                      "body_file": "b.md"}],
        "pr_body_file": "pr.md",
    }

    def fake_cmd(self, open_prs, open_issues, fail=()):
        calls = []

        def run(args):
            calls.append(args)
            if tuple(args[:3]) in fail:
                raise subprocess.CalledProcessError(1, args, output="", stderr="nope")
            if args[:3] == ["gh", "pr", "list"]:
                return json.dumps(open_prs)
            if args[:3] == ["gh", "issue", "list"]:
                return json.dumps(open_issues)
            return ""
        return run, calls

    def test_creates_pr_and_issue_when_none_open(self):
        # A similar but not identical title must not count as a duplicate.
        run, calls = self.fake_cmd([], [{"number": 9, "title": "upstream-sync: demo-local/SKILL.md v2"}])
        actions = us.publish(self.summary, "upstream.json", run)
        cmds = [c[:3] for c in calls]
        self.assertIn(["git", "checkout", "-B"], cmds)
        self.assertIn(["git", "add", "--", "demo/SKILL.md", "upstream.json"], [c[:5] for c in calls])
        self.assertIn(["gh", "pr", "create"], cmds)
        self.assertIn(["gh", "issue", "create"], cmds)
        self.assertEqual(len(actions), 2)

    def test_skips_when_already_open(self):
        run, calls = self.fake_cmd([{"number": 4}],
                                   [{"number": 5, "title": "upstream-sync: demo-local/SKILL.md"}])
        actions = us.publish(self.summary, "upstream.json", run)
        self.assertEqual([c[0] for c in calls], ["gh", "gh"])  # only the two list calls
        self.assertTrue(all(a.startswith("skip") for a in actions))

    def tmp_summary(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with open(os.path.join(d, "pr.md"), "w", encoding="utf-8") as f:
            f.write("PR BODY\n")
        return dict(self.summary, pr_body_file=os.path.join(d, "pr.md")), d

    def issue_creates(self, calls):
        return [c for c in calls if c[:3] == ["gh", "issue", "create"]]

    def test_pr_create_fails_opens_fallback_issue(self):
        summary, d = self.tmp_summary()
        run, calls = self.fake_cmd([], [], fail={("gh", "pr", "create")})
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/r"}):
            actions = us.publish(summary, "upstream.json", run)
        creates = self.issue_creates(calls)
        self.assertEqual([c[c.index("--title") + 1] for c in creates],
                         [us.PR_TITLE, "upstream-sync: demo-local/SKILL.md"])
        body = slurp(creates[0][creates[0].index("--body-file") + 1])
        self.assertEqual(os.path.dirname(creates[0][-1]), d)
        for want in ("PR BODY", us.VERBATIM_BRANCH,
                     "https://github.com/o/r/compare/upstream-sync/verbatim"):
            self.assertIn(want, body)
        self.assertFalse(any(a.startswith("failed:") for a in actions))

    def test_fallback_without_repo_env_names_branch(self):
        summary, _ = self.tmp_summary()
        run, calls = self.fake_cmd([], [], fail={("gh", "pr", "create")})
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_REPOSITORY"}
        with mock.patch.dict(os.environ, env, clear=True):
            us.publish(summary, "upstream.json", run)
        body = slurp(self.issue_creates(calls)[0][-1])
        self.assertIn(us.VERBATIM_BRANCH, body)
        self.assertNotIn("/compare/", body)

    def test_fallback_issue_already_open_is_skipped(self):
        summary, _ = self.tmp_summary()
        run, calls = self.fake_cmd([], [{"number": 7, "title": us.PR_TITLE}],
                                   fail={("gh", "pr", "create")})
        actions = us.publish(summary, "upstream.json", run)
        titles = [c[c.index("--title") + 1] for c in self.issue_creates(calls)]
        self.assertEqual(titles, ["upstream-sync: demo-local/SKILL.md"])
        self.assertTrue(actions[0].startswith("skip fallback issue: #7"))

    def test_verbatim_failure_still_opens_modified_issues(self):
        run, calls = self.fake_cmd([], [], fail={("git", "push", "--force")})
        actions = us.publish(self.summary, "upstream.json", run)
        self.assertNotIn(["gh", "pr", "create"], [c[:3] for c in calls])
        self.assertEqual(len(self.issue_creates(calls)), 1)
        self.assertTrue(actions[0].startswith("failed: verbatim"))
        self.assertEqual(actions[1], "opened issue: upstream-sync: demo-local/SKILL.md")

    def test_modified_failure_does_not_stop_later_items(self):
        two = dict(self.summary, verbatim=[], modified=self.summary["modified"] + [
            {"local_path": "x/SKILL.md", "title": "upstream-sync: x/SKILL.md", "body_file": "c.md"}])
        n = {"i": 0}
        run, calls = self.fake_cmd([], [])

        def flaky(args):
            if args[:3] == ["gh", "issue", "create"]:
                n["i"] += 1
                if n["i"] == 1:
                    calls.append(args)
                    raise subprocess.CalledProcessError(1, args)
            return run(args)
        actions = us.publish(two, "upstream.json", flaky)
        self.assertTrue(actions[0].startswith("failed: issue for demo-local/SKILL.md"))
        self.assertEqual(actions[1], "opened issue: upstream-sync: x/SKILL.md")

    def test_nothing_to_do(self):
        run, calls = self.fake_cmd([], [])
        self.assertEqual(us.publish({"verbatim": [], "modified": []}, "upstream.json", run), [])
        self.assertEqual(calls, [])


class MainExit(unittest.TestCase):
    def call_main(self, actions):
        summary = {"verbatim": [], "modified": [], "unchanged": [], "dry_run": False}
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        out = io.StringIO()
        with mock.patch.object(us, "run", return_value=summary), \
                mock.patch.object(us, "publish", return_value=actions) as pub, \
                contextlib.redirect_stdout(out):
            rc = us.main(["--publish", "--out", d, "--manifest", os.path.join(d, "upstream.json")])
        pub.assert_called_once()
        return rc, out.getvalue()

    def test_nonzero_after_printing_all_actions_when_one_failed(self):
        rc, out = self.call_main(["failed: verbatim PR (git push --force)", "opened issue: t"])
        self.assertEqual(rc, 1)
        self.assertIn("failed: verbatim PR", out)
        self.assertIn("opened issue: t", out)

    def test_zero_when_all_ok(self):
        rc, _ = self.call_main(["opened PR from upstream-sync/verbatim", "skip issue: #1"])
        self.assertEqual(rc, 0)


class Misc(Base):
    def test_token_sent_as_bearer(self):
        fake = FakeUpstream({HEAD: fixture("upstream_v1.md")}, latest=OLD)
        us.run(us.GitHub(fetch=fake.fetch, token="t0k"), self.root, self.manifest)
        self.assertTrue(all(h.get("Authorization") == "Bearer t0k" for _, h in fake.calls))

    def test_no_token_no_header(self):
        fake = FakeUpstream({HEAD: fixture("upstream_v1.md")}, latest=OLD)
        self.sync(fake)
        self.assertTrue(all("Authorization" not in h for _, h in fake.calls))

    def test_mark_synced_bumps_only_that_entry(self):
        fake = FakeUpstream({})
        self.assertEqual(us.mark_synced(us.GitHub(fetch=fake.fetch), self.manifest,
                                        "demo-local/SKILL.md"), HEAD)
        self.assertEqual(self.shas(), {"demo/SKILL.md": OLD, "demo-local/SKILL.md": HEAD})

    def test_manifest_roundtrip_keeps_format(self):
        repo_manifest = os.path.join(us.repo_root(), "upstream.json")
        text = slurp(repo_manifest)
        self.assertEqual(json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n", text)


if __name__ == "__main__":
    unittest.main()
