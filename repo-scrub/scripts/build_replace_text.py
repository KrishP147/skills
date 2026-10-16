#!/usr/bin/env python3
"""Build a git-filter-repo --replace-text expressions file for selected
secret findings.

findings.json only carries a secret_sha256 fingerprint per finding (see
summarize_findings.py) - the raw value is never written to disk there. This
script recovers the raw value by re-reading the original gitleaks report,
hashing each entry's Secret field, and matching it against the fingerprint
of each selected finding ID. The raw value is written straight to
expressions.txt and never printed to stdout or passed as a shell argument.

Usage:
    python build_replace_text.py \
        --gitleaks gitleaks-report.json \
        --findings findings.json \
        --ids S1 S3 \
        --out expressions.txt
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_values_by_fingerprint(gitleaks_path: Path) -> dict[str, str]:
    """Map secret_sha256 -> raw secret value, from a gitleaks report."""
    if not gitleaks_path.exists():
        return {}
    with gitleaks_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    by_fingerprint: dict[str, str] = {}
    for entry in raw:
        secret = entry.get("Secret", "")
        if not secret:
            continue
        by_fingerprint.setdefault(sha256_hex(secret), secret)
    return by_fingerprint


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gitleaks", type=Path, required=True)
    ap.add_argument("--findings", type=Path, required=True)
    ap.add_argument("--ids", nargs="+", required=True, help="Finding IDs to redact, e.g. S1 S3")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--replacement", default="REDACTED")
    args = ap.parse_args()

    findings = json.loads(args.findings.read_text(encoding="utf-8"))
    values_by_fingerprint = load_values_by_fingerprint(args.gitleaks)

    lines = []
    skipped = []
    for fid in args.ids:
        entry = findings.get(fid)
        if entry is None:
            skipped.append((fid, "not found in findings.json"))
            continue
        if entry.get("type") != "secret":
            skipped.append((fid, "not a secret finding - large-file removal uses --path, not --replace-text"))
            continue
        fingerprint = entry.get("secret_sha256")
        if not fingerprint and entry.get("location_key"):
            skipped.append((fid, "no secret value (empty gitleaks Secret) - scrub by --path or edit by hand"))
            continue
        value = values_by_fingerprint.get(fingerprint) if fingerprint else None
        if not value:
            skipped.append((fid, "could not recover value from gitleaks report (fingerprint mismatch or missing)"))
            continue
        lines.append(f"literal:{value}==>{args.replacement}")

    args.out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    # Never print the recovered values themselves - only counts/IDs.
    print(f"Wrote {len(lines)} replacement rule(s) to {args.out}")
    if skipped:
        print("Skipped:")
        for fid, reason in skipped:
            print(f"  {fid}: {reason}")

    return 0 if lines else 1


if __name__ == "__main__":
    sys.exit(main())
