import pytest
from core.events import (
    MacroValidated,
)
from processor.minervini_sepa_processor import MinerviniSepaProcessor
from processor.mean_reversion_processor import MeanReversionProcessor


def generate_minervini_candles(trend: str = "bullish") -> list[list]:
    candles = []
    base_price = 100.0
    for i in range(365):
        if trend == "bullish":
            base_price += 0.5
        else:
            base_price -= 0.2
        candles.append(
            [
                i * 86400 * 1000,
                base_price - 1.0,
                base_price + 2.0,
                base_price - 2.0,
                base_price,
                1000.0,
            ]
        )
    return candles


def generate_mean_reversion_candles(direction: str) -> list[list]:
    candles = []
    base_price = 100.0
    for i in range(100):
        candles.append(
            [
                i * 86400 * 1000,
                base_price - 1.0,
                base_price + 1.0,
                base_price - 1.0,
                base_price,
                1000.0,
            ]
        )
    # Last candle triggers BB/RSI conditions
    if direction == "buy":
        closes = [100.0 - j * 0.1 for j in range(99)] + [50.0]
        candles = []
        for i, cl in enumerate(closes):
            candles.append([i * 86400 * 1000, cl + 0.5, cl + 1.0, cl - 1.0, cl, 1000.0])
    elif direction == "sell":
        closes = [100.0 + j * 0.1 for j in range(99)] + [150.0]
        candles = []
        for i, cl in enumerate(closes):
            candles.append([i * 86400 * 1000, cl - 0.5, cl + 1.0, cl - 1.0, cl, 1000.0])
    return candles


@pytest.mark.asyncio
async def test_sepa_processor_accepted(mock_global_capture_client):
    mock_global_capture_client.return_value = generate_minervini_candles("bullish")
    processor = MinerviniSepaProcessor()

    event = MacroValidated(
        signal_id=1,
        symbol="BTCUSDT",
        action="buy",
        price=282.5,
        quote_qty=10.0,
        interval="1d",
        sl="",
        tp="",
        exchange="binance",
        mta_trend_score=1.0,
        market_regime="TREND",
    )

    result = await processor.process(event)
    assert result is True


@pytest.mark.asyncio
async def test_sepa_processor_rejected(mock_global_capture_client):
    mock_global_capture_client.return_value = generate_minervini_candles("bearish")
    processor = MinerviniSepaProcessor()

    event = MacroValidated(
        signal_id=2,
        symbol="BTCUSDT",
        action="buy",
        price=27.0,
        quote_qty=10.0,
        interval="1d",
        sl="",
        tp="",
        exchange="binance",
        mta_trend_score=-1.0,
        market_regime="TREND",
    )

    result = await processor.process(event)
    assert result is False


@pytest.mark.asyncio
async def test_mean_reversion_buy_accepted(mock_global_capture_client):
    mock_global_capture_client.return_value = generate_mean_reversion_candles("buy")
    processor = MeanReversionProcessor()

    event = MacroValidated(
        signal_id=3,
        symbol="BTCUSDT",
        action="buy",
        price=50.0,
        quote_qty=10.0,
        interval="15m",
        sl="",
        tp="",
        exchange="binance",
        mta_trend_score=0.0,
        market_regime="CHOP",
        mode="MIS",
    )

    result = await processor.process(event)
    assert result is True


@pytest.mark.asyncio
async def test_mean_reversion_sell_accepted(mock_global_capture_client):
    mock_global_capture_client.return_value = generate_mean_reversion_candles("sell")
    processor = MeanReversionProcessor()

    event = MacroValidated(
        signal_id=4,
        symbol="BTCUSDT",
        action="sell",
        price=150.0,
        quote_qty=10.0,
        interval="15m",
        sl="",
        tp="",
        exchange="binance",
        mta_trend_score=0.0,
        market_regime="CHOP",
        mode="MIS",
    )

    result = await processor.process(event)
    assert result is True


@pytest.mark.asyncio
async def test_mean_reversion_rejected(mock_global_capture_client):
    mock_global_capture_client.return_value = generate_mean_reversion_candles("normal")
    processor = MeanReversionProcessor()

    event = MacroValidated(
        signal_id=5,
        symbol="BTCUSDT",
        action="buy",
        price=100.0,
        quote_qty=10.0,
        interval="15m",
        sl="",
        tp="",
        exchange="binance",
        mta_trend_score=0.0,
        market_regime="CHOP",
        mode="MIS",
    )

    result = await processor.process(event)
    assert result is False


@pytest.mark.asyncio
async def test_fail_safe_active(mock_global_capture_client):
    mock_global_capture_client.return_value = None
    sepa = MinerviniSepaProcessor()
    mr = MeanReversionProcessor()

    event = MacroValidated(
        signal_id=6,
        symbol="BTCUSDT",
        action="buy",
        price=100.0,
        quote_qty=10.0,
        interval="15m",
        sl="",
        tp="",
        exchange="binance",
        mta_trend_score=0.0,
        market_regime="CHOP",
        mode="MIS",
    )

    res_sepa = await sepa.process(event)
    res_mr = await mr.process(event)

    assert res_sepa is True
    assert res_mr is True
