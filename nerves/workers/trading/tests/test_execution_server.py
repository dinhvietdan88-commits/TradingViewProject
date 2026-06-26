"""
test_execution_server.py — Tests for SERVER B Execution Server.

Uses httpx AsyncClient + ASGITransport pattern (no running server needed).
Mocks TradeEngine internals to isolate the endpoint logic.
"""

import os
import pathlib
import sys
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

# Ensure server/ is on path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient

# ─────────────────────────────────────────────────────────────────
# Fixture: exec_client — isolated test DB + configured secret
# ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def exec_client(tmp_path):
    """Provide httpx.AsyncClient wired to execution_server.app."""
    import config
    import database

    config.DB_PATH = str(tmp_path / "test_exec.db")
    config.SERVER_B_SECRET = "test-exec-secret"  # noqa: S105
    config.DEFAULT_EXCHANGE = "binance"
    config.TELEGRAM_BOT_ENABLED = False
    config.BRIEF_ENABLED = False
    config.MCP_ENABLED = False
    config.RAG_ENABLED = False
    original_forward_test = getattr(config, "FORWARD_TEST_ENABLED", False)
    config.FORWARD_TEST_ENABLED = False
    os.environ["DB_PATH"] = config.DB_PATH

    await database.init_db()

    from execution_server import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        try:
            yield ac
        finally:
            config.FORWARD_TEST_ENABLED = original_forward_test


# ─────────────────────────────────────────────────────────────────
# Helper: valid request payload + headers
# ─────────────────────────────────────────────────────────────────

VALID_HEADERS = {"X-Server-B-Secret": "test-exec-secret"}

VALID_PAYLOAD = {
    "symbol": "BTCUSDT",
    "action": "buy",
    "price": 68000.0,
    "quote_qty": 50.0,
    "sl": "67000",
    "tp": "72000",
    "exchange": "binance",
    "analysis_text": "Strong bullish pattern detected by AI analyzer.",
}


# ═══════════════════════════════════════════════════════════════
# TEST 1: Health endpoint
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_health_endpoint(exec_client):
    """GET /health returns status ok and identifies execution-vault-b."""
    resp = await exec_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["server"] == "execution-vault-b"


# ═══════════════════════════════════════════════════════════════
# TEST 2: Invalid secret → 401 Unauthorized
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_invalid_secret_returns_401(exec_client):
    """POST /api/execute-trade with wrong secret → 401."""
    resp = await exec_client.post(
        "/api/execute-trade",
        json=VALID_PAYLOAD,
        headers={"X-Server-B-Secret": "wrong-secret"},
    )
    assert resp.status_code == 401
    assert "Unauthorized" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_missing_secret_returns_401(exec_client):
    """POST /api/execute-trade without secret header → 401."""
    resp = await exec_client.post("/api/execute-trade", json=VALID_PAYLOAD)
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════
# TEST 3: Missing required fields → 400
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_missing_symbol_returns_400(exec_client):
    """POST /api/execute-trade without symbol → 400."""
    payload = {**VALID_PAYLOAD}
    del payload["symbol"]
    resp = await exec_client.post(
        "/api/execute-trade", json=payload, headers=VALID_HEADERS
    )
    assert resp.status_code == 400
    assert "symbol" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_missing_action_returns_400(exec_client):
    """POST /api/execute-trade without action → 400."""
    payload = {**VALID_PAYLOAD}
    del payload["action"]
    resp = await exec_client.post(
        "/api/execute-trade", json=payload, headers=VALID_HEADERS
    )
    assert resp.status_code == 400
    assert "action" in resp.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════════
# TEST 4: Valid trade execution (mock TradeEngine)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_valid_trade_execution_success(exec_client):
    """POST /api/execute-trade with valid payload → calls TradeEngine, returns success."""
    from core.events import TradeExecuted

    async def mock_execute_trade(event):
        """Simulate TradeEngine emitting TradeExecuted on the exec_bus."""
        # The execution server sets up an isolated bus and registers handlers.
        # We need to get that bus and emit TradeExecuted on it.
        from engine import trade_engine

        current_bus = trade_engine.get_bus()
        await current_bus.emit(
            TradeExecuted(
                signal_id=event.signal_id,
                trade_id=1,
                symbol=event.symbol,
                side=event.action.upper(),
                order_id="ORD-EXEC-001",
                status="FILLED",
                executed_qty=0.000735,
                executed_price=68000.0,
                quote_qty=50.0,
                exchange="binance",
            )
        )

    with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
        with patch("notifier.notify_all", new_callable=AsyncMock):
            resp = await exec_client.post(
                "/api/execute-trade", json=VALID_PAYLOAD, headers=VALID_HEADERS
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["order_id"] == "ORD-EXEC-001"
    assert data["fill_price"] == 68000.0
    assert data["status"] == "FILLED"
    assert data["executed_qty"] == 0.000735


@pytest.mark.asyncio
async def test_valid_trade_persists_signal_to_db(exec_client):
    """POST /api/execute-trade persists a signal row to the database."""
    from core.events import TradeExecuted

    async def mock_execute_trade(event):
        from engine import trade_engine

        current_bus = trade_engine.get_bus()
        await current_bus.emit(
            TradeExecuted(
                signal_id=event.signal_id,
                trade_id=1,
                symbol=event.symbol,
                side=event.action.upper(),
                order_id="ORD-DB-001",
                status="FILLED",
                executed_qty=0.001,
                executed_price=68000.0,
                quote_qty=50.0,
                exchange="binance",
            )
        )

    with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
        with patch("notifier.notify_all", new_callable=AsyncMock):
            resp = await exec_client.post(
                "/api/execute-trade", json=VALID_PAYLOAD, headers=VALID_HEADERS
            )

    assert resp.status_code == 200

    # Verify signal was persisted
    import aiosqlite

    import config

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM signals WHERE symbol = 'BTCUSDT'") as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row["action"] == "buy"
            assert row["symbol"] == "BTCUSDT"


# ═══════════════════════════════════════════════════════════════
# TEST 5: Trade engine failure handling
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_trade_engine_failure_returns_error(exec_client):
    """POST /api/execute-trade when TradeEngine emits TradeFailed → 500 with error."""
    from core.events import TradeFailed

    async def mock_execute_trade(event):
        from engine import trade_engine

        current_bus = trade_engine.get_bus()
        await current_bus.emit(
            TradeFailed(
                signal_id=event.signal_id,
                symbol=event.symbol,
                side=event.action.upper(),
                error="Insufficient balance",
                quote_qty=50.0,
                exchange="binance",
            )
        )

    with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
        resp = await exec_client.post(
            "/api/execute-trade", json=VALID_PAYLOAD, headers=VALID_HEADERS
        )

    assert resp.status_code == 500
    data = resp.json()
    assert data["success"] is False
    assert "Insufficient balance" in data["error"]


@pytest.mark.asyncio
async def test_trade_engine_exception_returns_500(exec_client):
    """POST /api/execute-trade when TradeEngine raises Exception → 500."""

    async def mock_execute_trade(event):
        raise RuntimeError("Exchange connection timeout")

    with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
        resp = await exec_client.post(
            "/api/execute-trade", json=VALID_PAYLOAD, headers=VALID_HEADERS
        )

    assert resp.status_code == 500
    data = resp.json()
    assert data["success"] is False
    assert "Internal server error during trade execution" in data["error"]


# ═══════════════════════════════════════════════════════════════
# TEST 6: SERVER_B_SECRET not configured → 500
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unconfigured_secret_returns_500(exec_client):
    """POST /api/execute-trade when SERVER_B_SECRET is empty → 500."""
    import config

    original = config.SERVER_B_SECRET
    config.SERVER_B_SECRET = ""
    try:
        resp = await exec_client.post(
            "/api/execute-trade",
            json=VALID_PAYLOAD,
            headers={"X-Server-B-Secret": "anything"},
        )
        assert resp.status_code == 500
        assert "not configured" in resp.json()["detail"].lower()
    finally:
        config.SERVER_B_SECRET = original


# ═══════════════════════════════════════════════════════════════
# TEST 7: Bus isolation — original bus restored after execution
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bus_restored_after_execution(exec_client):
    """Verify the trade_engine's original bus is restored even on failure."""
    from engine import trade_engine

    original_bus = trade_engine.get_bus()

    async def mock_execute_trade(event):
        raise RuntimeError("Simulated failure")

    with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
        await exec_client.post(
            "/api/execute-trade", json=VALID_PAYLOAD, headers=VALID_HEADERS
        )

    # The original bus should be restored
    assert trade_engine.get_bus() is original_bus


# ═══════════════════════════════════════════════════════════════
# TEST 8: Telegram notification called on success
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_telegram_notification_sent_on_success(exec_client):
    """Verify notify_all is called when trade succeeds."""
    from core.events import TradeExecuted

    async def mock_execute_trade(event):
        from engine import trade_engine

        current_bus = trade_engine.get_bus()
        await current_bus.emit(
            TradeExecuted(
                signal_id=event.signal_id,
                trade_id=1,
                symbol=event.symbol,
                side=event.action.upper(),
                order_id="ORD-NOTIFY-001",
                status="FILLED",
                executed_qty=0.001,
                executed_price=68000.0,
                quote_qty=50.0,
                exchange="binance",
            )
        )

    with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
        with patch("notifier.notify_all", new_callable=AsyncMock) as mock_notify:
            resp = await exec_client.post(
                "/api/execute-trade", json=VALID_PAYLOAD, headers=VALID_HEADERS
            )

    assert resp.status_code == 200
    mock_notify.assert_awaited_once()
    call_msg = mock_notify.call_args[0][0]
    assert "Pipeline Trade Executed" in call_msg
    assert "BTCUSDT" in call_msg


# ═══════════════════════════════════════════════════════════════
# TEST 9: Constant-time comparison (hmac.compare_digest used)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_secret_validation_uses_constant_time_compare(exec_client):
    """Verify _validate_secret uses hmac.compare_digest (not ==)."""
    with patch("execution_server.hmac.compare_digest", return_value=True) as mock_cmp:
        from core.events import TradeExecuted

        async def mock_execute_trade(event):
            from engine import trade_engine

            current_bus = trade_engine.get_bus()
            await current_bus.emit(
                TradeExecuted(
                    signal_id=event.signal_id,
                    trade_id=1,
                    symbol=event.symbol,
                    side="BUY",
                    order_id="ORD-CT-001",
                    status="FILLED",
                    executed_qty=0.001,
                    executed_price=68000.0,
                    quote_qty=50.0,
                    exchange="binance",
                )
            )

        with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
            with patch("notifier.notify_all", new_callable=AsyncMock):
                await exec_client.post(
                    "/api/execute-trade", json=VALID_PAYLOAD, headers=VALID_HEADERS
                )

        # hmac.compare_digest should have been called
        mock_cmp.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# TEST 10: Robust fallbacks for quote_qty and analysis_text
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_execute_trade_fallback_quote_qty_calculated_from_qty_and_price(
    exec_client,
):
    """Verify quote_qty is calculated from qty and price if missing."""
    from core.events import TradeExecuted

    captured_event = {}

    async def mock_execute_trade(event):
        from engine import trade_engine

        current_bus = trade_engine.get_bus()
        captured_event["quote_qty"] = event.quote_qty
        captured_event["analysis_text"] = event.analysis_text
        await current_bus.emit(
            TradeExecuted(
                signal_id=event.signal_id,
                trade_id=1,
                symbol=event.symbol,
                side=event.action.upper(),
                order_id="ORD-FB-001",
                status="FILLED",
                executed_qty=0.001,
                executed_price=68000.0,
                quote_qty=event.quote_qty,
                exchange="binance",
            )
        )

    payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 50000.0,
        "qty": 0.002,
        # quote_qty is missing
        "sl": "48000",
        "tp": "52000",
        "exchange": "binance",
        "analysis": "Calculated quantity test.",  # analysis instead of analysis_text
    }

    with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
        with patch("notifier.notify_all", new_callable=AsyncMock):
            resp = await exec_client.post(
                "/api/execute-trade", json=payload, headers=VALID_HEADERS
            )

    assert resp.status_code == 200
    # 0.002 * 50000.0 = 100.0
    assert captured_event.get("quote_qty") == 100.0
    assert captured_event.get("analysis_text") == "Calculated quantity test."


@pytest.mark.asyncio
async def test_execute_trade_fallback_quote_qty_default(exec_client):
    """Verify quote_qty defaults to 10.0 if quote_qty, qty, price are missing."""
    from core.events import TradeExecuted

    captured_event = {}

    async def mock_execute_trade(event):
        from engine import trade_engine

        current_bus = trade_engine.get_bus()
        captured_event["quote_qty"] = event.quote_qty
        await current_bus.emit(
            TradeExecuted(
                signal_id=event.signal_id,
                trade_id=1,
                symbol=event.symbol,
                side=event.action.upper(),
                order_id="ORD-FB-002",
                status="FILLED",
                executed_qty=0.001,
                executed_price=68000.0,
                quote_qty=event.quote_qty,
                exchange="binance",
            )
        )

    payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 50000.0,
        # qty is missing, quote_qty is missing
        "sl": "48000",
        "tp": "52000",
        "exchange": "binance",
        "analysis_text": "Default quote_qty test.",
    }

    with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
        with patch("notifier.notify_all", new_callable=AsyncMock):
            resp = await exec_client.post(
                "/api/execute-trade", json=payload, headers=VALID_HEADERS
            )

    assert resp.status_code == 200
    assert captured_event.get("quote_qty") == 10.0


@pytest.mark.asyncio
async def test_execute_trade_quote_qty_empty_string(exec_client):
    """Verify quote_qty as empty string "" falls back to default 10.0."""
    from core.events import TradeExecuted

    captured_event = {}

    async def mock_execute_trade(event):
        from engine import trade_engine

        current_bus = trade_engine.get_bus()
        captured_event["quote_qty"] = event.quote_qty
        captured_event["price"] = event.price
        await current_bus.emit(
            TradeExecuted(
                signal_id=event.signal_id,
                trade_id=1,
                symbol=event.symbol,
                side=event.action.upper(),
                order_id="ORD-FB-003",
                status="FILLED",
                executed_qty=0.001,
                executed_price=68000.0,
                quote_qty=event.quote_qty,
                exchange="binance",
            )
        )

    payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 50000.0,
        "quote_qty": "",
        "sl": "48000",
        "tp": "52000",
        "exchange": "binance",
    }

    with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
        with patch("notifier.notify_all", new_callable=AsyncMock):
            resp = await exec_client.post(
                "/api/execute-trade", json=payload, headers=VALID_HEADERS
            )

    assert resp.status_code == 200
    assert captured_event.get("quote_qty") == 10.0


@pytest.mark.asyncio
async def test_execute_trade_quote_qty_invalid_string(exec_client):
    """Verify quote_qty as invalid string "abc" falls back to default 10.0."""
    from core.events import TradeExecuted

    captured_event = {}

    async def mock_execute_trade(event):
        from engine import trade_engine

        current_bus = trade_engine.get_bus()
        captured_event["quote_qty"] = event.quote_qty
        await current_bus.emit(
            TradeExecuted(
                signal_id=event.signal_id,
                trade_id=1,
                symbol=event.symbol,
                side=event.action.upper(),
                order_id="ORD-FB-004",
                status="FILLED",
                executed_qty=0.001,
                executed_price=68000.0,
                quote_qty=event.quote_qty,
                exchange="binance",
            )
        )

    payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 50000.0,
        "quote_qty": "abc",
        "sl": "48000",
        "tp": "52000",
        "exchange": "binance",
    }

    with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
        with patch("notifier.notify_all", new_callable=AsyncMock):
            resp = await exec_client.post(
                "/api/execute-trade", json=payload, headers=VALID_HEADERS
            )

    assert resp.status_code == 200
    assert captured_event.get("quote_qty") == 10.0


@pytest.mark.asyncio
async def test_execute_trade_price_invalid_string(exec_client):
    """Verify price as invalid string "abc" falls back to None."""
    from core.events import TradeExecuted

    captured_event = {}

    async def mock_execute_trade(event):
        from engine import trade_engine

        current_bus = trade_engine.get_bus()
        captured_event["price"] = event.price
        await current_bus.emit(
            TradeExecuted(
                signal_id=event.signal_id,
                trade_id=1,
                symbol=event.symbol,
                side=event.action.upper(),
                order_id="ORD-FB-005",
                status="FILLED",
                executed_qty=0.001,
                executed_price=68000.0,
                quote_qty=event.quote_qty,
                exchange="binance",
            )
        )

    payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": "abc",
        "quote_qty": 50.0,
        "sl": "48000",
        "tp": "52000",
        "exchange": "binance",
    }

    with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
        with patch("notifier.notify_all", new_callable=AsyncMock):
            resp = await exec_client.post(
                "/api/execute-trade", json=payload, headers=VALID_HEADERS
            )

    assert resp.status_code == 200
    assert captured_event.get("price") is None


@pytest.mark.asyncio
async def test_execute_trade_invalid_qty_or_price_calculation(exec_client):
    """Verify invalid qty or price for calculation falls back to default 10.0."""
    from core.events import TradeExecuted

    captured_event = {}

    async def mock_execute_trade(event):
        from engine import trade_engine

        current_bus = trade_engine.get_bus()
        captured_event["quote_qty"] = event.quote_qty
        await current_bus.emit(
            TradeExecuted(
                signal_id=event.signal_id,
                trade_id=1,
                symbol=event.symbol,
                side=event.action.upper(),
                order_id="ORD-FB-006",
                status="FILLED",
                executed_qty=0.001,
                executed_price=68000.0,
                quote_qty=event.quote_qty,
                exchange="binance",
            )
        )

    # Scenario 1: qty is invalid, price is valid. quote_qty is missing.
    payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 50000.0,
        "qty": "abc",
        "sl": "48000",
        "tp": "52000",
        "exchange": "binance",
    }

    with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
        with patch("notifier.notify_all", new_callable=AsyncMock):
            resp = await exec_client.post(
                "/api/execute-trade", json=payload, headers=VALID_HEADERS
            )

    assert resp.status_code == 200
    assert captured_event.get("quote_qty") == 10.0
