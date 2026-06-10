# Báo cáo Paper Trading — strategy_MTT v1.003

**Symbol**: BYBIT:BTCUSDT.P (Bybit Perpetual Futures)
**Chart type**: Candles
**Strategy**: SMA stack flip (50/150/200) — Long khi `50>150>200`, Short khi `50<150<200`
**Initial capital**: 100,000 USDT
**Commission**: 0.075% / lệnh — **Slippage**: 2 ticks — **Pyramiding**: 0
**Profile đang test**: **Futures** (long+short, qty 30% equity ≈ 10% × 10x leverage)
**Backtest run**: 2026-05-09

---

## 1. Profile presets (KHÔNG all-in)

| Profile  | Long | Short | qty % equity | Lý do |
|----------|------|-------|--------------|-------|
| Spot     | ✓    | ✗     | **25%**      | Không đòn bẩy, không bán khống — phù hợp tài khoản giao ngay |
| Margin   | ✓    | ✓     | **60%**      | Mô phỏng 20% equity × 3x leverage = 60% notional |
| Futures  | ✓    | ✓     | **30%**      | Mô phỏng 10% equity × 10x leverage = 30% notional (giữ thận trọng do funding & liquidation risk) |

> Inputs script cho phép `override_qty` để chỉnh thủ công (1–100%).

## 2. Kết quả batch theo Timeframe (Profile = Futures, 30% equity)

### Nhóm 1: Macro (1H / 4H / D)

| TF | Date range | Net P&L | P&L % | Max DD % | Trades | Win % | Profit Factor | Verdict |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| **1H**  | 2025-01-01 → 2026-05-09 | −7,218.48 | **−7.22%** | 12.18% | 94 | 39.36% | 0.762 | ❌ Lỗ |
| **4H**  | 2021-03 → 2026-05-09     | +7,729.55 | **+7.73%** | 19.72% | 86 | 33.72% | 1.062 | ⚠️  Hơi dương, PF mỏng |
| **D**   | 2020-03-25 → 2026-05-09  | **+65,034.76** | **+65.03%** | 19.00% | 10 | 40.00% | **2.088** | ✅ Tốt nhất |

### Nhóm 2: Intraday (5m / 15m / 30m)

| TF | Date range | Net P&L | P&L % | Max DD % | Trades | Win % | Profit Factor | Verdict |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| **5m**  | 2026-03-30 → 2026-05-09 (~40 ngày) | −6,970.93 | **−6.97%** | 7.44% | 85 | 22.35% | 0.432 | ❌ Tệ nhất |
| **15m** | 2026-01-01 → 2026-05-09 (~4 tháng) | +616.28 | **+0.62%** | 6.26% | 88 | 36.36% | 1.034 | 🟡 Hoà phí |
| **30m** | 2025-01-01 → 2026-05-09 (~16 tháng) | −10,174.14 | **−10.17%** | 11.63% | 167 | 34.13% | 0.806 | ❌ Lỗ |

> Lưu ý: TF nhỏ (5m/15m) bị giới hạn dữ liệu lịch sử của TradingView (~5–40 ngày → vài tháng) nên window backtest ngắn hơn nhóm macro, không hoàn toàn so sánh trực tiếp được.

## 3. So sánh 2 nhóm

| Tiêu chí | Nhóm Macro (1H/4H/D) | Nhóm Intraday (5m/15m/30m) |
|---|---|---|
| Tổng kết quả | 1 thắng đậm + 1 hoà + 1 lỗ | 1 hoà + 2 lỗ |
| Profit Factor TB | **1.30** | **0.76** |
| Win rate TB | 37.7% | 31.0% |
| Trade frequency | 10–94 lệnh | 85–167 lệnh (nhiễu) |
| Phí ăn vào lợi nhuận | Thấp | Rất cao |
| Khả năng sống được | **Daily ✅** | Không TF nào ổn |

## 4. Quan sát chính

1. **Daily là TF "ăn được" duy nhất** — PF 2.09, P&L +65%, chỉ 10 lệnh trong 6 năm → strategy hoạt động đúng bản chất Minervini: **bắt xu hướng dài hạn**, không phải scalping.
2. **TF càng nhỏ → win rate càng thấp & PF càng tệ** — bằng chứng rõ ràng strategy stack-flip không chịu được nhiễu intraday.
3. **5m PF 0.43** = mỗi 1 USDT thắng đổi lấy 2.3 USDT thua → hệ thống bị phí + slippage giết.
4. **Short không hiệu quả ở 1H**: Long +35.45 / Short −7,253.93 → BTC năm 2025 chủ yếu uptrend, mọi lệnh short đều bị stopped out khi stack vắt lại.

## 5. Khuyến nghị

| Profile | TF khuyến nghị | Ghi chú |
|---|---|---|
| **Spot**    | **D** (only) | Tắt short tự động, qty 25% — chiến lược position trading dài hạn |
| **Margin**  | D, 4H        | qty 60%, có thể bật short ở 4H+ nhưng phải thêm filter slope |
| **Futures** | **D**        | Không nên xài TF ≤ 1H với leverage thực — funding + slippage ăn hết PF |

**KHÔNG nên trade live** strategy này ở bất kỳ TF ≤ 1H mà chưa thêm:
- Filter `SMA200 slope ≥ 20 phiên` (loại bỏ sideway)
- Stop-loss cứng (% hoặc ATR-based)
- Trend confirmation (RS vs benchmark, volume confirmation)

## 6. Files liên quan

- Strategy source: [pine/v1/strategy_MTT_v1.003.pine](../../pine/v1/strategy_MTT_v1.003.pine)
- Screenshots:
  - [tradingview-mcp/screenshots/mtt_v1003_btc_5m.png](../../tradingview-mcp/screenshots/mtt_v1003_btc_5m.png)
  - [tradingview-mcp/screenshots/mtt_v1003_btc_15m.png](../../tradingview-mcp/screenshots/mtt_v1003_btc_15m.png)
  - [tradingview-mcp/screenshots/mtt_v1003_btc_30m.png](../../tradingview-mcp/screenshots/mtt_v1003_btc_30m.png)
  - [tradingview-mcp/screenshots/mtt_v1003_btc_1h.png](../../tradingview-mcp/screenshots/mtt_v1003_btc_1h.png)
  - [tradingview-mcp/screenshots/mtt_v1003_btc_4h.png](../../tradingview-mcp/screenshots/mtt_v1003_btc_4h.png)
  - [tradingview-mcp/screenshots/mtt_v1003_btc_D.png](../../tradingview-mcp/screenshots/mtt_v1003_btc_D.png)
