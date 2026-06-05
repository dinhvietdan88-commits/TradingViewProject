"""
Secret Scanner — Detects hardcoded secrets in non-Python files.

Scans .env, .yml, .json, .sh, .ps1 files for leaked API keys,
tokens, and passwords.
"""

import re
from pathlib import Path
from typing import List

from security import Finding, Severity


SCANNER_NAME = "secret-detector"

# Patterns that indicate a secret value (not a placeholder/template)
SECRET_PATTERNS = [
    # Generic API key patterns (long alphanumeric strings)
    (
        re.compile(
            r'(?:api[_-]?key|apikey)\s*[=:]\s*["\']?([a-zA-Z0-9]{20,})["\']?',
            re.IGNORECASE,
        ),
        "API key",
        Severity.CRITICAL,
    ),
    # AWS-style keys
    (
        re.compile(r"AKIA[0-9A-Z]{16}"),
        "AWS Access Key",
        Severity.CRITICAL,
    ),
    # Telegram bot tokens
    (
        re.compile(r"\d{8,10}:[a-zA-Z0-9_-]{35}"),
        "Telegram Bot Token",
        Severity.CRITICAL,
    ),
    # Generic secret/password with real value (not placeholder)
    (
        re.compile(
            r'(?:secret|password|passwd|pwd)\s*[=:]\s*["\']([^"\']{8,})["\']',
            re.IGNORECASE,
        ),
        "Hardcoded secret/password",
        Severity.HIGH,
    ),
    # Binance API keys (base64-ish)
    (
        re.compile(
            r'(?:binance[_-]?(?:api[_-]?)?(?:key|secret))\s*[=:]\s*["\']?([a-zA-Z0-9]{30,})["\']?',
            re.IGNORECASE,
        ),
        "Binance API credential",
        Severity.CRITICAL,
    ),
]

# File extensions to scan
SCAN_EXTENSIONS = {
    ".env",
    ".yml",
    ".yaml",
    ".json",
    ".sh",
    ".ps1",
    ".bat",
    ".cmd",
    ".toml",
    ".ini",
    ".cfg",
}

# Files/patterns to skip
SKIP_PATTERNS = {
    ".env.example",
    ".env.template",
    ".env.sample",
    "example.env",
    ".env",
    ".env.production",
    "security_report.json",
}

# Known placeholders that are NOT secrets
PLACEHOLDER_PATTERNS = re.compile(
    r"(change_me|your_|xxx|placeholder|example|test|dummy|fake|sample|<|>|\$\{)",
    re.IGNORECASE,
)


def scan_directory(target_dir: Path) -> List[Finding]:
    """Scan config files for hardcoded secrets."""
    findings = []

    # Scan project root and server dir
    search_dirs = [target_dir, target_dir.parent]
    seen_files = set()

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for filepath in search_dir.iterdir():
            if filepath.is_dir():
                continue
            if filepath.suffix not in SCAN_EXTENSIONS and filepath.name not in (
                ".env",
            ):
                continue
            if filepath.name in SKIP_PATTERNS:
                continue
            if str(filepath) in seen_files:
                continue
            seen_files.add(str(filepath))
            findings.extend(_scan_file(filepath))

    return findings


def _scan_file(filepath: Path) -> List[Finding]:
    """Scan a single config file for secrets."""
    findings = []
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
    except Exception:
        return findings

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        for pattern, secret_type, severity in SECRET_PATTERNS:
            match = pattern.search(line)
            if match:
                value = match.group(1) if match.lastindex else match.group(0)
                # Skip placeholders
                if PLACEHOLDER_PATTERNS.search(value):
                    continue
                # Skip empty values
                if not value or value in ('""', "''", '""'):
                    continue

                findings.append(
                    Finding(
                        rule_id="SEC-001",
                        title=f"Potential {secret_type} in {filepath.name}",
                        severity=severity,
                        file=str(filepath),
                        line=i,
                        description=f"Detected what appears to be a {secret_type} in configuration file.",
                        evidence=f"{stripped[:40]}{'...' if len(stripped) > 40 else ''} (value redacted)",
                        scanner=SCANNER_NAME,
                        confidence=0.75,
                        remediation=(
                            "Move to a secrets manager or ensure this file is in .gitignore. "
                            "Never commit real credentials to version control."
                        ),
                        cwe="CWE-798",
                    )
                )

    return findings
