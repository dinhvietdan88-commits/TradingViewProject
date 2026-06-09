# Sprint 6.3 — Analysis Engine (Trend Template + VCP)
**Branch:** `feat/p6-mcp-morning-brief`  
**Commit:** `cf76141` (included in S1 batch)  
**Status:** ✅ Done

---

## Mục tiêu

Hiện thực hóa thuật toán **8 Minervini Trend Template criteria** và
**VCP (Volatility Contraction Pattern)** detector — core intelligence
của morning brief system.

---

## Kiến trúc

```
Watchlist symbols
    ↓ batch
analysis.scan_symbols()
    ↓ per symbol
┌─────────────────────────────────────────┐
│ mcp_client.get_quote()    → QuoteData   │
│ mcp_client.get_studies()  → StudyValues │
└─────────────────────────────────────────┘
    ↓
score_trend_template()  →  TrendTemplateResult (0-8 score)
detect_vcp()            →  VCPResult (bool + metrics)
    ↓
ScanResult[] → sorted by VCP + TT score
```

---

## Files

### [NEW] `server/analysis.py`

#### Trend Template Scorer — 8 Criteria

| # | Tiêu chí | Source |
|---|---------|--------|
| 1 | Price > SMA150 **AND** Price > SMA200 | Minervini ch.3 |
| 2 | SMA150 > SMA200 | Moving Average alignment |
| 3 | SMA200 trending up (slope > 0) | At least 1 month |
| 4 | SMA50 > SMA150 **AND** SMA50 > SMA200 | Short-term strength |
| 5 | Price > SMA50 | Momentum |
| 6 | Price ≥ 52w Low × 1.30 | At least 30% above low |
| 7 | Price ≥ 52w High × 0.75 | Within 25% of high |
| 8 | RS ratio > 1.0 | Outperforming benchmark |

**Stage classification:**
- **Score 7-8:** Stage 2 ⭐ (ideal buy zone)
- **Score 5-6:** Stage 1/2 Transition
- **Score 3-4:** Stage 1 (Base building)
- **Score 0-2:** Stage 3/4 (Avoid)

#### VCP Detector

| Signal | Điều kiện | Ý nghĩa |
|--------|----------|---------|
| Volume contraction | `volume / vol_avg_20 < 0.50` | Smart money tích lũy |
| Range contraction | `(H-L) / ATR14 < 0.50` | Biến động thu hẹp |
| Near breakout | `price >= 52w_high × 0.90` | Gần pivot breakout |
| **VCP confirmed** | Vol + Range cả hai co | Setup sẵn sàng |

**Pivot estimate:** `high × 1.005` (0.5% trên recent high)

#### Data Classes

```python
@dataclass
class TrendTemplateResult:
    score: int           # 0-8
    criteria: dict       # {name: True/False/None}
    stage: str           # "Stage 2 ⭐" etc.
    summary: str         # Human-readable

@dataclass
class VCPResult:
    detected: bool
    volume_ratio: float  # < 0.5 = contraction
    range_ratio: float   # < 0.5 = narrow
    pivot_level: float   # breakout price
    note: str            # Vietnamese analysis

@dataclass
class ScanResult:
    symbol, price, change_pct,
    trend_template, vcp, volume, volume_avg, error
```

### [MODIFY] `server/main.py`

**Endpoint mới:**

```
GET /api/scan/watchlist?symbols=BTCUSDT,ETHUSDT&timeframe=D
```

Response:
```json
{
  "scanned": 3,
  "timestamp": "2026-05-04T00:00:00Z",
  "results": [
    {
      "symbol": "BTCUSDT",
      "price": 68500.00,
      "trend_template_score": 7,
      "trend_template_stage": "Stage 2 ⭐",
      "vcp_detected": true,
      "volume_ratio": 0.35,
      "pivot_level": 69200.50,
      ...
    }
  ]
}
```

---

## Thuật toán chi tiết

### `score_trend_template()`

```python
# Input: price, sma50, sma150, sma200, high_52w, low_52w, sma200_slope, rs_ratio
# Output: TrendTemplateResult

criteria = {}
criteria["price_above_ma150_200"] = price > sma150 and price > sma200
criteria["ma150_above_ma200"]     = sma150 > sma200
criteria["ma200_trending_up"]     = sma200_slope > 0
criteria["ma50_above_ma150_200"]  = sma50 > sma150 and sma50 > sma200
criteria["price_above_ma50"]      = price > sma50
criteria["above_52w_low_130pct"]  = price >= low_52w * 1.30
criteria["within_25pct_of_52w_high"] = price >= high_52w * 0.75
criteria["rs_outperforming"]      = rs_ratio > 1.0

score = count(True in criteria.values())  # None = unknown = 0
```

### `detect_vcp()`

```python
# Input: price, high, low, volume, volume_avg20, atr14, high_52w
# Output: VCPResult

volume_ratio = volume / volume_avg20      # < 0.5 = vol drying up
range_ratio  = (high - low) / atr14      # < 0.5 = range contracting
detected     = volume_ratio < 0.5 AND range_ratio < 0.5
near_high    = price >= high_52w * 0.90   # bonus signal
```

---

## Verification

```bash
# Scan watchlist (cần MCP_ENABLED=true + TradingView chạy)
curl http://localhost:5000/api/scan/watchlist

# Scan symbols cụ thể
curl "http://localhost:5000/api/scan/watchlist?symbols=BTCUSDT,ETHUSDT"
```
