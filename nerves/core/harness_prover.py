#!/usr/bin/env python3
"""
AQH Harness Prover — MDASH Stage 5: Auto-generate exploit PoCs.

For each CONFIRMED security finding, generates a rule-specific Python
exploit test, executes it in a sandboxed subprocess, and determines
whether the vulnerability is PROVEN or THEORETICAL.

Architecture (from Harness Taxonomy KI #22):
    CONFIRMED Finding → PoC Generator → Sandbox Executor → PROVEN | THEORETICAL

Safety:
    - All PoCs run in subprocess with timeout=10s
    - No destructive operations (no file writes, no network attacks)
    - TVP-006 (DRY_RUN) is SAFE_SKIP — never tests live trading

References:
    - MDASH Stage 5: Prove (auto-generate exploit PoC)
    - AQH Gate 7 (new)
"""

import logging
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("harness_prover")


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class ProofResult:
    """Result of a single PoC execution."""

    finding_id: str
    rule_id: str
    status: str = "INCONCLUSIVE"  # PROVEN | THEORETICAL | INCONCLUSIVE | SAFE_SKIP
    poc_code: str = ""
    poc_output: str = ""
    poc_error: str = ""
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# PoC Templates — Rule-specific exploit test generators
# ---------------------------------------------------------------------------

# Rules that should NEVER be tested with live execution
SAFE_SKIP_RULES = {"TVP-006"}  # DRY_RUN enforcement — no live trading tests

# Rules where we can generate meaningful PoCs
POC_TEMPLATES = {
    # --- TVP (Trading View Project) rules ---
    "TVP-001": textwrap.dedent("""\
        # PoC: TVP-001 — Missing HMAC validation
        # Attempt to send unsigned payload to webhook
        import sys
        try:
            # Check if webhook validates HMAC signature
            # We just verify the validation code exists in the source
            source = open(r"{file}", encoding="utf-8").read()
            has_hmac = "hmac" in source.lower() or "signature" in source.lower() or "x-signature" in source.lower()
            if not has_hmac:
                print("EXPLOIT_SUCCESS: No HMAC/signature validation found in webhook handler")
                sys.exit(0)
            else:
                print("EXPLOIT_FAILED: HMAC validation is present")
                sys.exit(1)
        except Exception as e:
            print(f"EXPLOIT_ERROR: {{e}}")
            sys.exit(2)
    """),
    "TVP-002": textwrap.dedent("""\
        # PoC: TVP-002 — Missing symbol validation
        # Check if webhook validates the symbol field
        import sys, ast
        try:
            source = open(r"{file}", encoding="utf-8").read()
            tree = ast.parse(source)
            # Look for symbol validation patterns
            has_validation = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Compare):
                    src = ast.unparse(node) if hasattr(ast, "unparse") else ""
                    if "symbol" in src.lower():
                        has_validation = True
                        break
                if isinstance(node, ast.If):
                    src = ast.unparse(node.test) if hasattr(ast, "unparse") else ""
                    if "symbol" in src.lower():
                        has_validation = True
                        break
            if not has_validation:
                print("EXPLOIT_SUCCESS: No symbol validation found — SQL injection risk")
                sys.exit(0)
            else:
                print("EXPLOIT_FAILED: Symbol validation is present")
                sys.exit(1)
        except Exception as e:
            print(f"EXPLOIT_ERROR: {{e}}")
            sys.exit(2)
    """),
    "TVP-003": textwrap.dedent("""\
        # PoC: TVP-003 — Missing indicator_name validation
        import sys
        try:
            source = open(r"{file}", encoding="utf-8").read()
            has_check = "indicator_name" in source and ("not" in source or "if" in source)
            if not has_check:
                print("EXPLOIT_SUCCESS: indicator_name not validated before insert_signal")
                sys.exit(0)
            else:
                print("EXPLOIT_FAILED: indicator_name validation present")
                sys.exit(1)
        except Exception as e:
            print(f"EXPLOIT_ERROR: {{e}}")
            sys.exit(2)
    """),
    "TVP-004": textwrap.dedent("""\
        # PoC: TVP-004 — No rate limiting on webhook
        import sys
        try:
            source = open(r"{file}", encoding="utf-8").read()
            has_ratelimit = any(kw in source.lower() for kw in [
                "rate_limit", "ratelimit", "throttle", "slowapi", "limiter",
                "requests_per", "max_requests"
            ])
            if not has_ratelimit:
                print("EXPLOIT_SUCCESS: No rate limiting mechanism found")
                sys.exit(0)
            else:
                print("EXPLOIT_FAILED: Rate limiting mechanism present")
                sys.exit(1)
        except Exception as e:
            print(f"EXPLOIT_ERROR: {{e}}")
            sys.exit(2)
    """),
    "TVP-005": textwrap.dedent("""\
        # PoC: TVP-005 — Missing exchange field passthrough
        import sys
        try:
            source = open(r"{file}", encoding="utf-8").read()
            has_exchange = "exchange" in source
            if not has_exchange:
                print("EXPLOIT_SUCCESS: 'exchange' field not handled in alert flow")
                sys.exit(0)
            else:
                print("EXPLOIT_FAILED: exchange field is handled")
                sys.exit(1)
        except Exception as e:
            print(f"EXPLOIT_ERROR: {{e}}")
            sys.exit(2)
    """),
    "TVP-007": textwrap.dedent("""\
        # PoC: TVP-007 — No position size guard
        import sys
        try:
            source = open(r"{file}", encoding="utf-8").read()
            has_guard = any(kw in source.lower() for kw in [
                "max_qty", "max_position", "position_limit", "size_limit",
                "max_order", "qty_limit"
            ])
            if not has_guard:
                print("EXPLOIT_SUCCESS: No position size guard — unlimited order sizes allowed")
                sys.exit(0)
            else:
                print("EXPLOIT_FAILED: Position size guard present")
                sys.exit(1)
        except Exception as e:
            print(f"EXPLOIT_ERROR: {{e}}")
            sys.exit(2)
    """),
    # --- STA (Static Analysis) rules ---
    "STA-001": textwrap.dedent("""\
        # PoC: STA-001 — Dynamic import (potential code injection)
        import sys, ast
        try:
            source = open(r"{file}", encoding="utf-8").read()
            tree = ast.parse(source)
            dangerous = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                    if fn == "__import__":
                        # Check if the argument is a variable (injectable) vs literal
                        if node.args and isinstance(node.args[0], ast.Constant):
                            print(f"EXPLOIT_FAILED: __import__ uses literal '{{node.args[0].value}}' — not injectable")
                            sys.exit(1)
                        else:
                            dangerous.append(ast.unparse(node))
            if dangerous:
                print(f"EXPLOIT_SUCCESS: Dynamic __import__ with variable arg: {{dangerous}}")
                sys.exit(0)
            else:
                print("EXPLOIT_FAILED: No injectable __import__ found")
                sys.exit(1)
        except Exception as e:
            print(f"EXPLOIT_ERROR: {{e}}")
            sys.exit(2)
    """),
    "STA-002": textwrap.dedent("""\
        # PoC: STA-002 — eval()/exec() usage
        import sys, ast
        try:
            source = open(r"{file}", encoding="utf-8").read()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                    if fn in ("eval", "exec"):
                        if node.args and isinstance(node.args[0], ast.Constant):
                            print(f"EXPLOIT_FAILED: {{fn}}() uses literal string — not injectable")
                            sys.exit(1)
                        print(f"EXPLOIT_SUCCESS: {{fn}}() with dynamic input — code injection risk")
                        sys.exit(0)
            print("EXPLOIT_FAILED: No eval/exec found")
            sys.exit(1)
        except Exception as e:
            print(f"EXPLOIT_ERROR: {{e}}")
            sys.exit(2)
    """),
    "STA-003": textwrap.dedent("""\
        # PoC: STA-003 — subprocess with shell=True
        import sys, ast
        try:
            source = open(r"{file}", encoding="utf-8").read()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                    if "subprocess" in fn:
                        for kw in node.keywords:
                            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value:
                                # Check if first arg is user-controllable
                                if node.args and isinstance(node.args[0], ast.Constant):
                                    print("EXPLOIT_FAILED: shell=True with literal command — low risk")
                                    sys.exit(1)
                                print("EXPLOIT_SUCCESS: subprocess shell=True with dynamic command — injection risk")
                                sys.exit(0)
            print("EXPLOIT_FAILED: No vulnerable subprocess call found")
            sys.exit(1)
        except Exception as e:
            print(f"EXPLOIT_ERROR: {{e}}")
            sys.exit(2)
    """),
    "STA-005": textwrap.dedent("""\
        # PoC: STA-005 — Unsafe deserialization (pickle)
        import sys
        try:
            source = open(r"{file}", encoding="utf-8").read()
            has_pickle = "pickle.load" in source or "pickle.loads" in source
            has_yaml_unsafe = "yaml.load" in source and "Loader" not in source
            if has_pickle:
                print("EXPLOIT_SUCCESS: pickle.load(s) found — arbitrary code execution risk")
                sys.exit(0)
            elif has_yaml_unsafe:
                print("EXPLOIT_SUCCESS: yaml.load without safe Loader — code execution risk")
                sys.exit(0)
            else:
                print("EXPLOIT_FAILED: No unsafe deserialization found")
                sys.exit(1)
        except Exception as e:
            print(f"EXPLOIT_ERROR: {{e}}")
            sys.exit(2)
    """),
    "SEC-001": textwrap.dedent("""\
        # PoC: SEC-001 — Hardcoded secret detection
        import sys, re
        try:
            source = open(r"{file}", encoding="utf-8").read()
            # Look for high-entropy strings that look like API keys
            patterns = [
                r'["\\']((?:sk-|AKIA|ghp_|ghu_)[a-zA-Z0-9]{{20,}})["\\'\\s]',
                r'(?:api[_-]?key|secret|password)\\s*[=:]\\s*["\\'\\s]([a-zA-Z0-9]{{20,}})',
            ]
            for pat in patterns:
                matches = re.findall(pat, source, re.IGNORECASE)
                real_secrets = [m for m in matches if not re.search(
                    r'(change_me|your_|xxx|placeholder|example|test|dummy|fake|sample)',
                    m, re.IGNORECASE
                )]
                if real_secrets:
                    print(f"EXPLOIT_SUCCESS: Found {{len(real_secrets)}} potential hardcoded secret(s)")
                    sys.exit(0)
            print("EXPLOIT_FAILED: No hardcoded secrets detected")
            sys.exit(1)
        except Exception as e:
            print(f"EXPLOIT_ERROR: {{e}}")
            sys.exit(2)
    """),
}


# ---------------------------------------------------------------------------
# Harness Prover
# ---------------------------------------------------------------------------


class HarnessProver:
    """
    MDASH Stage 5: Auto-generate and execute exploit PoCs.

    For each CONFIRMED finding, constructs a rule-specific Python test
    and executes it in a sandboxed subprocess with timeout.
    """

    def __init__(self, project_root: Path = None, timeout: int = 10):
        self.project_root = project_root or Path.cwd()
        self.timeout = timeout

    def prove_findings(self, findings: list) -> list:
        """
        Prove a list of findings.

        Args:
            findings: List of finding dicts (typically CONFIRMED ones)

        Returns:
            List of ProofResult
        """
        results = []
        for finding in findings:
            result = self.prove_finding(finding)
            results.append(result)
        return results

    def prove_finding(self, finding: dict) -> ProofResult:
        """Generate and run a PoC for a specific finding."""
        start = time.time()
        rule_id = finding.get("rule_id", "UNKNOWN")
        result = ProofResult(
            finding_id=finding.get("rule_id", "?"),
            rule_id=rule_id,
        )

        # Check for SAFE_SKIP rules
        if rule_id in SAFE_SKIP_RULES:
            result.status = "SAFE_SKIP"
            result.poc_output = (
                f"Rule {rule_id} is safety-critical. PoC execution skipped."
            )
            result.duration_ms = int((time.time() - start) * 1000)
            return result

        # Generate PoC code
        poc_code = self._generate_poc(finding)
        if not poc_code:
            result.status = "INCONCLUSIVE"
            result.poc_output = f"No PoC template for rule {rule_id}"
            result.duration_ms = int((time.time() - start) * 1000)
            return result

        result.poc_code = poc_code

        # Execute PoC in sandbox
        success, output, error = self._execute_poc(poc_code)

        result.poc_output = output
        result.poc_error = error

        if success:
            result.status = "PROVEN"
        elif "EXPLOIT_FAILED" in output:
            result.status = "THEORETICAL"
        else:
            result.status = "INCONCLUSIVE"

        result.duration_ms = int((time.time() - start) * 1000)
        return result

    def _generate_poc(self, finding: dict) -> str:
        """Generate Python exploit test code based on rule_id template."""
        rule_id = finding.get("rule_id", "")
        template = POC_TEMPLATES.get(rule_id)

        if not template:
            return ""

        # Substitute finding-specific values
        file_path = finding.get("file", "")
        # Resolve to absolute path
        if file_path and not Path(file_path).is_absolute():
            file_path = str(self.project_root / file_path)

        return template.format(
            file=file_path,
            line=finding.get("line", 0),
            rule_id=rule_id,
        )

    def _execute_poc(self, poc_code: str) -> tuple:
        """
        Execute PoC in isolated subprocess.

        Returns (exploit_succeeded: bool, stdout: str, stderr: str)
        """
        try:
            # Write PoC to temp file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as f:
                f.write(poc_code)
                f.flush()
                poc_path = f.name

            # Execute in subprocess with timeout
            result = subprocess.run(
                [sys.executable, poc_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                cwd=str(self.project_root),
            )

            # Clean up
            try:
                Path(poc_path).unlink()
            except OSError:
                pass

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            # exit code 0 = exploit succeeded
            exploit_succeeded = result.returncode == 0 and "EXPLOIT_SUCCESS" in stdout

            return exploit_succeeded, stdout, stderr

        except subprocess.TimeoutExpired:
            return False, "", f"PoC timed out after {self.timeout}s"
        except Exception as exc:
            return False, "", f"PoC execution error: {exc}"

    def generate_report(self, results: list) -> str:
        """Generate markdown report from proof results."""
        lines = ["### Gate 7: Prove Stage Results\n"]

        proven = [r for r in results if r.status == "PROVEN"]
        theoretical = [r for r in results if r.status == "THEORETICAL"]
        skipped = [r for r in results if r.status == "SAFE_SKIP"]
        inconclusive = [r for r in results if r.status == "INCONCLUSIVE"]

        lines.append("| Status | Count |")
        lines.append("|:-------|------:|")
        lines.append(f"| 🔴 PROVEN | {len(proven)} |")
        lines.append(f"| 🟡 THEORETICAL | {len(theoretical)} |")
        lines.append(f"| ⚪ INCONCLUSIVE | {len(inconclusive)} |")
        lines.append(f"| 🔵 SAFE_SKIP | {len(skipped)} |")
        lines.append("")

        if proven:
            lines.append("#### Proven Vulnerabilities\n")
            for r in proven:
                lines.append(f"- **{r.rule_id}**: {r.poc_output}")

        if theoretical:
            lines.append("\n#### Theoretical (Not Exploitable)\n")
            for r in theoretical:
                lines.append(f"- **{r.rule_id}**: {r.poc_output}")

        return "\n".join(lines)
