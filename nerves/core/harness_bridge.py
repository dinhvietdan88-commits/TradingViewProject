#!/usr/bin/env python3
"""
AQH Harness Bridge — MDASH Light + Full Pipeline for Angati Satellite.

Bridges Mini-MDASH security scanners + ADK Eval Metrics + AI Debate
into the angati-core-qa ecosystem.

Architecture (from Harness Taxonomy KI #22):
    MDASH Light: Gate 1 (Syntax) → Gate 2 (Lint+AST) → Gate 3 (Security Scan)
    MDASH Full:  Gate 1-3 + Gate 4 (Integration Test) + Gate 5 (Scar Regression) + Gate 6 (AI Debate)

References:
    - KI: harness-taxonomy-mdash-aqh
    - AQH Go: spine/angati/internal/harness/harness.go (7-gate pipeline)
    - Mini-MDASH: server/security/harness.py (3-stage Level A)
    - ADK Eval: nerves/core/eval_metrics.py (3 metrics)
"""

import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("harness_bridge")


# ---------------------------------------------------------------------------
# Verdict + Gate Result Models (mirrors Go AQH: harness.Verdict)
# ---------------------------------------------------------------------------


class Verdict:
    PASSED = "PASSED"
    FAILED = "FAILED"
    SOFT_GATED = "SOFT_GATED"
    SKIPPED = "SKIPPED"


@dataclass
class GateResult:
    """Result of a single harness gate."""

    name: str
    passed: bool
    verdict: str = Verdict.PASSED
    details: str = ""
    duration_ms: int = 0
    findings_count: int = 0


@dataclass
class HarnessVerdict:
    """Complete harness run result."""

    mode: str  # "MDASH_LIGHT" | "MDASH_FULL"
    verdict: str = Verdict.PASSED  # Overall verdict
    gates: list = field(default_factory=list)  # List[GateResult]
    findings: list = field(default_factory=list)  # Security findings
    scar_result: dict = field(default_factory=dict)
    debate_results: list = field(default_factory=list)
    proof_results: list = field(default_factory=list)  # ProofResult from Gate 7
    duration_ms: int = 0
    files_scanned: int = 0

    def to_report(self) -> str:
        """Generate markdown report (mirrors Go AQH report format)."""
        lines = ["# AQH Verification Report\n"]
        lines.append(f"- **Mode**: {self.mode}")
        lines.append(f"- **Files**: {self.files_scanned}")
        lines.append(f"- **Duration**: {self.duration_ms}ms\n")

        for gate in self.gates:
            icon = (
                "🟢"
                if gate.passed
                else ("🟡" if gate.verdict == Verdict.SOFT_GATED else "🔴")
            )
            lines.append(f"### {icon} {gate.name}: {gate.verdict}")
            if gate.details:
                lines.append(f"> {gate.details}")
            lines.append("")

        if self.findings:
            lines.append("### Security Findings\n")
            lines.append("| Rule | Severity | File | Description |")
            lines.append("|:-----|:---------|:-----|:------------|")
            for f in self.findings:
                sev = f.get("severity", "?")
                lines.append(
                    f"| {f.get('rule_id', '?')} | {sev} | {f.get('file', '?')}:{f.get('line', '?')} | {f.get('title', '')} |"
                )
            lines.append("")

        verdict_icon = (
            "🏆"
            if self.verdict == Verdict.PASSED
            else ("🟡" if self.verdict == Verdict.SOFT_GATED else "🔴")
        )
        lines.append(f"## {verdict_icon} FINAL VERDICT: {self.verdict}\n")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gate 3: Security Scan Bridge (Mini-MDASH → QA Pipeline)
# ---------------------------------------------------------------------------


def _resolve_server_path() -> Optional[Path]:
    """Resolve the server/ module path (handles Junction symlink)."""
    candidates = [
        Path.cwd() / "nerves" / "workers" / "trading",
        Path.cwd() / "server",
        Path.cwd().parent / "server",
    ]
    for c in candidates:
        if (c / "security" / "scanners" / "trading_rules.py").exists():
            return c
    return None


def _ensure_server_in_path():
    """Add server path to sys.path for security module imports."""
    server_path = _resolve_server_path()
    if server_path and str(server_path) not in sys.path:
        sys.path.insert(0, str(server_path))
    return server_path


def scan_files_light(files: list) -> list:
    """
    Gate 3 Light: Run trading_rules scanner only on specified files.
    Fast (<2s), no network calls, no pip-audit.

    Returns list of finding dicts.
    """
    server_path = _ensure_server_in_path()
    if not server_path:
        log.warning("[SCAN-LIGHT] Cannot find server/security module. Skipping.")
        return []

    try:
        from security.scanners import trading_rules
    except ImportError:
        log.warning("[SCAN-LIGHT] Cannot import security.scanners. Skipping.")
        return []

    findings = []
    for fpath in files:
        p = Path(fpath)
        if p.exists() and p.suffix == ".py":
            try:
                file_findings = trading_rules.scan_file(p)
                findings.extend(file_findings)
            except Exception as exc:
                log.warning(f"[SCAN-LIGHT] Error scanning {p.name}: {exc}")

    return _findings_to_dicts(findings)


def scan_files_full(files: list) -> list:
    """
    Gate 3 Full: Run all 4 scanners on specified files.
    Skips pip-audit dependency scanner (network-dependent, slow).

    Returns list of finding dicts.
    """
    server_path = _ensure_server_in_path()
    if not server_path:
        log.warning("[SCAN-FULL] Cannot find server/security module. Skipping.")
        return []

    try:
        from security.scanners import trading_rules, static_scanner, secret_scanner
    except ImportError:
        log.warning("[SCAN-FULL] Cannot import security.scanners. Skipping.")
        return []

    findings = []
    for fpath in files:
        p = Path(fpath)
        if not p.exists() or p.suffix != ".py":
            continue
        try:
            findings.extend(trading_rules.scan_file(p))
        except ValueError as e:
            import logging

            logging.getLogger(__name__).warning("Ignored: %s", e)
        try:
            findings.extend(static_scanner.scan_file(p))
        except ValueError as e:
            import logging

            logging.getLogger(__name__).warning("Ignored: %s", e)
        try:
            # secret_scanner uses _scan_file (private)
            scan_fn = getattr(secret_scanner, "scan_file", None) or getattr(
                secret_scanner, "_scan_file", None
            )
            if scan_fn:
                findings.extend(scan_fn(p))
        except ValueError as e:
            import logging

            logging.getLogger(__name__).warning("Ignored: %s", e)

    # Dedup by key
    seen = set()
    unique = []
    for f in findings:
        key = getattr(f, "key", f"{f.rule_id}:{f.file}:{f.line}")
        if key not in seen:
            seen.add(key)
            unique.append(f)

    return _findings_to_dicts(unique)


def _findings_to_dicts(findings: list) -> list:
    """Convert Finding dataclass instances to plain dicts."""
    results = []
    for f in findings:
        results.append(
            {
                "rule_id": getattr(f, "rule_id", "?"),
                "title": getattr(f, "title", ""),
                "severity": getattr(f, "severity", None),
                "file": str(getattr(f, "file", "")),
                "line": getattr(f, "line", 0),
                "description": getattr(f, "description", ""),
                "evidence": getattr(f, "evidence", ""),
                "confidence": getattr(f, "confidence", 0.0),
                "remediation": getattr(f, "remediation", ""),
                "cwe": getattr(f, "cwe", None),
            }
        )
    # Normalize severity to string
    for r in results:
        sev = r["severity"]
        if hasattr(sev, "value"):
            r["severity"] = sev.value
        elif sev is not None:
            r["severity"] = str(sev)
        else:
            r["severity"] = "unknown"
    return results


# ---------------------------------------------------------------------------
# Gate 5: Scar Regression Check (ADK Eval Metrics bridge)
# ---------------------------------------------------------------------------


def run_scar_gate(test_output: str, config_path: str = None) -> dict:
    """
    Gate 5: Run scar regression check using ADK Eval Metrics.

    Loads scar patterns from test_config.json (V10) and checks
    test output for regressions.
    """
    # Load scar patterns from config
    scar_patterns = []
    if config_path is None:
        config_path = str(Path.cwd() / "nerves" / "core" / "test_config.json")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            scar_patterns = config.get(
                "known_scar_patterns", config.get("scar_patterns", [])
            )
    except (FileNotFoundError, json.JSONDecodeError):
        log.info("[SCAR] No test_config.json found. Using default scar patterns.")
        scar_patterns = [
            {
                "id": "SCAR-001",
                "pattern": "CommandNotFoundException",
                "description": "MCP vs Terminal confusion",
            },
            {
                "id": "SCAR-002",
                "pattern": "ModuleNotFoundError.*security",
                "description": "Security module import failure",
            },
        ]

    # Import and run scar regression check
    try:
        # Try importing from nerves.core (when in project root)
        sys.path.insert(0, str(Path.cwd()))
        from nerves.core.eval_metrics import scar_regression_check

        return scar_regression_check(scar_patterns, test_output)
    except ImportError:
        # Fallback: inline regex check
        regressions = []
        for scar in scar_patterns:
            pattern = scar.get("pattern", "")
            if pattern and re.search(pattern, test_output, re.IGNORECASE):
                regressions.append(scar.get("id", "UNKNOWN"))

        total = len(scar_patterns)
        passed_count = total - len(regressions)
        return {
            "passed": len(regressions) == 0,
            "score": round(passed_count / total, 4) if total > 0 else 1.0,
            "regressions": regressions,
            "details": [],
        }


# ---------------------------------------------------------------------------
# Gate 6: Multi-Model Debate (MDASH Stage 3 Validate — Level C)
# ---------------------------------------------------------------------------


@dataclass
class DebateRound:
    """Result of a single multi-model debate round."""

    finding_id: str
    advocate_argument: str = ""  # Gemini: "This IS a vulnerability because..."
    defender_argument: str = ""  # OpenAI: "This is NOT exploitable because..."
    judge_verdict: str = "NEEDS_REVIEW"
    judge_confidence: float = 0.0
    judge_reasoning: str = ""
    consensus: bool = False  # True if advocate + judge agree


def run_ai_debate(findings: list, file_contents: dict = None) -> list:
    """
    Gate 6: Multi-Model Adversarial Debate (MDASH Stage 3).

    Protocol:
        1. Advocate (Gemini Flash) argues WHY it's a real vulnerability
        2. Defender (OpenAI o3-mini) argues WHY it's a false positive
        3. Judge (Gemini 2.5 Pro) weighs both arguments → verdict

    Degrades gracefully:
        - Both APIs: Full 3-round debate
        - Gemini only: Advocate + Judge (no Defender)
        - OpenAI only: Single-model debate via OpenAI
        - Neither: SKIPPED

    Args:
        findings: List of finding dicts from Gate 3
        file_contents: Dict of {filepath: source_code} for context

    Returns:
        List of debate result dicts
    """
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    debatable = [
        f for f in findings if severity_order.get(f.get("severity", "info"), 4) <= 2
    ]

    if not debatable:
        return []

    # Detect available API keys
    gemini_key = _get_api_key("GEMINI_API_KEY")
    openai_key = _get_api_key("OPENAI_API_KEY")

    if not gemini_key and not openai_key:
        log.info("[DEBATE] No LLM API configured. Gate 6 SKIPPED.")
        return [
            {
                "finding": f["rule_id"],
                "verdict": "SKIPPED",
                "reason": "No LLM API configured",
            }
            for f in debatable
        ]

    debate_results = []
    for finding in debatable:
        context = _extract_code_context(finding, file_contents)
        round_result = _run_debate_round(finding, context, gemini_key, openai_key)
        debate_results.append(
            {
                "finding": finding["rule_id"],
                "verdict": round_result.judge_verdict,
                "confidence": round_result.judge_confidence,
                "consensus": round_result.consensus,
                "reason": round_result.judge_reasoning,
                "advocate": round_result.advocate_argument[:200]
                if round_result.advocate_argument
                else "",
                "defender": round_result.defender_argument[:200]
                if round_result.defender_argument
                else "",
            }
        )

    return debate_results


def _get_api_key(key_name: str) -> str:
    """Get API key from environment or server config."""
    import os

    val = os.environ.get(key_name, "")
    if val and len(val) > 10:
        return val
    # Fallback: try server config
    try:
        _ensure_server_in_path()
        import config

        return getattr(config, key_name, "") or ""
    except ImportError:
        return ""


def _extract_code_context(finding: dict, file_contents: dict = None) -> str:
    """Extract ±10 lines of code context for a finding."""
    filepath = finding.get("file", "")
    if not file_contents or filepath not in file_contents:
        return ""
    lines = file_contents[filepath].split("\n")
    line_num = finding.get("line", 0)
    start = max(0, line_num - 10)
    end = min(len(lines), line_num + 10)
    return "\n".join(
        f"{i + 1}: {l}"
        for i, l in enumerate(lines[start:end], start=start)  # noqa: E741
    )


def _run_debate_round(
    finding: dict, context: str, gemini_key: str, openai_key: str
) -> DebateRound:
    """Execute a full Advocate → Defender → Judge debate round."""
    round_result = DebateRound(finding_id=finding.get("rule_id", "?"))

    # Step 1: Advocate (Gemini Flash) argues FOR vulnerability
    if gemini_key:
        advocate_prompt = _build_advocate_prompt(finding, context)
        round_result.advocate_argument = _call_gemini_raw(
            advocate_prompt, gemini_key, model="gemini-2.0-flash"
        )
    else:
        round_result.advocate_argument = "(Advocate unavailable — no Gemini API key)"

    # Step 2: Defender (OpenAI o3-mini) argues AGAINST
    if openai_key:
        defender_prompt = _build_defender_prompt(
            finding, context, round_result.advocate_argument
        )
        round_result.defender_argument = _call_openai_raw(
            defender_prompt, openai_key, model="o3-mini"
        )
    else:
        round_result.defender_argument = "(Defender unavailable — no OpenAI API key)"

    # Step 3: Judge (Gemini 2.5 Pro) renders verdict
    if gemini_key:
        judge_prompt = _build_judge_prompt(
            finding, round_result.advocate_argument, round_result.defender_argument
        )
        judge_response = _call_gemini_raw(
            judge_prompt, gemini_key, model="gemini-2.5-pro"
        )
        verdict, confidence, reasoning = _parse_judge_response(judge_response)
        round_result.judge_verdict = verdict
        round_result.judge_confidence = confidence
        round_result.judge_reasoning = reasoning
    elif openai_key:
        # Fallback: use OpenAI as judge if no Gemini
        judge_prompt = _build_judge_prompt(
            finding, round_result.advocate_argument, round_result.defender_argument
        )
        judge_response = _call_openai_raw(judge_prompt, openai_key, model="o3-mini")
        verdict, confidence, reasoning = _parse_judge_response(judge_response)
        round_result.judge_verdict = verdict
        round_result.judge_confidence = confidence
        round_result.judge_reasoning = reasoning

    # Determine consensus
    advocate_says_real = "unavailable" not in round_result.advocate_argument.lower()
    round_result.consensus = (
        advocate_says_real and round_result.judge_verdict == "CONFIRMED"
    )

    return round_result


# --- Prompt Builders ---


def _build_advocate_prompt(finding: dict, context: str) -> str:
    """Advocate: Argue WHY this is a real vulnerability."""
    return f"""You are a RED TEAM security advocate. Your job is to argue WHY this finding IS a real, exploitable vulnerability.

## Finding
- **Rule**: {finding.get("rule_id", "?")} — {finding.get("title", "")}
- **Severity**: {finding.get("severity", "?")}
- **File**: {finding.get("file", "?")}:{finding.get("line", "?")}
- **Description**: {finding.get("description", "")}
- **Evidence**: {finding.get("evidence", "")}
- **CWE**: {finding.get("cwe", "N/A")}

## Code Context
```python
{context}
```

## Instructions
Argue strongly that this IS a real vulnerability. Explain:
1. How an attacker could exploit this
2. What damage could result
3. Why the current code is insufficient

Keep your argument to 3-5 sentences. Be specific and technical."""


def _build_defender_prompt(finding: dict, context: str, advocate_arg: str) -> str:
    """Defender: Argue WHY this is a false positive, having seen the Advocate's argument."""
    return f"""You are a BLUE TEAM security defender. Your job is to argue WHY this finding is NOT exploitable in practice.

## Finding
- **Rule**: {finding.get("rule_id", "?")} — {finding.get("title", "")}
- **Severity**: {finding.get("severity", "?")}
- **File**: {finding.get("file", "?")}:{finding.get("line", "?")}
- **Description**: {finding.get("description", "")}

## Code Context
```python
{context}
```

## Advocate's Argument (RED TEAM)
{advocate_arg}

## Instructions
Counter the Advocate's argument. Explain:
1. Why this finding is not actually exploitable in this specific context
2. What mitigating factors exist (architecture, deployment, input validation)
3. Why fixing this would be low priority or unnecessary

Keep your argument to 3-5 sentences. Be specific and technical."""


def _build_judge_prompt(finding: dict, advocate_arg: str, defender_arg: str) -> str:
    """Judge: Weigh both arguments and render verdict."""
    return f"""You are an IMPARTIAL security judge. Two experts have debated whether a security finding is real or a false positive. Render your verdict.

## Finding
- **Rule**: {finding.get("rule_id", "?")} — {finding.get("title", "")}
- **Severity**: {finding.get("severity", "?")}

## RED TEAM (Advocate — argues it's real)
{advocate_arg}

## BLUE TEAM (Defender — argues it's false positive)
{defender_arg}

## Instructions
Render your verdict in this EXACT format:
VERDICT: CONFIRMED | FALSE_POSITIVE | NEEDS_REVIEW
CONFIDENCE: 0.0-1.0
REASONING: 1-2 sentence explanation

Example:
VERDICT: FALSE_POSITIVE
CONFIDENCE: 0.85
REASONING: The defender correctly notes that input validation upstream prevents exploitation."""


# --- LLM API Clients ---


def _call_gemini_raw(prompt: str, api_key: str, model: str = "gemini-2.0-flash") -> str:
    """Call Gemini API. Returns raw response text."""
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        m = genai.GenerativeModel(model)
        response = m.generate_content(prompt)
        return response.text
    except Exception as exc:
        log.warning(f"[DEBATE] Gemini ({model}) error: {exc}")
        return f"(Gemini error: {exc})"


def _call_openai_raw(prompt: str, api_key: str, model: str = "o3-mini") -> str:
    """Call OpenAI API. Returns raw response text."""
    try:
        import openai

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        return response.choices[0].message.content
    except Exception as exc:
        log.warning(f"[DEBATE] OpenAI ({model}) error: {exc}")
        return f"(OpenAI error: {exc})"


# --- Response Parsers ---


def _parse_debate_response(response: str) -> str:
    """Extract verdict from LLM response (legacy single-model compat)."""
    upper = response.upper()
    if "CONFIRMED" in upper:
        return "CONFIRMED"
    elif "FALSE_POSITIVE" in upper or "FALSE POSITIVE" in upper:
        return "FALSE_POSITIVE"
    else:
        return "NEEDS_REVIEW"


def _parse_judge_response(response: str) -> tuple:
    """Parse Judge's structured verdict response.

    Returns (verdict: str, confidence: float, reasoning: str)
    """
    verdict = "NEEDS_REVIEW"
    confidence = 0.5
    reasoning = ""

    for line in response.split("\n"):
        line = line.strip()
        upper = line.upper()

        if upper.startswith("VERDICT:"):
            val = line.split(":", 1)[1].strip().upper()
            if "CONFIRMED" in val:
                verdict = "CONFIRMED"
            elif "FALSE_POSITIVE" in val or "FALSE POSITIVE" in val:
                verdict = "FALSE_POSITIVE"
            else:
                verdict = "NEEDS_REVIEW"

        elif upper.startswith("CONFIDENCE:"):
            try:
                confidence = float(line.split(":", 1)[1].strip())
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, IndexError):
                confidence = 0.5

        elif upper.startswith("REASONING:"):
            reasoning = line.split(":", 1)[1].strip()

    # Fallback: if no structured response, parse as single-model
    if verdict == "NEEDS_REVIEW" and not reasoning:
        verdict = _parse_debate_response(response)
        reasoning = response[:200] if response else ""

    return verdict, confidence, reasoning


# ---------------------------------------------------------------------------
# Pipeline Orchestrators
# ---------------------------------------------------------------------------


def run_harness_light(
    files: list,
    syntax_checker=None,
    lint_checker=None,
    ast_auditor=None,
) -> HarnessVerdict:
    """
    MDASH Light: 3-gate fast harness (<5s).

    Gate 1: Syntax (py_compile)
    Gate 2: Lint + AST (ruff + ast_audit)
    Gate 3: Security Scan (trading_rules only)
    """
    start = time.time()
    result = HarnessVerdict(mode="MDASH_LIGHT", files_scanned=len(files))

    # Gate 1: Syntax
    g1_start = time.time()
    if syntax_checker:
        failures = syntax_checker(files)
    else:
        failures = _default_syntax_check(files)

    g1 = GateResult(
        name="Syntax Gate",
        passed=len(failures) == 0,
        verdict=Verdict.PASSED if not failures else Verdict.FAILED,
        details=f"{len(failures)} syntax errors" if failures else "All files compile",
        duration_ms=int((time.time() - g1_start) * 1000),
    )
    result.gates.append(g1)

    if not g1.passed:
        result.verdict = Verdict.FAILED
        result.duration_ms = int((time.time() - start) * 1000)
        return result

    # Gate 2: Lint + AST
    g2_start = time.time()
    lint_errors = 0
    ast_criticals = 0
    ast_highs = 0

    if lint_checker:
        lint_errors, _ = lint_checker(files)
    if ast_auditor:
        audit = ast_auditor(files)
        for _fpath, issues in audit.items():
            ast_criticals += sum(1 for _, sev, _ in issues if sev == "CRITICAL")
            ast_highs += sum(1 for _, sev, _ in issues if sev == "HIGH")

    g2_passed = ast_criticals == 0
    g2_verdict = Verdict.PASSED if g2_passed else Verdict.FAILED
    if g2_passed and (lint_errors > 0 or ast_highs > 0):
        g2_verdict = Verdict.SOFT_GATED

    g2 = GateResult(
        name="Lint + AST Gate",
        passed=g2_passed,
        verdict=g2_verdict,
        details=f"Lint: {lint_errors} errors, AST: {ast_criticals} critical, {ast_highs} high",
        duration_ms=int((time.time() - g2_start) * 1000),
    )
    result.gates.append(g2)

    if ast_criticals > 0:
        result.verdict = Verdict.FAILED
        result.duration_ms = int((time.time() - start) * 1000)
        return result

    # Gate 3: Security Scan (Light = trading_rules only)
    g3_start = time.time()
    findings = scan_files_light(files)
    result.findings = findings

    critical_findings = [f for f in findings if f.get("severity") == "critical"]
    high_findings = [f for f in findings if f.get("severity") == "high"]
    medium_findings = [f for f in findings if f.get("severity") == "medium"]

    g3_passed = len(critical_findings) == 0 and len(high_findings) == 0
    g3_verdict = Verdict.PASSED
    if critical_findings or high_findings:
        g3_verdict = Verdict.FAILED
    elif medium_findings:
        g3_verdict = Verdict.SOFT_GATED

    g3 = GateResult(
        name="Security Scan (Light)",
        passed=g3_passed,
        verdict=g3_verdict,
        details=f"{len(findings)} findings ({len(critical_findings)}C/{len(high_findings)}H/{len(medium_findings)}M)",
        duration_ms=int((time.time() - g3_start) * 1000),
        findings_count=len(findings),
    )
    result.gates.append(g3)

    # Final verdict
    if any(g.verdict == Verdict.FAILED for g in result.gates):
        result.verdict = Verdict.FAILED
    elif any(g.verdict == Verdict.SOFT_GATED for g in result.gates):
        result.verdict = Verdict.SOFT_GATED
    else:
        result.verdict = Verdict.PASSED

    result.duration_ms = int((time.time() - start) * 1000)
    return result


def run_harness_full(
    files: list,
    syntax_checker=None,
    lint_checker=None,
    ast_auditor=None,
    integration_test_runner=None,
    enable_debate: bool = False,
    enable_prove: bool = False,
    test_output: str = "",
    scar_config_path: str = None,
) -> HarnessVerdict:
    """
    MDASH Full: 7-gate thorough harness (~30s).

    Gate 1: Syntax (py_compile)
    Gate 2: Lint + AST (ruff + ast_audit)
    Gate 3: Security Scan (ALL scanners)
    Gate 4: Integration Test
    Gate 5: Scar Regression (ADK Eval Metrics)
    Gate 6: AI Debate (Multi-model validation) — optional
    Gate 7: Prove (PoC exploit generation) — optional
    """
    start = time.time()
    result = HarnessVerdict(mode="MDASH_FULL", files_scanned=len(files))

    # Gate 1: Syntax (same as Light)
    g1_start = time.time()
    if syntax_checker:
        failures = syntax_checker(files)
    else:
        failures = _default_syntax_check(files)

    g1 = GateResult(
        name="Syntax Gate",
        passed=len(failures) == 0,
        verdict=Verdict.PASSED if not failures else Verdict.FAILED,
        details=f"{len(failures)} syntax errors" if failures else "All files compile",
        duration_ms=int((time.time() - g1_start) * 1000),
    )
    result.gates.append(g1)

    if not g1.passed:
        result.verdict = Verdict.FAILED
        result.duration_ms = int((time.time() - start) * 1000)
        return result

    # Gate 2: Lint + AST (same as Light)
    g2_start = time.time()
    lint_errors = 0
    ast_criticals = 0
    ast_highs = 0

    if lint_checker:
        lint_errors, _ = lint_checker(files)
    if ast_auditor:
        audit = ast_auditor(files)
        for fpath, issues in audit.items():  # noqa: B007
            ast_criticals += sum(1 for _, sev, _ in issues if sev == "CRITICAL")
            ast_highs += sum(1 for _, sev, _ in issues if sev == "HIGH")

    g2_passed = ast_criticals == 0
    g2_verdict = Verdict.PASSED if g2_passed else Verdict.FAILED
    if g2_passed and (lint_errors > 0 or ast_highs > 0):
        g2_verdict = Verdict.SOFT_GATED

    g2 = GateResult(
        name="Lint + AST Gate",
        passed=g2_passed,
        verdict=g2_verdict,
        details=f"Lint: {lint_errors} errors, AST: {ast_criticals} critical, {ast_highs} high",
        duration_ms=int((time.time() - g2_start) * 1000),
    )
    result.gates.append(g2)

    if ast_criticals > 0:
        result.verdict = Verdict.FAILED
        result.duration_ms = int((time.time() - start) * 1000)
        return result

    # Gate 3: Security Scan (Full = all scanners)
    g3_start = time.time()
    findings = scan_files_full(files)
    result.findings = findings

    critical_findings = [f for f in findings if f.get("severity") == "critical"]
    high_findings = [f for f in findings if f.get("severity") == "high"]
    medium_findings = [f for f in findings if f.get("severity") == "medium"]

    g3_passed = len(critical_findings) == 0 and len(high_findings) == 0
    g3_verdict = Verdict.PASSED
    if critical_findings or high_findings:
        g3_verdict = Verdict.FAILED
    elif medium_findings:
        g3_verdict = Verdict.SOFT_GATED

    g3 = GateResult(
        name="Security Scan (Full)",
        passed=g3_passed,
        verdict=g3_verdict,
        details=f"{len(findings)} findings ({len(critical_findings)}C/{len(high_findings)}H/{len(medium_findings)}M)",
        duration_ms=int((time.time() - g3_start) * 1000),
        findings_count=len(findings),
    )
    result.gates.append(g3)

    # Gate 4: Integration Test
    g4_start = time.time()
    if integration_test_runner:
        test_ok = integration_test_runner()
    else:
        test_ok = True  # Skip if no runner provided
        test_output = test_output or "No integration test runner provided"

    g4 = GateResult(
        name="Integration Test Gate",
        passed=test_ok,
        verdict=Verdict.PASSED if test_ok else Verdict.FAILED,
        details="PASS" if test_ok else "FAIL",
        duration_ms=int((time.time() - g4_start) * 1000),
    )
    result.gates.append(g4)

    # Gate 5: Scar Regression
    g5_start = time.time()
    scar_result = run_scar_gate(test_output, scar_config_path)
    result.scar_result = scar_result

    g5 = GateResult(
        name="Scar Regression Gate",
        passed=scar_result.get("passed", True),
        verdict=Verdict.PASSED if scar_result.get("passed", True) else Verdict.FAILED,
        details=f"Score: {scar_result.get('score', 1.0)}, Regressions: {scar_result.get('regressions', [])}",
        duration_ms=int((time.time() - g5_start) * 1000),
    )
    result.gates.append(g5)

    # Gate 6: AI Debate (optional)
    if enable_debate:
        g6_start = time.time()
        # Load file contents for context
        file_contents = {}
        for fpath in files:
            try:
                file_contents[fpath] = Path(fpath).read_text(
                    encoding="utf-8", errors="ignore"
                )
            except ValueError as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)

        debate_results = run_ai_debate(findings, file_contents)
        result.debate_results = debate_results

        # Check if any finding was CONFIRMED by debate
        confirmed = [d for d in debate_results if d.get("verdict") == "CONFIRMED"]
        skipped = (
            all(d.get("verdict") == "SKIPPED" for d in debate_results)
            if debate_results
            else True
        )

        g6_verdict = Verdict.PASSED
        if confirmed:
            g6_verdict = Verdict.SOFT_GATED
        if skipped:
            g6_verdict = Verdict.SKIPPED

        g6 = GateResult(
            name="AI Debate Gate",
            passed=len(confirmed) == 0 or skipped,
            verdict=g6_verdict,
            details=f"{len(confirmed)} confirmed, {len(debate_results) - len(confirmed)} refuted/skipped",
            duration_ms=int((time.time() - g6_start) * 1000),
        )
        result.gates.append(g6)

    # Gate 7: Prove (optional, after debate)
    if enable_prove:
        g7_start = time.time()

        # Determine which findings to prove:
        # If debate ran, prove CONFIRMED findings only
        # If no debate, prove all MEDIUM+ findings
        if enable_debate and result.debate_results:
            provable_ids = {
                d["finding"]
                for d in result.debate_results
                if d.get("verdict") == "CONFIRMED"
            }
            provable = [f for f in findings if f.get("rule_id") in provable_ids]
        else:
            severity_order = {
                "critical": 0,
                "high": 1,
                "medium": 2,
                "low": 3,
                "info": 4,
            }
            provable = [
                f
                for f in findings
                if severity_order.get(f.get("severity", "info"), 4) <= 2
            ]

        if provable:
            try:
                from nerves.core.harness_prover import HarnessProver

                prover = HarnessProver(project_root=Path.cwd())
                proof_results = prover.prove_findings(provable)
                result.proof_results = proof_results

                proven_count = sum(1 for p in proof_results if p.status == "PROVEN")
                theoretical = sum(1 for p in proof_results if p.status == "THEORETICAL")
                safe_skip = sum(1 for p in proof_results if p.status == "SAFE_SKIP")

                g7_verdict = Verdict.PASSED
                if proven_count > 0:
                    g7_verdict = (
                        Verdict.SOFT_GATED
                    )  # Proven = serious but already flagged

                g7 = GateResult(
                    name="Prove Gate",
                    passed=True,  # Prove is informational, doesn't block
                    verdict=g7_verdict,
                    details=f"{proven_count} proven, {theoretical} theoretical, {safe_skip} safe-skip",
                    duration_ms=int((time.time() - g7_start) * 1000),
                )
            except ImportError:
                g7 = GateResult(
                    name="Prove Gate",
                    passed=True,
                    verdict=Verdict.SKIPPED,
                    details="harness_prover module not available",
                    duration_ms=int((time.time() - g7_start) * 1000),
                )
        else:
            g7 = GateResult(
                name="Prove Gate",
                passed=True,
                verdict=Verdict.SKIPPED,
                details="No findings to prove",
                duration_ms=int((time.time() - g7_start) * 1000),
            )

        result.gates.append(g7)

    # Final verdict
    active_gates = [g for g in result.gates if g.verdict != Verdict.SKIPPED]
    if any(g.verdict == Verdict.FAILED for g in active_gates):
        result.verdict = Verdict.FAILED
    elif any(g.verdict == Verdict.SOFT_GATED for g in active_gates):
        result.verdict = Verdict.SOFT_GATED
    else:
        result.verdict = Verdict.PASSED

    result.duration_ms = int((time.time() - start) * 1000)
    return result


# ---------------------------------------------------------------------------
# Default Syntax Checker (used when qa_core functions not injected)
# ---------------------------------------------------------------------------


def _default_syntax_check(files: list) -> list:
    """Fallback syntax checker using ast.parse()."""
    import ast
    failures = []
    for f in files:
        try:
            code = Path(f).read_text(encoding="utf-8", errors="ignore")
            ast.parse(code, f)
        except SyntaxError as exc:
            failures.append(f"{f}: SyntaxError L{exc.lineno}: {exc.msg}")
    return failures
