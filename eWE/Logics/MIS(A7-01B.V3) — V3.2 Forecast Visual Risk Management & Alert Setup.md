# Walkthrough: MIS(A7-01B.V3) — V3.2 Forecast Visual Risk Management & Alert Setup

> **Date**: 2026-05-30 (Session 3)
> **Previous**: V3.1 (RRR presets + labels + version input)
> **This session**: V3.2 (Forecast zones + expanded SL + trailing stop + visual settings) + Webhook Secret & Alert 4 Configuration

---

## Changes Summary

### 1. Forecast Zones (replaces bgcolor flash)
- **Before**: Simple `bgcolor()` flash on entire bar
- **After**: `box.new()` forecast zones
  - **Long**: Green box UP (entry→TP) + Red box DOWN (entry→SL)
  - **Short**: Red box UP (entry→SL) + Green box DOWN (entry→TP)
  - Boxes extend 40 bars and auto-grow with trailing stop
- **Status**: Live & working on Binance BTCUSDT chart

### 2. Version Auto-Update
- **Before**: `input.string("V3.1", "Version")` — user editable
- **After**: `VERSION = "V3.2"` — constant, auto in table header + webhook

### 3. Expanded SL Settings
- **Before**: Only ATR × multiplier
- **After**: SL Mode dropdown:
  - `ATR` — dynamic ATR × multiplier (default)
  - `Fixed` — absolute USDT amount
  - `Percent` — % of price

### 4. Trailing Stop TP Mode
- **Before**: Fixed RRR only
- **After**: TP Mode dropdown:
  - `Fixed RRR` — static TP = SL × RRR (default)
  - `Trailing Stop` — dynamic TP that follows price with ATR × trail multiplier
  - Trail line (amber, arrow style) updates each bar
  - Trail hit fires exit alert + flag marker "T"

### 5. Visual Settings Group
- **New inputs**: Bull/Bear/Entry/Trail colors + Forecast zone transparency
- All visual elements use configurable colors instead of hardcoded

### 6. Status Table Expanded (9 rows)
| Row | Label | Value |
|-----|-------|-------|
| 0 | MIS V3.2 | 60m |
| 1 | Trend | BULL/BEAR |
| 2 | EMA | 20/50 |
| 3 | RSI | 45.2 |
| 4 | ATR | 349 |
| 5 | R:R | 3.5:1 |
| 6 | SL | 76,123 |
| 7 | TP/Trail | 79,267 or trail level |
| 8 | Mode | ATR \| Fixed RRR |

---

## Webhook and Alert 4 (Test04) Setup

To complete the A.007 + MIS Webhook integration, we configured the 4th alert (Test04) for our newly compiled `MIS(A7-01B.V3) Webhook` indicator on the Binance BTCUSDT 1h chart:

1. **Indicator Instance & Webhook Secret**:
   - Indicator instance `"TxEeEx"` is loaded, running healthy, and defaults to the correct webhook secret from `.env` (`7086c59c523e87c90f9d56db63a66fd9045cb081264afe65c4ce8c37cff89104`).
2. **Alert Condition**:
   - Set to `"MIS(A7-01B.V3) Webhook"` indicator with `"Any alert() function call"` trigger condition.
3. **Alert Notifications**:
   - Enabled Webhook URL and configured it to the VBS webhook:
     `https://trading.utopiavn.co/ingest?secret=9ea7c89fbfd63a8a2bc8644e99da54fc5b2c7e098fe1d9e2b10a4e320f781a7b`
4. **Alert Details**:
   - Named the alert: `"Test04: MIS(A7-01B.V3) Webhook"`.
   - Message is left empty as it is dynamically dispatched by the script's `alert()` function on every signal event.

---

## File Changed

### [a007_mis_webhook.pine](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/pine/v2/a007_mis_webhook.pine)

| Feature | V3.1 | V3.2 |
|---------|------|------|
| Background flash | bgcolor() full bar | box.new() forecast zones |
| Version | input.string | const VERSION |
| SL modes | ATR only | ATR / Fixed / Percent |
| TP modes | Fixed RRR only | Fixed RRR / Trailing Stop |
| Visual config | None | Bull/Bear/Entry/Trail colors |
| Input groups | 3 | 4 (Core, Risk, Toggles, Settings) |
| Status table rows | 8 | 9 (+Mode row) |
| Webhook fields | 7 metadata | 10 metadata (+version, sl_mode, tp_mode, trail_stop) |
| max_boxes_count | N/A | 50 |
| Trail hit marker | N/A | Flag "T" shape |

---

## Verification & Active Alerts List

- **Pine v6 compile**: ✅ **0 errors**
- **Chart**: Forecast boxes visible (green reward + red/amber risk zones)
- **plotshape fix**: Split trail hit into two calls (Long/Short) to avoid `series string` error on `location` param
- **Alert Verification**: Running `alert_list` confirms **4 active alerts** on the chart:

| Alert ID | Alert Name | Type | Webhook URL | Active |
|---|---|---|---|---|
| **4816282803** | **Test04: MIS(A7-01B.V3) Webhook** | `indicator` | `https://trading.utopiavn.co/ingest?secret=9ea7c89fb...` | **true** |
| 4800272820 | Test3: A.007 + MIS v1 Combined | `strategy` | `https://trading.utopiavn.co/ingest?secret=9ea7c89fb...` | true |
| 4800248169 | Test02: A.007 + MIS v2 Combined | `strategy` | `https://trading.utopiavn.co/ingest?secret=9ea7c89fb...` | true |
| 4800166430 | Test01: A.007 strategy (Order Filler) | `strategy` | `https://trading.utopiavn.co/ingest?secret=9ea7c89fb...` | true |
