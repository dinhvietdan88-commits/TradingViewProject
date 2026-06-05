import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from analysis import (
    fetch_candles_with_retry,
    scan_single_symbol_rest,
    scan_all_configured_exchanges,
    ScanResult,
    TrendTemplateResult,
    VCPResult,
)
import analysis as analysis_module


@pytest.mark.asyncio
async def test_fetch_candles_weex_success():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value=[["1684812345000", "100.0", "105.0", "95.0", "101.0", "1000.0"]]
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.get = MagicMock(return_value=mock_resp)

    res = await fetch_candles_with_retry(session, "weex", "BTCUSDT_UMCBL")
    assert len(res) == 1
    assert res[0] == [1684812345000, 100.0, 105.0, 95.0, 101.0, 1000.0]
    session.get.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_candles_bybit_success():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "retCode": 0,
            "result": {
                "list": [["1684812345000", "100.0", "105.0", "95.0", "101.0", "1000.0"]]
            },
        }
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.get = MagicMock(return_value=mock_resp)

    res = await fetch_candles_with_retry(session, "bybit", "BTCUSDT")
    assert len(res) == 1
    assert res[0] == [1684812345000, 100.0, 105.0, 95.0, 101.0, 1000.0]


@pytest.mark.asyncio
async def test_fetch_candles_binance_success():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value=[[1684812345000, "100.0", "105.0", "95.0", "101.0", "1000.0"]]
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.get = MagicMock(return_value=mock_resp)

    res = await fetch_candles_with_retry(session, "binance", "BTCUSDT")
    assert len(res) == 1
    assert res[0] == [1684812345000, 100.0, 105.0, 95.0, 101.0, 1000.0]


@pytest.mark.asyncio
async def test_fetch_candles_rate_limited():
    mock_resp_429 = AsyncMock()
    mock_resp_429.status = 429
    mock_resp_429.headers = {"Retry-After": "0.1"}
    mock_resp_429.__aenter__ = AsyncMock(return_value=mock_resp_429)
    mock_resp_429.__aexit__ = AsyncMock(return_value=None)

    mock_resp_200 = AsyncMock()
    mock_resp_200.status = 200
    mock_resp_200.json = AsyncMock(
        return_value=[[1684812345000, "100.0", "105.0", "95.0", "101.0", "1000.0"]]
    )
    mock_resp_200.__aenter__ = AsyncMock(return_value=mock_resp_200)
    mock_resp_200.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.get = MagicMock(side_effect=[mock_resp_429, mock_resp_200])

    with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
        res = await fetch_candles_with_retry(session, "binance", "BTCUSDT")
        assert len(res) == 1
        assert res[0][4] == 101.0
        mock_sleep.assert_called_once()
        assert session.get.call_count == 2


@pytest.mark.asyncio
async def test_fetch_candles_failure_fallback():
    mock_resp_500 = AsyncMock()
    mock_resp_500.status = 500
    mock_resp_500.__aenter__ = AsyncMock(return_value=mock_resp_500)
    mock_resp_500.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.get = MagicMock(return_value=mock_resp_500)

    with patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(RuntimeError) as exc_info:
            await fetch_candles_with_retry(session, "binance", "BTCUSDT", max_retries=2)
        assert (
            "Failed to fetch candles for BTCUSDT on binance after 2 attempts."
            in str(exc_info.value)
        )


@pytest.mark.asyncio
async def test_scan_single_symbol_rest():
    mock_candles = []
    import time

    now_ms = int(time.time() * 1000)
    day_ms = 24 * 60 * 60 * 1000

    for i in range(250):
        ts = now_ms - (250 - i) * day_ms
        price = 100.0 + i * 0.5
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

    session = MagicMock()
    semaphore = asyncio.Semaphore(1)

    with patch(
        "analysis.fetch_candles_with_retry", AsyncMock(return_value=mock_candles)
    ):
        res = await scan_single_symbol_rest(
            session=session,
            exchange_name="weex",
            symbol="BTCUSDT_UMCBL",
            btc_closes={},
            btc_candles=[],
            semaphore=semaphore,
        )

        assert isinstance(res, ScanResult)
        assert res.symbol == "BTCUSDT_UMCBL"
        assert res.price > 100.0
        assert res.trend_template is not None
        assert res.vcp is not None
        assert res.error is None


@pytest.mark.asyncio
async def test_scan_all_configured_exchanges():
    mock_adapter = MagicMock()
    mock_adapter.exchange_name = "weex"
    mock_adapter.get_active_symbols = AsyncMock(
        return_value=["BTCUSDT_UMCBL", "ETHUSDT_UMCBL"]
    )

    mock_registry = MagicMock()
    mock_registry.list_exchange_ids = MagicMock(return_value=["weex"])
    mock_registry.get_adapter = MagicMock(return_value=mock_adapter)

    mock_candles = [[1684812345000, 100.0, 105.0, 95.0, 101.0, 1000.0]] * 60

    with (
        patch("exchanges.registry.get_registry", return_value=mock_registry),
        patch(
            "analysis.fetch_candles_with_retry", AsyncMock(return_value=mock_candles)
        ),
    ):
        analysis_module._scan_status = "idle"
        analysis_module._latest_scan_results = []

        results = await scan_all_configured_exchanges()

        assert len(results) == 2
        assert results[0].exchange == "weex"
        assert analysis_module._scan_status == "completed"
        assert len(analysis_module._latest_scan_results) == 2


@pytest.mark.asyncio
async def test_api_scan_all_endpoint(client):
    analysis_module._scan_status = "idle"
    analysis_module._latest_scan_results = []
    analysis_module._scan_start_time = None
    analysis_module._scan_end_time = None
    analysis_module._scan_error = None

    with patch("analysis.scan_all_configured_exchanges", AsyncMock()):
        response = await client.get("/api/scan/all?force=true")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "idle"
        assert "results" in data


@pytest.mark.asyncio
async def test_telegram_cmd_scan_all():
    from telegram_bot import cmd_scan_all

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_update.effective_chat = MagicMock()
    mock_update.effective_chat.id = 12345

    mock_context = MagicMock()
    mock_context.bot = AsyncMock()
    mock_context.bot.send_message = AsyncMock()

    mock_results = [
        ScanResult(
            symbol="BTCUSDT_UMCBL",
            price=65000.0,
            change_pct=1.5,
            trend_template=TrendTemplateResult(8, {}, "Stage 2", "Criteria passed"),
            vcp=VCPResult(True, 1.2, 0.8, 64500.0, False, "VCP setup"),
            volume=5000.0,
            volume_avg=4000.0,
            exchange="weex",
            error=None,
        )
    ]

    with patch(
        "analysis.scan_all_configured_exchanges", AsyncMock(return_value=mock_results)
    ):
        await cmd_scan_all(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once_with(
            "🔄 Đang bắt đầu scan toàn bộ các sàn trong background... Vui lòng chờ kết quả."
        )

        await asyncio.sleep(0.1)

        mock_context.bot.send_message.assert_called_once()
        call_args = mock_context.bot.send_message.call_args[1]
        assert call_args["chat_id"] == 12345
        assert "Kết quả Scan All" in call_args["text"]
        assert "weex" in call_args["text"]
        assert "BTCUSDT_UMCBL" in call_args["text"]
