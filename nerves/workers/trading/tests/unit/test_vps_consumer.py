from unittest.mock import AsyncMock, patch

import pytest

import config
import database
from core.events import SignalReceived, TradeExecuted, TradeFailed
from workers.vps_consumer import VpsSignalConsumer


@pytest.mark.asyncio
async def test_vps_consumer_stale_check(tmp_path):
    # Set up temp database for the test
    config.DB_PATH = str(tmp_path / "test_vps.db")
    await database.init_db()

    consumer = VpsSignalConsumer()
    consumer.send_acks = AsyncMock(return_value=True)

    # Mock stale signal: age 300 minutes > max 240 minutes
    stale_signal = {
        "queue_id": 101,
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 68000.0,
        "quote_qty": 10.0,
        "age_minutes": 300.0,
        "payload": {"symbol": "BTCUSDT", "action": "buy", "price": 68000.0},
    }

    # Process signal
    await consumer._process_signal(stale_signal)

    # Verify skipped stale ACK was sent
    consumer.send_acks.assert_called_once_with(
        [
            {
                "queue_id": 101,
                "status": "skipped_stale",
                "error_msg": "Signal age (300.0m) exceeded configured limit (240m)",
            }
        ]
    )


@pytest.mark.asyncio
async def test_vps_consumer_duplicate_check(tmp_path):
    config.DB_PATH = str(tmp_path / "test_vps.db")
    await database.init_db()

    # Pre-insert signal with vbs_queue_id=102
    await database.insert_signal(
        symbol="BTCUSDT", action="buy", price=68000.0, quote_qty=10.0, vbs_queue_id=102
    )

    consumer = VpsSignalConsumer()
    consumer.send_acks = AsyncMock(return_value=True)

    # Pull duplicate signal
    dup_signal = {
        "queue_id": 102,
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 68000.0,
        "quote_qty": 10.0,
        "age_minutes": 5.0,
        "payload": {"symbol": "BTCUSDT", "action": "buy"},
    }

    await consumer._process_signal(dup_signal)

    # Verify it immediately ACKs with "executed" (skips re-execution)
    consumer.send_acks.assert_called_once_with(
        [
            {
                "queue_id": 102,
                "status": "executed",
                "error_msg": "Duplicate signal already stored locally",
            }
        ]
    )


@pytest.mark.asyncio
async def test_vps_consumer_success_flow(tmp_path):
    config.DB_PATH = str(tmp_path / "test_vps.db")
    await database.init_db()

    consumer = VpsSignalConsumer()
    consumer.send_acks = AsyncMock(return_value=True)

    signal = {
        "queue_id": 103,
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 68000.0,
        "quote_qty": 10.0,
        "age_minutes": 5.0,
        "payload": {"symbol": "BTCUSDT", "action": "buy", "price": 68000.0},
    }

    # Process signal
    with patch(
        "core.event_bus.bus.emit_background", new_callable=AsyncMock
    ) as mock_emit:
        await consumer._process_signal(signal)

        # Verify signal inserted to local DB
        pending_acks_keys = list(consumer.pending_acks.keys())
        assert len(pending_acks_keys) == 1
        local_sig_id = pending_acks_keys[0]
        assert consumer.pending_acks[local_sig_id] == 103

        # Verify SignalReceived event emitted
        mock_emit.assert_called_once()
        event = mock_emit.call_args[0][0]
        assert isinstance(event, SignalReceived)
        assert event.signal_id == local_sig_id
        assert event.symbol == "BTCUSDT"
        assert event.action == "buy"

    # Trigger successful trade execution callback
    exec_event = TradeExecuted(
        signal_id=local_sig_id,
        trade_id=1,
        symbol="BTCUSDT",
        side="BUY",
        order_id="ORD123",
        status="FILLED",
    )

    await consumer.on_trade_executed(exec_event)

    # Verify ACK sent to VBS and pending ack removed
    consumer.send_acks.assert_called_with([{"queue_id": 103, "status": "executed"}])
    assert local_sig_id not in consumer.pending_acks


@pytest.mark.asyncio
async def test_vps_consumer_failure_flow(tmp_path):
    config.DB_PATH = str(tmp_path / "test_vps.db")
    await database.init_db()

    consumer = VpsSignalConsumer()
    consumer.send_acks = AsyncMock(return_value=True)

    local_sig_id = 999
    consumer.pending_acks[local_sig_id] = 104

    # Trigger trade failure callback
    fail_event = TradeFailed(
        signal_id=local_sig_id,
        symbol="BTCUSDT",
        side="BUY",
        error="Insufficient margin balance",
    )

    await consumer.on_trade_failed(fail_event)

    # Verify failed ACK sent to VBS
    consumer.send_acks.assert_called_once_with(
        [
            {
                "queue_id": 104,
                "status": "failed",
                "error_msg": "Insufficient margin balance",
            }
        ]
    )
    assert local_sig_id not in consumer.pending_acks
