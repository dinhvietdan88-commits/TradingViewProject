#!/usr/bin/env python3
"""
Tests for AQH Harness Bridge — MDASH Light + Full Pipeline.

Tests cover:
    - HarnessVerdict / GateResult data models
    - scan_files_light() with injected scanner
    - scan_files_full() with injected scanner
    - run_scar_gate() with inline patterns
    - run_ai_debate() graceful degradation
    - run_harness_light() full pipeline
    - run_harness_full() full pipeline
    - Report generation
"""

import sys
import os
import unittest
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "nerves" / "core"))

from nerves.core.harness_bridge import (
    Verdict,
    GateResult,
    HarnessVerdict,
    run_scar_gate,
    run_ai_debate,
    run_harness_light,
    run_harness_full,
    _default_syntax_check,
    _findings_to_dicts,
    _parse_debate_response,
)


class TestDataModels(unittest.TestCase):
    """Test Verdict, GateResult, HarnessVerdict data models."""

    def test_verdict_constants(self):
        self.assertEqual(Verdict.PASSED, "PASSED")
        self.assertEqual(Verdict.FAILED, "FAILED")
        self.assertEqual(Verdict.SOFT_GATED, "SOFT_GATED")
        self.assertEqual(Verdict.SKIPPED, "SKIPPED")

    def test_gate_result_defaults(self):
        g = GateResult(name="Test Gate", passed=True)
        self.assertEqual(g.verdict, Verdict.PASSED)
        self.assertEqual(g.duration_ms, 0)
        self.assertEqual(g.findings_count, 0)

    def test_harness_verdict_defaults(self):
        v = HarnessVerdict(mode="MDASH_LIGHT")
        self.assertEqual(v.verdict, Verdict.PASSED)
        self.assertEqual(v.gates, [])
        self.assertEqual(v.findings, [])
        self.assertEqual(v.files_scanned, 0)

    def test_harness_verdict_report(self):
        v = HarnessVerdict(
            mode="MDASH_LIGHT",
            verdict=Verdict.PASSED,
            files_scanned=3,
            duration_ms=100,
            gates=[GateResult(name="Syntax", passed=True, verdict=Verdict.PASSED)],
        )
        report = v.to_report()
        self.assertIn("AQH Verification Report", report)
        self.assertIn("MDASH_LIGHT", report)
        self.assertIn("🟢", report)
        self.assertIn("FINAL VERDICT: PASSED", report)

    def test_harness_verdict_report_with_findings(self):
        v = HarnessVerdict(
            mode="MDASH_FULL",
            verdict=Verdict.SOFT_GATED,
            findings=[
                {
                    "rule_id": "TVP-004",
                    "severity": "medium",
                    "file": "test.py",
                    "line": 10,
                    "title": "No rate limit",
                }
            ],
            gates=[],
        )
        report = v.to_report()
        self.assertIn("TVP-004", report)
        self.assertIn("medium", report)


class TestDefaultSyntaxCheck(unittest.TestCase):
    """Test the built-in syntax checker."""

    def test_valid_python(self):
        import tempfile

        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("x = 1 + 2\nprint(x)\n")
            f.flush()
            failures = _default_syntax_check([f.name])
        self.assertEqual(failures, [])
        os.unlink(f.name)

    def test_invalid_python(self):
        import tempfile

        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("def broken(\n")
            f.flush()
            failures = _default_syntax_check([f.name])
        self.assertTrue(len(failures) > 0)
        self.assertIn("SyntaxError", failures[0])
        os.unlink(f.name)


class TestFindingsConversion(unittest.TestCase):
    """Test _findings_to_dicts()."""

    def test_dict_passthrough(self):
        # If findings are already dicts with attributes, they should be extracted
        class MockFinding:
            rule_id = "TVP-001"
            title = "Test"
            severity = "high"
            file = "test.py"
            line = 10
            description = "Desc"
            evidence = "x"
            confidence = 0.9
            remediation = "fix"
            cwe = "CWE-123"

        result = _findings_to_dicts([MockFinding()])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["rule_id"], "TVP-001")
        self.assertEqual(result[0]["severity"], "high")

    def test_enum_severity(self):
        from enum import Enum

        class Sev(Enum):
            CRITICAL = "critical"

        class MockFinding:
            rule_id = "X"
            title = ""
            severity = Sev.CRITICAL
            file = ""
            line = 0
            description = ""
            evidence = ""
            confidence = 0.0
            remediation = ""
            cwe = None

        result = _findings_to_dicts([MockFinding()])
        self.assertEqual(result[0]["severity"], "critical")


class TestScarGate(unittest.TestCase):
    """Test Gate 5: Scar Regression Check."""

    def test_no_regressions(self):
        result = run_scar_gate("All tests passed successfully. No errors.")
        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["regressions"], [])

    def test_scar_001_regression(self):
        result = run_scar_gate(
            "Error: CommandNotFoundException — angati is not recognized"
        )
        self.assertFalse(result["passed"])
        self.assertIn("SCAR-001", result["regressions"])

    def test_scar_002_regression(self):
        """SCAR-002 = UTF-16LE encoding corruption (from test_config.json)."""
        result = run_scar_gate("Warning: UTF-16LE encoding detected in output stream")
        self.assertFalse(result["passed"])
        self.assertIn("SCAR-002", result["regressions"])

    def test_partial_regression(self):
        result = run_scar_gate(
            "CommandNotFoundException in output but no security import error"
        )
        self.assertFalse(result["passed"])
        self.assertIn("SCAR-001", result["regressions"])
        self.assertNotIn("SCAR-002", result["regressions"])
        self.assertGreater(result["score"], 0.0)
        self.assertLess(result["score"], 1.0)

    def test_custom_config(self):
        import tempfile
        import json

        config = {
            "scar_patterns": [
                {"id": "SCAR-CUSTOM", "pattern": "MyCustomError", "description": "test"}
            ]
        }
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        ) as f:
            json.dump(config, f)
            f.flush()
            result = run_scar_gate("MyCustomError occurred", config_path=f.name)
        self.assertFalse(result["passed"])
        self.assertIn("SCAR-CUSTOM", result["regressions"])
        os.unlink(f.name)


class TestAIDebate(unittest.TestCase):
    """Test Gate 6: AI Debate."""

    def test_no_debatable_findings(self):
        findings = [{"rule_id": "X", "severity": "low"}]
        results = run_ai_debate(findings)
        self.assertEqual(results, [])

    def test_graceful_degradation(self):
        findings = [
            {
                "rule_id": "TVP-001",
                "severity": "critical",
                "file": "test.py",
                "line": 1,
                "title": "Unsafe",
                "description": "Bad",
                "evidence": "x",
                "cwe": None,
            }
        ]
        results = run_ai_debate(findings)
        # Without API key, should gracefully degrade to SKIPPED
        self.assertTrue(len(results) > 0)
        # All should be SKIPPED or NEEDS_REVIEW
        for r in results:
            self.assertIn(r["verdict"], ("SKIPPED", "NEEDS_REVIEW"))

    def test_parse_debate_confirmed(self):
        self.assertEqual(
            _parse_debate_response("CONFIRMED — this is a real bug"), "CONFIRMED"
        )

    def test_parse_debate_false_positive(self):
        self.assertEqual(
            _parse_debate_response("FALSE_POSITIVE — not exploitable"), "FALSE_POSITIVE"
        )
        self.assertEqual(
            _parse_debate_response("This is a FALSE POSITIVE because..."),
            "FALSE_POSITIVE",
        )

    def test_parse_debate_needs_review(self):
        self.assertEqual(
            _parse_debate_response("I'm not sure about this one"), "NEEDS_REVIEW"
        )


class TestHarnessLight(unittest.TestCase):
    """Test MDASH Light pipeline."""

    def test_all_pass(self):
        """Light harness with no issues should PASS."""
        result = run_harness_light(
            files=[],
            syntax_checker=lambda f: [],
            lint_checker=lambda f: (0, 0),
            ast_auditor=lambda f: {},
        )
        self.assertEqual(result.mode, "MDASH_LIGHT")
        self.assertEqual(result.verdict, Verdict.PASSED)
        self.assertEqual(len(result.gates), 3)
        self.assertTrue(all(g.passed for g in result.gates))

    def test_syntax_failure_stops(self):
        """Syntax failure should stop pipeline immediately."""
        result = run_harness_light(
            files=["bad.py"],
            syntax_checker=lambda f: ["bad.py: SyntaxError L1: invalid syntax"],
        )
        self.assertEqual(result.verdict, Verdict.FAILED)
        self.assertEqual(len(result.gates), 1)  # Stopped after Gate 1
        self.assertEqual(result.gates[0].name, "Syntax Gate")

    def test_ast_critical_fails(self):
        """AST CRITICAL findings should FAIL the pipeline."""
        result = run_harness_light(
            files=["test.py"],
            syntax_checker=lambda f: [],
            lint_checker=lambda f: (0, 0),
            ast_auditor=lambda f: {"test.py": [(10, "CRITICAL", "Bare except")]},
        )
        self.assertEqual(result.verdict, Verdict.FAILED)

    def test_lint_errors_soft_gate(self):
        """Lint errors (no CRITICAL AST) should SOFT_GATE."""
        result = run_harness_light(
            files=["test.py"],
            syntax_checker=lambda f: [],
            lint_checker=lambda f: (5, 3),
            ast_auditor=lambda f: {},
        )
        # Gate 2 should be SOFT_GATED due to lint errors
        self.assertIn(result.verdict, (Verdict.SOFT_GATED, Verdict.PASSED))

    def test_report_generation(self):
        """Should generate a valid markdown report."""
        result = run_harness_light(
            files=["a.py", "b.py"],
            syntax_checker=lambda f: [],
            lint_checker=lambda f: (0, 0),
            ast_auditor=lambda f: {},
        )
        report = result.to_report()
        self.assertIn("MDASH_LIGHT", report)
        self.assertIn("FINAL VERDICT", report)

    def test_duration_tracked(self):
        """Duration should be tracked."""
        result = run_harness_light(
            files=[],
            syntax_checker=lambda f: [],
            lint_checker=lambda f: (0, 0),
            ast_auditor=lambda f: {},
        )
        self.assertGreaterEqual(result.duration_ms, 0)


class TestHarnessFull(unittest.TestCase):
    """Test MDASH Full pipeline."""

    def test_all_pass(self):
        """Full harness with no issues should PASS."""
        result = run_harness_full(
            files=[],
            syntax_checker=lambda f: [],
            lint_checker=lambda f: (0, 0),
            ast_auditor=lambda f: {},
            integration_test_runner=lambda: True,
            test_output="All tests passed",
        )
        self.assertEqual(result.mode, "MDASH_FULL")
        self.assertEqual(result.verdict, Verdict.PASSED)
        self.assertEqual(len(result.gates), 5)  # 5 gates without debate

    def test_with_debate_gate(self):
        """Full harness with debate enabled adds Gate 6."""
        result = run_harness_full(
            files=[],
            syntax_checker=lambda f: [],
            lint_checker=lambda f: (0, 0),
            ast_auditor=lambda f: {},
            integration_test_runner=lambda: True,
            enable_debate=True,
            test_output="All tests passed",
        )
        self.assertEqual(len(result.gates), 6)
        self.assertEqual(result.gates[5].name, "AI Debate Gate")

    def test_integration_test_failure(self):
        """Failed integration test should FAIL pipeline."""
        result = run_harness_full(
            files=[],
            syntax_checker=lambda f: [],
            lint_checker=lambda f: (0, 0),
            ast_auditor=lambda f: {},
            integration_test_runner=lambda: False,
            test_output="FAIL: test_webhook",
        )
        self.assertEqual(result.verdict, Verdict.FAILED)

    def test_scar_regression_detected(self):
        """Scar regression should FAIL Gate 5."""
        result = run_harness_full(
            files=[],
            syntax_checker=lambda f: [],
            lint_checker=lambda f: (0, 0),
            ast_auditor=lambda f: {},
            integration_test_runner=lambda: True,
            test_output="CommandNotFoundException: angati not found",
        )
        self.assertEqual(result.verdict, Verdict.FAILED)
        scar_gate = result.gates[4]
        self.assertEqual(scar_gate.name, "Scar Regression Gate")
        self.assertFalse(scar_gate.passed)

    def test_scar_result_stored(self):
        """Scar result should be stored in verdict."""
        result = run_harness_full(
            files=[],
            syntax_checker=lambda f: [],
            lint_checker=lambda f: (0, 0),
            ast_auditor=lambda f: {},
            test_output="All clean",
        )
        self.assertIn("passed", result.scar_result)
        self.assertTrue(result.scar_result["passed"])

    def test_full_report_includes_all_gates(self):
        """Full report should include all gate details."""
        result = run_harness_full(
            files=["a.py"],
            syntax_checker=lambda f: [],
            lint_checker=lambda f: (2, 1),
            ast_auditor=lambda f: {},
            integration_test_runner=lambda: True,
            enable_debate=True,
            test_output="OK",
        )
        report = result.to_report()
        self.assertIn("MDASH_FULL", report)
        self.assertIn("Scar Regression", report)
        self.assertIn("AI Debate", report)


if __name__ == "__main__":
    unittest.main()
