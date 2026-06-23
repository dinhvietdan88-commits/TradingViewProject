# Kế hoạch Nghiên cứu & Triển khai các Kỹ thuật Kiểm thử Tiếp theo (Hậu S1-S6)

Tài liệu này trình bày kết quả nghiên cứu và kế hoạch thiết lập các kỹ thuật kiểm thử chuyên sâu nhằm đánh giá toàn diện độ bền bỉ (Robustness), tính ổn định tham số (Parameter Stability), khả năng chống chọi rủi ro hệ thống (Systemic Risk Resilience), và khả năng vận hành của hệ thống giao dịch tự động **TradingViewProject** sau khi đã hoàn thiện 6 kịch bản Backtest cơ bản (S1-S6).

---

## 🔬 Kết Quả Nghiên Cứu & Đề Xuất Các Kỹ Thuật Kiểm Thử Tiếp Theo

Sau khi hoàn thành tối ưu hóa và chạy Backtest trên 6 kịch bản (S1 đến S6):
1. **S1**: Baseline (Không dùng bộ lọc AI)
2. **S2**: Standard Minervini Filter (SEPA)
3. **S3**: Short-term EMA Filter
4. **S4**: Tight SL / Trailing Stop
5. **S5**: Multi-Timeframe Validation (MLTS)
6. **S6**: Optimized Hybrid Mode (Trend + Momentum)

Để đảm bảo các chiến lược này có khả năng sinh lời bền vững trong thực tế (Mainnet) và hệ thống phần mềm không gặp lỗi nghiêm trọng, chúng ta cần triển khai các kỹ thuật kiểm thử nâng cao được chia làm hai nhóm chính: **Quantitative Strategy Validation** (Kiểm thử định lượng chiến lược) và **Engineering & System Chaos Validation** (Kiểm thử kỹ thuật & Vận hành hệ thống).

```
                      ┌──────────────────────────────────────────────┐
                      │    KẾ HOẠCH KIỂM THỬ HẬU S1-S6 (DEEP TEST)   │
                      └──────────────────────┬───────────────────────┘
                                             │
               ┌─────────────────────────────┴─────────────────────────────┐
               ▼                                                           ▼
┌──────────────────────────────┐                            ┌──────────────────────────────┐
│ QUANTITATIVE STRATEGY TEST   │                            │   ENGINEERING & SYSTEM TEST  │
├──────────────────────────────┤                            ├──────────────────────────────┤
│ 1. Monte Carlo Simulations   │                            │ 1. Chaos Engineering & Fault │
│ 2. Walk-Forward Analysis     │                            │ 2. Concurrency & Race Tests  │
│ 3. Slippage/Latency Decay    │                            │ 3. Network & Transport Proof │
│ 4. Regime Stress Testing     │                            │ 4. E2E Dry-run (Testnet)     │
└──────────────────────────────┘                            └──────────────────────────────┘
```

---

### PHẦN A: KIỂM THỬ ĐỊNH LƯỢNG CHIẾN LƯỢC (QUANTITATIVE STRATEGY VALIDATION)

#### 1. Mô Phỏng Monte Carlo (Monte Carlo Simulations)
Mục tiêu là phá vỡ chuỗi kết quả Backtest tĩnh để tìm ra xác suất xảy ra mức sụt giảm tài sản lớn nhất (Max Drawdown) và khả năng cháy tài khoản trong thực tế.
- **Type I (Trade Resampling / Order Shuffling)**: Tráo đổi ngẫu nhiên thứ tự thực hiện các lệnh trong lịch sử S1-S6 (chạy 10,000 lần mô phỏng). Việc này loại bỏ yếu tố may mắn khi thị trường đi vào xu hướng thuận lợi liên tục, giúp đo lường phân phối xác suất của Drawdown thực tế.
- **Type II (Win-Rate / Profit Degradation)**: Loại bỏ ngẫu nhiên 10% đến 20% các lệnh thắng lớn nhất (Outliers) để đánh giá xem chiến lược có phụ thuộc quá mức vào một vài giao dịch may mắn hay không. Chiến lược mạnh phải giữ được P&L dương ngay cả khi hiệu suất của các lệnh thắng bị giảm sút.
- **Type III (Parameter Noise / Robustness Testing)**: Thêm nhiễu ngẫu nhiên (+/- 5-10%) vào các tham số đầu vào (ví dụ: chu kỳ EMA, hệ số ATR SL/TP, ngưỡng RSI). Nếu hiệu suất giảm đột ngột (Cliff Effect), chiến lược đã bị Overfit. Ngược lại, nếu P&L biến động nhẹ và mượt mà, chiến lược nằm trong vùng tham số an toàn (Robustness Region).

#### 2. Phân Tích Walk-Forward (Walk-Forward Analysis - WFA)
WFA là tiêu chuẩn vàng để xác minh xem bộ lọc tham số tối ưu hóa trong S1-S6 có thể tiếp tục hoạt động tốt trên dữ liệu chưa từng thấy trong tương lai hay không.
- Chia dữ liệu lịch sử thành các cửa sổ cuốn chiếu (Rolling Windows):
  - **In-Sample (IS)**: 70% dữ liệu dùng để tối ưu hóa tham số.
  - **Out-of-Sample (OOS)**: 30% dữ liệu tiếp theo dùng để chạy thử nghiệm với tham số tối ưu thu được từ IS.
- Tính toán chỉ số **Walk-Forward Efficiency (WFE)**:
  $$\text{WFE} = \frac{\text{Profit Factor (OOS)}}{\text{Profit Factor (IS)}}$$
  - **WFE > 60%**: Chiến lược có tính thích ứng cao và sẵn sàng chạy thực tế.
  - **WFE < 50%**: Chiến lược bị Overfit nặng, cần thiết lập lại các bộ lọc.

#### 3. Phân Tích Độ Nhạy Trượt Giá & Độ Trễ (Slippage & Latency Decay)
Các mô phỏng Backtest tĩnh thường giả định khớp lệnh tại mức giá đóng nến của TradingView. Thực tế, độ trễ mạng và thanh khoản sàn sẽ gây trượt giá (Slippage).
- Xây dựng biểu đồ phân rã hiệu suất (Decay Curve):
  - Chạy thử nghiệm chiến lược với các mức trượt giá tăng dần: $0.00\%$ (lý thuyết), $0.05\%$ (chuẩn), $0.10\%$ (cao), $0.25\%$, và $0.50\%$ (trường hợp thị trường biến động mạnh).
  - Phân tích độ trễ từ lúc nhận webhook (Server A) -> Analyzer (Server C) -> Khớp lệnh (Server B). Xác định ngưỡng thời gian tối đa (Latency Threshold) trước khi lợi thế cạnh tranh bị triệt tiêu hoàn toàn.

#### 4. Kiểm Thử Kháng Cự Regime & Stress Test (Regime Stress Testing)
- **Historical Stress Tests**: Chạy mô phỏng qua các giai đoạn thị trường khủng hoảng cực độ (FTX sập tháng 11/2022, SVB sập tháng 3/2023, Covid-19 tháng 3/2020) để đảm bảo các chốt chặn an toàn (Chandelier Trailing, Daily Loss Cap) hoạt động đúng lúc.
- **Synthetic Regimes**: Sử dụng mô hình Geometric Brownian Motion kết hợp Jump-Diffusion để tạo ra 1,000 chuỗi dữ liệu giả lập có biên độ dao động lớn, khoảng trống giá (Gaps) lớn để thử nghiệm khả năng chịu đựng của tài khoản.

---

### PHẦN B: KIỂM THỬ KỸ THUẬT & HỆ THỐNG PHẦN MỀM (ENGINEERING & SYSTEM CHAOS VALIDATION)

#### 1. Chaos Engineering & Khôi Phục Lỗi (Fault Tolerance)
Kiểm thử cách thức hệ thống 3 máy chủ phản ứng khi các thành phần hạ tầng bị sập:
- **Server C (AI Core) Offline**: Mô phỏng lỗi kết nối tới ChromaDB hoặc API Gemini bị cạn kiệt hạn mức (Quota limit). Hệ thống phải tự động chuyển sang chế độ **Algorithmic Mode** (Bypass AI, chạy thuần kỹ thuật) mà không làm rớt hay treo luồng xử lý tín hiệu.
- **Server B (Execution Vault) Offline**: Khi Server B bị sập hoặc mất mạng Tailscale, Server C phải ghi nhận trạng thái hàng đợi và kích hoạt cơ chế lưu trữ cục bộ tạm thời, tránh mất mát tín hiệu giao dịch.
- **Exchange API Outage**: Thử nghiệm cơ chế Failover định tuyến tài khoản (ví dụ: từ WEEX chuyển sang Binance hoặc Bybit) khi API WEEX bị lỗi 5xx hoặc mất kết nối socket.

#### 2. Kiểm Thử Đồng Thời & Tránh Trùng Lặp (Concurrency, Race Condition & Queue Saturation)
Khi thị trường biến động mạnh, nhiều chỉ báo kỹ thuật có thể kích hoạt Webhook đồng thời.
- **Load Test**: Bắn đồng thời 100-200 tín hiệu webhook giả lập vào Server A trong vòng 1 giây.
- Xác minh:
  - Cơ chế khóa dữ liệu (Mutex, File Lock) tại SQLite `trades.db` hoạt động tốt, không gây lỗi `database is locked`.
  - Bộ lọc trùng lặp tín hiệu (Deduplication Gate) lọc chính xác các tín hiệu trùng khớp về Symbol, Price và Timestamp.
  - Hàng đợi (Queue) xử lý theo thứ tự FIFO (First In First Out) và không xảy ra hiện tượng thất thoát tín hiệu (Message Loss).

#### 3. Kiểm Thử Bảo Mật & Chứng Thực Đường Truyền Vật Lý (Network & Transport Proof)
- Xác thực nguyên lý **A2A Route Evidence (Bằng Chứng Vận Chuyển)**: Bất kỳ lệnh điều hướng/giao dịch nào từ xa phải trình ra bằng chứng vật lý (`route_verified=true`) bao gồm chữ ký Ed25519 hợp lệ và mã phản hồi HTTP JSON-RPC thành công. Chặn đứng hoàn toàn việc giả mạo tín hiệu nội bộ.
- Kiểm tra cơ chế tự phục hồi (Self-Healing) của các kết nối VPN Tailscale và Cloudflare Tunnel khi gặp gián đoạn đường truyền vật lý.

#### 4. E2E Dry-run Campaign trên Testnet
- Triển khai toàn bộ hệ thống thực tế trên môi trường Staging/Testnet (WEEX Trial hoặc Binance Testnet).
- Sử dụng các tín hiệu trực tiếp từ TradingView hoặc Replay Client để thực hiện các giao dịch với volume siêu nhỏ (Micro-Volume) liên tục trong 72 giờ để đánh giá độ trễ thực tế, độ ổn định của API và độ tin cậy của robot Telegram thông báo phê duyệt thủ công.

---

## ⚠️ Đánh Giá Rủi Ro & Yêu Cầu Người Dùng Phê Duyệt (User Review Required)

> [!IMPORTANT]
> **Rủi ro Quá tải Tài nguyên (Resource & Token Exhaustion):**
> Việc chạy mô phỏng Monte Carlo và tối ưu hóa Walk-Forward trên số lượng lớn dữ liệu lịch sử có thể tiêu tốn nhiều tài nguyên CPU và gọi API LLM (nếu tích hợp phân tích AI vào mô phỏng). 
> - **Giải pháp**: Tất cả các kiểm thử định lượng chiến lược (Monte Carlo, WFA) sẽ được thiết kế để chạy **hoàn toàn cục bộ (offline)** sử dụng dữ liệu lịch sử đã lưu trữ trong SQLite và mô phỏng toán học, **không thực hiện gọi API LLM trả phí** trừ khi được yêu cầu rõ ràng.

> [!WARNING]
> **Kiểm thử trên tài khoản thực (Mainnet Micro-Volume Trading):**
> Khi thực hiện kiểm thử E2E ở pha cuối, hệ thống có thể kết nối với sàn giao dịch thực.
> - **Nguyên tắc bắt buộc**: Bắt buộc giới hạn khối lượng tối đa cực thấp ($10 USDT/lệnh), đặt mức cắt lỗ nghiêm ngặt và kích hoạt Daily Loss Cap ($10 USDT tối đa một ngày) để bảo vệ tài khoản trong mọi tình huống phát sinh lỗi code.

---

## ❓ Câu Hỏi Thảo Luận (Open Questions)

> [!NOTE]
> Bạn vui lòng cho ý kiến về các điểm dưới đây để tối ưu hóa kế hoạch triển khai:
> 1. **Về Kiểm thử Định lượng (Quantitative)**: Bạn muốn ưu tiên triển khai công cụ nào trước trong số Monte Carlo, Walk-Forward Analysis (WFA) hay Kiểm thử trượt giá (Slippage/Latency)?
> 2. **Về Stress Test**: Chúng ta nên tập trung Stress Test vào các sự kiện lịch sử cụ thể nào (ví dụ: ngày sụp đổ FTX tháng 11/2022, hoặc các ngày biến động mạnh gần đây của năm 2026)?
> 3. **Về Môi trường chạy thử**: Hệ thống có cần tích hợp một Testnet thật của WEEX/Binance trong pha kiểm thử E2E Dry-run, hay chỉ cần chạy qua Simulator cục bộ (Offline Mock Server)?

---

## 🛠️ Đề Xuất Các Thay Đổi Cấu Trúc (Proposed Changes)

Khi kế hoạch được phê duyệt, chúng ta sẽ xây dựng các module kiểm thử mới mà không làm ảnh hưởng đến mã nguồn vận hành chính:

### [Test Infrastructure]

#### [NEW] [test_monte_carlo.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/tests/advanced/test_monte_carlo.py)
- Module thực hiện tráo đổi lệnh (Shuffling), loại bỏ lệnh thắng lớn (Outliers) và phân tích phân phối Drawdown từ chuỗi dữ liệu lịch sử S1-S6.

#### [NEW] [walk_forward_runner.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/scripts/walk_forward_runner.py)
- Kịch bản tự động chia dữ liệu thành các đoạn In-Sample/Out-of-Sample cuốn chiếu để đo lường chỉ số WFE.

#### [NEW] [test_slippage_decay.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/tests/advanced/test_slippage_decay.py)
- Chạy giả lập khớp lệnh với mức Slippage biến thiên từ 0% đến 1.0% để vẽ biểu đồ suy giảm lợi nhuận.

#### [NEW] [test_network_chaos.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/tests/advanced/test_network_chaos.py)
- Kịch bản kiểm thử Chaos Engineering ngắt kết nối đột ngột giữa Server A, C và B để đo lường khả năng khôi phục và chuyển đổi sang Algorithmic Mode của hệ thống.

---

## 🧪 Kế Hoạch Xác Minh (Verification Plan)

Sau khi viết xong các module kiểm thử trên, chúng ta sẽ kiểm tra tính hoạt động đúng đắn của chính chúng:
1. **Kiểm thử tự động (Automated Tests)**:
   - Chạy `pytest` trên các module mới để đảm bảo thuật toán Monte Carlo tính toán đúng phân phối xác suất, thuật toán WFA phân tách dữ liệu chính xác và không bị rò rỉ dữ liệu (data leakage) giữa IS và OOS.
   - Lệnh chạy: `pytest nerves/workers/trading/tests/advanced/`
2. **Xác minh đầu ra (Output Verification)**:
   - Đảm bảo các kết quả phân tích Monte Carlo và WFA xuất ra các báo cáo dạng Markdown và biểu đồ trực quan (matplotlib png) lưu trữ tại `docs/reports/advanced_tests/` để người dùng dễ dàng đánh giá trực quan.
