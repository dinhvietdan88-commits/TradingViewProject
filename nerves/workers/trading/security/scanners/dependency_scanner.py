"""
Dependency Scanner — Checks requirements.txt for known CVEs.

Uses pip-audit if available, falls back to manual requirements parsing.
"""

import json
import re
import subprocess
from pathlib import Path

from security import Finding, Severity

SCANNER_NAME = "dependency-audit"


def scan_requirements(target_dir: Path) -> list[Finding]:
    """Scan requirements.txt for known vulnerabilities."""
    findings = []

    req_file = target_dir / "requirements.txt"
    if not req_file.exists():
        # Try parent dir
        req_file = target_dir.parent / "requirements.txt"
    if not req_file.exists():
        return findings

    # Try pip-audit first (best results, bypassed on Windows due to grandchild pipe hang bug)
    try:
        import os
        if os.name != "nt":
            cmd = [
                "pip-audit",
                "-r",
                str(req_file),
                "--format",
                "json",
                "--progress-spinner",
                "off",
            ]
            cmd = ["bash", "-c", " ".join(cmd)]

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=2, check=False
            )
            if result.returncode == 0 or result.stdout:
                return _parse_pip_audit_output(result.stdout, str(req_file))
    except FileNotFoundError:
        pass  # pip-audit not installed
    except subprocess.TimeoutExpired:
        pass

    # Fallback: basic version pinning check
    findings.extend(_check_version_pinning(req_file))

    return findings


def _parse_pip_audit_output(output: str, req_path: str) -> list[Finding]:
    """Parse pip-audit JSON output into Findings."""
    findings = []
    try:
        data = json.loads(output)
        dependencies = data.get("dependencies", [])
        for dep in dependencies:
            vulns = dep.get("vulns", [])
            for vuln in vulns:
                severity = Severity.HIGH
                if "critical" in vuln.get("description", "").lower():
                    severity = Severity.CRITICAL

                findings.append(
                    Finding(
                        rule_id="DEP-001",
                        title=f"Known vulnerability in {dep['name']} {dep.get('version', '?')}",
                        severity=severity,
                        file=req_path,
                        line=1,
                        description=(
                            f"{vuln.get('id', 'Unknown CVE')}: {vuln.get('description', 'No description')}"
                        ),
                        evidence=f"{dep['name']}=={dep.get('version', '?')} → fix: {vuln.get('fix_versions', ['?'])}",
                        scanner=SCANNER_NAME,
                        confidence=0.95,
                        remediation=f"Upgrade {dep['name']} to {vuln.get('fix_versions', ['latest'])}",
                        cwe="CWE-1104",  # Use of Unmaintained Third Party Components
                    )
                )
    except (json.JSONDecodeError, KeyError):
        pass
    return findings


def _check_version_pinning(req_file: Path) -> list[Finding]:
    """Check if dependencies are pinned to specific versions."""
    findings = []
    try:
        lines = req_file.read_text(encoding="utf-8").split("\n")
    except Exception:
        return findings

    unpinned = []
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Check if version is pinned (has ==)
        if "==" not in line and ">=" not in line:
            pkg_name = re.split(r"[<>=!]", line)[0].strip()
            if pkg_name:
                unpinned.append((i, pkg_name))

    if unpinned:
        findings.append(
            Finding(
                rule_id="DEP-002",
                title=f"{len(unpinned)} unpinned dependencies in requirements.txt",
                severity=Severity.LOW,
                file=str(req_file),
                line=unpinned[0][0],
                description=(
                    "Unpinned dependencies can introduce breaking changes or "
                    "supply-chain attacks via version hijacking."
                ),
                evidence=f"Unpinned: {', '.join(p for _, p in unpinned[:5])}",
                scanner=SCANNER_NAME,
                confidence=0.8,
                remediation="Pin all dependencies: pip freeze > requirements.txt",
                cwe="CWE-1104",
            )
        )

    return findings
