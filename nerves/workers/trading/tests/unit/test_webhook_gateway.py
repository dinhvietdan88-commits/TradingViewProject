"""
Unit tests for WebhookGateway component.

Tests verify:
- Secret authentication (header / query-param / body)
- Dashboard-token bypass (Bearer auth)
- Unauthorized rejection (401)
- Empty payload rejection (400)
- Rate limiting (429 after 15 requests per minute)
- TVP-001: Safe price parsing (comma-separated, invalid, missing)
- TVP-002: quoteQty capping at MAX_QUOTE_QTY
- IP extraction via X-Forwarded-For header
- EventBus dispatch: SignalReceived emitted after ingress
- Source IP rate-limit window reset after 60s
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════


def _make_request(payload: dict, headers: dict = None, client_host: str = "127.0.0.1"):
    """Build a minimal mock fastapi.Request for webhook tests."""
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = client_host
    req.headers = {**(headers or {})}
    req.query_params = {}
    req.json = AsyncMock(return_value=payload)
    return req


# ═══════════════════════════════════════════════════════════════
# AUTH TESTS
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_webhook_auth_via_body_secret():
    """Secret in body JSON should authenticate successfully."""
    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()

    with (
        patch("gateway.webhook.config") as mock_config,
        patch("gateway.webhook._event_bus") as mock_bus,
    ):
        mock_config.WEBHOOK_SECRET = "test-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 1000.0
        mock_config.DEFAULT_EXCHANGE = "binance"
        mock_bus.emit_background = AsyncMock()

        import database as _db_module

        with patch.object(
            _db_module, "insert_signal", new_callable=AsyncMock, return_value=1
        ):
            req = _make_request(
                payload={
                    "secret": "test-secret",
                    "symbol": "BTCUSDT",
                    "action": "buy",
                    "price": 68000,
                }
            )
            resp = await webhook(req)
        assert resp["received"] is True
        assert resp["signal_id"] == 1


@pytest.mark.asyncio
async def test_webhook_auth_via_header():
    """Secret in X-TV-Secret header should authenticate successfully."""
    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()

    with (
        patch("gateway.webhook.config") as mock_config,
        patch("gateway.webhook._event_bus") as mock_bus,
    ):
        mock_config.WEBHOOK_SECRET = "header-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 1000.0
        mock_config.DEFAULT_EXCHANGE = "binance"
        mock_bus.emit_background = AsyncMock()

        import database as _db_module

        with patch.object(
            _db_module, "insert_signal", new_callable=AsyncMock, return_value=2
        ):
            req = _make_request(
                payload={"symbol": "ETHUSDT", "action": "sell"},
                headers={"X-TV-Secret": "header-secret"},
            )
            resp = await webhook(req)
        assert resp["received"] is True


@pytest.mark.asyncio
async def test_webhook_dashboard_token_bypass():
    """A valid DASHBOARD_TOKEN Bearer auth bypasses webhook secret check."""
    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()

    with (
        patch("gateway.webhook.config") as mock_config,
        patch("gateway.webhook._event_bus") as mock_bus,
    ):
        mock_config.WEBHOOK_SECRET = "real-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = "dashboard-token-xyz"  # noqa: S105
        mock_config.MAX_QUOTE_QTY = 1000.0
        mock_config.DEFAULT_EXCHANGE = "binance"
        mock_bus.emit_background = AsyncMock()

        import database as _db_module

        with patch.object(
            _db_module, "insert_signal", new_callable=AsyncMock, return_value=3
        ):
            req = _make_request(
                payload={"symbol": "BTCUSDT", "action": "buy"},  # No secret
                headers={"Authorization": "Bearer dashboard-token-xyz"},
            )
            resp = await webhook(req)
        assert resp["received"] is True


@pytest.mark.asyncio
async def test_webhook_unauthorized_wrong_secret():
    """Wrong secret should return 401 Unauthorized."""
    from fastapi import HTTPException

    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()

    with patch("gateway.webhook.config") as mock_config:
        mock_config.WEBHOOK_SECRET = "correct-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 1000.0

        req = _make_request(
            payload={"secret": "wrong-secret", "symbol": "BTCUSDT", "action": "buy"}
        )
        with pytest.raises(HTTPException) as exc_info:
            await webhook(req)
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_indicator_webhook_missing_name_no_db_insert():
    """Invalid indicator payload must return 400 without persisting a signal row."""
    from fastapi import HTTPException

    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()

    with (
        patch("gateway.webhook.config") as mock_config,
        patch("gateway.webhook._event_bus") as mock_bus,
    ):
        mock_config.WEBHOOK_SECRET = "test-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 1000.0
        mock_config.DEFAULT_EXCHANGE = "binance"
        mock_bus.emit_background = AsyncMock()

        import database as _db_module

        with patch.object(
            _db_module, "insert_signal", new_callable=AsyncMock
        ) as mock_db:
            req = _make_request(
                payload={
                    "secret": "test-secret",
                    "source": "indicator",
                    "symbol": "BTCUSDT",
                    "signal_type": "entry",
                    "confidence_score": 80,
                }
            )
            with pytest.raises(HTTPException) as exc_info:
                await webhook(req)

            assert exc_info.value.status_code == 400
            assert "indicator_name" in exc_info.value.detail
            mock_db.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_empty_payload_after_secret_stripped():
    """Payload that becomes empty after secret is stripped should return 400."""
    from fastapi import HTTPException

    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()

    with patch("gateway.webhook.config") as mock_config:
        mock_config.WEBHOOK_SECRET = "test-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 1000.0

        # Only key is "secret" — after .pop() the dict is empty
        req = _make_request(payload={"secret": "test-secret"})
        with pytest.raises(HTTPException) as exc_info:
            await webhook(req)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Missing required field: symbol"


# ═══════════════════════════════════════════════════════════════
# RATE LIMITING (TVP-004)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_15_requests():
    """16th request from same IP within 60s should return 429."""
    from fastapi import HTTPException

    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()

    ip = "10.0.0.5"
    # Pre-fill the rate limit cache: 15 requests in current window
    _WEBHOOK_RATE_LIMITS[ip] = (15, time.time())

    with patch("gateway.webhook.config") as mock_config:
        mock_config.WEBHOOK_SECRET = "test-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 1000.0
        mock_config.DISABLE_RATE_LIMIT = False
        mock_config.DEFAULT_EXCHANGE = "binance"

        req = _make_request(
            payload={"secret": "test-secret", "symbol": "BTCUSDT", "action": "buy"},
            client_host=ip,
        )
        with pytest.raises(HTTPException) as exc_info:
            await webhook(req)
        assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_resets_after_window():
    """First request after the 60s window should not be rate-limited."""
    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()

    ip = "10.0.0.6"
    # Simulate a stale window (70 seconds ago)
    _WEBHOOK_RATE_LIMITS[ip] = (15, time.time() - 70)

    with (
        patch("gateway.webhook.config") as mock_config,
        patch("gateway.webhook._event_bus") as mock_bus,
    ):
        mock_config.WEBHOOK_SECRET = "test-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 1000.0
        mock_config.DISABLE_RATE_LIMIT = False
        mock_config.DEFAULT_EXCHANGE = "binance"
        mock_config.DEFAULT_EXCHANGE = "binance"
        mock_bus.emit_background = AsyncMock()

        import database as _db_module

        with patch.object(
            _db_module, "insert_signal", new_callable=AsyncMock, return_value=10
        ):
            req = _make_request(
                payload={"secret": "test-secret", "symbol": "BTCUSDT", "action": "buy"},
                client_host=ip,
            )
            resp = await webhook(req)
        assert resp["received"] is True
        # Counter should have been reset to 1
        assert _WEBHOOK_RATE_LIMITS[ip][0] == 1


# ═══════════════════════════════════════════════════════════════
# PRICE PARSING (TVP-001)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_price_parsed_with_comma_separator():
    """Prices with commas (e.g., '68,000.50') should be parsed correctly."""
    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()
    captured_args = {}

    async def capture_insert(symbol, action, price, quote_qty, source_ip, payload):
        captured_args["price"] = price
        return 20

    with (
        patch("gateway.webhook.config") as mock_config,
        patch("gateway.webhook._event_bus") as mock_bus,
    ):
        mock_config.WEBHOOK_SECRET = "test-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 1000.0
        mock_config.DEFAULT_EXCHANGE = "binance"
        mock_bus.emit_background = AsyncMock()

        import database as _db_module

        with patch.object(
            _db_module, "insert_signal", new_callable=AsyncMock, return_value=20
        ) as mock_insert:
            req = _make_request(
                payload={
                    "secret": "test-secret",
                    "symbol": "BTCUSDT",
                    "action": "buy",
                    "price": "68,000.50",
                }
            )
            await webhook(req)
            price = mock_insert.call_args.kwargs["price"]
        assert price == pytest.approx(68000.50)


@pytest.mark.asyncio
async def test_invalid_price_becomes_none():
    """Non-numeric price strings should resolve to None (not crash)."""
    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()
    captured_args = {}

    async def capture_insert(symbol, action, price, quote_qty, source_ip, payload):
        captured_args["price"] = price
        return 21

    with (
        patch("gateway.webhook.config") as mock_config,
        patch("gateway.webhook._event_bus") as mock_bus,
    ):
        mock_config.WEBHOOK_SECRET = "test-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 1000.0
        mock_config.DEFAULT_EXCHANGE = "binance"
        mock_bus.emit_background = AsyncMock()

        import database as _db_module

        with patch.object(
            _db_module, "insert_signal", new_callable=AsyncMock, return_value=21
        ) as mock_insert:
            req = _make_request(
                payload={
                    "secret": "test-secret",
                    "symbol": "BTCUSDT",
                    "action": "buy",
                    "price": "INVALID",
                }
            )
            await webhook(req)
            price = mock_insert.call_args.kwargs["price"]
        assert price is None


# ═══════════════════════════════════════════════════════════════
# QUOTE QTY CAPPING (TVP-002)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_quote_qty_capped_at_max():
    """quoteQty exceeding MAX_QUOTE_QTY should be capped."""
    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()
    captured_args = {}

    async def capture_insert(symbol, action, price, quote_qty, source_ip, payload):
        captured_args["quote_qty"] = quote_qty
        return 30

    with (
        patch("gateway.webhook.config") as mock_config,
        patch("gateway.webhook._event_bus") as mock_bus,
    ):
        mock_config.WEBHOOK_SECRET = "test-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 500.0
        mock_config.DEFAULT_EXCHANGE = "binance"
        mock_bus.emit_background = AsyncMock()

        import database as _db_module

        with patch.object(
            _db_module, "insert_signal", new_callable=AsyncMock, return_value=30
        ) as mock_insert:
            req = _make_request(
                payload={
                    "secret": "test-secret",
                    "symbol": "BTCUSDT",
                    "action": "buy",
                    "quoteQty": 99999,
                }
            )
            await webhook(req)
            quote_qty = mock_insert.call_args.kwargs["quote_qty"]
        assert quote_qty == pytest.approx(500.0)


@pytest.mark.asyncio
async def test_quote_qty_defaults_to_10_on_invalid():
    """Invalid quoteQty (e.g., text string) should default to 10.0."""
    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()
    captured_args = {}

    async def capture_insert(symbol, action, price, quote_qty, source_ip, payload):
        captured_args["quote_qty"] = quote_qty
        return 31

    with (
        patch("gateway.webhook.config") as mock_config,
        patch("gateway.webhook._event_bus") as mock_bus,
    ):
        mock_config.WEBHOOK_SECRET = "test-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 500.0
        mock_config.DEFAULT_EXCHANGE = "binance"
        mock_bus.emit_background = AsyncMock()

        import database as _db_module

        with patch.object(
            _db_module, "insert_signal", new_callable=AsyncMock, return_value=31
        ) as mock_insert:
            req = _make_request(
                payload={
                    "secret": "test-secret",
                    "symbol": "BTCUSDT",
                    "action": "buy",
                    "quoteQty": "abc",
                }
            )
            await webhook(req)
            quote_qty = mock_insert.call_args.kwargs["quote_qty"]
        assert quote_qty == pytest.approx(10.0)


# ═══════════════════════════════════════════════════════════════
# IP EXTRACTION
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ip_extracted_from_x_forwarded_for():
    """SEC-001 fix: Source IP must be taken from the RIGHTMOST hop in X-Forwarded-For.

    The rightmost entry is appended by the trusted reverse proxy and cannot be
    spoofed by the client. The leftmost entry (203.0.113.5) is client-provided
    and untrusted. The rightmost entry (10.0.0.1) is what our proxy recorded.
    """
    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()
    captured_args = {}

    async def capture_insert(symbol, action, price, quote_qty, source_ip, payload):
        captured_args["source_ip"] = source_ip
        return 40

    with (
        patch("gateway.webhook.config") as mock_config,
        patch("gateway.webhook._event_bus") as mock_bus,
    ):
        mock_config.WEBHOOK_SECRET = "test-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 1000.0
        mock_config.DEFAULT_EXCHANGE = "binance"
        mock_bus.emit_background = AsyncMock()

        import database as _db_module

        with patch.object(
            _db_module, "insert_signal", new_callable=AsyncMock, return_value=40
        ) as mock_insert:
            req = _make_request(
                payload={"secret": "test-secret", "symbol": "BTCUSDT", "action": "buy"},
                headers={"x-forwarded-for": "203.0.113.5, 10.0.0.1"},
                client_host="10.0.0.1",
            )
            await webhook(req)
            source_ip = mock_insert.call_args.kwargs["source_ip"]
        assert source_ip == "10.0.0.1"


# ═══════════════════════════════════════════════════════════════
# EVENT DISPATCH
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_signal_received_dispatched_to_event_bus():
    """Successful ingress should fire emit_background with a SignalReceived event."""
    from core.events import SignalReceived
    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()

    emitted_events = []

    async def capture_emit(event):
        emitted_events.append(event)

    with (
        patch("gateway.webhook.config") as mock_config,
        patch("gateway.webhook._event_bus") as mock_bus,
    ):
        mock_config.WEBHOOK_SECRET = "test-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 1000.0
        mock_config.DEFAULT_EXCHANGE = "binance"
        mock_bus.emit_background = AsyncMock(side_effect=capture_emit)

        import database as _db_module

        with patch.object(
            _db_module, "insert_signal", new_callable=AsyncMock, return_value=99
        ):
            req = _make_request(
                payload={
                    "secret": "test-secret",
                    "symbol": "SOLUSDT",
                    "action": "buy",
                    "price": 150.0,
                    "interval": "60",
                    "sl": "140",
                    "tp": "165",
                    "exchange": "bybit",
                }
            )
            resp = await webhook(req)
        assert resp["status"] == "dispatched"

        assert len(emitted_events) == 1
        evt = emitted_events[0]
        assert isinstance(evt, SignalReceived)
        assert evt.symbol == "SOLUSDT"
        assert evt.action == "buy"
        assert evt.price == pytest.approx(150.0)
        assert evt.interval == "60"
        assert evt.sl == "140"
        assert evt.tp == "165"
        assert evt.exchange == "bybit"
        assert evt.signal_id == 99


@pytest.mark.asyncio
async def test_secret_stripped_from_stored_payload():
    """The 'secret' key must NOT be stored in the DB payload after auth."""
    from gateway.webhook import _WEBHOOK_RATE_LIMITS, webhook

    _WEBHOOK_RATE_LIMITS.clear()
    captured_args = {}

    async def capture_insert(symbol, action, price, quote_qty, source_ip, payload):
        captured_args["payload"] = payload
        return 50

    with (
        patch("gateway.webhook.config") as mock_config,
        patch("gateway.webhook._event_bus") as mock_bus,
    ):
        mock_config.WEBHOOK_SECRET = "test-secret"  # noqa: S105
        mock_config.DASHBOARD_TOKEN = ""
        mock_config.MAX_QUOTE_QTY = 1000.0
        mock_config.DEFAULT_EXCHANGE = "binance"
        mock_bus.emit_background = AsyncMock()

        import database as _db_module

        with patch.object(
            _db_module, "insert_signal", new_callable=AsyncMock, return_value=50
        ) as mock_insert:
            req = _make_request(
                payload={"secret": "test-secret", "symbol": "BTCUSDT", "action": "buy"}
            )
            await webhook(req)
            payload = mock_insert.call_args.kwargs["payload"]
        # Secret should be stripped from the stored payload
        assert "secret" not in payload
