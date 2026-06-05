"""
Tests for get_stats_by_mode() in data/query_service.py.

Strategy: use aiosqlite in-memory DB (":memory:") to avoid filesystem dependencies.
"""

import pytest
import aiosqlite
from unittest.mock import patch, AsyncMock


# ── Fixtures ──────────────────────────────────────────────────────────────────


async def _make_db():
    """Return an in-memory aiosqlite connection with signals + trades schema."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.execute("""
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY,
            mode TEXT
        )
    """)
    await db.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY,
            signal_id INTEGER,
            status TEXT,
            pnl REAL,
            order_type TEXT DEFAULT 'MARKET',
            order_id TEXT,
            exchange TEXT DEFAULT 'binance'
        )
    """)
    await db.commit()
    return db


async def _seed(db, rows):
    """Insert (signal_mode, trade_pnl, trade_status) tuples."""
    for i, (mode, pnl, status) in enumerate(rows, start=1):
        await db.execute("INSERT INTO signals (id, mode) VALUES (?, ?)", (i, mode))
        await db.execute(
            "INSERT INTO trades (id, signal_id, status, pnl, order_id, exchange) VALUES (?, ?, ?, ?, ?, ?)",
            (i, i, status, pnl, f"10000{i}", "binance"),
        )
    await db.commit()


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_stats_by_mode_empty():
    """With no FILLED trades, all buckets must return zero stats."""
    from data.query_service import get_stats_by_mode

    db = await _make_db()

    with patch("data.query_service.aiosqlite.connect") as mock_connect:
        # Return the in-memory db from the context manager
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=db)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_connect.return_value = mock_ctx

        result = await get_stats_by_mode()

    await db.close()

    assert result["overall"]["total_trades"] == 0
    assert result["by_mode"]["MTT"]["total_trades"] == 0
    assert result["by_mode"]["MIS"]["total_trades"] == 0
    assert result["by_mode"]["OTHER"]["total_trades"] == 0


@pytest.mark.asyncio
async def test_get_stats_by_mode_groups_correctly():
    """MTT and MIS signals must be counted in separate buckets with correct metrics."""
    from data.query_service import get_stats_by_mode

    db = await _make_db()
    # 2 MTT wins, 1 MTT loss; 1 MIS win
    await _seed(
        db,
        [
            ("MTT", +10.0, "FILLED"),
            ("MTT", +20.0, "FILLED"),
            ("MTT", -5.0, "FILLED"),
            ("MIS", +15.0, "FILLED"),
        ],
    )

    with patch("data.query_service.aiosqlite.connect") as mock_connect:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=db)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_connect.return_value = mock_ctx

        result = await get_stats_by_mode()

    await db.close()

    # Overall
    assert result["overall"]["total_trades"] == 4
    assert result["overall"]["winning_trades"] == 3
    assert result["overall"]["total_pnl"] == pytest.approx(40.0)

    # MTT bucket
    mtt = result["by_mode"]["MTT"]
    assert mtt["total_trades"] == 3
    assert mtt["winning_trades"] == 2
    assert mtt["losing_trades"] == 1
    assert mtt["total_pnl"] == pytest.approx(25.0)
    assert mtt["win_rate"] == pytest.approx(66.7, abs=0.1)

    # MIS bucket
    mis = result["by_mode"]["MIS"]
    assert mis["total_trades"] == 1
    assert mis["winning_trades"] == 1
    assert mis["total_pnl"] == pytest.approx(15.0)
    assert mis["win_rate"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_get_stats_by_mode_unknown_mode_grouped_as_other():
    """Signals with NULL or empty mode must be grouped under the 'OTHER' key."""
    from data.query_service import get_stats_by_mode

    db = await _make_db()
    # NULL mode and empty string mode — both should land in OTHER
    await _seed(
        db,
        [
            (None, +8.0, "FILLED"),  # NULL mode
            ("", -3.0, "FILLED"),  # empty string mode
            ("MTT", +5.0, "FILLED"),  # known mode — should NOT go to OTHER
        ],
    )

    with patch("data.query_service.aiosqlite.connect") as mock_connect:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=db)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_connect.return_value = mock_ctx

        result = await get_stats_by_mode()

    await db.close()

    other = result["by_mode"]["OTHER"]
    assert other["total_trades"] == 2, (
        f"NULL and empty modes must both land in OTHER, got total_trades={other['total_trades']}"
    )
    assert other["total_pnl"] == pytest.approx(5.0)  # 8 + (-3)

    mtt = result["by_mode"]["MTT"]
    assert mtt["total_trades"] == 1

    # MIS sentinel must still exist with 0 trades
    assert result["by_mode"]["MIS"]["total_trades"] == 0


@pytest.mark.asyncio
async def test_get_stats_by_mode_weex_dry_run_included():
    """weex dry-run trades must be included when demo=False, but binance dry-run must be excluded."""
    from data.query_service import get_stats_by_mode

    db = await _make_db()

    await db.execute("INSERT INTO signals (id, mode) VALUES (1, 'MTT')")
    await db.execute("INSERT INTO signals (id, mode) VALUES (2, 'MTT')")
    await db.execute("INSERT INTO signals (id, mode) VALUES (3, 'MTT')")

    # 1. Binance dry-run trade
    await db.execute(
        "INSERT INTO trades (id, signal_id, status, pnl, order_type, order_id, exchange) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, 1, "FILLED", 10.0, "DRY_RUN", "DRY-LIM-12345", "binance"),
    )
    # 2. Weex dry-run trade
    await db.execute(
        "INSERT INTO trades (id, signal_id, status, pnl, order_type, order_id, exchange) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (2, 2, "FILLED", 20.0, "DRY_RUN", "DRY-WEX-54", "weex"),
    )
    # 3. Normal Binance trade
    await db.execute(
        "INSERT INTO trades (id, signal_id, status, pnl, order_type, order_id, exchange) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (3, 3, "FILLED", 30.0, "LIMIT", "REAL-12345", "binance"),
    )
    await db.commit()

    with patch("data.query_service.aiosqlite.connect") as mock_connect:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=db)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_connect.value = mock_ctx
        mock_connect.return_value = mock_ctx

        # When demo=False (default)
        result = await get_stats_by_mode(demo=False)

    await db.close()

    # Total should be 2: Weex dry-run (20.0) + Normal Binance (30.0)
    assert result["overall"]["total_trades"] == 2
    assert result["overall"]["total_pnl"] == pytest.approx(50.0)
