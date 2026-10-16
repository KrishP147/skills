#!/usr/bin/env python3
"""Check files derived from upstream repos (listed in upstream.json) for
upstream changes. Stdlib only.

Modes, per manifest entry:
- verbatim: our file must stay byte-identical with upstream. If upstream
  HEAD differs (compared after CRLF -> LF), write the upstream content with
  LF endings and bump upstream_sha to that HEAD.
- modified: our file intentionally differs, so it is never diffed against
  upstream. "Changed" means the commits API shows a commit touching the
  upstream path that is not already contained in upstream_sha. Then we
  produce the upstream diff upstream_sha..HEAD for that path. upstream_sha
  is NOT bumped here: a human ports the change, then runs
  `--mark-synced <local_path>` to record the new HEAD.

Usage:
  python scripts/upstream_sync.py [--dry-run] [--out DIR] [--manifest PATH]
  python scripts/upstream_sync.py --mark-synced handoff/SKILL.md
  python scripts/upstream_sync.py --out DIR --publish   # CI only

--dry-run reports only and writes nothing (not even --out). --out DIR
writes summary.json plus ready-made PR/issue body files. --publish (used by
.github/workflows/upstream-sync.yml) then opens one PR from branch
upstream-sync/verbatim for verbatim changes and one issue titled
"upstream-sync: <local_path>" per modified file, skipping any already open.
Uses GITHUB_TOKEN or GH_TOKEN as a bearer token when set.
"""
import argparse
import difflib
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
DEFAULT_REF = "main"
MAX_BODY = 60000  # GitHub caps issue/PR bodies at 65536 chars

CI_NOTE = ("CI does not run on bot PRs: close and reopen, or push an empty "
           "commit, to trigger ci.")


def repo_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ---------- HTTP ----------

def urllib_fetch(url, headers):
    """Return (status, body bytes). 404 etc. are returned, not raised."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class GitHub:
    def __init__(self, fetch=urllib_fetch, token=None):
        self.fetch = fetch
        self.token = token
        self._heads = {}

    def _get(self, path, raw=False):
        headers = {
            "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
            "User-Agent": "upstream-sync",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        return self.fetch(API + path, headers)

    def _json(self, path):
        status, body = self._get(path)
        if status != 200:
            raise RuntimeError("GET %s -> %s: %s" % (path, status, body[:200]))
        return json.loads(body.decode("utf-8"))

    def head(self, repo, ref=DEFAULT_REF):
        key = (repo, ref)
        if key not in self._heads:
            self._heads[key] = self._json("/repos/%s/commits/%s" % (repo, ref))["sha"]
        return self._heads[key]

    def file_at(self, repo, path, ref):
        """File text at ref, or None if it does not exist there."""
        status, body = self._get("/repos/%s/contents/%s?ref=%s" % (repo, path, ref), raw=True)
        if status == 404:
            return None
        if status != 200:
            raise RuntimeError("contents %s@%s -> %s" % (path, ref, status))
        return body.decode("utf-8")

    def latest_commit_for_path(self, repo, path, ref):
        commits = self._json("/repos/%s/commits?path=%s&sha=%s&per_page=1" % (repo, path, ref))
        return commits[0]["sha"] if commits else None

    def compare_status(self, repo, base, head):
        """'ahead' | 'behind' | 'identical' | 'diverged' (head relative to base)."""
        return self._json("/repos/%s/compare/%s...%s" % (repo, base, head))["status"]


# ---------- decision logic ----------

def lf(text):
    return text.replace("\r\n", "\n")


def verbatim_differs(upstream_text, local_text):
    return lf(upstream_text) != lf(local_text)


def path_changed(gh, repo, path, recorded, ref=DEFAULT_REF):
    """True when a commit touching `path` is reachable from ref but not from
    `recorded`. Never looks at our local file."""
    latest = gh.latest_commit_for_path(repo, path, ref)
    if latest is None or latest == recorded:
        return False
    # latest already contained in recorded -> recorded is ahead/identical.
    return gh.compare_status(repo, recorded, latest) not in ("behind", "identical")


def upstream_diff(old_text, new_text, path, old_sha, new_sha):
    old = lf(old_text or "").splitlines(keepends=True)
    new = lf(new_text or "").splitlines(keepends=True)
    return "".join(difflib.unified_diff(
        old, new,
        fromfile="a/%s@%s" % (path, old_sha[:7]),
        tofile="b/%s@%s" % (path, new_sha[:7])))


def slug(path):
    return re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-").lower()


def issue_title(local_path):
    return "upstream-sync: %s" % local_path


def fence(text):
    ticks = "```"
    while ticks in text:
        ticks += "`"
    return ticks


def issue_body(entry, head, diff):
    repo, up = entry["repo"], entry["upstream_path"]
    if len(diff) > MAX_BODY:
        diff = diff[:MAX_BODY] + "\n... (truncated, see the compare link)\n"
    if diff and not diff.endswith("\n"):
        diff += "\n"
    f = fence(diff)
    local, old = entry["local_path"], entry["upstream_sha"]
    return (
        "Upstream `{repo}` changed `{up}` since our last sync. Our `{local}` is a "
        "**modified** copy, so this is not applied automatically.\n\n"
        "Compare: https://github.com/{repo}/compare/{old}...{head}\n\n"
        "Upstream diff ({o7}..{h7}, this path only):\n\n{f}diff\n{diff}{f}\n\n"
        "To resolve: port what applies into `{local}`, then run "
        "`python scripts/upstream_sync.py --mark-synced {local}` and commit both. "
        "To skip the change, run only the `--mark-synced` step.\n"
    ).format(repo=repo, up=up, local=local, old=old, head=head,
             o7=old[:7], h7=head[:7], f=f, diff=diff)


def pr_body(items):
    lines = ["Weekly upstream sync: these files are **verbatim** copies and "
             "upstream changed them, so this PR copies the new content and "
             "bumps `upstream_sha` in `upstream.json`.", ""]
    for it in items:
        lines.append("- `%s` <- `%s:%s` (https://github.com/%s/compare/%s...%s)" % (
            it["local_path"], it["repo"], it["upstream_path"], it["repo"], it["from"], it["to"]))
    lines += ["", CI_NOTE, ""]
    return "\n".join(lines)


def load_manifest(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump_manifest(path, manifest):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


def read_local(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8", newline="") as f:
        return f.read()


def write_local(root, rel, text):
    with open(os.path.join(root, rel), "wb") as f:
        f.write(lf(text).encode("utf-8"))


def run(gh, root, manifest_path, dry_run=False, out_dir=None):
    """Return the summary dict; writes files unless dry_run."""
    manifest = load_manifest(manifest_path)
    summary = {"dry_run": dry_run, "verbatim": [], "modified": [], "unchanged": [],
               "pr_body_file": None}
    bumped = False
    for entry in manifest["entries"]:
        repo, up, local = entry["repo"], entry["upstream_path"], entry["local_path"]
        ref = entry.get("ref", DEFAULT_REF)
        head = gh.head(repo, ref)
        item = {"local_path": local, "repo": repo, "upstream_path": up,
                "from": entry["upstream_sha"], "to": head}
        if entry["mode"] == "verbatim":
            text = gh.file_at(repo, up, head)
            if text is None:
                raise RuntimeError("%s: upstream %s missing at %s" % (local, up, head))
            if not verbatim_differs(text, read_local(root, local)):
                summary["unchanged"].append(local)
                continue
            summary["verbatim"].append(item)
            if not dry_run:
                write_local(root, local, text)
                entry["upstream_sha"] = head
                bumped = True
        elif entry["mode"] == "modified":
            if not path_changed(gh, repo, up, entry["upstream_sha"], head):
                summary["unchanged"].append(local)
                continue
            old = gh.file_at(repo, up, entry["upstream_sha"])
            new = gh.file_at(repo, up, head)
            diff = upstream_diff(old, new, up, entry["upstream_sha"], head)
            item["title"] = issue_title(local)
            item["upstream_missing"] = new is None
            item["diff"] = diff
            item["body"] = issue_body(entry, head, diff)
            summary["modified"].append(item)
        else:
            raise RuntimeError("%s: unknown mode %r" % (local, entry["mode"]))

    if dry_run:
        return summary
    if bumped:
        dump_manifest(manifest_path, manifest)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        if summary["verbatim"]:
            p = os.path.join(out_dir, "pr-body.md")
            _write(p, pr_body(summary["verbatim"]))
            summary["pr_body_file"] = p
        for item in summary["modified"]:
            base = os.path.join(out_dir, "issue-" + slug(item["local_path"]))
            _write(base + ".diff", item.pop("diff"))
            _write(base + ".md", item.pop("body"))
            item["diff_file"], item["body_file"] = base + ".diff", base + ".md"
        _write(os.path.join(out_dir, "summary.json"), json.dumps(summary, indent=2) + "\n")
    return summary


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def mark_synced(gh, manifest_path, local_path):
    manifest = load_manifest(manifest_path)
    hits = [e for e in manifest["entries"] if e["local_path"] == local_path]
    if not hits:
        raise SystemExit("no manifest entry with local_path %r" % local_path)
    for e in hits:
        e["upstream_sha"] = gh.head(e["repo"], e.get("ref", DEFAULT_REF))
    dump_manifest(manifest_path, manifest)
    return hits[0]["upstream_sha"]


VERBATIM_BRANCH = "upstream-sync/verbatim"
PR_TITLE = "upstream-sync: verbatim copies"


def subprocess_run(args):
    import subprocess
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as e:
        print("command failed (exit %s): %s" % (e.returncode, " ".join(args)), file=sys.stderr)
        print("stderr: %s" % (e.stderr or "").strip(), file=sys.stderr)
        print("stdout: %s" % (e.stdout or "").strip(), file=sys.stderr)
        if list(args[:3]) == ["gh", "pr", "create"]:
            print("note: falling back to an issue linking branch %s" % VERBATIM_BRANCH,
                  file=sys.stderr)
        raise


def find_open_issue(run_cmd, title):
    """Number of an open issue with exactly this title, or None."""
    found = json.loads(run_cmd(["gh", "issue", "list", "--state", "open", "--search",
                                '"%s" in:title' % title, "--json", "number,title"]) or "[]")
    hit = [i for i in found if i["title"] == title]
    return hit[0]["number"] if hit else None


def fallback_body(pr_body_file):
    """Write PR body + branch/compare link next to pr_body_file; return its path."""
    with open(pr_body_file, encoding="utf-8") as f:
        body = f.read()
    repo = os.environ.get("GITHUB_REPOSITORY")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    link = ("%s/%s/compare/%s?expand=1" % (server, repo, VERBATIM_BRANCH) if repo
            else "compare `%s` against the default branch" % VERBATIM_BRANCH)
    body += ("\n\n---\n\nCould not open the PR (GitHub Actions may not create PRs here). "
             "Changes are pushed to branch `%s`; open the PR by hand: %s\n" % (VERBATIM_BRANCH, link))
    path = os.path.join(os.path.dirname(os.path.abspath(pr_body_file)), "verbatim-issue.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return path


def publish_verbatim(summary, manifest_rel, run_cmd):
    import subprocess
    open_prs = json.loads(run_cmd(["gh", "pr", "list", "--head", VERBATIM_BRANCH,
                                   "--state", "open", "--json", "number"]) or "[]")
    if open_prs:
        return "skip PR: #%s already open" % open_prs[0]["number"]
    files = [it["local_path"] for it in summary["verbatim"]] + [manifest_rel]
    run_cmd(["git", "checkout", "-B", VERBATIM_BRANCH])
    run_cmd(["git", "add", "--"] + files)
    run_cmd(["git", "commit", "-m", "chore: sync verbatim upstream copies"])
    run_cmd(["git", "push", "--force", "origin", VERBATIM_BRANCH])
    try:
        run_cmd(["gh", "pr", "create", "--head", VERBATIM_BRANCH, "--title", PR_TITLE,
                 "--body-file", summary["pr_body_file"]])
        return "opened PR from %s" % VERBATIM_BRANCH
    except subprocess.CalledProcessError:
        pass
    n = find_open_issue(run_cmd, PR_TITLE)
    if n is not None:
        return "skip fallback issue: #%s already open for %s" % (n, VERBATIM_BRANCH)
    run_cmd(["gh", "issue", "create", "--title", PR_TITLE,
             "--body-file", fallback_body(summary["pr_body_file"])])
    return "PR create failed; opened issue: %s" % PR_TITLE


def publish(summary, manifest_rel, run_cmd=subprocess_run):
    """Open one PR for verbatim changes (an issue linking the branch if PR
    creation fails) and one issue per modified file via git + gh, skipping
    any already open. Each step runs even if an earlier one failed. Returns
    action strings; failed steps start with "failed:". Needs --out (body
    files) and a non-dry run."""
    import subprocess
    actions = []
    if summary["verbatim"]:
        try:
            actions.append(publish_verbatim(summary, manifest_rel, run_cmd))
        except subprocess.CalledProcessError as e:
            actions.append("failed: verbatim PR (%s)" % " ".join(map(str, e.cmd[:3])))
    for it in summary["modified"]:
        try:
            n = find_open_issue(run_cmd, it["title"])
            if n is not None:
                actions.append("skip issue: #%s already open for %s" % (n, it["local_path"]))
                continue
            run_cmd(["gh", "issue", "create", "--title", it["title"], "--body-file", it["body_file"]])
            actions.append("opened issue: %s" % it["title"])
        except subprocess.CalledProcessError as e:
            actions.append("failed: issue for %s (%s)" % (it["local_path"], " ".join(map(str, e.cmd[:3]))))
    return actions


def report(summary):
    out = []
    tag = "would " if summary["dry_run"] else ""
    for it in summary["verbatim"]:
        out.append("verbatim changed: %s (%s%s -> %s)" % (
            it["local_path"], tag + "update ", it["from"][:7], it["to"][:7]))
    for it in summary["modified"]:
        out.append("modified upstream changed: %s (%s..%s)%s" % (
            it["local_path"], it["from"][:7], it["to"][:7],
            " [upstream file deleted]" if it.get("upstream_missing") else ""))
    for p in summary["unchanged"]:
        out.append("unchanged: %s" % p)
    n = len(summary["verbatim"]) + len(summary["modified"])
    out.append("no changes" if n == 0 else "%d change(s)" % n)
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--out", help="dir for summary.json and PR/issue body files")
    ap.add_argument("--manifest", default=os.path.join(repo_root(), "upstream.json"))
    ap.add_argument("--mark-synced", metavar="LOCAL_PATH",
                    help="set that entry's upstream_sha to upstream HEAD (after porting)")
    ap.add_argument("--publish", action="store_true",
                    help="CI: open the verbatim PR and modified-file issues via git + gh")
    args = ap.parse_args(argv)
    gh = GitHub(token=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
    root = os.path.dirname(os.path.abspath(args.manifest))
    if args.mark_synced:
        sha = mark_synced(gh, args.manifest, args.mark_synced)
        print("%s marked synced at %s" % (args.mark_synced, sha))
        return 0
    if args.publish and (args.dry_run or not args.out):
        ap.error("--publish needs --out and no --dry-run")
    summary = run(gh, root, args.manifest, dry_run=args.dry_run, out_dir=args.out)
    print(report(summary))
    if args.publish:
        rel = os.path.relpath(os.path.abspath(args.manifest), root).replace(os.sep, "/")
        actions = publish(summary, rel)
        for line in actions:
            print(line)
        if any(a.startswith("failed:") for a in actions):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
