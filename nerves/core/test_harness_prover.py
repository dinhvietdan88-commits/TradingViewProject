#!/usr/bin/env python3
"""
Tests for harness_prover.py — MDASH Stage 5 (Prove) implementation.
"""

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from nerves.core.harness_prover import (
    POC_TEMPLATES,
    SAFE_SKIP_RULES,
    HarnessProver,
    ProofResult,
)


class TestProofResult(unittest.TestCase):
    """Test ProofResult dataclass."""

    def test_defaults(self):
        r = ProofResult(finding_id="TVP-001", rule_id="TVP-001")
        self.assertEqual(r.status, "INCONCLUSIVE")
        self.assertEqual(r.poc_code, "")
        self.assertEqual(r.poc_output, "")
        self.assertEqual(r.duration_ms, 0)

    def test_proven_status(self):
        r = ProofResult(
            finding_id="STA-003",
            rule_id="STA-003",
            status="PROVEN",
            poc_output="EXPLOIT_SUCCESS: subprocess shell=False found",
        )
        self.assertEqual(r.status, "PROVEN")
        self.assertIn("EXPLOIT_SUCCESS", r.poc_output)


class TestPoCTemplates(unittest.TestCase):
    """Test PoC template coverage."""

    def test_all_templates_exist(self):
        """Verify we have templates for the expected rules."""
        expected_rules = [
            "TVP-001",
            "TVP-002",
            "TVP-003",
            "TVP-004",
            "TVP-005",
            "TVP-007",
            "STA-001",
            "STA-002",
            "STA-003",
            "STA-005",
            "SEC-001",
        ]
        for rule in expected_rules:
            self.assertIn(rule, POC_TEMPLATES, f"Missing PoC template for {rule}")

    def test_safe_skip_rules(self):
        """TVP-006 should be in SAFE_SKIP."""
        self.assertIn("TVP-006", SAFE_SKIP_RULES)

    def test_templates_have_file_placeholder(self):
        """All templates should have {file} placeholder."""
        for rule_id, template in POC_TEMPLATES.items():
            self.assertIn(
                "{file}", template, f"{rule_id} template missing {{file}} placeholder"
            )

    def test_templates_have_exit_codes(self):
        """All templates should use sys.exit(0) for success and sys.exit(1) for failure."""
        for rule_id, template in POC_TEMPLATES.items():
            self.assertIn(
                "sys.exit(0)", template, f"{rule_id}: missing success exit code"
            )
            self.assertIn(
                "sys.exit(1)", template, f"{rule_id}: missing failure exit code"
            )


class TestHarnessProverGeneration(unittest.TestCase):
    """Test PoC code generation."""

    def setUp(self):
        self.prover = HarnessProver(project_root=Path.cwd())

    def test_generate_known_rule(self):
        """Should generate PoC for a known rule."""
        finding = {
            "rule_id": "TVP-001",
            "file": "server/gateway/webhook.py",
            "line": 50,
        }
        poc = self.prover._generate_poc(finding)
        self.assertIn("TVP-001", poc)
        self.assertIn("HMAC", poc)

    def test_generate_unknown_rule(self):
        """Should return empty string for unknown rule."""
        finding = {"rule_id": "UNKNOWN-999", "file": "test.py"}
        poc = self.prover._generate_poc(finding)
        self.assertEqual(poc, "")

    def test_safe_skip_finding(self):
        """TVP-006 should be SAFE_SKIP without generating PoC."""
        finding = {"rule_id": "TVP-006", "file": "test.py"}
        result = self.prover.prove_finding(finding)
        self.assertEqual(result.status, "SAFE_SKIP")
        self.assertEqual(result.poc_code, "")

    def test_generate_sta003_poc(self):
        """STA-003 should generate subprocess shell=False detection."""
        finding = {
            "rule_id": "STA-003",
            "file": "nerves/core/hook_service.py",
            "line": 187,
        }
        poc = self.prover._generate_poc(finding)
        self.assertIn("subprocess", poc)
        self.assertIn("shell", poc)


class TestHarnessProverExecution(unittest.TestCase):
    """Test PoC sandbox execution."""

    def setUp(self):
        self.prover = HarnessProver(project_root=Path.cwd(), timeout=5)

    def test_execute_successful_exploit(self):
        """PoC that prints EXPLOIT_SUCCESS should be PROVEN."""
        poc = textwrap.dedent("""\
            import sys
            print("EXPLOIT_SUCCESS: vulnerability confirmed")
            sys.exit(0)
        """)
        success, output, error = self.prover._execute_poc(poc)
        self.assertTrue(success)
        self.assertIn("EXPLOIT_SUCCESS", output)

    def test_execute_failed_exploit(self):
        """PoC that prints EXPLOIT_FAILED should NOT be proven."""
        poc = textwrap.dedent("""\
            import sys
            print("EXPLOIT_FAILED: not exploitable")
            sys.exit(1)
        """)
        success, output, error = self.prover._execute_poc(poc)
        self.assertFalse(success)
        self.assertIn("EXPLOIT_FAILED", output)

    def test_execute_timeout(self):
        """PoC that hangs should timeout gracefully."""
        poc = textwrap.dedent("""\
            import time
            time.sleep(30)
        """)
        prover = HarnessProver(timeout=2)
        success, output, error = prover._execute_poc(poc)
        self.assertFalse(success)
        self.assertIn("timed out", error)

    def test_execute_error(self):
        """PoC with import error should be INCONCLUSIVE."""
        poc = textwrap.dedent("""\
            import nonexistent_module_xyz
        """)
        success, output, error = self.prover._execute_poc(poc)
        self.assertFalse(success)

    def test_prove_finding_with_real_file(self):
        """Test proving a finding against a real temp file."""
        # Create temp file with shell=False subprocess call
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(
                textwrap.dedent("""\
                import subprocess
                def run_cmd(user_input):
                    subprocess.run(user_input, shell=False)
            """)
            )
            f.flush()
            temp_path = f.name

        try:
            finding = {"rule_id": "STA-003", "file": temp_path, "line": 3}
            result = self.prover.prove_finding(finding)
            self.assertEqual(result.rule_id, "STA-003")
            self.assertEqual(result.status, "PROVEN")
            self.assertIn("EXPLOIT_SUCCESS", result.poc_output)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_prove_finding_not_exploitable(self):
        """Test proving a finding where the code is safe."""
        # File with subprocess but NO shell=False
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(
                textwrap.dedent("""\
                import subprocess
                def run_cmd():
                    subprocess.run(["ls", "-la"])
            """)
            )
            f.flush()
            temp_path = f.name

        try:
            finding = {"rule_id": "STA-003", "file": temp_path, "line": 3}
            result = self.prover.prove_finding(finding)
            self.assertEqual(result.status, "THEORETICAL")
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestHarnessProverReport(unittest.TestCase):
    """Test report generation."""

    def test_report_generation(self):
        prover = HarnessProver()
        results = [
            ProofResult(
                finding_id="STA-003",
                rule_id="STA-003",
                status="PROVEN",
                poc_output="EXPLOIT_SUCCESS: shell=False with dynamic cmd",
            ),
            ProofResult(
                finding_id="STA-001",
                rule_id="STA-001",
                status="THEORETICAL",
                poc_output="EXPLOIT_FAILED: literal import",
            ),
            ProofResult(
                finding_id="TVP-006",
                rule_id="TVP-006",
                status="SAFE_SKIP",
                poc_output="Safety-critical rule",
            ),
        ]
        report = prover.generate_report(results)
        self.assertIn("PROVEN", report)
        self.assertIn("THEORETICAL", report)
        self.assertIn("SAFE_SKIP", report)
        self.assertIn("STA-003", report)

    def test_empty_report(self):
        prover = HarnessProver()
        report = prover.generate_report([])
        self.assertIn("Prove Stage", report)


class TestProverIntegration(unittest.TestCase):
    """Test Prover integration with harness_bridge Gate 7."""

    def test_gate7_with_enable_prove(self):
        """Gate 7 should run when enable_prove=True and findings exist."""
        from nerves.core.harness_bridge import run_harness_full

        # Create a temp file with a shell=False subprocess
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(
                textwrap.dedent("""\
                import subprocess
                def dangerous(user_cmd):
                    subprocess.run(user_cmd, shell=False)
            """)
            )
            f.flush()
            temp_path = f.name

        try:
            # Mock the security scan to return a finding
            with patch("nerves.core.harness_bridge.scan_files_full") as mock_scan:
                mock_scan.return_value = [
                    {
                        "rule_id": "STA-003",
                        "title": "subprocess with shell=False",
                        "severity": "high",
                        "file": temp_path,
                        "line": 3,
                        "description": "test",
                        "evidence": "shell=False",
                        "confidence": 1.0,
                        "remediation": "",
                        "cwe": "CWE-78",
                    }
                ]

                result = run_harness_full(
                    files=[temp_path],
                    syntax_checker=lambda f: [],
                    lint_checker=lambda f: (0, ""),
                    enable_prove=True,
                )

                # Gate 7 should be present
                gate_names = [g.name for g in result.gates]
                self.assertIn("Prove Gate", gate_names)

                # Should have proof results
                self.assertTrue(len(result.proof_results) > 0)
                self.assertEqual(result.proof_results[0].rule_id, "STA-003")
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_gate7_skipped_when_disabled(self):
        """Gate 7 should NOT run when enable_prove=False."""
        from nerves.core.harness_bridge import run_harness_full

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write("x = 1\n")
            f.flush()
            temp_path = f.name

        try:
            result = run_harness_full(
                files=[temp_path],
                syntax_checker=lambda f: [],
                lint_checker=lambda f: (0, ""),
                enable_prove=False,  # Disabled
            )

            gate_names = [g.name for g in result.gates]
            self.assertNotIn("Prove Gate", gate_names)
        finally:
            Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
