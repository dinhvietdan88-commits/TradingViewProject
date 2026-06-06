"""
Unit tests: database.py CRUD operations
Uses a temp file DB per test to avoid :memory: isolation issues.
"""

import pathlib
import sys

import pytest
import pytest_asyncio

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
import config
import database


@pytest_asyncio.fixture(autouse=True)
async def isolated_db(tmp_path):
    """Tao file DB rieng cho moi test, xoa sau khi xong."""
    db_file = str(tmp_path / "test.db")
    config.DB_PATH = db_file
    await database.init_db()
    yield
    # Cleanup automatic qua tmp_path


# ═══ SIGNAL CRUD ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_insert_signal_returns_id():
    sig_id = await database.insert_signal("BTCUSDT", "buy", 68000.0, 50.0)
    assert isinstance(sig_id, int)
    assert sig_id >= 1


@pytest.mark.asyncio
async def test_insert_multiple_signals_increments_id():
    id1 = await database.insert_signal("BTCUSDT", "buy", 68000.0)
    id2 = await database.insert_signal("ETHUSDT", "sell", 3500.0)
    assert id2 > id1


@pytest.mark.asyncio
async def test_update_signal_status():
    sig_id = await database.insert_signal("BTCUSDT", "buy")
    await database.update_signal_status(sig_id, 1)
    # No exception = pass


# ═══ TRADE CRUD ═══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_insert_trade_returns_id():
    sig_id = await database.insert_signal("BTCUSDT", "buy")
    trade_id = await database.insert_trade(
        signal_id=sig_id,
        symbol="BTCUSDT",
        side="BUY",
        status="FILLED",
        pnl=150.0,
        order_id="123456",
    )
    assert isinstance(trade_id, int)
    assert trade_id >= 1


@pytest.mark.asyncio
async def test_get_trades_empty():
    result = await database.get_trades()
    assert result["total"] == 0
    assert result["trades"] == []


@pytest.mark.asyncio
async def test_get_trades_returns_inserted():
    sig_id = await database.insert_signal("BTCUSDT", "buy", 68000.0)
    await database.insert_trade(
        signal_id=sig_id,
        symbol="BTCUSDT",
        side="BUY",
        status="FILLED",
        pnl=100.0,
        order_id="123456",
    )
    result = await database.get_trades()
    assert result["total"] == 1
    assert result["trades"][0]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_get_trades_filter_by_symbol():
    s1 = await database.insert_signal("BTCUSDT", "buy")
    s2 = await database.insert_signal("ETHUSDT", "buy")
    await database.insert_trade(
        signal_id=s1,
        symbol="BTCUSDT",
        side="BUY",
        status="FILLED",
        pnl=100.0,
        order_id="123456",
    )
    await database.insert_trade(
        signal_id=s2,
        symbol="ETHUSDT",
        side="BUY",
        status="FILLED",
        pnl=-50.0,
        order_id="123457",
    )
    result = await database.get_trades(symbol="BTCUSDT")
    assert result["total"] == 1
    assert all(t["symbol"] == "BTCUSDT" for t in result["trades"])


@pytest.mark.asyncio
async def test_get_trades_pagination():
    sig = await database.insert_signal("BTCUSDT", "buy")
    for i in range(10):
        await database.insert_trade(
            signal_id=sig,
            symbol="BTCUSDT",
            side="BUY",
            status="FILLED",
            pnl=float(i * 10),
            order_id=f"12345{i}",
        )
    result = await database.get_trades(limit=3, offset=0)
    assert len(result["trades"]) == 3
    assert result["total"] == 10


# ═══ STATS ════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_stats_no_trades():
    stats = await database.get_stats()
    assert stats["total_trades"] == 0
    assert stats["win_rate"] == 0.0


@pytest.mark.asyncio
async def test_stats_correct_win_rate():
    sig = await database.insert_signal("BTCUSDT", "buy")
    await database.insert_trade(
        signal_id=sig,
        symbol="BTCUSDT",
        side="BUY",
        status="FILLED",
        pnl=100.0,
        order_id="123456",
    )
    await database.insert_trade(
        signal_id=sig,
        symbol="BTCUSDT",
        side="SELL",
        status="FILLED",
        pnl=-50.0,
        order_id="123457",
    )
    stats = await database.get_stats()
    assert stats["total_trades"] == 2
    assert stats["win_rate"] == 50.0


@pytest.mark.asyncio
async def test_stats_profit_factor():
    sig = await database.insert_signal("BTCUSDT", "buy")
    await database.insert_trade(
        signal_id=sig,
        symbol="BTCUSDT",
        side="BUY",
        status="FILLED",
        pnl=200.0,
        order_id="123456",
    )
    await database.insert_trade(
        signal_id=sig,
        symbol="BTCUSDT",
        side="SELL",
        status="FILLED",
        pnl=-100.0,
        order_id="123457",
    )
    stats = await database.get_stats()
    assert stats["profit_factor"] == 2.0


@pytest.mark.asyncio
async def test_stats_excludes_failed_trades():
    """FAILED trades khong co pnl -> khong tinh vao stats."""
    sig = await database.insert_signal("BTCUSDT", "buy")
    await database.insert_trade(
        signal_id=sig, symbol="BTCUSDT", side="BUY", status="FAILED", order_id="123456"
    )
    stats = await database.get_stats()
    assert stats["total_trades"] == 0


# ═══ EQUITY CURVE ═════════════════════════════════════════════


@pytest.mark.asyncio
async def test_equity_empty():
    result = await database.get_equity_curve()
    assert result["labels"] == []
    assert result["cumulative_pnl"] == []


@pytest.mark.asyncio
async def test_equity_cumulative_correct():
    sig = await database.insert_signal("BTCUSDT", "buy")
    await database.insert_trade(
        signal_id=sig,
        symbol="BTCUSDT",
        side="BUY",
        status="FILLED",
        pnl=100.0,
        order_id="123456",
    )
    await database.insert_trade(
        signal_id=sig,
        symbol="BTCUSDT",
        side="SELL",
        status="FILLED",
        pnl=-30.0,
        order_id="123457",
    )
    await database.insert_trade(
        signal_id=sig,
        symbol="BTCUSDT",
        side="BUY",
        status="FILLED",
        pnl=50.0,
        order_id="123458",
    )
    result = await database.get_equity_curve()
    assert result["cumulative_pnl"] == [100.0, 70.0, 120.0]
