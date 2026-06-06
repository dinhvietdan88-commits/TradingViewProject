"""
Mini-MDASH: Agentic Security Harness for TradingView Webhook Server.

A 3-stage security pipeline inspired by Microsoft's MDASH:
  Stage 1: SCAN — Static analysis + custom trading rules
  Stage 2: VALIDATE — AI-assisted debate (optional, Level C)
  Stage 3: PROVE — Exploit simulation against running server

Usage:
  python -m security.cli scan --target ./server
  python -m security.cli prove --base-url http://localhost:5000
"""

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum


class Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingStatus(Enum):
    RAW = "raw"  # Stage 1 output
    CONFIRMED = "confirmed"  # Stage 2 validated
    FALSE_POS = "false_pos"  # Stage 2 rejected
    PROVEN = "proven"  # Stage 3 exploited
    MANUAL = "manual"  # Needs human review


@dataclass
class Finding:
    """A single security finding from any scanner."""

    rule_id: str  # e.g., "TVP-001"
    title: str
    severity: Severity
    file: str
    line: int
    description: str
    evidence: str = ""  # Code snippet or payload
    status: FindingStatus = FindingStatus.RAW
    scanner: str = ""  # Which scanner found it
    confidence: float = 0.0  # 0.0-1.0
    remediation: str = ""  # Fix suggestion
    cwe: str | None = None  # CWE reference

    @property
    def key(self) -> str:
        """Unique key for dedup."""
        return f"{self.rule_id}:{self.file}:{self.line}"


@dataclass
class ProbeResult:
    """Result of a Stage 3 exploit simulation probe."""

    probe_name: str
    target: str
    method: str
    payload: str
    expected: str
    actual: str
    passed: bool  # True = security held, False = vulnerability confirmed
    response_code: int | None = None
    response_time_ms: float | None = None
    details: str = ""


@dataclass
class SecurityReport:
    """Complete report from a full harness run."""

    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    target: str = ""
    total_files_scanned: int = 0
    findings: list = field(default_factory=list)
    probe_results: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.HIGH)

    @property
    def probes_failed(self) -> int:
        return sum(1 for p in self.probe_results if not p.passed)
