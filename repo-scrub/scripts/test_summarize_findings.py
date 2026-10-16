#!/usr/bin/env python3
"""Stdlib unittest coverage for summarize_findings.py. Run with:

    python -m unittest discover -s repo-scrub/scripts -p "test_*.py" -v

No network, no real git/gitleaks/filter-repo calls - fixtures only.
"""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "summarize_findings.py"
_spec = importlib.util.spec_from_file_location("summarize_findings", MODULE_PATH)
sf = importlib.util.module_from_spec(_spec)
sys.modules["summarize_findings"] = sf
_spec.loader.exec_module(sf)


# The exact row format `git filter-repo --analyze` writes to
# path-all-sizes.txt: two leading spaces, unpacked size right-justified
# in 10, a space, packed size right-justified in 10, a space, then
# "<present>" or a "YYYY-MM-DD" deletion date left-justified in 10,
# a space, then the path (which may itself contain spaces).
ROW_FMT = "  {:>10} {:>10} {:<10s} {}"

HEADER = "     Unpacked      Packed Date       Path\n"


def make_analysis_dir(tmp: Path, rows) -> Path:
    analysis_dir = tmp / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    lines = [HEADER]
    for unpacked, packed, date_or_present, path in rows:
        lines.append(ROW_FMT.format(unpacked, packed, date_or_present, path) + "\n")
    (analysis_dir / "path-all-sizes.txt").write_text("".join(lines), encoding="utf-8")
    return analysis_dir


class TestLargeFileParsing(unittest.TestCase):
    """Reproduces and then guards the <present>/path parse bug from issue #18:
    the old regex captured the date column into the path group, e.g.
    "<present>  assets/demo.mov" or "2026-01-02 big.bin"."""

    def test_present_and_dated_rows_and_spaces_in_path(self):
        rows = [
            (1_234_567, 65_432, "<present>", "assets/demo.mov"),
            (2_345_678, 123_456, "2026-01-02", "big.bin"),
            (999, 500, "<present>", "path with spaces/file name.txt"),
            (42, 10, "2025-12-31", "another/path here.bin"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            analysis_dir = make_analysis_dir(Path(tmp), rows)
            findings = sf.load_filter_repo_analysis(analysis_dir, threshold_bytes=1)

        paths = {f["path"] for f in findings}

        self.assertIn("assets/demo.mov", paths)
        self.assertIn("big.bin", paths)
        self.assertIn("path with spaces/file name.txt", paths)
        self.assertIn("another/path here.bin", paths)

        # None of the parsed paths should have swallowed the date/present
        # column ahead of the real path.
        for path in paths:
            self.assertFalse(path.startswith("<present>"), path)
            self.assertFalse(path[:10].count("-") == 2, path)

    def test_threshold_filters_small_paths(self):
        rows = [
            (10, 5, "<present>", "tiny.txt"),
            (5_000_000, 4_000_000, "<present>", "big.bin"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            analysis_dir = make_analysis_dir(Path(tmp), rows)
            findings = sf.load_filter_repo_analysis(
                analysis_dir, threshold_bytes=1_000_000
            )
        paths = {f["path"] for f in findings}
        self.assertEqual(paths, {"big.bin"})

    def test_missing_analysis_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            findings = sf.load_filter_repo_analysis(
                Path(tmp) / "nope", threshold_bytes=1
            )
        self.assertEqual(findings, [])

    def test_field_is_accumulated_bytes_not_size_bytes(self):
        # Size here is accumulated across every version of the path in
        # history, not one blob's size - name it accordingly.
        rows = [(100, 50, "<present>", "f.bin")]
        with tempfile.TemporaryDirectory() as tmp:
            analysis_dir = make_analysis_dir(Path(tmp), rows)
            findings = sf.load_filter_repo_analysis(analysis_dir, threshold_bytes=1)
        self.assertEqual(findings[0]["accumulated_bytes"], 100)
        self.assertNotIn("size_bytes", findings[0])


class TestGitleaksDedupe(unittest.TestCase):
    def _write_report(self, tmp: Path, entries) -> Path:
        report = tmp / "gitleaks-report.json"
        report.write_text(json.dumps(entries), encoding="utf-8")
        return report

    def test_dedupes_same_rule_and_secret_across_commits(self):
        entries = [
            {
                "RuleID": "aws-access-key",
                "Secret": "fake-test-secret-value-0001",
                "File": "config/dev.env",
                "StartLine": 3,
                "Commit": "commit1",
            },
            {
                "RuleID": "aws-access-key",
                "Secret": "fake-test-secret-value-0001",
                "File": "config/prod.env",
                "StartLine": 7,
                "Commit": "commit2",
            },
            {
                "RuleID": "aws-access-key",
                "Secret": "fake-test-secret-value-0001",
                "File": "config/dev.env",
                "StartLine": 3,
                "Commit": "commit3",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            report = self._write_report(Path(tmp), entries)
            findings = sf.load_gitleaks(report)

        self.assertEqual(len(findings), 1)
        entry = findings[0]
        self.assertEqual(entry["rule"], "aws-access-key")
        self.assertEqual(
            entry["secret_sha256"],
            hashlib.sha256(b"fake-test-secret-value-0001").hexdigest(),
        )
        self.assertEqual(sorted(entry["commits"]), ["commit1", "commit2", "commit3"])
        self.assertEqual(len(entry["paths"]), 2)
        self.assertIn({"path": "config/dev.env", "line": 3}, entry["paths"])
        self.assertIn({"path": "config/prod.env", "line": 7}, entry["paths"])
        # No raw secret value anywhere in the finding.
        dumped = json.dumps(entry)
        self.assertNotIn("fake-test-secret-value-0001", dumped)

    def test_empty_secret_keyed_by_location(self):
        base = {"RuleID": "generic-api-key", "Secret": "", "File": "a.txt", "StartLine": 1, "Commit": "c1"}
        entries = [
            base,
            dict(base, File="b.txt"),
            dict(base, StartLine=2),
            dict(base, Commit="c2"),
            dict(base),  # exact duplicate
        ]
        with tempfile.TemporaryDirectory() as tmp:
            findings = sf.load_gitleaks(self._write_report(Path(tmp), entries))
        self.assertEqual(len(findings), 4)
        for f in findings:
            self.assertIsNone(f["secret_sha256"])
            self.assertTrue(f["location_key"])
            self.assertEqual(len(f["paths"]), 1)
        self.assertEqual(len({f["location_key"] for f in findings}), 4)

    def test_missing_secret_key_and_startline(self):
        entries = [
            {"RuleID": "r", "File": "a.txt", "Commit": "c1"},
            {"RuleID": "r", "File": "b.txt", "Commit": "c1"},
            {"RuleID": "r", "File": "a.txt", "Commit": "c1"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            findings = sf.load_gitleaks(self._write_report(Path(tmp), entries))
        self.assertEqual(len(findings), 2)
        self.assertIsNone(findings[0]["secret_sha256"])

    def test_empty_secret_prefers_fingerprint(self):
        entries = [
            {"RuleID": "r", "Secret": "", "File": "a", "StartLine": 1, "Commit": "c1", "Fingerprint": "c1:a:r:1"},
            {"RuleID": "r", "Secret": "", "File": "a", "StartLine": 1, "Commit": "c1", "Fingerprint": "c1:a:r:1"},
            {"RuleID": "r", "Secret": "", "File": "a", "StartLine": 1, "Commit": "c1", "Fingerprint": "c1:a:r:9"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            findings = sf.load_gitleaks(self._write_report(Path(tmp), entries))
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["location_key"], "c1:a:r:1")

    def test_different_secrets_stay_separate(self):
        entries = [
            {
                "RuleID": "generic-api-key",
                "Secret": "secret-one",
                "File": "a.txt",
                "StartLine": 1,
                "Commit": "c1",
            },
            {
                "RuleID": "generic-api-key",
                "Secret": "secret-two",
                "File": "b.txt",
                "StartLine": 1,
                "Commit": "c2",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            report = self._write_report(Path(tmp), entries)
            findings = sf.load_gitleaks(report)
        self.assertEqual(len(findings), 2)

    def test_missing_report_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            findings = sf.load_gitleaks(Path(tmp) / "nope.json")
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
