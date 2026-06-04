"""
Static Scanner — AST-based Python security pattern detection.

Lightweight alternative to Bandit for common dangerous patterns:
- eval/exec on user input
- subprocess with shell=True
- pickle.loads on untrusted data
- hardcoded credentials
- debug mode in production
"""

import ast
import re
from pathlib import Path
from typing import List

from security import Finding, Severity


SCANNER_NAME = "static-analysis"


# Dangerous function calls to flag
DANGEROUS_CALLS = {
    "eval": ("Dangerous eval() call", Severity.CRITICAL, "CWE-95"),
    "exec": ("Dangerous exec() call", Severity.CRITICAL, "CWE-95"),
    "compile": ("Potential code injection via compile()", Severity.HIGH, "CWE-95"),
    "__import__": ("Dynamic import — potential code injection", Severity.MEDIUM, "CWE-502"),
}

# Dangerous module.function patterns
DANGEROUS_ATTR_CALLS = {
    ("pickle", "loads"): ("Deserialization of untrusted data", Severity.HIGH, "CWE-502"),
    ("pickle", "load"): ("Deserialization of untrusted data", Severity.HIGH, "CWE-502"),
    ("yaml", "load"): ("Unsafe YAML load (use safe_load)", Severity.MEDIUM, "CWE-502"),
    ("subprocess", "call"): ("Subprocess call — check for shell injection", Severity.MEDIUM, "CWE-78"),
    ("subprocess", "Popen"): ("Subprocess Popen — check for shell injection", Severity.MEDIUM, "CWE-78"),
    ("os", "system"): ("OS command execution", Severity.HIGH, "CWE-78"),
    ("os", "popen"): ("OS command execution", Severity.HIGH, "CWE-78"),
}


class _DangerousCallVisitor(ast.NodeVisitor):
    """AST visitor that detects dangerous function calls."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.findings: List[Finding] = []

    def visit_Call(self, node: ast.Call):
        # Direct calls: eval(), exec()
        if isinstance(node.func, ast.Name) and node.func.id in DANGEROUS_CALLS:
            title, severity, cwe = DANGEROUS_CALLS[node.func.id]
            self.findings.append(Finding(
                rule_id="STA-001",
                title=title,
                severity=severity,
                file=self.filepath,
                line=node.lineno,
                description=f"Call to {node.func.id}() detected. This can execute arbitrary code.",
                evidence=f"{node.func.id}(...) at line {node.lineno}",
                scanner=SCANNER_NAME,
                confidence=0.9,
                remediation=f"Remove {node.func.id}() or use a safe alternative.",
                cwe=cwe,
            ))

        # Attribute calls: pickle.loads(), os.system()
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            key = (node.func.value.id, node.func.attr)
            if key in DANGEROUS_ATTR_CALLS:
                title, severity, cwe = DANGEROUS_ATTR_CALLS[key]
                self.findings.append(Finding(
                    rule_id="STA-002",
                    title=title,
                    severity=severity,
                    file=self.filepath,
                    line=node.lineno,
                    description=f"Call to {key[0]}.{key[1]}() detected.",
                    evidence=f"{key[0]}.{key[1]}(...) at line {node.lineno}",
                    scanner=SCANNER_NAME,
                    confidence=0.85,
                    remediation=f"Use a safe alternative to {key[0]}.{key[1]}().",
                    cwe=cwe,
                ))

        # subprocess with shell=True
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("call", "Popen", "run"):
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    self.findings.append(Finding(
                        rule_id="STA-003",
                        title="Subprocess with shell=True",
                        severity=Severity.HIGH,
                        file=self.filepath,
                        line=node.lineno,
                        description="shell=True enables shell injection if arguments are user-controlled.",
                        evidence=f"subprocess.{node.func.attr}(..., shell=True)",
                        scanner=SCANNER_NAME,
                        confidence=0.9,
                        remediation="Use shell=False and pass arguments as a list.",
                        cwe="CWE-78",
                    ))

        self.generic_visit(node)


def scan_file(filepath: Path) -> List[Finding]:
    """Run static analysis on a single Python file.

    Handles RecursionError for large/complex files (issue #71).
    telegram_bot.py (3123 lines, deeply nested async code) caused
    ast.NodeVisitor.visit() to exhaust Python's call stack (~1000 frames).
    """
    import logging
    _log = logging.getLogger(__name__)

    findings = []
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return findings

    # Guard: skip files > 300KB — AST traversal cost is O(n) in code depth,
    # not just file size, but very large files are the primary RecursionError risk.
    file_size = len(content.encode("utf-8"))
    if file_size > 300_000:
        _log.warning(
            f"static_scanner: {filepath.name} is {file_size // 1024}KB — "
            f"skipping AST visitor (too large, risk of RecursionError). "
            f"Regex checks still applied."
        )
        # Still run regex-based checks (no recursion risk)
        lines = content.split("\n")
        findings.extend(_check_debug_mode(filepath, lines))
        findings.extend(_check_hardcoded_secrets(filepath, lines))
        return findings

    try:
        tree = ast.parse(content, filename=str(filepath))
    except SyntaxError:
        return findings
    except Exception:
        return findings

    # AST visitor — MUST be wrapped in RecursionError guard.
    # ast.NodeVisitor.visit() → generic_visit() is recursive and can exhaust
    # Python's call stack (~1000 frames) on deeply nested code (e.g. telegram_bot.py).
    try:
        visitor = _DangerousCallVisitor(str(filepath))
        visitor.visit(tree)
        findings.extend(visitor.findings)
    except RecursionError:
        _log.warning(
            f"static_scanner: RecursionError visiting AST of {filepath.name} "
            f"({file_size // 1024}KB, deeply nested code) — AST scan skipped, "
            f"regex checks still applied. Fix #71."
        )
    except Exception as e:
        _log.debug(f"static_scanner: unexpected error visiting {filepath.name}: {e}")

    # Regex-based checks — no recursion risk, always applied
    lines = content.split("\n")
    findings.extend(_check_debug_mode(filepath, lines))
    findings.extend(_check_hardcoded_secrets(filepath, lines))

    return findings


def scan_directory(target_dir: Path) -> List[Finding]:
    """Scan all Python files in the target directory.

    Skips: .venv, venv, site-packages, tests, security scanner itself, __pycache__.
    Uses Path.parts for platform-independent filtering (avoids Windows backslash issues).
    """
    SKIP_PARTS = {".venv", "venv", "site-packages", "tests", "security", "__pycache__"}
    findings = []
    for py_file in target_dir.rglob("*.py"):
        # Skip directories by path component (works on Windows + Linux)
        if any(part in SKIP_PARTS for part in py_file.parts):
            continue
        if py_file.name.startswith("test_"):
            continue
        findings.extend(scan_file(py_file))
    return findings


def _check_debug_mode(filepath: Path, lines: list) -> List[Finding]:
    """Detect debug mode enabled in production config."""
    findings = []
    for i, line in enumerate(lines, 1):
        if re.search(r'DEBUG\s*=\s*(True|"true"|1)', line, re.IGNORECASE):
            findings.append(Finding(
                rule_id="STA-004",
                title="Debug mode potentially enabled",
                severity=Severity.MEDIUM,
                file=str(filepath),
                line=i,
                description="DEBUG is set to a truthy value. Ensure this is from env var, not hardcoded.",
                evidence=line.strip(),
                scanner=SCANNER_NAME,
                confidence=0.5,
                remediation="Ensure DEBUG is loaded from environment and defaults to False.",
                cwe="CWE-489",
            ))
    return findings


def _check_hardcoded_secrets(filepath: Path, lines: list) -> List[Finding]:
    """Detect potential hardcoded secrets (API keys, tokens, passwords)."""
    findings = []
    secret_pattern = re.compile(
        r'(?:api_key|secret|password|token|credential)\s*=\s*["\'][a-zA-Z0-9]{16,}["\']',
        re.IGNORECASE,
    )
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("#"):
            continue
        if secret_pattern.search(line):
            # Skip env var loading patterns
            if "os.getenv" in line or "os.environ" in line:
                continue
            findings.append(Finding(
                rule_id="STA-005",
                title="Potential hardcoded secret",
                severity=Severity.CRITICAL,
                file=str(filepath),
                line=i,
                description="A string that looks like an API key or secret is hardcoded in source.",
                evidence=line.strip()[:80] + "...",
                scanner=SCANNER_NAME,
                confidence=0.7,
                remediation="Move secrets to .env file and load via os.getenv().",
                cwe="CWE-798",
            ))
    return findings
