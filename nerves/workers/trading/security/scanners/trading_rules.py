"""
TVP Trading Rules Scanner — Custom security rules specific to trading systems.

Rules:
  TVP-001: unsafe_price_parse — float() without try/except on user input
  TVP-002: uncapped_quote_qty — No max limit on trade size
  TVP-003: secret_in_payload — Webhook secret logged/stored before stripping
  TVP-004: missing_rate_limit — Endpoints without rate limiting
  TVP-005: screenshot_path_traversal — User-controlled file paths in screenshot saving
  TVP-006: dry_run_bypass — DRY_RUN config overridable via env injection
  TVP-007: telegram_token_exposure — Bot token leaked via error messages
"""

import re
from pathlib import Path
from typing import List

from security import Finding, Severity


SCANNER_NAME = "tvp-trading-rules"


def scan_file(filepath: Path) -> List[Finding]:
    """Run all trading-specific rules against a single Python file."""
    findings = []
    try:
        content = filepath.read_text(encoding="utf-8")
        lines = content.split("\n")
    except Exception:
        return findings

    findings.extend(_tvp001_unsafe_price_parse(filepath, content, lines))
    findings.extend(_tvp002_uncapped_quote_qty(filepath, content, lines))
    findings.extend(_tvp003_secret_in_payload(filepath, content, lines))
    findings.extend(_tvp004_missing_rate_limit(filepath, content, lines))
    findings.extend(_tvp005_path_traversal(filepath, content, lines))
    findings.extend(_tvp006_dry_run_bypass(filepath, content, lines))
    findings.extend(_tvp007_telegram_token_exposure(filepath, content, lines))

    return findings


def scan_directory(target_dir: Path) -> List[Finding]:
    """Scan all Python files in the target directory."""
    findings = []
    for py_file in target_dir.rglob("*.py"):
        rel = str(py_file).replace("\\", "/")
        if "/.venv/" in rel or "/venv/" in rel:
            continue
        # Skip test files — they're allowed to do dangerous things
        if "/tests/" in rel or "test_" in py_file.name:
            continue
        # Skip the security harness itself
        if "/security/" in str(py_file).replace("\\", "/"):
            continue
        findings.extend(scan_file(py_file))
    return findings


# ── TVP-001: Unsafe Price Parsing ─────────────────────────────────────────────
def _tvp001_unsafe_price_parse(
    filepath: Path, content: str, lines: list
) -> List[Finding]:
    """Detect float() calls on user-controlled price/qty without try/except."""
    findings = []
    # Pattern: float(something) where something looks like payload/user data
    # We look for float() on variables named price, qty, sl, tp, etc.
    pattern = re.compile(
        r"float\s*\(\s*(?:str\s*\(\s*)?(price|qty|quote_qty|sl|tp|amount|size)",
        re.IGNORECASE,
    )

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip comments
        if stripped.startswith("#"):
            continue
        match = pattern.search(line)
        if match:
            # Check if this float() is already wrapped in try/except
            # Look back up to 5 lines for a try: block
            in_try = False
            for look_back in range(max(0, i - 6), i - 1):
                if "try:" in lines[look_back]:
                    in_try = True
                    break
            if not in_try:
                findings.append(
                    Finding(
                        rule_id="TVP-001",
                        title="Unsafe price/qty parsing without try/except",
                        severity=Severity.HIGH,
                        file=str(filepath),
                        line=i,
                        description=(
                            f"float() called on user-controlled variable '{match.group(1)}' "
                            "without try/except guard. A non-numeric webhook payload "
                            "will crash the handler."
                        ),
                        evidence=stripped,
                        scanner=SCANNER_NAME,
                        confidence=0.8,
                        remediation="Wrap in try/except (ValueError, TypeError) with safe default.",
                        cwe="CWE-20",  # Improper Input Validation
                    )
                )
    return findings


# ── TVP-002: Uncapped Trade Size ──────────────────────────────────────────────
def _tvp002_uncapped_quote_qty(
    filepath: Path, content: str, lines: list
) -> List[Finding]:
    """Detect missing max-cap on quoteQty / trade size from webhook payload."""
    findings = []
    if "webhook" not in filepath.name.lower() and "main" not in filepath.name.lower():
        return findings

    # Check if quoteQty is extracted from payload without max() capping
    has_quote_qty = re.search(r"quote_qty\s*=\s*payload\.get\(", content)
    has_max_cap = re.search(r"(min|max)\s*\(.*quote_qty", content)
    has_validation = re.search(r"if\s+.*quote_qty\s*[>>=]", content)

    if has_quote_qty and not has_max_cap and not has_validation:
        line_num = 1
        for i, line in enumerate(lines, 1):
            if "quote_qty" in line and "payload.get" in line:
                line_num = i
                break
        findings.append(
            Finding(
                rule_id="TVP-002",
                title="Uncapped trade size from webhook payload",
                severity=Severity.CRITICAL,
                file=str(filepath),
                line=line_num,
                description=(
                    "quoteQty is extracted from webhook payload without a maximum cap. "
                    "An attacker who compromises the webhook secret could submit a trade "
                    "with quoteQty=999999, draining the Binance account."
                ),
                evidence="quote_qty = payload.get('quoteQty', ...)",
                scanner=SCANNER_NAME,
                confidence=0.9,
                remediation=(
                    "Add MAX_QUOTE_QTY config (e.g., 100 USDT) and clamp: "
                    "quote_qty = min(float(quote_qty), config.MAX_QUOTE_QTY)"
                ),
                cwe="CWE-770",  # Allocation of Resources Without Limits
            )
        )
    return findings


# ── TVP-003: Secret in Payload ────────────────────────────────────────────────
def _tvp003_secret_in_payload(
    filepath: Path, content: str, lines: list
) -> List[Finding]:
    """Detect if webhook secret is read from payload body before being stripped."""
    findings = []

    # Check order: if secret is read from payload BEFORE pop()
    secret_read = None
    secret_pop = None
    for i, line in enumerate(lines, 1):
        if 'payload.get("secret"' in line or "payload.get('secret'" in line:
            if secret_read is None:
                secret_read = i
        if 'payload.pop("secret"' in line or "payload.pop('secret'" in line:
            secret_pop = i

    # If pop happens AFTER get, the secret was in the dict when insert_signal runs
    if secret_read and secret_pop and secret_pop > secret_read:
        # Check if insert_signal is called between get and pop
        for i in range(secret_read, secret_pop):
            if "insert_signal" in lines[i - 1] or "payload" in lines[i - 1]:
                # The secret was still in payload during potential logging
                pass
        # Actually check if pop happens BEFORE insert_signal
        insert_line = None
        for i, line in enumerate(lines, 1):
            if "insert_signal" in line:
                insert_line = i
                break
        if insert_line and secret_pop < insert_line:
            # Secret is popped before DB insert — SAFE
            return findings
        elif insert_line and secret_pop > insert_line:
            findings.append(
                Finding(
                    rule_id="TVP-003",
                    title="Webhook secret stored in database before stripping",
                    severity=Severity.MEDIUM,
                    file=str(filepath),
                    line=secret_read,
                    description=(
                        "The webhook secret is read from the payload body (line {}) "
                        "but not stripped until line {}. If insert_signal() stores the "
                        "full payload, the secret will be persisted in the database."
                    ).format(secret_read, secret_pop),
                    evidence=f"secret read: L{secret_read}, pop: L{secret_pop}, insert: L{insert_line}",
                    scanner=SCANNER_NAME,
                    confidence=0.7,
                    remediation="Move payload.pop('secret') immediately after reading it, before any DB operations.",
                    cwe="CWE-312",  # Cleartext Storage of Sensitive Information
                )
            )
    return findings


# ── TVP-004: Missing Rate Limiting ────────────────────────────────────────────
def _tvp004_missing_rate_limit(
    filepath: Path, content: str, lines: list
) -> List[Finding]:
    """Check if FastAPI endpoints lack rate limiting decorators."""
    findings = []
    if "main" not in filepath.name.lower():
        return findings

    # Find all route decorators
    route_pattern = re.compile(
        r'@app\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)'
    )
    has_rate_limit = (
        "slowapi" in content
        or "RateLimiter" in content
        or "rate_limit" in content.lower()
    )

    if not has_rate_limit:
        # Count endpoints
        endpoints = []
        for i, line in enumerate(lines, 1):
            match = route_pattern.search(line)
            if match:
                endpoints.append((i, match.group(1).upper(), match.group(2)))

        if endpoints:
            gw = filepath.parent / "gateway" / "webhook.py"
            webhook_rl = False
            if gw.is_file():
                try:
                    gw_txt = gw.read_text(encoding="utf-8", errors="replace")
                    webhook_rl = "_WEBHOOK_RATE_LIMITS" in gw_txt and "429" in gw_txt
                except OSError:
                    webhook_rl = False
            desc_extra = ""
            if webhook_rl:
                desc_extra = (
                    " POST /webhook is rate-limited in gateway/webhook.py (per-IP); "
                    "remaining routes in main.py may still be unbounded."
                )
            findings.append(
                Finding(
                    rule_id="TVP-004",
                    title="No global rate limiting on API endpoints",
                    severity=Severity.MEDIUM,
                    file=str(filepath),
                    line=endpoints[0][0],
                    description=(
                        f"Found {len(endpoints)} FastAPI routes in main.py with no global rate-limit "
                        "middleware (slowapi / shared limiter). "
                        "A client could flood authenticated or expensive routes."
                        + desc_extra
                    ),
                    evidence=f"Endpoints: {', '.join(f'{m} {p}' for _, m, p in endpoints[:5])}",
                    scanner=SCANNER_NAME,
                    confidence=0.95,
                    remediation=(
                        "Add app-wide or per-route rate limits (e.g. slowapi). "
                        "Keep webhook-specific limits in gateway/webhook.py."
                    ),
                    cwe="CWE-770",
                )
            )
    return findings


# ── TVP-005: Screenshot Path Traversal ────────────────────────────────────────
def _tvp005_path_traversal(filepath: Path, content: str, lines: list) -> List[Finding]:
    """Detect user-controlled file paths in screenshot saving."""
    findings = []
    pattern = re.compile(r"save_path\s*=.*(?:symbol|payload|request)", re.IGNORECASE)
    for i, line in enumerate(lines, 1):
        if pattern.search(line):
            if "safe_symbol" in line:
                continue
            # Check if path is sanitized
            has_sanitize = any(
                kw
                in content[max(0, content.find(line) - 200) : content.find(line) + 200]
                for kw in [
                    "sanitize",
                    "secure_filename",
                    "replace('..', '')",
                    "resolve()",
                    "re.sub",
                ]
            )
            if not has_sanitize:
                findings.append(
                    Finding(
                        rule_id="TVP-005",
                        title="Potential path traversal in screenshot save path",
                        severity=Severity.MEDIUM,
                        file=str(filepath),
                        line=i,
                        description=(
                            "File save path may incorporate user-controlled data (symbol from webhook). "
                            "A crafted symbol like '../../etc/passwd' could write outside the screenshots dir."
                        ),
                        evidence=line.strip(),
                        scanner=SCANNER_NAME,
                        confidence=0.6,
                        remediation="Sanitize symbol name: symbol = re.sub(r'[^A-Za-z0-9]', '', symbol)",
                        cwe="CWE-22",  # Path Traversal
                    )
                )
    return findings


# ── TVP-006: Dry Run Bypass ───────────────────────────────────────────────────
def _tvp006_dry_run_bypass(filepath: Path, content: str, lines: list) -> List[Finding]:
    """Check if BINANCE_DRY_RUN can be overridden at runtime."""
    findings = []
    if "config" not in filepath.name.lower():
        return findings

    # Check if DRY_RUN is loaded from env without validation
    for i, line in enumerate(lines, 1):
        if "BINANCE_DRY_RUN" in line and "os.getenv" in line:
            if "true" in line.lower():
                # Default is true (safe), but check if there's any runtime override mechanism
                findings.append(
                    Finding(
                        rule_id="TVP-006",
                        title="DRY_RUN mode overridable via environment variable",
                        severity=Severity.LOW,
                        file=str(filepath),
                        line=i,
                        description=(
                            "BINANCE_DRY_RUN is loaded from environment at startup. "
                            "If .env file is writable or env can be injected, an attacker "
                            "could disable dry-run mode and execute real trades."
                        ),
                        evidence=line.strip(),
                        scanner=SCANNER_NAME,
                        confidence=0.5,
                        remediation="Add runtime validation: if production, force DRY_RUN=true unless explicit unlock.",
                        cwe="CWE-1188",  # Insecure Default Initialization of Resource
                    )
                )
    return findings


# ── TVP-007: Telegram Token Exposure ──────────────────────────────────────────
def _tvp007_telegram_token_exposure(
    filepath: Path, content: str, lines: list
) -> List[Finding]:
    """Detect if Telegram bot token could leak via error messages or health endpoints."""
    findings = []
    # Check for token in error messages
    token_in_error = re.compile(
        r"(log\.(error|warning|info)|print|raise|HTTPException).*"
        r"(TELEGRAM_BOT_TOKEN|bot_token|BOT_TOKEN)",
        re.IGNORECASE,
    )
    for i, line in enumerate(lines, 1):
        if token_in_error.search(line):
            findings.append(
                Finding(
                    rule_id="TVP-007",
                    title="Telegram bot token potentially exposed in error output",
                    severity=Severity.HIGH,
                    file=str(filepath),
                    line=i,
                    description=(
                        "Telegram bot token referenced in logging/error handling code. "
                        "If the token value is interpolated into the message, it will appear "
                        "in trades.log and could be exfiltrated."
                    ),
                    evidence=line.strip(),
                    scanner=SCANNER_NAME,
                    confidence=0.7,
                    remediation="Never log token values. Log only 'token_present=True/False'.",
                    cwe="CWE-532",  # Insertion of Sensitive Information into Log File
                )
            )
    return findings
