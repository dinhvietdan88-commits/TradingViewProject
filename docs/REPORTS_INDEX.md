# 📚 Chỉ Mục Toàn Bộ Báo Cáo — Angati TradingView Project

> Tài liệu này tổng hợp tất cả báo cáo phân tích, kiểm thử, và kiểm toán bảo mật của hệ thống Angati TradingView Webhook Server.
> Cập nhật lần cuối: **2026-06-26** · Branch: `dev/infra/forward-test-live-validation`

---

## 📊 Bảng So Sánh Toàn Bộ Kịch Bản

| Nguồn / Kịch Bản | Tín Hiệu | Win Rate | Profit Factor | Expectancy | Loại |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Back-test Extended (1,100)** | 1,100 | 55.55% | 2.138 | +3.27% | Tổng hợp |
| **Forward-Test Mẫu (28)** | 28 | 64.29% | 3.147 | +6.14% | Paper |
| **Server A Thực Tế (285)** | 285 | 18.6%* | — | — | Live signals |
| **S1: Baseline Bypass AI** | 1,008 | 47.5% | 0.94 | — | Back-test |
| **S4: Tight SL / Trailing** | 1,008 | 46.8% | 1.19 | — | Back-test |
| **S5: Multi-Timeframe MTF** | 289 | 51.2% | 1.40 | — | Back-test |

> *Win Rate Server A thấp = tỷ lệ `ACKED/executed` = 18.6%, phản ánh mất kết nối Server B, không phải chất lượng tín hiệu.

---

## 🆕 Báo Cáo Mới (v7.0 — Forward Test Edition)

### 📈 Backtest Signal Report — 1,100 Tín Hiệu

| | |
|:---|:---|
| **HTML** | [backtest_signal_report.html](../reports/backtest_signal_report.html) |
| **Markdown** | [backtest_signal_report.md](../reports/backtest_signal_report.md) |
| **Script** | `python scripts/generate_backtest_report.py` |
| **Dữ liệu** | 710 trades thực (trades_data.json) + 390 simulated (BTC/ETH/SOL) |

**Nội dung:**
- KPI dashboard: Win Rate, P&L, Profit Factor, Expectancy, Sharpe
- Equity Curve (Chart.js interactive)
- Monthly P&L breakdown + Win Rate trend
- Outcome distribution (TP/SL/TIMEOUT)
- P&L theo symbol (BTC/ETH/SOL)
- Trade log 100 lệnh gần nhất

**Kết quả chính:**

| Chỉ Số | Giá Trị |
| :--- | :--- |
| Tổng tín hiệu | **1,100** |
| Win Rate | **55.55%** |
| Profit Factor | **2.138** |
| Expectancy | **+3.27%/lệnh** |
| Gross Profit | +1,996.50% |
| Gross Loss | -933.50% |
| Total P&L | **+3,592.89%** |

---

### 📋 Forward-Test Sample Report — 28 Paper Trades

| | |
|:---|:---|
| **HTML** | [forward_test_sample_report.html](../reports/forward_test_sample_report.html) |
| **Markdown** | [forward_test_sample_report.md](../reports/forward_test_sample_report.md) |
| **Script** | `python scripts/generate_forward_test_report.py` |
| **Mục đích** | Template mẫu tĩnh để so sánh khi Forward Test live chạy thực |

**Nội dung:**
- Paper trading equity curve (bắt đầu 10,000 USDT ảo)
- Win Rate radar chart theo symbol
- Outcome distribution donut chart
- Trade log đầy đủ (28 lệnh BTC/ETH/SOL)

**Kết quả chính:**

| Symbol | Lệnh | Win Rate | P&L |
| :--- | :---: | :---: | :--- |
| BTCUSDT | 10 | 60.0% | +60.43% |
| ETHUSDT | 8 | 62.5% | +61.76% |
| SOLUSDT | 10 | 70.0% | +49.57% |
| **Tổng** | **28** | **64.29%** | **+171.76%** |

---

## 📋 Báo Cáo Tín Hiệu & Lệnh Giao Dịch

### 📡 Server A Signals Report

| | |
|:---|:---|
| **File** | [server_a_signals_report.md](../reports/server_a_signals_report.md) |
| **Phạm vi** | 2026-05-30 → 2026-06-02 (4 ngày) |
| **Tổng tín hiệu** | 285 |

**Thống kê:**

| Trạng Thái | Số Lượng | Mô Tả |
| :--- | :--- | :--- |
| `ACKED/executed` | 53 | Thực thi thành công |
| `ACKED/rejected` | 5 | Bị từ chối bởi AI filter (Minervini) |
| `FAILED` | 87 | Lỗi kết nối Server B |
| `STALE` | 131 | Hết TTL, không xử lý kịp |
| `PENDING` | 11 | Đang chờ xử lý |

**Phân bố cặp:**
- BTCUSDT: 280 (98.2%)
- ETHUSDT: 2 (0.7%)
- TESTUSDT: 3 (1.1%)

---

### 🔄 Trade Replay

| | |
|:---|:---|
| **File** | [trade_replay.html](../reports/trade_replay.html) |
| **Kích thước** | ~1.4 MB |
| **Nội dung** | Replay toàn bộ lịch sử giao dịch với timeline animation |

---

## 🔬 Báo Cáo Kiểm Thử Chiến Thuật

### 📊 Strategy Summary

| | |
|:---|:---|
| **File** | [strategy_summary.html](../reports/strategy_summary.html) |
| **Nội dung** | Tổng quan hiệu suất chiến thuật SuperTrend VBS |

### 📉 Supertrend Equity Curve

| | |
|:---|:---|
| **File** | [supertrend_equity_curve.html](../reports/supertrend_equity_curve.html) |
| **Nội dung** | Equity curve theo Supertrend indicator |

### 📐 Walk-Forward Analysis

| Báo Cáo | File | Nội Dung |
| :--- | :--- | :--- |
| Walk-Forward Validation | [walkforward_validation.html](../reports/walkforward_validation.html) | Kết quả WFA toàn diện |
| Rolling Walk-Forward | [walkforward_rolling.html](../reports/walkforward_rolling.html) | Phân tích lăn bánh |
| 3-Month Walk-Forward | [walkforward_3month.html](../reports/walkforward_3month.html) | Chu kỳ 3 tháng |

### 🎨 Pattern Analysis

| Báo Cáo | File | Nội Dung |
| :--- | :--- | :--- |
| Pattern Analysis | [pattern_analysis.html](../reports/pattern_analysis.html) | Phân tích mẫu hình VCP |
| Monthly Pattern | [monthly_pattern_analysis.html](../reports/monthly_pattern_analysis.html) | Phân bổ theo tháng |

---

## 📁 Báo Cáo Scenarios Chi Tiết (v2.1.0-7.6.3)

Xem tại: [`docs/reports/v2.1.0-7.6.3/`](reports/v2.1.0-7.6.3/)

### Bảng Kịch Bản (Fixed Sizing — $100/lệnh)

| Scenario | Mô Tả | Lệnh | Win Rate | P&L | PF | Report |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| S1 | Baseline Bypass AI (MIS v1) | 1008 | 47.5% | -184.90 | 0.94 | [report](reports/v2.1.0-7.6.3/mis_v1/report.md) |
| S2 | Standard Minervini (MIS v12b) | 150 | 0.0% | -618.92 | 0.00 | [report](reports/v2.1.0-7.6.3/mis_v12b/report.md) |
| S3 | Short-term EMA (Strategy MTT) | 441 | 26.5% | -1140.40 | 0.28 | [report](reports/v2.1.0-7.6.3/strategy_mtt/report.md) |
| S4 | Tight SL / Trailing Stop | 1008 | 46.8% | **+423.14** | **1.19** | [report](reports/v2.1.0-7.6.3/mis_v10/report.md) |
| S5 | Multi-Timeframe (MIS v13c) | 289 | **51.2%** | **+342.06** | **1.40** | [report](reports/v2.1.0-7.6.3/mis_v13c/report.md) |
| S6 | Optimized Hybrid | 370 | 28.1% | -520.75 | 0.62 | [report](reports/v2.1.0-7.6.3/mis_v15_v16_v2/report.md) |

> **Kết luận:** S4 (Tight SL) và S5 (MTF) là hai kịch bản sinh lợi nhất. S5 có Win Rate cao nhất (51.2%) và Profit Factor tốt nhất (1.40).

---

## 🛡️ Báo Cáo Kiểm Toán Bảo Mật

### 🔐 SEC-04 Independent Audit

| | |
|:---|:---|
| **File** | [Bao_Cao_Nghiem_Thu_Doc_Lap.md](../Bao_Cao_Nghiem_Thu_Doc_Lap.md) |
| **Kết quả** | **56/56 kịch bản PASSED** |
| **Phạm vi** | SSRF, Path Traversal, Log Injection, XSS |

**Chi tiết:**
- 20/20 SSRF attacks blocked by `validate_exchange_params`
- 18/18 Path Traversal blocked by `safe_path`
- 10/10 Log Injection blocked by `safe_log_input`
- 8/8 XSS patterns sanitized

### 🔒 Security Scars Report

| | |
|:---|:---|
| **File** | [Security_Scars_Report.md](../Security_Scars_Report.md) |
| **Nội dung** | Lessons learned, SCAR rules, remediation evidence |

### 🔍 Harness Report

| | |
|:---|:---|
| **File** | [harness_report.md](../harness_report.md) |
| **Nội dung** | Security harness scan results |

---

## 📂 Nhật Ký Lỗi & Thay Đổi Theo Nhánh (Branch Issue Logs)

Thư mục `docs/branches/` chứa nhật ký lỗi đã sửa và tiến trình tính năng cho từng nhánh phát triển:

* 📡 [Forward Test & Live Validation](branches/dev-infra-forward-test-live-validation.md) - Kiểm thử dashboard và checkbox filters.
* 🔑 [Telegram Dashboard Auth](branches/dev-ai-easy-access-dashboard.md) - Tính năng quick login qua Telegram `/login` bot command.
* 🤖 [AI Core & Security Gates](branches/dev-ai-server-c-ai-core.md) - Mini-MDASH hook trong Go daemon và sửa assertion lỗi test vision.
* 📐 [FX Tactix Pine Generator](branches/dev-infra-fx-tactix.md) - Bộ sinh mã Pine Script v5 bằng AI.
* 📈 [Indicator Filters V1.006](branches/dev-infra-v1.006-filters.md) - Bộ lọc Slope, Volume, ATR-trail cho tín hiệu TradingView.
* ⏱️ [Regime Detection V1.007](branches/dev-infra-v1.007-regime.md) - Nhận diện xu hướng ADX/Bollinger Bands và chiến thuật kết hợp.

---



## 🧪 Test Coverage

| Loại Test | Số Lượng | Kết Quả |
| :--- | :---: | :--- |
| Unit Tests | ~750 | ✅ 100% PASSED |
| Integration Tests | ~120 | ✅ 100% PASSED |
| Stress Tests | ~60 | ✅ 100% PASSED |
| **Tổng cộng** | **~930** | **✅ 100% PASSED** |

Test quan trọng: `tests/integration/test_forward_test_routing.py`

---

## 🔄 Tái Tạo Báo Cáo

```bash
# 1. Back-test signal report (1,100 signals)
$env:PYTHONIOENCODING='utf-8'; python scripts/generate_backtest_report.py

# 2. Forward-test sample report
$env:PYTHONIOENCODING='utf-8'; python scripts/generate_forward_test_report.py

# 3. Xem toàn bộ reports trong thư mục
Get-ChildItem reports/ -Name
```

---

*Chỉ mục được tạo tự động · Angati v7.1 · Branch: `dev/infra/forward-test-live-validation`*
