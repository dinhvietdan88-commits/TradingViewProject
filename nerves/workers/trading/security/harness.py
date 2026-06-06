"""
Mini-MDASH Security Harness — Core Pipeline Orchestrator.

Runs the security scanning pipeline:
  Stage 1: SCAN — All scanner plugins against target directory
  Dedup: Remove semantically equivalent findings
  Output: SecurityReport with findings sorted by severity
"""

import logging
from pathlib import Path

from security import Finding, SecurityReport, Severity
from security.scanners import (
    dependency_scanner,
    secret_scanner,
    static_scanner,
    trading_rules,
)

log = logging.getLogger("security.harness")


class SecurityHarness:
    """Orchestrates the Mini-MDASH security pipeline."""

    def __init__(self, target_dir: str, exclude_rules: list[str] | None = None):
        self.target_dir = Path(target_dir)
        self.exclude_rules = set(exclude_rules or [])
        self._findings: list[Finding] = []

    def scan(self) -> "SecurityHarness":
        """Stage 1: Run all scanners against the target directory."""
        log.info(f"[SCAN] Starting scan of {self.target_dir}")

        # 1. Custom trading rules (highest value)
        log.info("[SCAN] Running TVP Trading Rules scanner...")
        self._findings.extend(trading_rules.scan_directory(self.target_dir))

        # 2. Static analysis (AST-based)
        log.info("[SCAN] Running Static Analysis scanner...")
        self._findings.extend(static_scanner.scan_directory(self.target_dir))

        # 3. Dependency audit
        log.info("[SCAN] Running Dependency scanner...")
        self._findings.extend(dependency_scanner.scan_requirements(self.target_dir))

        # 4. Secret detection
        log.info("[SCAN] Running Secret scanner...")
        self._findings.extend(secret_scanner.scan_directory(self.target_dir))

        log.info(f"[SCAN] Complete: {len(self._findings)} raw findings")
        return self

    def dedup(self) -> "SecurityHarness":
        """Remove duplicate/overlapping findings."""
        seen_keys = set()
        unique = []
        for f in self._findings:
            if f.key not in seen_keys:
                seen_keys.add(f.key)
                unique.append(f)
        removed = len(self._findings) - len(unique)
        if removed > 0:
            log.info(f"[DEDUP] Removed {removed} duplicate findings")
        self._findings = unique
        return self

    def filter_rules(self) -> "SecurityHarness":
        """Filter out excluded rules."""
        if self.exclude_rules:
            before = len(self._findings)
            self._findings = [
                f for f in self._findings if f.rule_id not in self.exclude_rules
            ]
            log.info(
                f"[FILTER] Excluded {before - len(self._findings)} findings by rule filter"
            )
        return self

    def build_report(self) -> SecurityReport:
        """Build the final security report."""
        # Sort by severity (critical first)
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3,
            Severity.INFO: 4,
        }
        self._findings.sort(key=lambda f: severity_order.get(f.severity, 99))

        # Count files scanned
        py_files = set()
        for py_file in self.target_dir.rglob("*.py"):
            rel = str(py_file).replace("\\", "/")
            if "/.venv/" in rel or "/venv/" in rel:
                continue
            if "/tests/" not in rel and "/security/" not in rel:
                py_files.add(str(py_file))

        report = SecurityReport(
            target=str(self.target_dir),
            total_files_scanned=len(py_files),
            findings=self._findings,
            summary={
                "total_findings": len(self._findings),
                "critical": sum(
                    1 for f in self._findings if f.severity == Severity.CRITICAL
                ),
                "high": sum(1 for f in self._findings if f.severity == Severity.HIGH),
                "medium": sum(
                    1 for f in self._findings if f.severity == Severity.MEDIUM
                ),
                "low": sum(1 for f in self._findings if f.severity == Severity.LOW),
                "info": sum(1 for f in self._findings if f.severity == Severity.INFO),
                "scanners_used": list({f.scanner for f in self._findings}),
            },
        )
        return report

    def run(self) -> SecurityReport:
        """Run the full Level A pipeline: Scan → Dedup → Report."""
        return self.scan().dedup().filter_rules().build_report()
