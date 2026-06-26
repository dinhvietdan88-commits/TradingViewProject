# ✅ Replay Test - Checklist Thực hiện

## 🎯 Mục tiêu
- Test 2 chiến lược cùng lúc từ 2024-2026 với tốc độ 3x
- So sánh diễn biến thực tế
- Capture metrics & results

---

## 📋 PRE-TEST (Chuẩn bị)

- [ ] **TradingView Desktop cài đặt & khởi chạy**
  - Window focused trên TradingView
  - Menu bar hiển thị

- [ ] **Verify cả 2 chiến lược có sẵn**
  - Pine Script Editor → "Minervini_TT_Indicator (Version1.1)" tồn tại
  - Pine Script Editor → "SEPA_Multi-Indicator Strategy (Version1)" tồn tại

- [ ] **Chọn Symbol & Timeframe**
  - Symbol: `BINANCE:BTCUSDT` (or other)
  - Timeframe: `D` (Daily)

---

## 🔧 SETUP (Thiết lập Panes)

### Pane Trái - Minervini_TT_Indicator

- [ ] **Chart Setup**
  - [ ] Chart symbol = BINANCE:BTCUSDT
  - [ ] Chart timeframe = D (Daily)
  - [ ] Chart type = Candle

- [ ] **Apply Strategy**
  - [ ] Pine Editor → Select "Minervini_TT_Indicator (Version1.1)"
  - [ ] Click "Add to Chart"
  - [ ] Strategy overlay visible on chart
  - [ ] Signals/trades visible

- [ ] **Open Strategy Tester**
  - [ ] Bottom panel → "Strategy Tester" tab
  - [ ] Initial capital = 10000
  - [ ] Verify no errors in tester

### Pane Phải - SEPA_Multi-Indicator

- [ ] **Chart Setup** (repeat as above)
  - [ ] Symbol = BINANCE:BTCUSDT
  - [ ] Timeframe = D
  - [ ] Type = Candle

- [ ] **Apply Strategy**
  - [ ] Pine Editor → Select "SEPA_Multi-Indicator Strategy (Version1)"
  - [ ] Click "Add to Chart"
  - [ ] Strategy overlay visible
  - [ ] Signals/trades visible

- [ ] **Open Strategy Tester**
  - [ ] Bottom panel → "Strategy Tester" tab
  - [ ] Verify setup complete

---

## ▶️ REPLAY (Bắt đầu Replay Mode)

### Pane Trái Setup
- [ ] **Start Replay**
  - [ ] Right-click on chart → "Start Replay" (or Replay button)
  - [ ] Select start date: **2024-01-01**
  - [ ] Click: Start

- [ ] **Verify replay is running**
  - [ ] Candles moving
  - [ ] Time bar progressing
  - [ ] Trades executing on chart

### Pane Phải Setup
- [ ] **Start Replay** (cùng date: 2024-01-01)
  - [ ] Right-click → "Start Replay"
  - [ ] Date: **2024-01-01**
  - [ ] Click: Start

- [ ] **Verify both panes in sync**
  - [ ] Both showing same date
  - [ ] Both candles moving

---

## ⏱️ SPEED CONTROL (Tốc độ 3x)

- [ ] **Set Autoplay Speed**
  - [ ] Replay controls (below chart)
  - [ ] Find: **Autoplay** button or speed dropdown
  - [ ] Select: **100ms per bar** (= 3x speed approximately)
  
- [ ] **Click Play ▶️**
  - [ ] Both panes should auto-advance
  - [ ] Candles moving at fast speed

- [ ] **Monitor Progress**
  - [ ] Date progressing (e.g., Jan → Feb → Mar)
  - [ ] P&L chart updating in tester
  - [ ] Trades list growing

---

## 👁️ OBSERVATION (Theo dõi Quá trình)

### Metrics to Track

- [ ] **Pane Trái (Minervini_TT):**
  - [ ] First trade entry date: __________
  - [ ] Number of trades so far: __________
  - [ ] Current P&L: __________
  - [ ] Max Drawdown: __________

- [ ] **Pane Phải (SEPA_Multi):**
  - [ ] First trade entry date: __________
  - [ ] Number of trades so far: __________
  - [ ] Current P&L: __________
  - [ ] Max Drawdown: __________

### Key Moments to Screenshot

- [ ] **Start (2024-01)**
  - [ ] Screenshot: Both strategies starting point
  - [ ] Filename: `replay_start_2024-01.png`

- [ ] **First Major Trend**
  - [ ] Screenshot: When trend forms
  - [ ] Filename: `replay_trend_2024.png`

- [ ] **Drawdown/Correction**
  - [ ] Screenshot: How each strategy handles pullback
  - [ ] Filename: `replay_drawdown_2024.png`

- [ ] **Mid-Period (2025 mark)**
  - [ ] Screenshot: Progress check
  - [ ] Filename: `replay_2025_mid.png`

- [ ] **Final Results (2026 end)**
  - [ ] Screenshot: Both final equity curves
  - [ ] Filename: `replay_final_2026.png`

---

## 🛑 STOP & ANALYZE (Kết thúc & Phân tích)

### When Replay Finishes (or manually stop)

- [ ] **Pause Autoplay**
  - [ ] Click: ⏸️ (Pause)
  - [ ] Check: Date shows 2026-12-31 (or near end)

- [ ] **Collect Final Metrics - Pane Trái**

| Metric | Value |
|--------|-------|
| **Total Trades** | ___ |
| **Win Trades** | ___ |
| **Win Rate (%)** | ___ |
| **Total Return (%)** | ___ |
| **Profit Factor** | ___ |
| **Max Drawdown (%)** | ___ |
| **Avg Trade P&L** | ___ |

- [ ] **Collect Final Metrics - Pane Phải**

| Metric | Value |
|--------|-------|
| **Total Trades** | ___ |
| **Win Trades** | ___ |
| **Win Rate (%)** | ___ |
| **Total Return (%)** | ___ |
| **Profit Factor** | ___ |
| **Max Drawdown (%)** | ___ |
| **Avg Trade P&L** | ___ |

---

## 💾 EXPORT & SAVE (Lưu Kết quả)

### From TradingView Strategy Tester

**Pane Trái (Minervini_TT):**
- [ ] Strategy Tester panel (bottom)
- [ ] Click: "Select All" (or select key trades)
- [ ] Click: "Export" or "Copy"
- [ ] Save as: `reports/minervini_trades_2024-2026.csv`

**Pane Phải (SEPA_Multi):**
- [ ] Strategy Tester panel (bottom)
- [ ] Click: "Select All"
- [ ] Click: "Export"
- [ ] Save as: `reports/sepa_multi_trades_2024-2026.csv`

### Screenshots

- [ ] Save all captured screenshots to: `reports/replay_screenshots_[date]/`

### Final Summary

- [ ] Create: `reports/REPLAY_RESULTS_2024-2026.md`
  - [ ] Include metrics table above
  - [ ] Include key observations
  - [ ] Include winner strategy
  - [ ] Include next steps recommendation

---

## 🔍 ANALYSIS (Phân tích & So sánh)

### Minervini_TT_Indicator (Version1.1)

**Observations:**
- Total trades executed: ___
- Best month: ___________ (P&L: ___)
- Worst month: ___________ (Drawdown: ___)
- Trend-following effectiveness: [Low / Medium / High]
- Comments: _______________________________________________

### SEPA_Multi-Indicator Strategy (Version1)

**Observations:**
- Total trades executed: ___
- Best month: ___________ (P&L: ___)
- Worst month: ___________ (Drawdown: ___)
- Multi-indicator robustness: [Low / Medium / High]
- Comments: _______________________________________________

### Head-to-Head Comparison

| Aspect | Winner | Margin |
|--------|--------|--------|
| Win Rate | [ ] MTT / [ ] SEPA | ___ % |
| Total Return | [ ] MTT / [ ] SEPA | ___ % |
| Risk-Adjusted (Sharpe) | [ ] MTT / [ ] SEPA | ___ |
| Consistency (Std Dev) | [ ] MTT / [ ] SEPA | ___ |
| Max Drawdown | [ ] MTT / [ ] SEPA | ___ % |
| Recovery Speed | [ ] MTT / [ ] SEPA | ___ days |

---

## ✨ CONCLUSION

**Overall Winner:** ______________________

**Why:** 
- Aspect 1: ___________________________________________________
- Aspect 2: ___________________________________________________
- Aspect 3: ___________________________________________________

**Recommendation for Live Trading:**
- [ ] Deploy Minervini_TT
- [ ] Deploy SEPA_Multi
- [ ] Hybrid approach (use different timeframes/symbols)
- [ ] Further optimization needed

**Next Steps:**
1. ___________________________________________________________
2. ___________________________________________________________
3. ___________________________________________________________

---

## 📞 Support

**Issues?**
- Check: `C:\Users\Admin\TradingViewProject\docs\REPLAY_TEST_GUIDE.md`
- Logs: `C:\Users\Admin\TradingViewProject\reports/`

**Questions about strategies?**
- MTT_v1.A005: Check `pine/v1/strategy_MTT_v1.A005.pine`
- Multi-Indicator v16: Check `pine/v1/strategy_multi_indicator_v16.pine`

---

**Date Started:** ___________________
**Date Completed:** ___________________
**Total Time:** ___________________
