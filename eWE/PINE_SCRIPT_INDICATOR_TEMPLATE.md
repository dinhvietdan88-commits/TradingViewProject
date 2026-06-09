# Pine Script v5 — Indicator Alert Message Template

## Overview

This template defines the exact JSON payload format that TradingView Indicators must emit
as alert messages. The Sovereign Trading Node's **WebhookGateway** routes these payloads
through the dedicated **Indicator Signal Pipeline** (v6.0+).

---

## JSON Payload Format

TradingView alert message field (paste into **Message** box):

```json
{
  "source": "indicator",
  "symbol": "{{ticker}}",
  "indicator_name": "SuperTrend",
  "signal_type": "entry",
  "interval": "{{interval}}",
  "price": {{close}},
  "confidence_score": 85,
  "conditions_met": ["price > supertrend", "uptrend confirmed"],
  "metadata": {
    "atr_value": "{{atr14}}",
    "supertrend_value": "{{supertrend}}",
    "trend_direction": "bullish"
  },
  "exchange": "binance"
}
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | string | **YES** | Must be `"indicator"` to route via indicator pipeline |
| `symbol` | string | **YES** | e.g. `"BTCUSDT"`. Use TradingView `{{ticker}}` variable |
| `indicator_name` | string | **YES** | Human-readable indicator name, e.g. `"SuperTrend"`, `"RSI Divergence"` |
| `signal_type` | string | **YES** | `"entry"` → buy signal, `"exit"` → sell signal, `"info"` → notify only |
| `interval` | string | NO | Timeframe: `"60"`, `"240"`, `"D"`, `"W"`. Use `{{interval}}` |
| `price` | float | NO | Signal price. Use `{{close}}` |
| `confidence_score` | integer | NO | 0–100. Signals < 50 are automatically rejected |
| `conditions_met` | array | NO | List of human-readable conditions that triggered this alert |
| `metadata` | object | NO | Additional indicator values (ATR, MA, etc.) for SL/TP computation |
| `exchange` | string | NO | Default: `"binance"`. Options: `"binance"`, `"bybit"` |

---

## Signal Type Routing

| `signal_type` | Pipeline Route | Effect |
|---------------|---------------|--------|
| `entry` | IndicatorSignalValidated → SignalValidated → TradeEngine | ATR-based SL/TP computed, trade executed |
| `exit` | IndicatorSignalValidated → SignalValidated → TradeEngine | Sell signal, ATR-based SL/TP |
| `info` | IndicatorSignalValidated → Telegram Notification | No trade, alert only |

---

## ATR-Based SL/TP Computation

When `metadata.atr_value > 0`, the Sovereign Node automatically computes:

```
stop_loss  = price - (atr * 2)
take_profit = price + (atr * 3)
```

If `atr_value` is absent or `0`, the fallback defaults apply:

```
stop_loss  = price * 0.95   # 5% below entry
take_profit = price * 1.10  # 10% above entry
```

---

## Pine Script v5 Example — SuperTrend Indicator

```pine
//@version=5
indicator("SuperTrend Alerts", overlay=true)

// --- SuperTrend ---
atrPeriod = input.int(14, "ATR Period")
factor    = input.float(3.0, "Factor")
[st, dir] = ta.supertrend(factor, atrPeriod)

// --- Signal conditions ---
entrySignal = ta.crossover(close, st) and dir < 0   // Bullish crossover
exitSignal  = ta.crossunder(close, st) and dir > 0  // Bearish crossunder

// --- Alert messages ---
if entrySignal
    alert(str.tostring({
        "source": "indicator",
        "symbol": syminfo.ticker,
        "indicator_name": "SuperTrend",
        "signal_type": "entry",
        "interval": timeframe.period,
        "price": close,
        "confidence_score": 85,
        "conditions_met": ["price > supertrend"],
        "metadata": {
            "atr_value": str.tostring(ta.atr(atrPeriod)),
            "supertrend_value": str.tostring(st)
        },
        "exchange": "binance"
    }), alert.freq_once_per_bar_close)

if exitSignal
    alert(str.tostring({
        "source": "indicator",
        "symbol": syminfo.ticker,
        "indicator_name": "SuperTrend",
        "signal_type": "exit",
        "interval": timeframe.period,
        "price": close,
        "confidence_score": 85,
        "conditions_met": ["price < supertrend"],
        "metadata": {
            "atr_value": str.tostring(ta.atr(atrPeriod)),
            "supertrend_value": str.tostring(st)
        },
        "exchange": "binance"
    }), alert.freq_once_per_bar_close)
```

---

## TradingView Alert Setup

1. Add the indicator to your chart
2. Right-click the indicator → **Add Alert**
3. **Condition**: `(your indicator function)` → `Alert()`
4. **Alert frequency**: `Once Per Bar Close` ← critical for `alert.freq_once_per_bar_close`
5. **Webhook URL**: `https://your-node.domain/webhook/signal`
6. **Message**: Paste the JSON payload from the template above

---

## Confidence Score Guidelines

| Score | Meaning | Pipeline Behavior |
|-------|---------|------------------|
| < 50 | Low confidence | **Auto-rejected** — signal is discarded |
| 50–80 | Medium confidence | Processed normally |
| > 80 | High confidence | **KHẨN CẤP** prefix on Telegram notification |

---

## Deduplication

The pipeline prevents duplicate indicator signals using:

- **Key**: `(symbol, indicator_name, signal_type)`
- **TTL**: 60 seconds
- **Scope**: Per-indicator (does NOT collide with strategy signals)

If the same indicator fires twice on the same candle, only the first is processed.
Use `alert.freq_once_per_bar_close` to avoid this scenario at the source.

---

## Useful Dynamic TradingView Variables

| TV Variable | Description |
|-------------|-------------|
| `{{ticker}}` | Symbol (e.g. `BTCUSDT`) |
| `{{close}}` | Closing price |
| `{{interval}}` | Current timeframe |
| `{{volume}}` | Current volume |
| `{{time}}` | Bar timestamp (UTC) |
| `{{exchange}}` | Exchange name |
