#!/usr/bin/env python3
"""Merge gitleaks JSON + git-filter-repo --analyze output into one findings
list with stable IDs (S1, S2... secrets / L1, L2... large blobs).

Usage:
    python summarize_findings.py \
        --gitleaks gitleaks-report.json \
        --analysis-dir .git/filter-repo/analysis \
        --out findings.json \
        [--large-threshold-bytes 1000000]

Writes findings.json and prints a human-readable table to stdout. Secret
findings are deduped by (RuleID, Secret), or by location (gitleaks Fingerprint,
else RuleID+File+StartLine+Commit) when Secret is empty, and never carry a raw
secret value - only a sha256 fingerprint, rule, paths/lines, and commits. (git-sizer is not
used; before/after repo size comes from `git count-objects -vH` instead.)
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def load_gitleaks(path: Path) -> list[dict]:
    """Merge gitleaks JSON entries into one finding per unique (RuleID,
    Secret) pair - the same leaked value showing up in several commits or
    files is one secret, not N findings. Entries with an empty/missing Secret
    can't be grouped by value, so they key on location instead (gitleaks
    Fingerprint if set, else RuleID+File+StartLine+Commit) and get their own
    finding with secret_sha256=null and a location_key. Never keeps the raw secret value:
    only its sha256 fingerprint, so it can be looked back up against the
    gitleaks report (which build_replace_text.py reads separately) without
    ever writing the value itself to findings.json.
    """
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)

    grouped: dict[tuple, dict] = {}
    order: list[tuple] = []
    for entry in raw:
        secret = entry.get("Secret", "")
        rule = entry.get("RuleID", "unknown-rule")
        if secret:
            key = (rule, secret)
            location_key = None
        else:
            location_key = entry.get("Fingerprint") or ":".join(
                str(entry.get(k) if entry.get(k) is not None else "")
                for k in ("RuleID", "File", "StartLine", "Commit")
            )
            key = (rule, "", location_key)
        if key not in grouped:
            grouped[key] = {
                "type": "secret",
                "rule": rule,
                "secret_sha256": (
                    hashlib.sha256(secret.encode("utf-8")).hexdigest()
                    if secret
                    else None
                ),
                "paths": [],
                "commits": [],
            }
            if location_key is not None:
                grouped[key]["location_key"] = location_key
            order.append(key)
        g = grouped[key]
        location = {"path": entry.get("File", "unknown"), "line": entry.get("StartLine")}
        if location not in g["paths"]:
            g["paths"].append(location)
        commit = entry.get("Commit")
        if commit and commit not in g["commits"]:
            g["commits"].append(commit)

    return [grouped[k] for k in order]


def load_filter_repo_analysis(analysis_dir: Path, threshold_bytes: int) -> list[dict]:
    """Parse path-all-sizes.txt (or path-all-sizes-and-checkouts.txt) from
    `git filter-repo --analyze` output. Each row is
    "  {unpacked:>10} {packed:>10} {<present>-or-date:<10} {path}".
    """
    candidates = [
        analysis_dir / "path-all-sizes.txt",
        analysis_dir / "path-all-sizes-and-checkouts.txt",
    ]
    report = next((c for c in candidates if c.exists()), None)
    if report is None:
        return []

    findings = []
    # Explicit date-or-<present> column so it can't be swallowed into the
    # path group - the path is everything after that column, verbatim
    # (it may itself contain spaces).
    size_re = re.compile(
        r"^\s*([\d,]+)\s+([\d,]+)\s+(?:<present>|\d{4}-\d{2}-\d{2})\s+(.+?)\s*$"
    )
    with report.open(encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines[1:]:  # skip header row
        m = size_re.match(line)
        if not m:
            continue
        max_size = int(m.group(1).replace(",", ""))
        path = m.group(3)
        if max_size >= threshold_bytes:
            findings.append(
                {
                    "type": "large",
                    "path": path,
                    # Cumulative size across every version of this path in
                    # history, not one blob's size - filter-repo's column.
                    "accumulated_bytes": max_size,
                    "commits": [],
                }
            )
    return findings


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}TB"


def table_row(fid: str, entry: dict) -> str:
    """One report-table row. Large blobs have no commit list: Commits is `-`."""
    if entry["type"] == "secret":
        detail = entry["rule"]
        locations = entry.get("paths", [])
        path = locations[0]["path"] if locations else "unknown"
        if len(locations) > 1:
            path += f" (+{len(locations) - 1} more)"
        commits = str(len(entry.get("commits", [])))
    else:
        detail = f"{human_size(entry['accumulated_bytes'])} accum. (all versions)"
        path = entry["path"]
        commits = "-"
    path = path[:38]
    return f"{fid:<5}{entry['type']:<8}{path:<40}{detail:<45}{commits}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gitleaks", type=Path, required=True)
    ap.add_argument("--analysis-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--large-threshold-bytes", type=int, default=1_000_000)
    args = ap.parse_args()

    secrets = load_gitleaks(args.gitleaks)
    large = load_filter_repo_analysis(args.analysis_dir, args.large_threshold_bytes)

    findings = {}
    for i, s in enumerate(secrets, start=1):
        findings[f"S{i}"] = s
    for i, entry in enumerate(large, start=1):
        findings[f"L{i}"] = entry

    args.out.write_text(json.dumps(findings, indent=2), encoding="utf-8")

    # human-readable table - never print secret values, only the fingerprint
    print(f"{'ID':<5}{'Type':<8}{'Path(s)':<40}{'Detail (rule / accum. size, all versions)':<45}Commits")
    for fid, entry in findings.items():
        print(table_row(fid, entry))

    n_secrets = len(secrets)
    n_large = len(large)
    total_large_bytes = sum(e["accumulated_bytes"] for e in large)
    print(
        f"\n{n_secrets} secret(s), {n_large} large blob(s) "
        f"totaling {human_size(total_large_bytes)}."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
