# Ma Trận Tham Số Tối Ưu Hóa (Optimized Parameters Matrix)

Tài liệu này đúc kết toàn bộ các tham số tối ưu hóa ("Winning Edge") được kiểm chứng qua các chiến dịch backtest lớn trên **1,296 tín hiệu** của hệ thống Angati TradingView Webhook.

---

## 📊 Ma Trận Tham Số Cấu Hình Tối Ưu (Optimal Config Matrix)

Dưới đây là bộ cấu hình mặc định đề xuất để cài đặt trực tiếp vào hệ thống Webhook Server và mã nguồn Pine Script:

| Tên Tham Số (Pine/API Variable) | Chế độ Daily MTT | Chế độ 1H MIS | Giải thích vai trò & Khuyến nghị vận hành |
| :--- | :---: | :---: | :--- |
| **Timeframe** | `D` (Daily) | `1H` (Hourly) | Khung thời gian vận hành chiến lược và lọc tín hiệu. |
| **Benchmark Market** | `BTCUSD` | `SPY` / `BTCUSD` | Benchmark để tính Relative Strength (RS). Tắt nếu tự trade benchmark. |
| **MA Type** | `EMA` | `SMA` (for TT) | Loại trung bình động được sử dụng để xác định xu hướng chính. |
| **Fast MA Length** | `20` | `50` | Đường trung bình nhanh (EMA 20 cho MTT, SMA 50 cho MIS). |
| **Medium MA Length** | `50` | `150` | Đường trung bình trung hạn (EMA 50 cho MTT, SMA 150 cho MIS). |
| **Slow MA Length** | `100` | `200` | Đường trung bình chậm (EMA 100 cho MTT, SMA 200 cho MIS). |
| **RSI Floor** | `—` | `50` | Ngưỡng dưới của RSI (Long chỉ được kích hoạt khi RSI > 50). |
| **VCP Lookback (bars)** | `—` | `20` | Độ dài cửa sổ quét tìm điểm tích lũy và pivot thắt chặt VCP. |
| **VCP Volume Dry-up** | `—` | `0.6` (60%) | Volume tại Pivot phải thấp hơn 60% trung bình 50 phiên trước đó. |
| **VCP Range Tightness** | `—` | `0.7` (70%) | Biên độ nến tại Pivot phải nhỏ hơn 70% của ATR(14). |
| **Breakout Window** | `—` | `15` | Điểm nổ (Breakout) phải xảy ra trong vòng 15 nến kể từ Pivot. |
| **Breakout Volume** | `—` | `1.5` (150%) | Khối lượng breakout phải lớn hơn 1.5 lần trung bình 50 phiên. |
| **Risk Per Trade (% Equity)** | `—` | `1.0%` | Phần trăm vốn chấp nhận mất trên mỗi lệnh giao dịch. |
| **ATR SL Multiplier** | `2.5` | `2.0` | Hệ số ATR để tính khoảng cách dừng lỗ từ điểm entry. |
| **ATR TP Multiplier** | `—` | `8.0` | Hệ số ATR để tính điểm chốt lời (R:R = 4:1 trong chế độ MIS). |
| **Hard Stop Loss Cap** | `—` | `8.0%` | Giới hạn dừng lỗ cứng tối đa (không thương lượng theo SEPA). |
| **Max Position Notional** | `10.0%` (Spot) | `95.0%` | Tổng quy mô vị thế so với tổng tài sản (MTT vs MIS). |
| **ATR Trailing Stop** | `True` (2.5) | `True` (3.0) | Kích hoạt dừng lỗ kéo theo (Chandelier) bám sát xu hướng. |
| **Regime Filters (ADX)** | `True` (ADX > 20) | `True` (ADX >= 25)| Bỏ qua các tín hiệu trong thị trường Sideway không xu hướng. |
| **Bollinger Squeeze Filter**| `True` (width > 5%)| `—` | Chặn các vùng tích lũy BB quá thắt chặt dễ gây quét 2 đầu. |
| **Time-based Stop** | `True` (20 bars) | `—` | Tự động cắt lệnh hòa vốn/lỗ nhẹ sau 20 phiên không chạy. |
| **Cooldown Bars** | `—` | `3` | Số nến đứng ngoài sau khi thoát lệnh để tránh whipsaw. |

---

## 🛡️ Hướng Dẫn Vận Hành & Quản Lý Rủi Ro (SRE & QA Guides)

### 1. Quản lý Drawdown Compounding trong Chế độ MTT
- **Thách thức**: Nhánh MTT (Daily) đạt lợi nhuận cực cao (+106K USDT khi compounding 2% risk) nhưng Max Drawdown lên tới **86.86%**. Mức sụt giảm này không khả thi cho quỹ hoặc tài khoản cá nhân thông thường.
- **Giải pháp khắc phục**:
  1. Giảm tỷ lệ Risk Per Trade xuống **0.5% - 1.0%** thay vì để 2% mặc định.
  2. Áp dụng cơ chế **Max Position Size Cap** ở mức 20% vốn khả dụng thay vì cho phép đòn bẩy Futures tối đa.
  3. Kích hoạt bộ lọc **ADX > 20** và **BB Squeeze** (width >= 5%) làm cấu hình mặc định để lọc bỏ các vùng tích lũy giả.

### 2. Quản lý trượt giá (Slippage Management)
- **Thách thức**: Hiệu suất giảm đáng kể khi trượt giá tăng (Profit Factor giảm từ 1.79 ở 0% slippage xuống 1.52 ở 0.50% slippage).
- **Giải pháp khắc phục**:
  1. Chỉ sử dụng lệnh **Limit Order** hoặc **Stop-Limit Order** cho các điểm breakout, cấm sử dụng lệnh Market Order trực tiếp.
  2. Bố trí máy chủ giao dịch (Server B) tại vùng có kết nối độ trễ thấp tới sàn giao dịch (<100ms) để giảm thiểu trễ khớp lệnh.
  3. Thiết lập cảnh báo bảo vệ trượt giá tối đa **0.15%** tại API Execution Gateway.
