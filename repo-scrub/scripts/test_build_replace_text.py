#!/usr/bin/env python3
"""Stdlib unittest coverage for build_replace_text.py. Run with:

    python -m unittest discover -s repo-scrub/scripts -p "test_*.py" -v
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "build_replace_text.py"
_spec = importlib.util.spec_from_file_location("build_replace_text", MODULE_PATH)
brt = importlib.util.module_from_spec(_spec)
sys.modules["build_replace_text"] = brt
_spec.loader.exec_module(brt)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class TestBuildReplaceText(unittest.TestCase):
    def _run(self, tmp: Path, findings: dict, gitleaks_entries: list, ids: list):
        gitleaks_path = tmp / "gitleaks-report.json"
        gitleaks_path.write_text(json.dumps(gitleaks_entries), encoding="utf-8")
        findings_path = tmp / "findings.json"
        findings_path.write_text(json.dumps(findings), encoding="utf-8")
        out_path = tmp / "expressions.txt"

        argv = [
            "build_replace_text.py",
            "--gitleaks",
            str(gitleaks_path),
            "--findings",
            str(findings_path),
            "--ids",
            *ids,
            "--out",
            str(out_path),
        ]
        old_argv = sys.argv
        sys.argv = argv
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                rc = brt.main()
        finally:
            sys.argv = old_argv
        return rc, out_path, captured.getvalue()

    def test_recovers_value_by_fingerprint_and_never_prints_it(self):
        secret_value = "fake-test-secret-value-0001"
        findings = {
            "S1": {
                "type": "secret",
                "rule": "aws-access-key",
                "secret_sha256": sha256_hex(secret_value),
                "paths": [{"path": "config/dev.env", "line": 3}],
                "commits": ["c1"],
            }
        }
        gitleaks_entries = [
            {
                "RuleID": "aws-access-key",
                "Secret": secret_value,
                "File": "config/dev.env",
                "StartLine": 3,
                "Commit": "c1",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            rc, out_path, stdout = self._run(
                Path(tmp), findings, gitleaks_entries, ["S1"]
            )
            content = out_path.read_text(encoding="utf-8")

        self.assertEqual(rc, 0)
        self.assertEqual(content.strip(), f"literal:{secret_value}==>REDACTED")
        self.assertNotIn(secret_value, stdout)

    def test_skips_non_secret_finding(self):
        findings = {
            "L1": {"type": "large", "path": "big.bin", "accumulated_bytes": 999, "commits": []}
        }
        with tempfile.TemporaryDirectory() as tmp:
            rc, out_path, stdout = self._run(Path(tmp), findings, [], ["L1"])
            content = out_path.read_text(encoding="utf-8")

        self.assertEqual(rc, 1)
        self.assertEqual(content, "")
        self.assertIn("L1", stdout)
        self.assertIn("not a secret finding", stdout)

    def test_skips_unknown_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out_path, stdout = self._run(Path(tmp), {}, [], ["S99"])
        self.assertEqual(rc, 1)
        self.assertIn("not found in findings.json", stdout)

    def test_skips_when_fingerprint_not_in_gitleaks_report(self):
        findings = {
            "S1": {
                "type": "secret",
                "rule": "generic-api-key",
                "secret_sha256": "deadbeef" * 8,
                "paths": [],
                "commits": [],
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            rc, out_path, stdout = self._run(Path(tmp), findings, [], ["S1"])
        self.assertEqual(rc, 1)
        self.assertIn("could not recover value", stdout)

    def test_skips_location_only_finding(self):
        findings = {
            "S1": {
                "type": "secret",
                "rule": "private-key",
                "secret_sha256": None,
                "location_key": "c1:k.pem:private-key:1",
                "paths": [],
                "commits": [],
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            rc, out_path, stdout = self._run(Path(tmp), findings, [], ["S1"])
        self.assertEqual(rc, 1)
        self.assertIn("no secret value", stdout)

    def test_no_ids_writes_empty_file_and_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out_path, _ = self._run(Path(tmp), {}, [], [])
            self.assertTrue(out_path.exists())
            content = out_path.read_text(encoding="utf-8")
        self.assertEqual(rc, 0)
        self.assertEqual(content, "")

    def test_only_personal_ids_succeeds_with_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out_path, stdout = self._run(Path(tmp), {}, [], ["P1", "P2"])
            content = out_path.read_text(encoding="utf-8")
        self.assertEqual(rc, 0)
        self.assertEqual(content, "")
        self.assertIn("P1 P2", stdout)
        self.assertNotIn("not found in findings.json", stdout)

    def test_multiple_ids_writes_multiple_lines(self):
        v1, v2 = "secret-one", "secret-two"
        findings = {
            "S1": {"type": "secret", "rule": "r1", "secret_sha256": sha256_hex(v1), "paths": [], "commits": []},
            "S2": {"type": "secret", "rule": "r2", "secret_sha256": sha256_hex(v2), "paths": [], "commits": []},
        }
        gitleaks_entries = [
            {"RuleID": "r1", "Secret": v1, "File": "a.txt", "StartLine": 1, "Commit": "c1"},
            {"RuleID": "r2", "Secret": v2, "File": "b.txt", "StartLine": 1, "Commit": "c2"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            rc, out_path, _ = self._run(Path(tmp), findings, gitleaks_entries, ["S1", "S2"])
            lines = out_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(rc, 0)
        self.assertEqual(len(lines), 2)
        self.assertIn(f"literal:{v1}==>REDACTED", lines)
        self.assertIn(f"literal:{v2}==>REDACTED", lines)


if __name__ == "__main__":
    unittest.main()
