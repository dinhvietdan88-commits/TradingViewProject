# 🔄 Automated Replay Test Guide (2024-2026, 3x Speed)

## Overview
Kỹ thuật test tự động với **replay mode** để so sánh diễn biến thực tế của 2 chiến lược từ 2024 đến 2026 với tốc độ 3x.

### Chiến lược cần test:
1. **Minervini_TT_Indicator (Version1.1)**
   - Dựa trên: `strategy_MTT_v1.A005.pine`
   - Chỉ báo: ADX25 + Trailing Stop
   - Gating: Trend Template (8 criteria)

2. **SEPA_Multi-Indicator Strategy (Version1)**
   - Dựa trên: `strategy_multi_indicator_v16.pine`
   - Chỉ báo: EMA + RSI + MACD + Volume + ATR
   - Gating: SEPA Stage 2 Freshness

---

## 📋 Chuẩn bị

### Yêu cầu
- ✅ TradingView Desktop đã cài đặt
- ✅ Cả 2 chiến lược đã import/setup trên TradingView
- ✅ Symbol: `BINANCE:BTCUSDT` (hoặc tuỳ chọn)
- ✅ Timeframe: `D` (Daily)

### Kiểm tra trước khi bắt đầu
```powershell
# Verify both strategies are available in TradingView
# Open TradingView → Pine Script Editor → check both strategies
```

---

## 🚀 Quá trình Replay Test

### Phương pháp A: Script Tự động (Khuyến nghị)

#### 1. Chạy script setup
```powershell
cd C:\Users\Admin\TradingViewProject
.\scripts\automated_replay_test.ps1 -Symbol "BINANCE:BTCUSDT" -Timeframe "D" -Speed 3
```

**Tham số:**
- `-Symbol`: Trading pair (default: BINANCE:BTCUSDT)
- `-Timeframe`: Chart resolution (default: D)
- `-StartDate`: Ngày bắt đầu (default: 2024-01-01)
- `-EndDate`: Ngày kết thúc (default: 2026-12-31)
- `-Speed`: Tốc độ replay (default: 3)
- `-CaptureInterval`: Screenshot mỗi N bars (default: 50)

#### 2. Tuân theo hướng dẫn từ script
Script sẽ cung cấp hướng dẫn từng bước về cách thiết lập TradingView.

---

### Phương pháp B: Hướng dẫn Thủ công

#### Bước 1: Thiết lập Pane Layout

1. Mở **TradingView Desktop**
2. Tạo **2 pane** ngang nhau:
   - **Pane trái**: Chiến lược 1
   - **Pane phải**: Chiến lược 2

```
┌─────────────────────┬─────────────────────┐
│  Pane 0 (Left)      │  Pane 1 (Right)     │
│                     │                     │
│  Minervini_TT_      │  SEPA_Multi-       │
│  Indicator v1.1     │  Indicator v1      │
│                     │                     │
└─────────────────────┴─────────────────────┘
```

#### Bước 2: Thiết lập Pane trái (Minervini_TT_Indicator)

1. **Chart Settings:**
   - Symbol: `BINANCE:BTCUSDT`
   - Timeframe: `D` (Daily)

2. **Apply Strategy:**
   - Click: Pine Script Editor → Select "Minervini_TT_Indicator (Version1.1)"
   - Click: **Add to Chart**
   - Verify: Strategy overlay + signals visible on chart

3. **Open Strategy Tester:**
   - Bottom panel → **Strategy Tester** tab
   - Verify: Initial capital, equity curve visible

#### Bước 3: Thiết lập Pane phải (SEPA_Multi-Indicator)

Lặp lại Bước 2 với:
- Strategy: **SEPA_Multi-Indicator Strategy (Version1)**

#### Bước 4: Bắt đầu Replay Mode

**Pane trái:**
1. Chart → Right-click → **Start Replay**
2. Select date: **2024-01-01**
3. Click: **Start**

**Pane phải:**
1. Lặp lại, cũng chọn **2024-01-01**

#### Bước 5: Thiết lập Tốc độ 3x

1. Replay controls (dưới chart):
   - Find: **Autoplay** button
   - Click: Dropdown speed selector
   - Select: **100ms per bar** (tương đương 3x speed)
   - Click: **Play** ▶️

2. Verify:
   - Cả 2 pane đang replay đồng thời
   - Candles đang di chuyển
   - Trades được execute trên cả 2 strategy

#### Bước 6: Quan sát & Capture

Trong quá trình replay (2024-2026):

**Metrics cần theo dõi:**
- ✅ Entry signals (trong Stage 2 hoặc khi conditions met)
- ✅ Exit points (Stop loss / Take profit / Trail stop)
- ✅ P&L trên mỗi trade
- ✅ Drawdown max
- ✅ Win rate (wins / total trades)
- ✅ Equity curve trajectory

**Capture Key Moments:**
- 📸 Khi bắt đầu replay (2024-01)
- 📸 First major trend (2024 bull run)
- 📸 Correction phase
- 📸 2025 performance
- 📸 Final results (2026)

#### Bước 7: Kiểm tra Kết quả

Khi replay hoàn tất:

1. **Strategy Tester panel:**
   - Total Trades
   - Win Rate (%)
   - Profit Factor
   - Max Drawdown
   - Return (%)

2. **Equity Curve:**
   - Compare visual shapes (smooth vs volatile)
   - Identify best/worst periods

3. **Trade List:**
   - Export hoặc screenshot
   - Analyze entry/exit logic

---

## 📊 So sánh Kết quả

Sau khi cả 2 chiến lược hoàn tất replay:

### Metrics Comparison Table

| Metric | Minervini_TT | SEPA_Multi | Winner |
|--------|-------------|-----------|--------|
| Total Trades | ? | ? | |
| Win Rate (%) | ? | ? | |
| Profit Factor | ? | ? | |
| Total Return (%) | ? | ? | |
| Max Drawdown (%) | ? | ? | |
| Sharpe Ratio | ? | ? | |
| Avg Win/Loss Ratio | ? | ? | |

### Analysis Points

**Minervini_TT_Indicator:**
- ✅ Trend Template gating → fewer but higher-quality entries
- ✅ ADX25 filter → works well in strong trends
- ⚠️ May miss quick reversals
- 📊 Expected: Fewer trades, higher accuracy, lower frequency

**SEPA_Multi-Indicator:**
- ✅ Multi-layer confirmation → robust in various markets
- ✅ EMA stack positioning → captures momentum
- ⚠️ May have more whipsaws
- 📊 Expected: More trades, varied accuracy, higher frequency

---

## 💾 Lưu lại Kết quả

### Automatic Results File
```
C:\Users\Admin\TradingViewProject\reports\replay_test_[YYYYMMDD_HHMMSS].json
```

### Manual Export from TradingView

1. **Strategy Tester** → **Select All trades** → **Export**
2. Save as:
   ```
   reports/strategy_tester_minervini_TT_2024-2026.csv
   reports/strategy_tester_sepa_multi_2024-2026.csv
   ```

3. **Chart** → **Screenshot** (key moments):
   ```
   reports/replay_screenshot_minervini_2024.png
   reports/replay_screenshot_sepa_2024.png
   ...
   ```

---

## 🔧 Troubleshooting

### ❌ Chiến lược không hiển thị tín hiệu
- ✅ Kiểm tra chart timeframe = D (Daily)
- ✅ Kiểm tra Strategy Tester settings (initial capital, commission)
- ✅ Verify indicator inputs (Trend Template, RSI floor, v.v.)

### ❌ Replay không chạy
- ✅ Ensure TradingView is up-to-date
- ✅ Check: Symbol có dữ liệu từ 2024 không?
- ✅ Try: Start from closer date (e.g., 2025-01-01)

### ❌ Tốc độ replay quá nhanh/chậm
- ✅ Adjust autoplay speed dropdown
- ✅ 100ms = ~3x speed
- ✅ 50ms = ~6x speed
- ✅ 200ms = ~1.5x speed

### ❌ Hai pane không đồng bộ
- ✅ Pause both (Click: ⏸️)
- ✅ Restart both từ same date
- ✅ Ensure autoplay speed same

---

## 📈 Next Steps Sau Replay

1. **Analyze P&L curves** → Which strategy smoother?
2. **Review specific trades** → Why did one work, other didn't?
3. **Check market phases** → Which strategy better in bull/bear?
4. **Optimize parameters** → Adjust if needed
5. **Paper trade live** → Test with real-time conditions

---

## 📝 Notes

- Replay mode sử dụng historical data → không phản ánh slippage/spread thực tế
- Commission & slippage đã được config trong strategy
- TradingView Strategy Tester = backtest, không forward-test
- Để test live: sử dụng **Paper Trading** mode

---

**Script location:** `C:\Users\Admin\TradingViewProject\scripts\automated_replay_test.ps1`

**Questions?** Check logs at: `C:\Users\Admin\TradingViewProject\reports\`
