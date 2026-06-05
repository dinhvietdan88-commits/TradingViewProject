"""
SEC-4 Regression Test Suite — Runtime Guard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tests for security.runtime_guard covering all 3 vulnerability classes:
  - R1: SSRF (CWE-918) via validate_exchange_url and validate_exchange_params
  - R2: Path Traversal (CWE-22) via safe_path and safe_screenshot_path
  - R3: ReDoS (CWE-400) via safe_regex_input

Run with:
    pytest tests/test_sec4_runtime_guard.py -v --tb=short

All tests are fully offline (no live network calls, no exchange API requests).
"""

import sys
import time
from pathlib import Path

import pytest

# Add parent dir to sys.path so we can import security.runtime_guard
sys.path.insert(0, str(Path(__file__).parent.parent))

from security.runtime_guard import (
    SecurityError,
    safe_path,
    safe_regex_input,
    validate_exchange_params,
    validate_exchange_url,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_base(tmp_path: Path) -> Path:
    """Provides a temporary base directory with a screenshots subdirectory."""
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    return tmp_path


@pytest.fixture
def sample_image(tmp_base: Path) -> Path:
    """Creates a real PNG file in the screenshots directory."""
    img_file = tmp_base / "screenshots" / "test_chart.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)  # minimal PNG header
    return img_file


# ──────────────────────────────────────────────────────────────────────────────
# R1: SSRF — validate_exchange_url
# ──────────────────────────────────────────────────────────────────────────────


class TestValidateExchangeUrl:
    """SSRF prevention: URL allowlist validation (CWE-918)."""

    # === ALLOWED URLs ===

    def test_allow_binance_klines(self):
        url = (
            "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=150"
        )
        assert validate_exchange_url(url) == url

    def test_allow_binance_api1(self):
        url = "https://api1.binance.com/api/v3/klines"
        assert validate_exchange_url(url) == url

    def test_allow_bybit_kline(self):
        url = "https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=1h"
        assert validate_exchange_url(url) == url

    def test_allow_weex_candles(self):
        url = "https://api-contract.weex.com/capi/v2/market/candles?symbol=cmt_btcusdt"
        assert validate_exchange_url(url) == url

    def test_allow_binance_testnet(self):
        url = "https://testnet.binance.vision/api/v3/klines"
        assert validate_exchange_url(url) == url

    # === BLOCKED: HTTP (non-HTTPS) ===

    def test_block_http_binance(self):
        """Plain HTTP to a legitimate domain must be blocked."""
        with pytest.raises(SecurityError, match="HTTPS"):
            validate_exchange_url("http://api.binance.com/api/v3/klines")

    def test_block_http_internal(self):
        """Plain HTTP to internal server must be blocked."""
        with pytest.raises(SecurityError):
            validate_exchange_url("http://internal-metadata/steal")

    # === BLOCKED: Private/Internal IP ranges ===

    def test_block_localhost(self):
        with pytest.raises(SecurityError):
            validate_exchange_url("https://localhost/steal")

    def test_block_127_0_0_1(self):
        with pytest.raises(SecurityError):
            validate_exchange_url("https://127.0.0.1/steal")

    def test_block_10_net(self):
        with pytest.raises(SecurityError):
            validate_exchange_url("https://10.0.0.1/steal")

    def test_block_192_168(self):
        with pytest.raises(SecurityError):
            validate_exchange_url("https://192.168.1.100/steal")

    def test_block_172_16(self):
        with pytest.raises(SecurityError):
            validate_exchange_url("https://172.16.0.1/steal")

    def test_block_169_254_metadata(self):
        """AWS/GCP metadata endpoint must be blocked."""
        with pytest.raises(SecurityError):
            validate_exchange_url("https://169.254.169.254/latest/meta-data/")

    # === BLOCKED: Unknown domains ===

    def test_block_unknown_domain(self):
        with pytest.raises(SecurityError, match="allowlist"):
            validate_exchange_url("https://evil.com/steal-keys")

    def test_block_lookalike_domain(self):
        """Lookalike domain (binance.com.evil.com) must be rejected."""
        with pytest.raises(SecurityError):
            validate_exchange_url("https://api.binance.com.evil.com/v3/klines")

    def test_block_empty_string(self):
        with pytest.raises(SecurityError):
            validate_exchange_url("")

    def test_block_none_like(self):
        with pytest.raises(SecurityError):
            validate_exchange_url("   ")

    def test_block_internal_hostname(self):
        with pytest.raises(SecurityError):
            validate_exchange_url("https://trading-db.internal/admin")

    def test_block_local_hostname(self):
        with pytest.raises(SecurityError):
            validate_exchange_url("https://myserver.local/config")


# ──────────────────────────────────────────────────────────────────────────────
# R1: SSRF — validate_exchange_params (query param injection prevention)
# ──────────────────────────────────────────────────────────────────────────────


class TestValidateExchangeParams:
    """SSRF query parameter injection prevention."""

    def test_allow_normal_symbol_interval(self):
        s, i = validate_exchange_params("BTCUSDT", "1h")
        assert s == "BTCUSDT"
        assert i == "1h"

    def test_allow_slash_symbol(self):
        s, i = validate_exchange_params("BTC/USDT", "4h")
        assert s == "BTC/USDT"

    def test_allow_dash_symbol(self):
        s, i = validate_exchange_params("BTC-USDT", "1d")
        assert s == "BTC-USDT"

    def test_allow_daily_interval(self):
        _, i = validate_exchange_params("ETHUSDT", "1d")
        assert i == "1d"

    def test_block_symbol_ampersand_injection(self):
        """Prevent &extra=param injection in symbol."""
        with pytest.raises(SecurityError):
            validate_exchange_params("BTC&extra=evil", "1h")

    def test_block_symbol_hash_injection(self):
        with pytest.raises(SecurityError):
            validate_exchange_params("BTC#fragment", "1h")

    def test_block_interval_semicolon(self):
        with pytest.raises(SecurityError):
            validate_exchange_params("BTCUSDT", "1h;rm -rf /")

    def test_block_interval_newline(self):
        with pytest.raises(SecurityError):
            validate_exchange_params("BTCUSDT", "1h\nHTTP/1.1 200 OK")

    def test_block_symbol_too_long(self):
        with pytest.raises(SecurityError):
            validate_exchange_params("A" * 31, "1h")


# ──────────────────────────────────────────────────────────────────────────────
# R2: Path Traversal — safe_path
# ──────────────────────────────────────────────────────────────────────────────


class TestSafePath:
    """Path traversal prevention: canonicalized resolution (CWE-22)."""

    def test_allow_valid_relative_path(self, tmp_base: Path, sample_image: Path):
        """A relative path within base_dir resolves correctly."""
        result = safe_path("screenshots/test_chart.png", tmp_base)
        assert result == sample_image.resolve()

    def test_allow_absolute_path_within_base(self, tmp_base: Path, sample_image: Path):
        """An absolute path within base_dir resolves correctly."""
        result = safe_path(str(sample_image), tmp_base)
        assert result.exists()

    def test_block_dotdot_traversal(self, tmp_base: Path):
        """../../ traversal must be blocked."""
        with pytest.raises(SecurityError, match="traversal"):
            safe_path("../../etc/passwd", tmp_base)

    def test_block_absolute_escape(self, tmp_base: Path):
        """Absolute path outside base_dir must be blocked."""
        with pytest.raises(SecurityError):
            safe_path("/etc/passwd", tmp_base)

    def test_block_windows_drive_escape(self, tmp_base: Path):
        """Windows absolute path outside base_dir must be blocked."""
        with pytest.raises(SecurityError):
            safe_path("C:\\Windows\\System32\\config\\SAM", tmp_base)

    def test_block_null_byte(self, tmp_base: Path):
        """Null byte in path (classic bypass) must be handled."""
        with pytest.raises((SecurityError, ValueError, OSError)):
            safe_path("screenshots/test\x00.png", tmp_base)

    def test_must_exist_raises_when_missing(self, tmp_base: Path):
        """must_exist=True raises SecurityError when file doesn't exist."""
        with pytest.raises(SecurityError, match="does not exist"):
            safe_path("screenshots/nonexistent.png", tmp_base, must_exist=True)

    def test_must_exist_passes_when_present(self, tmp_base: Path, sample_image: Path):
        """must_exist=True passes when file exists."""
        result = safe_path(str(sample_image), tmp_base, must_exist=True)
        assert result.exists()

    def test_allowed_extension_passes(self, tmp_base: Path, sample_image: Path):
        """allowed_extensions check passes for .png."""
        result = safe_path(
            str(sample_image), tmp_base, allowed_extensions=frozenset({".png", ".jpg"})
        )
        assert result.suffix == ".png"

    def test_blocked_extension_raises(self, tmp_base: Path):
        """allowed_extensions check blocks .py files."""
        py_file = tmp_base / "screenshots" / "exploit.py"
        py_file.write_text("import os; os.system('rm -rf /')")
        with pytest.raises(SecurityError, match="extension"):
            safe_path(str(py_file), tmp_base, allowed_extensions=frozenset({".png"}))

    def test_symlink_outside_base_blocked(self, tmp_base: Path):
        """Symlink pointing outside base_dir must be blocked after resolution."""
        symlink = tmp_base / "screenshots" / "evil_link"
        try:
            symlink.symlink_to("/etc/passwd")
        except (OSError, NotImplementedError):
            pytest.skip("Symlink creation not supported")
        with pytest.raises(SecurityError):
            safe_path(str(symlink), tmp_base, must_exist=False)


# ──────────────────────────────────────────────────────────────────────────────
# R3: ReDoS — safe_regex_input
# ──────────────────────────────────────────────────────────────────────────────


class TestSafeRegexInput:
    """ReDoS prevention: input length enforcement (CWE-400)."""

    def test_allow_normal_string(self):
        result = safe_regex_input("**BTC is looking bullish** with a VCP pattern")
        assert "bullish" in result

    def test_allow_string_at_limit(self):
        result = safe_regex_input("a" * 2000, max_len=2000)
        assert len(result) == 2000

    def test_block_string_over_limit(self):
        """Input exceeding max_len raises SecurityError."""
        with pytest.raises(SecurityError, match="ReDoS"):
            safe_regex_input("a" * 10001)

    def test_truncate_mode(self):
        """Truncate mode returns truncated string instead of raising."""
        result = safe_regex_input("a" * 10001, truncate=True)
        assert len(result) == 2000  # default max_len

    def test_custom_max_len_block(self):
        """Custom max_len is respected."""
        with pytest.raises(SecurityError):
            safe_regex_input("x" * 101, max_len=100)

    def test_custom_max_len_allow(self):
        """String within custom max_len is allowed."""
        result = safe_regex_input("x" * 100, max_len=100)
        assert len(result) == 100

    def test_adversarial_string_completes_quickly(self):
        """
        When safe_regex_input is used, processing a 10K adversarial string
        via sanitize_for_telegram_html must complete in < 1 second (not exponential).
        """
        sys.path.insert(0, str(Path(__file__).parent.parent))
        try:
            from notifier import sanitize_for_telegram_html
        except ImportError:
            pytest.skip("notifier.py not importable in this context")

        # Adversarial string that would cause catastrophic backtracking without the guard
        adversarial = "*" * 9999 + "x"

        start = time.monotonic()
        result = sanitize_for_telegram_html(adversarial)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, (
            f"sanitize_for_telegram_html took {elapsed:.2f}s on adversarial input "
            "(potential ReDoS — SEC-4 guard may not be active)"
        )

    def test_non_string_raises(self):
        """Non-string input raises SecurityError."""
        with pytest.raises(SecurityError):
            safe_regex_input(12345)  # type: ignore[arg-type]

    def test_empty_string_allowed(self):
        """Empty string is a valid, short input."""
        result = safe_regex_input("")
        assert result == ""


# ──────────────────────────────────────────────────────────────────────────────
# SecurityError class contract
# ──────────────────────────────────────────────────────────────────────────────


class TestSecurityErrorContract:
    """SecurityError must be a ValueError subclass with rule attribute."""

    def test_is_value_error_subclass(self):
        err = SecurityError("test")
        assert isinstance(err, ValueError)

    def test_has_rule_attribute(self):
        err = SecurityError("test", rule="TEST-001")
        assert err.rule == "TEST-001"

    def test_has_evidence_attribute(self):
        err = SecurityError("test", evidence="raw data here")
        assert err.evidence == "raw data here"

    def test_message_accessible(self):
        err = SecurityError("malicious input detected")
        assert "malicious" in str(err)

    def test_caught_by_value_error(self):
        """Existing try/except (ValueError, TypeError) blocks will catch it."""
        caught = False
        try:
            raise SecurityError("test")
        except (ValueError, TypeError):
            caught = True
        assert caught


# ──────────────────────────────────────────────────────────────────────────────
# Integration: End-to-End SSRF Scenario
# ──────────────────────────────────────────────────────────────────────────────


class TestSSRFIntegration:
    """
    Integration test simulating the actual capture_client.py attack scenario.
    An attacker cannot redirect OHLCV fetches to an internal server.
    """

    def test_attacker_cannot_inject_internal_server_via_symbol(self):
        """
        Simulates an attacker who controls the 'exchange' or 'symbol' parameter
        and tries to get the system to fetch from an internal metadata endpoint.
        """
        # This is what an attacker would try to do via a malicious webhook payload
        malicious_symbol = "BTCUSDT&interval=1h&limit=1&url=http://169.254.169.254"
        with pytest.raises(SecurityError):
            validate_exchange_params(malicious_symbol, "1h")

    def test_attacker_cannot_inject_via_direct_url(self):
        """Even if attacker constructs a URL directly, allowlist blocks it."""
        attacker_url = (
            "https://169.254.169.254/latest/meta-data/iam/security-credentials/"
        )
        with pytest.raises(SecurityError):
            validate_exchange_url(attacker_url)

    def test_legitimate_trading_flow_unaffected(self):
        """The happy path for BTCUSDT on Binance remains functional."""
        symbol, interval = validate_exchange_params("BTCUSDT", "1h")
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=150"
        validated_url = validate_exchange_url(url)
        assert "BTCUSDT" in validated_url
        assert "api.binance.com" in validated_url
