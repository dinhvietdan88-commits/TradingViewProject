"""
Tests for agy_harness.py — AgyHarness HTTP client wrapper.

Tests cover:
  - AgyResponse dataclass
  - AgyHarness.analyze() success/failure paths
  - Circuit breaker OPEN handling
  - Connection refused handling
  - Response validation (too short)
  - Retry logic
  - Health check
  - Context manager protocol
"""

import os

# Ensure the trading module path is importable
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "nerves", "workers", "trading"),
)

from agy_harness import AgyHarness, AgyResponse

# ════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def harness():
    """Create a harness with a fake bridge URL."""
    h = AgyHarness(
        bridge_url="http://fake-bridge:9100",
        timeout_sec=10,
        max_retries=1,
        model="gemini-2.5-flash",
    )
    return h


# ════════════════════════════════════════════════════════════════
# AgyResponse Tests
# ════════════════════════════════════════════════════════════════


class TestAgyResponse:
    def test_success_response(self):
        resp = AgyResponse(
            advice="Buy BTCUSDT with SL at 65000",
            model="gemini-2.5-flash",
            latency_ms=1500.0,
            success=True,
        )
        assert resp.success is True
        assert resp.error is None
        assert resp.exit_code == 0
        assert len(resp.advice) > 10

    def test_failure_response(self):
        resp = AgyResponse(
            advice="",
            model="gemini-2.5-flash",
            latency_ms=0,
            success=False,
            error="Connection refused",
        )
        assert resp.success is False
        assert resp.error == "Connection refused"
        assert resp.advice == ""


# ════════════════════════════════════════════════════════════════
# AgyHarness Tests
# ════════════════════════════════════════════════════════════════


class TestAgyHarness:
    @pytest.mark.asyncio
    async def test_analyze_success(self, harness):
        """Test successful analysis call."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "advice": "📈 BTCUSDT: Tín hiệu mạnh. Mua với SL tại 65000.",
                "model": "gemini-2.5-flash",
                "latency_ms": 1500.0,
                "exit_code": 0,
                "stdout_len": 55,
            }
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        mock_session.closed = False

        harness._session = mock_session

        result = await harness.analyze("Analyze BTCUSDT buy @ 68000")

        assert result.success is True
        assert "BTCUSDT" in result.advice
        assert result.latency_ms == 1500.0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_analyze_empty_response(self, harness):
        """Test that empty/short responses are caught by Gate 3."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "advice": "OK",  # Too short (< 10 chars)
                "model": "gemini-2.5-flash",
                "latency_ms": 100.0,
                "exit_code": 0,
                "stdout_len": 2,
            }
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        mock_session.closed = False

        harness._session = mock_session

        result = await harness.analyze("Test prompt")

        assert result.success is False
        assert "short" in result.error.lower() or "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_analyze_circuit_breaker_open(self, harness):
        """Test that 503 (CB OPEN) doesn't retry."""
        mock_resp = AsyncMock()
        mock_resp.status = 503
        mock_resp.text = AsyncMock(return_value='{"error": "agy circuit breaker OPEN"}')

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        mock_session.closed = False

        harness._session = mock_session
        harness.max_retries = 2  # Would normally retry 2 times

        result = await harness.analyze("Test prompt")

        assert result.success is False
        assert "OPEN" in (result.error or "")
        # Should NOT retry when CB is OPEN — verify only 1 call
        assert mock_session.post.call_count == 1

    @pytest.mark.asyncio
    async def test_analyze_server_error(self, harness):
        """Test that 502 errors trigger retry."""
        mock_resp = AsyncMock()
        mock_resp.status = 502
        mock_resp.text = AsyncMock(return_value='{"error": "agy exit 1"}')

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        mock_session.closed = False

        harness._session = mock_session
        harness.max_retries = 1

        result = await harness.analyze("Test prompt")

        assert result.success is False
        # Should have retried: 1 initial + 1 retry = 2 calls
        assert mock_session.post.call_count == 2

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager protocol."""
        async with AgyHarness(bridge_url="http://fake:9100") as h:
            assert h is not None
            assert h.bridge_url == "http://fake:9100"

    @pytest.mark.asyncio
    async def test_close_idempotent(self, harness):
        """Test that close() can be called multiple times safely."""
        await harness.close()  # No session yet — should not error
        await harness.close()  # Still safe

    def test_default_config(self):
        """Test default configuration values."""
        h = AgyHarness()
        assert h.bridge_url == "http://host.docker.internal:9100"
        assert h.timeout_sec == 25
        assert h.max_retries == 1
        assert h.model == "gemini-2.5-flash"

    def test_url_trailing_slash_stripped(self):
        """Test that trailing slashes are stripped from bridge_url."""
        h = AgyHarness(bridge_url="http://localhost:9100/")
        assert h.bridge_url == "http://localhost:9100"
