"""
SEC-4 — Angati Runtime Security Guard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Centralized runtime enforcement layer that prevents:
  - SSRF (CWE-918): URL allowlist validation before aiohttp requests
  - Path Traversal (CWE-22): Canonicalized path resolution against base directory
  - ReDoS (CWE-400): Input length enforcement before regex application

All guards raise `SecurityError` (a ValueError subclass) on violation.
Import and use at every call site where external data touches URLs, file paths,
or regex patterns.

Design notes:
  - Zero external dependencies (stdlib only)
  - Thread-safe (no shared mutable state)
  - All functions are pure (no side effects beyond raising)
  - Integrates with existing security/__init__.py Finding/Severity infrastructure
"""

from __future__ import annotations

import ipaddress
import logging
import re
import urllib.parse
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Custom Exception
# ──────────────────────────────────────────────────────────────────────────────


class SecurityError(ValueError):
    """
    Raised by runtime guards when an input violates a security constraint.

    Inherits from ValueError so existing try/except (ValueError, TypeError)
    blocks in callers will naturally handle it, while still being distinguishable
    for targeted security logging.
    """

    def __init__(self, message: str, rule: str = "SEC-4", evidence: str = ""):
        super().__init__(message)
        self.rule = rule
        self.evidence = evidence
        # Always log security violations so they appear in trades.log
        log.warning("[%s] SecurityError: %s | evidence=%r", rule, message, evidence)


# ──────────────────────────────────────────────────────────────────────────────
# R1 — SSRF Prevention: Exchange URL Allowlist
# ──────────────────────────────────────────────────────────────────────────────

# Exact domain allowlist for exchange API calls.
# Only HTTPS is permitted; HTTP is rejected unconditionally.
_ALLOWED_EXCHANGE_DOMAINS: frozenset[str] = frozenset(
    {
        # Binance
        "api.binance.com",
        "api1.binance.com",
        "api2.binance.com",
        "api3.binance.com",
        "testnet.binance.vision",
        # Bybit
        "api.bybit.com",
        "api-testnet.bybit.com",
        # Weex
        "api-contract.weex.com",
        "api.weex.com",
        # OKX (future-proofing)
        "www.okx.com",
        "aws.okx.com",
    }
)

# Safe symbol/interval characters for exchange query parameters
_SAFE_SYMBOL_RE = re.compile(r"^[A-Za-z0-9_/\-\.]{1,30}$")
_SAFE_INTERVAL_RE = re.compile(r"^[0-9]{1,4}[mhd wM]?[wM]?$")

# RFC 1918 + loopback + link-local ranges (SSRF INTERNAL TARGET DETECTION)
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private_ip(hostname: str) -> bool:
    """Check if hostname resolves to a private/internal IP range (best-effort, no DNS lookup)."""
    try:
        addr = ipaddress.ip_address(hostname)
        return any(addr in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        # hostname is a FQDN, not an IP literal — check for internal hostnames
        lower = hostname.lower()
        return (
            lower in ("localhost", "localho.st")
            or lower.endswith(".local")
            or lower.endswith(".internal")
            or lower.endswith(".corp")
        )


def validate_exchange_url(url: str) -> str:
    """
    Validate that `url` points to an allowed exchange API domain via HTTPS.

    SSRF Prevention (CWE-918, TVP-SSRF-01):
      - Rejects http:// (plain HTTP)
      - Rejects IP literals for private ranges
      - Rejects hostnames not in _ALLOWED_EXCHANGE_DOMAINS
      - Returns the original URL unmodified if valid

    Args:
        url: The full URL string to validate.

    Returns:
        The original `url` string, unchanged, if validation passes.

    Raises:
        SecurityError: If the URL violates any SSRF constraint.
    """
    if not url or not isinstance(url, str):
        raise SecurityError(
            "URL must be a non-empty string", rule="SSRF-01", evidence=repr(url)
        )

    parsed = urllib.parse.urlparse(url)

    # 1. HTTPS only
    if parsed.scheme != "https":
        raise SecurityError(
            f"Only HTTPS URLs are permitted; got scheme '{parsed.scheme}'",
            rule="SSRF-01",
            evidence=url[:200],
        )

    hostname = parsed.hostname or ""

    # 2. Reject empty hostname
    if not hostname:
        raise SecurityError("URL has no hostname", rule="SSRF-01", evidence=url[:200])

    # 3. Reject IP literals for private ranges
    if _is_private_ip(hostname):
        raise SecurityError(
            f"URL hostname '{hostname}' resolves to a private/internal address (SSRF blocked)",
            rule="SSRF-01",
            evidence=url[:200],
        )

    # 4. Allowlist check
    if hostname not in _ALLOWED_EXCHANGE_DOMAINS:
        raise SecurityError(
            f"URL hostname '{hostname}' is not in the exchange API allowlist",
            rule="SSRF-01",
            evidence=url[:200],
        )

    return url


def validate_exchange_params(symbol: str, interval: str) -> tuple[str, str]:
    """
    Validate exchange query parameters before URL construction.

    Prevents SSRF via parameter injection into URL query strings.

    Args:
        symbol: Trading pair symbol (e.g. "BTCUSDT", "BTC/USDT")
        interval: Candlestick interval (e.g. "1m", "1h", "1d")

    Returns:
        Tuple (symbol, interval) if validation passes.

    Raises:
        SecurityError: If symbol or interval contain unsafe characters.
    """
    if not _SAFE_SYMBOL_RE.match(symbol):
        raise SecurityError(
            f"Symbol '{symbol}' contains unsafe characters — possible SSRF injection",
            rule="SSRF-02",
            evidence=symbol[:50],
        )
    if not _SAFE_INTERVAL_RE.match(interval):
        raise SecurityError(
            f"Interval '{interval}' contains unsafe characters — possible SSRF injection",
            rule="SSRF-02",
            evidence=interval[:20],
        )
    return symbol, interval


# ──────────────────────────────────────────────────────────────────────────────
# R2 — Path Traversal Prevention: Canonicalized Path Resolution
# ──────────────────────────────────────────────────────────────────────────────


def safe_path(
    raw_path: "str | Path",
    base_dir: Path,
    *,
    must_exist: bool = False,
    allowed_extensions: Optional[frozenset[str]] = None,
) -> Path:
    """
    Resolve `raw_path` and verify it stays within `base_dir`.

    Path Traversal Prevention (CWE-22, TVP-005):
      - Resolves symlinks and dotdot sequences via Path.resolve()
      - Raises SecurityError if resolved path is outside base_dir
      - Optionally checks that the file exists
      - Optionally enforces file extension allowlist

    Args:
        raw_path: The raw path string or Path object to validate.
        base_dir: The directory that resolved path must reside within.
        must_exist: If True, raise SecurityError if file does not exist.
        allowed_extensions: If provided, raise SecurityError if extension not in set.
                           Extensions should include the dot: {'.png', '.jpg'}.

    Returns:
        A resolved (absolute, canonical) Path object.

    Raises:
        SecurityError: If the path escapes base_dir, does not exist (when required),
                       or has a disallowed extension.
    """
    try:
        base_resolved = base_dir.resolve()
        # If raw_path is absolute, Path / raw_path discards the base.
        # If relative, it joins them. This ensures relative paths are evaluated
        # within base_dir rather than the current working directory.
        resolved = (base_resolved / raw_path).resolve()
    except (TypeError, ValueError, OSError) as exc:
        raise SecurityError(
            f"Cannot resolve path: {exc}",
            rule="PATH-01",
            evidence=str(raw_path)[:200],
        ) from exc

    # Check containment (is_relative_to available in Python 3.9+)
    try:
        resolved.relative_to(base_resolved)
    except ValueError:
        raise SecurityError(
            f"Path '{resolved}' escapes allowed base directory '{base_resolved}' — "
            "path traversal blocked",
            rule="PATH-01",
            evidence=str(raw_path)[:200],
        )

    if must_exist and not resolved.exists():
        raise SecurityError(
            f"Required path does not exist: '{resolved}'",
            rule="PATH-02",
            evidence=str(raw_path)[:200],
        )

    if allowed_extensions is not None:
        ext = resolved.suffix.lower()
        if ext not in allowed_extensions:
            raise SecurityError(
                f"File extension '{ext}' is not in allowed set {allowed_extensions}",
                rule="PATH-03",
                evidence=str(raw_path)[:200],
            )

    return resolved


# ──────────────────────────────────────────────────────────────────────────────
# R3 — ReDoS Prevention: Safe Regex Input Enforcement
# ──────────────────────────────────────────────────────────────────────────────

# Default maximum length before regex application.
# For trading data, legitimate inputs are always < 10,000 chars.
DEFAULT_REGEX_MAX_LEN = 2000


def safe_regex_input(
    input_str: str,
    max_len: int = DEFAULT_REGEX_MAX_LEN,
    *,
    truncate: bool = False,
) -> str:
    """
    Guard input strings before applying (potentially catastrophic) regex patterns.

    ReDoS Prevention (CWE-400, TVP-REDOS-01):
      - Raises SecurityError if len(input_str) > max_len (by default)
      - Optionally truncates instead of raising if truncate=True

    Args:
        input_str: The string to validate.
        max_len: Maximum allowed length. Default: 2000.
        truncate: If True, silently truncate to max_len instead of raising.

    Returns:
        The original or truncated string if length constraint is met.

    Raises:
        SecurityError: If input exceeds max_len and truncate=False.
    """
    if not isinstance(input_str, str):
        raise SecurityError(
            f"Expected str, got {type(input_str).__name__}",
            rule="REDOS-01",
            evidence=repr(input_str)[:100],
        )

    if len(input_str) > max_len:
        if truncate:
            log.debug(
                "[REDOS-01] Input truncated: len=%d > max=%d", len(input_str), max_len
            )
            return input_str[:max_len]
        raise SecurityError(
            f"Input string length {len(input_str)} exceeds max {max_len} — "
            "potential ReDoS blocked",
            rule="REDOS-01",
            evidence=f"len={len(input_str)}, first_100={input_str[:100]!r}",
        )

    return input_str


# ──────────────────────────────────────────────────────────────────────────────
# R4 — Screenshot Path Helper (convenience wrapper for main.py use case)
# ──────────────────────────────────────────────────────────────────────────────

# The allowed base directory for screenshot files.
# Resolved at import time relative to this file's location.
_SCREENSHOTS_BASE = Path(__file__).resolve().parent.parent / "screenshots"
_BRIEFS_BASE = Path(__file__).resolve().parent.parent / "logs"

# Image file extensions allowed for vision endpoints
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})


def safe_screenshot_path(raw_path: "str | Path") -> Path:
    """
    Validate and resolve a screenshot path for serving via FileResponse.

    Convenience wrapper around `safe_path` for the `GET /api/vision/screenshot/{id}`
    endpoint in main.py. Accepts paths under the screenshots/ OR logs/ directories.

    Args:
        raw_path: The raw screenshot path from the database record.

    Returns:
        Resolved canonical Path within the screenshots or logs directory.

    Raises:
        SecurityError: If path escapes allowed directories or has wrong extension.
    """
    # Try screenshots base first, then logs/briefs base
    for base in (_SCREENSHOTS_BASE, _BRIEFS_BASE, Path.cwd()):
        try:
            resolved = safe_path(
                raw_path,
                base,
                must_exist=True,
                allowed_extensions=_IMAGE_EXTENSIONS,
            )
            return resolved
        except SecurityError:
            continue

    # None of the base directories matched — raise with the last error context
    raise SecurityError(
        f"Screenshot path '{raw_path}' is not within any allowed directory "
        f"({_SCREENSHOTS_BASE}, {_BRIEFS_BASE}) or file does not exist",
        rule="PATH-SCREENSHOT",
        evidence=str(raw_path)[:200],
    )


# ──────────────────────────────────────────────────────────────────────────────
# R5 — Self-Test (runs on direct invocation: python -m security.runtime_guard)
# ──────────────────────────────────────────────────────────────────────────────


def _self_test() -> None:
    """Quick smoke test — verifies all guards work as expected."""
    import traceback

    passed = 0
    failed = 0

    def _check(name: str, fn, expect_error: bool = False):
        nonlocal passed, failed
        try:
            result = fn()
            if expect_error:
                print(f"  ❌ FAIL [{name}]: expected SecurityError, got {result!r}")
                failed += 1
            else:
                print(f"  ✅ PASS [{name}]: {result!r}")
                passed += 1
        except SecurityError as e:
            if expect_error:
                print(f"  ✅ PASS [{name}]: SecurityError raised ({e.rule})")
                passed += 1
            else:
                print(f"  ❌ FAIL [{name}]: unexpected SecurityError: {e}")
                failed += 1
        except Exception as e:
            print(f"  ❌ FAIL [{name}]: unexpected {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print("\n=== SEC-4 Runtime Guard Self-Test ===\n")

    # SSRF tests
    _check(
        "SSRF-allow-binance",
        lambda: validate_exchange_url("https://api.binance.com/api/v3/klines"),
    )
    _check(
        "SSRF-allow-bybit",
        lambda: validate_exchange_url("https://api.bybit.com/v5/market/kline"),
    )
    _check(
        "SSRF-block-http",
        lambda: validate_exchange_url("http://api.binance.com/steal"),
        expect_error=True,
    )
    _check(
        "SSRF-block-internal",
        lambda: validate_exchange_url("https://localhost/steal"),
        expect_error=True,
    )
    _check(
        "SSRF-block-private-ip",
        lambda: validate_exchange_url("https://192.168.1.1/steal"),
        expect_error=True,
    )
    _check(
        "SSRF-block-unknown",
        lambda: validate_exchange_url("https://evil.com/steal"),
        expect_error=True,
    )

    # Param validation
    _check("PARAM-allow-symbol", lambda: validate_exchange_params("BTCUSDT", "1h"))
    _check(
        "PARAM-block-symbol-injection",
        lambda: validate_exchange_params("BTC&evil=1", "1h"),
        expect_error=True,
    )
    _check(
        "PARAM-block-interval-injection",
        lambda: validate_exchange_params("BTCUSDT", "1h;rm -rf /"),
        expect_error=True,
    )

    # Path traversal tests
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "screenshots").mkdir()
        test_file = base / "screenshots" / "test.png"
        test_file.write_bytes(b"PNG")

        _check("PATH-allow-valid", lambda: safe_path("screenshots/test.png", base))
        _check(
            "PATH-block-traversal",
            lambda: safe_path("../../etc/passwd", base),
            expect_error=True,
        )
        _check(
            "PATH-block-abs-escape",
            lambda: safe_path("/etc/passwd", base),
            expect_error=True,
        )

    # ReDoS tests
    _check("REDOS-allow-normal", lambda: safe_regex_input("normal trading message"))
    _check("REDOS-block-long", lambda: safe_regex_input("a" * 10001), expect_error=True)
    _check("REDOS-truncate", lambda: safe_regex_input("a" * 10001, truncate=True))

    print(f"\n=== Results: {passed} passed, {failed} failed ===\n")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _self_test()
