# 📊 Central Configuration Matrix: Optimized Parameters for Multi-Asset Trading

Bản tổng hợp ma trận cấu hình tham số tối ưu (Optimized Parameters Matrix) được đồng bộ giữa TradingView Pine Script (V2) và Python execution engine đối với các cặp giao dịch: **BTC**, **ETH**, và **SOL**.

Các tham số của **ETH** và **SOL** được điều chỉnh và nhân tỷ lệ (scaled) từ bộ tham số cơ sở của **BTC** dựa trên hệ số biến động lịch sử tương đối (Beta / Volatility) nhằm duy trì mức chịu đựng rủi ro đồng đều trên toàn bộ danh mục đầu tư.

---

## 📈 1. CENTRAL MULTI-ASSET CONFIGURATION MATRIX

| Parameter Group | Parameter Name / Pine Variable | Python Config Variable | BTC (Beta = 1.0) | ETH (Beta = 1.25) | SOL (Beta = 1.6) | Scale & Adaptation Rationale |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- |
| **Asset Identity** | — | — | **BTCUSDT** | **ETHUSDT** | **SOLUSDT** | Target assets from active watchlist |
| **Volatility Benchmark**| — | — | **Beta = 1.00** | **Beta = 1.25** | **Beta = 1.60** | Base asset relative volatility index |
| **Strategy Execution Mode**| `strat_mode` | — | `"Daily Trend Follower (MTT v1.005-b)"` hoặc `"1H SEPA / Momentum (MIS v1.6)"` | Chế độ chạy hợp nhất v2 |
| **Moving Averages (MTT)**| `fast_len` / `med_len` / `slow_len_mtt` | — | **EMA 20 / 50 / 100** | **EMA 20 / 50 / 100** | **EMA 20 / 50 / 100** | Daily Trend Follower setup |
| **Moving Averages (MIS)**| `fast_len` / `med_len` / `slow_len_mis` | — | **EMA 20 / 50 / 200** | **EMA 20 / 50 / 200** | **EMA 20 / 50 / 200** | 1H Momentum & Mean-reversion setup |
| **Hard Stop Loss** | `hard_sl_pct` | `STOP_LOSS_PCT` | **8.0%** | **10.0%** | **13.0%** | Scaled linearly by Beta to prevent premature stopout |
| **ATR SL Multiplier** | `atr_sl_mul` | — | **2.0** | **2.5** | **3.2** | Multiplier of ATR 14 used to place stop loss |
| **ATR TP Multiplier** | `atr_tp_mul` | `TAKE_PROFIT_PCT` | **8.0** | **10.0** | **13.0** | Scaled to capture larger swings in higher beta assets |
| **Risk Per Trade** | `risk_pct` | `RISK_PER_TRADE` | **1.0%** | **0.8%** | **0.6%** | Scaled down for higher volatility to prevent drawdown |
| **Futures Position Size**| `futures_pct` (profile) | — | **10.0%** | **8.0%** | **6.0%** | Sizing cap for Futures profile |
| **Margin Position Size** | `margin_pct` (profile) | — | **20.0%** | **16.0%** | **12.0%** | Sizing cap for Margin profile |
| **Spot Position Size** | `spot_pct` (profile) | — | **10.0%** | **8.0%** | **6.0%** | Sizing cap for Spot profile |
| **Maximum Position Size**| `max_pos_pct` | `MAX_QUOTE_QTY` | **95.0%** | **95.0%** | **95.0%** | Absolute limit on total portfolio margin allocation |
| **Trailing Stop (Chandelier)**| `trail_atr_mul` | — | **3.0** | **3.75** | **4.8** | Trail stop distance scaled by Beta |
| **Order Cooldown** | `cooldown_bars` | — | **3 bars** | **3 bars** | **3 bars** | Rest bars before re-entering |

---

## 🛡️ 2. STOP-LOSS & TAKE-PROFIT CALCULATION DETAILS

1. **Hard Stop-Loss Limit:**
   - **BTC**: $8\%$
   - **ETH**: $8\% \times 1.25 = 10\%$
   - **SOL**: $8\% \times 1.625 \approx 13\%$ (Tuning chọn $13.0\%$ cố định)
2. **Take Profit (ATR-Based):**
   - **BTC**: $8.0 \times \text{ATR}$
   - **ETH**: $8.0 \times 1.25 = 10.0 \times \text{ATR}$
   - **SOL**: $8.0 \times 1.6 = 12.8 \times \text{ATR}$ (Tuning chọn $13.0 \times \text{ATR}$)
3. **Risk-to-Reward Ratio (R:R Target):**
   - Đối với chiến lược MIS (1H), R:R danh nghĩa tối thiểu luôn được duy trì ở mức $\ge 4:1$ (từ hệ số ATR SL 2.0x và ATR TP 8.0x đối với BTC, tương tự cho ETH và SOL).

---

## 📡 3. WEBHOOK PAYLOAD SPECIFICATIONS

Các webhook payload được chuẩn hóa gửi từ TradingView Alert đến auto-trading execution server. Các tham số bao gồm:
* `secret`: Khóa bảo mật webhook.
* `action`: `"alert"` (vào lệnh) hoặc `"sell"` (đóng lệnh).
* `symbol`: Cặp giao dịch gốc.
* `price`: Giá khớp lệnh tại TradingView.
* `interval`: Khung thời gian hiện tại của nến phát tín hiệu.
* `mode`: `"MTT"` hoặc `"MIS"`.
* `quoteQty`: Giới hạn khối lượng đặt lệnh tương đối quy đổi theo độ phân bổ vốn.

### A. Bitcoin (BTCUSDT) Webhook Payload
- **Buy / Long Alert (MTT/MIS):**
  ```json
  {
    "secret": "your_webhook_secret_here",
    "action": "alert",
    "symbol": "BTCUSDT",
    "price": 65230.5,
    "interval": "1D",
    "mode": "MTT",
    "quoteQty": 1000.0
  }
  ```
- **Sell / Close Alert (MTT/MIS):**
  ```json
  {
    "secret": "your_webhook_secret_here",
    "action": "sell",
    "symbol": "BTCUSDT",
    "price": 68400.0,
    "interval": "1D",
    "mode": "MTT"
  }
  ```

### B. Ethereum (ETHUSDT) Webhook Payload
- **Buy / Long Alert (MTT/MIS):**
  ```json
  {
    "secret": "your_webhook_secret_here",
    "action": "alert",
    "symbol": "ETHUSDT",
    "price": 3480.25,
    "interval": "1D",
    "mode": "MTT",
    "quoteQty": 800.0
  }
  ```
- **Sell / Close Alert (MTT/MIS):**
  ```json
  {
    "secret": "your_webhook_secret_here",
    "action": "sell",
    "symbol": "ETHUSDT",
    "price": 3720.5,
    "interval": "1D",
    "mode": "MTT"
  }
  ```

### C. Solana (SOLUSDT) Webhook Payload
- **Buy / Long Alert (MTT/MIS):**
  ```json
  {
    "secret": "your_webhook_secret_here",
    "action": "alert",
    "symbol": "SOLUSDT",
    "price": 165.4,
    "interval": "1D",
    "mode": "MTT",
    "quoteQty": 600.0
  }
  ```
- **Sell / Close Alert (MTT/MIS):**
  ```json
  {
    "secret": "your_webhook_secret_here",
    "action": "sell",
    "symbol": "SOLUSDT",
    "price": 182.3,
    "interval": "1D",
    "mode": "MTT"
  }
  ```
