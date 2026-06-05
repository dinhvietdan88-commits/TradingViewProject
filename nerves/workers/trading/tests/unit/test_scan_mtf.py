import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from pathlib import Path

from analysis import (
    ScanResult,
    TrendTemplateResult,
    VCPResult,
    MTFScanResult,
    scan_symbol_multi_timeframe,
)
from telegram_bot import parse_mtf_trade_params


@pytest.mark.asyncio
async def test_scan_symbol_multi_timeframe():
    session = MagicMock()
    semaphore = asyncio.Semaphore(1)

    # 250 bars of mock candles to satisfy Trend Template indicators
    mock_candles = []
    import time

    now_ms = int(time.time() * 1000)
    day_ms = 24 * 60 * 60 * 1000
    for i in range(250):
        ts = now_ms - (250 - i) * day_ms
        price = 100.0 + i * 0.5  # clear uptrend
        mock_candles.append(
            [
                ts,
                price,  # open
                price + 2.0,  # high
                price - 2.0,  # low
                price + 0.1,  # close
                1000.0,  # volume
            ]
        )

    with patch(
        "analysis.fetch_candles_with_retry", AsyncMock(return_value=mock_candles)
    ):
        res = await scan_symbol_multi_timeframe(
            session=session,
            exchange_name="binance",
            symbol="BTCUSDT",
            semaphore=semaphore,
        )

        assert isinstance(res, MTFScanResult)
        assert res.symbol == "BTCUSDT"
        assert res.exchange == "binance"
        assert res.aligned_long is True
        assert res.aligned_short is False
        assert "LONG" in res.verdict


def test_parse_mtf_trade_params():
    # Test BUY parsing
    text = (
        "👁️ MULTI-TIMEFRAME ANALYSIS — BTCUSDT\n\n"
        "Tín hiệu: LONG (Mua)\n"
        "Entry Price (Giá vào): 65,000.00\n"
        "Stop Loss (Cắt lỗ): 63,500.00\n"
        "Take Profit (Chốt lời): 68,000.00\n"
    )
    entry, sl, tp, side = parse_mtf_trade_params(text, 65000.0)
    assert side == "BUY"
    assert entry == 65000.0
    assert sl == 63500.0
    assert tp == 68000.0

    # Test SELL parsing
    text_sell = (
        "Tín hiệu: SHORT (Bán)\n"
        "Entry Price: 62000.5\n"
        "Stop Loss: 63000\n"
        "Take Profit: 59000.2\n"
    )
    entry, sl, tp, side = parse_mtf_trade_params(text_sell, 62000.5)
    assert side == "SELL"
    assert entry == 62000.5
    assert sl == 63000.0
    assert tp == 59000.2

    # Test fallback
    entry, sl, tp, side = parse_mtf_trade_params("No price mentioned", 65000.0)
    assert side == "AVOID"
    assert entry == 65000.0
    assert sl is None
    assert tp is None


@pytest.mark.asyncio
async def test_api_scan_mtf_endpoint(client):
    mock_scan_res = MTFScanResult(
        symbol="BTCUSDT",
        exchange="binance",
        price=65000.0,
        timeframes={
            "1d": ScanResult(
                "BTCUSDT",
                65000.0,
                1.2,
                TrendTemplateResult(8, {}, "Stage 2", "Uptrend"),
                VCPResult(True, 1.2, 0.8, 64500.0, False, ""),
                1000.0,
                900.0,
                "binance",
            ),
            "4h": ScanResult(
                "BTCUSDT",
                65000.0,
                1.2,
                TrendTemplateResult(6, {}, "Stage 2", "Uptrend"),
                VCPResult(False, 1.2, 0.8, None, False, ""),
                1000.0,
                900.0,
                "binance",
            ),
            "1h": ScanResult(
                "BTCUSDT",
                65000.0,
                1.2,
                TrendTemplateResult(6, {}, "Stage 2", "Uptrend"),
                VCPResult(False, 1.2, 0.8, None, False, ""),
                1000.0,
                900.0,
                "binance",
            ),
        },
        aligned_long=True,
        aligned_short=False,
        verdict="LONG SIGNAL (MTF Aligned) 📈",
    )

    mock_vision_res = {
        "analysis": "Tín hiệu: LONG. Entry: 65000. SL: 63000. TP: 69000.",
        "confidence": 8,
        "patterns": ["VCP"],
        "combined_score": "8.0/10",
        "verdict": "🟢 STRONG LONG SETUP",
    }

    import tempfile

    temp_dir = tempfile.TemporaryDirectory()
    dummy_img = Path(temp_dir.name) / "dummy.png"
    dummy_img.write_bytes(b"dummy content")

    with (
        patch(
            "analysis.scan_symbol_multi_timeframe",
            AsyncMock(return_value=mock_scan_res),
        ),
        patch(
            "mcp_client.MCPClient.capture_screenshot", AsyncMock(return_value=dummy_img)
        ),
        patch(
            "vision.analyze_chart_vision_mtf", AsyncMock(return_value=mock_vision_res)
        ),
    ):
        response = await client.get("/api/scan/mtf?symbol=BTCUSDT")
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "BTCUSDT"
        assert data["exchange"] == "binance"
        assert data["aligned_long"] is True
        assert data["vision"]["confidence"] == 8
        assert data["vision"]["verdict"] == "🟢 STRONG LONG SETUP"

    temp_dir.cleanup()


@pytest.mark.asyncio
async def test_telegram_cmd_scan_mtf():
    from telegram_bot import cmd_scan_mtf

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_update.message.reply_media_group = AsyncMock()
    mock_update.effective_chat = MagicMock()
    mock_update.effective_chat.id = 12345

    mock_context = MagicMock()
    mock_context.args = ["BTCUSDT"]
    mock_context.bot = AsyncMock()

    mock_scan_res = MTFScanResult(
        symbol="BTCUSDT",
        exchange="binance",
        price=65000.0,
        timeframes={},
        aligned_long=True,
        aligned_short=False,
        verdict="LONG SIGNAL (MTF Aligned) 📈",
    )

    mock_vision_res = {
        "analysis": "Tín hiệu: LONG. Entry: 65000. SL: 63000. TP: 69000.",
        "confidence": 8,
        "patterns": ["VCP"],
        "combined_score": "8.0/10",
        "verdict": "🟢 STRONG LONG SETUP",
    }

    # Create dummy files to avoid FileNotFoundError in open() inside cmd_scan_mtf
    import tempfile

    temp_dir = tempfile.TemporaryDirectory()
    dummy_img = Path(temp_dir.name) / "dummy.png"
    dummy_img.write_bytes(b"dummy content")

    with (
        patch(
            "analysis.scan_symbol_multi_timeframe",
            AsyncMock(return_value=mock_scan_res),
        ),
        patch(
            "mcp_client.MCPClient.capture_screenshot", AsyncMock(return_value=dummy_img)
        ),
        patch(
            "vision.analyze_chart_vision_mtf", AsyncMock(return_value=mock_vision_res)
        ),
        patch("database.insert_signal", AsyncMock(return_value=42)),
        patch("telegram_bot.get_approval_timeout_mgr", return_value=None),
    ):
        await cmd_scan_mtf(mock_update, mock_context)
        await asyncio.sleep(1.5)

        # Verify it replied with media group and then report text
        mock_update.message.reply_media_group.assert_called_once()
        mock_update.message.reply_text.assert_called_with(
            ANY, parse_mode="HTML", reply_markup=ANY
        )

        # Check report text
        report_text = mock_update.message.reply_text.call_args[0][0]
        assert "MULTI-TIMEFRAME ANALYSIS" in report_text
        assert "BTCUSDT" in report_text
        assert "65,000.0000" in report_text
        assert "63,000.0000" in report_text
        assert "69,000.0000" in report_text

    temp_dir.cleanup()


@pytest.mark.asyncio
async def test_telegram_cmd_recommend():
    from telegram_bot import cmd_recommend

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()

    mock_context = MagicMock()
    mock_context.args = []
    mock_context.bot = AsyncMock()

    mock_watchlist = ["BTCUSDT", "ETHUSDT"]

    mock_scan_res = MTFScanResult(
        symbol="BTCUSDT",
        exchange="binance",
        price=65000.0,
        timeframes={},
        aligned_long=True,
        aligned_short=False,
        verdict="LONG SIGNAL (MTF Aligned) 📈",
    )

    with (
        patch("watchlist.get_watchlist", return_value=mock_watchlist),
        patch(
            "analysis.scan_symbol_multi_timeframe",
            AsyncMock(return_value=mock_scan_res),
        ),
    ):
        await cmd_recommend(mock_update, mock_context)
        await asyncio.sleep(0.2)

        mock_context.bot.send_message.assert_called_with(
            chat_id=ANY, text=ANY, parse_mode="HTML"
        )

        # Check final text contains recommend list header
        report_text = mock_context.bot.send_message.call_args[1]["text"]
        assert "Gợi ý Đa Khung Thời Gian" in report_text
        assert "BTCUSDT" in report_text


@pytest.mark.asyncio
async def test_telegram_cmd_scan_mtf_empty_menu():
    from telegram_bot import cmd_scan_mtf

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_update.callback_query = None

    mock_context = MagicMock()
    mock_context.args = []

    mock_watchlist = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    with patch("watchlist.get_watchlist", return_value=mock_watchlist):
        await cmd_scan_mtf(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        text = mock_update.message.reply_text.call_args[0][0]
        assert "Multi-Timeframe Scan Studio" in text
        assert "Vui lòng chọn" in text

        kwargs = mock_update.message.reply_text.call_args[1]
        assert "reply_markup" in kwargs
