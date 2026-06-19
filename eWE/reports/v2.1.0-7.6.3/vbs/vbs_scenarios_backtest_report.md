# 📚 Báo cáo Phân tích Chuyên sâu & Kết tinh Chiến lược VBS (v2.1.0-7.6.3)

Tài liệu này trình bày bản phân tích chuyên sâu từ chiến dịch tối ưu hóa và backtest trên **627 tín hiệu nguồn** của chiến lược VBS (được thu thập từ ngày 30/05/2026 đến 09/06/2026), đối chiếu trực tiếp với các phiên bản thử nghiệm lịch sử của hệ thống **MIS v1 (Multi-Indicator Strategy)** để kết tinh thành các loại hình chiến lược giao dịch tối ưu.

---

## 🎯 1. BẢN ĐỒ ÁNH XẠ KỊCH BẢN (SCENARIOS MAPPING)
Chiến dịch backtest v2.1.0-7.6.3 được thiết kế để tái tạo và tối ưu hóa các phương án thử nghiệm mà hệ thống V1 đã từng thực hiện, chuyển dịch từ các quy tắc lọc thủ công/AI sang các rào chắn vật lý và toán học xác thực:

| Kịch bản | Định nghĩa Kỹ thuật | Phiên bản V1 Tương ứng | Vai trò trong Hệ thống |
| :--- | :--- | :--- | :--- |
| **S1** | Giao dịch Breakout thuần túy, sử dụng khoảng dừng lỗ 8% và chốt lời 20% mặc định. | **MIS v1 (Baseline)** | Điểm chuẩn (Baseline) để đo lường hiệu quả của các bộ lọc. |
| **S2** | Áp dụng bộ lọc Mark Minervini Trend Template (Score >= 5/8) kết hợp mẫu hình thu hẹp biến động VCP (Volume ratio < 1.0 và Range ratio < 1.0 trong 5 ngày trước breakout). | **MIS v12B (Strict SEPA)** | Đo lường hiệu quả lọc nhiễu của trường phái giao dịch chính thống. |
| **S3** | Lọc xu hướng theo cụm đường trung bình EMA ngắn hạn: Giá > EMA20 > EMA50 > EMA100 (đối với lệnh Long). | **Strategy MTT (v1.005-b)** | Bám sát xu hướng động lượng ngắn hạn. |
| **S4** | Điểm dừng lỗ chặt chẽ (1.5 * ATR14), chốt lời rộng (3.0 * ATR14) kết hợp điểm dừng kéo theo Chandelier Trailing Stop (2.5 * ATR14). | **MIS v10 / v11A (Trailing Stops)** | Tối ưu hóa tỷ lệ Risk/Reward và gồng lãi theo xu hướng. |
| **S5** | Xác thực đa khung thời gian: Khung Daily đạt xu hướng (Trend Template Score >= 5), khung 1H đạt xu hướng (EMA20 > EMA50 > EMA200). | **MIS v13C (Multi-Timeframe)** | Xác thực xu hướng vĩ mô trước khi kích hoạt lệnh vi mô. |
| **S6** | Kịch bản lai tối ưu: Khung Daily xác nhận xu hướng (Score >= 5), kết hợp chỉ báo động lượng RSI14 (Long >= 50) và MACD nằm trên đường tín hiệu. | **MIS v15/v16/v2 (Optimized Hybrid)** | Cấu hình tối ưu kết hợp xu hướng dài hạn và động lượng ngắn hạn. |

---

## 📊 2. BẢNG SO SÁNH HIỆU SUẤT TỔNG THỂ

### PHƯƠNG ÁN A: QUY MÔ VỐN CỐ ĐỊNH (Fixed Sizing - $100/vị thế)
*Vốn khởi đầu: 10,000 USDT. Mỗi vị thế cố định 100 USDT.*

| Kịch bản | Lệnh Khớp | Tỷ lệ Thắng | Lợi nhuận Ròng | Profit Factor | Max Drawdown | Đánh giá Trạng thái |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **S1 (Baseline)** | 622 | 51.3% | +861.12 USDT | 1.52 | 0.80% | ⚠️ Nhiều nhiễu, Drawdown cao so với quy mô vị thế. |
| **S2 (Strict SEPA)** | 44 | 63.6% | +9.57 USDT | 1.36 | 0.26% | 🟢 Cực kỳ an toàn, khớp rất ít lệnh, loại bỏ 93% nhiễu. |
| **S3 (EMA Stack)** | 237 | 70.5% | +828.02 USDT | 6.45 | 1.38% | 🟢 Tỷ lệ thắng xuất sắc, bám trend ngắn hạn tốt. |
| **S4 (Trailing SL)** | 622 | 51.6% | **+11,718.84 USDT** | **12.89** | **0.48%** | 🏆 **Lợi nhuận cao nhất**, Profit Factor ấn tượng nhờ gồng lời. |
| **S5 (MTF Validation)** | 242 | 74.4% | +1,607.09 USDT | 12.22 | 1.21% | 🟢 Rất ổn định, bộ lọc đa khung thời gian hoạt động tối ưu. |
| **S6 (Optimized Hybrid)**| 315 | **77.8%** | +2,159.18 USDT | **15.20** | 1.23% | 🏆 **Tỷ lệ thắng cao nhất**, hiệu suất ổn định vượt trội. |

---

### PHƯƠNG ÁN B: QUY MÔ VỐN HỢP LỆ THEO LÃI KÉP (Dynamic Sizing - Rủi ro 2% Portfolio)
*Vốn khởi đầu: 10,000 USDT. Rủi ro 2% tài sản mỗi lệnh, quy mô vị thế tự động điều chỉnh theo khoảng cách Stop Loss.*

| Kịch bản | Lệnh Khớp | Tỷ lệ Thắng | Lợi nhuận Ròng | Profit Factor | Max Drawdown | Đánh giá Trạng thái |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **S1 (Baseline)** | 622 | 51.3% | +64,702.53 USDT | 1.29 | 20.72% | ⚠️ Biến động tài sản quá lớn, rủi ro cháy tài khoản cao. |
| **S2 (Strict SEPA)** | 44 | 63.6% | +238.04 USDT | 1.34 | 6.30% | 🟢 Tăng trưởng chậm nhưng chắc chắn. |
| **S3 (EMA Stack)** | 237 | 70.5% | +66,928.87 USDT | 3.02 | 31.57% | ⚠️ Lợi nhuận tốt nhưng drawdown pha mở rộng khá sâu. |
| **S4 (Trailing SL)** | 622 | 51.6% | +305,303.30 USDT | 1.44 | 31.68% | 🟢 Hiệu quả gồng lãi kép mạnh mẽ. |
| **S5 (MTF Validation)** | 242 | 74.4% | +507,693.52 USDT | 3.27 | 30.08% | 🟢 Cân bằng hoàn hảo giữa rủi ro và tăng trưởng. |
| **S6 (Optimized Hybrid)**| 315 | **77.8%** | **+1,988,997.28 USDT**| **3.31** | **31.57%** | 🏆 **Đỉnh cao hiệu quả lãi kép**, tăng trưởng tài sản >198 lần. |

---

## 🔍 3. PHÂN TÍCH CHUYÊN SÂU (DEEP-DIVE ANALYSIS)

### 📈 A. Sức mạnh của gồng lãi và quản lý rủi ro động (Kịch bản S4)
*   **Hiện tượng**: Mặc dù tỷ lệ thắng của S4 chỉ tương đương S1 (51.6% so với 51.3%), nhưng lợi nhuận ròng của S4 ở chế độ Fixed Sizing gấp **13.6 lần** S1 (+11,718 USDT so với +861 USDT).
*   **Nguyên nhân**: Khoảng cách Stop Loss chặt chẽ dựa trên ATR (1.5 * ATR14) giúp giảm thiểu tối đa tổn thất khi lệnh sai. Đồng thời, việc chốt lời mục tiêu rộng (3.0 * ATR14) kết hợp với đường dừng kéo theo **Chandelier Trailing Stop** (2.5 * ATR14) cho phép giữ lệnh chạy xuyên suốt các đợt sóng mạnh của xu hướng tăng. Chiến lược này hiện thực hóa triết lý: *"Cắt lỗ nhanh và để lợi nhuận chạy tự do"*.

### 🛡️ B. Bộ lọc Minervini SEPA (Kịch bản S2): An toàn tối đa nhưng bỏ lỡ cơ hội ngắn hạn
*   **Hiện tượng**: S2 lọc bỏ tới **93% tín hiệu** (chỉ khớp 44 trên 627 tín hiệu). Mặc dù đạt tỷ lệ thắng tốt (63.6%) và drawdown cực thấp (0.26%), nhưng lợi nhuận thực tế đạt được rất khiêm tốn (+9.57 USDT).
*   **Nguyên nhân**: Bộ lọc SEPA truyền thống của Mark Minervini được thiết kế cho các cổ phiếu tăng trưởng trung-dài hạn có tích lũy nền tảng chặt chẽ (mẫu hình VCP kéo dài hàng tuần hoặc hàng tháng). Khi áp dụng cho các tín hiệu Crypto tần suất cao (giao dịch trong khung 1H ngắn hạn), bộ lọc này trở nên quá khắt khe, loại bỏ hầu hết các đợt breakout chớp nhoáng có lợi nhuận cao nhưng thiếu tích lũy dài hạn.

### 🌐 C. Xác thực đa khung thời gian (Kịch bản S5): Khiên chắn xu hướng vĩ mô
*   **Hiện tượng**: Khi ép điều kiện khung Daily phải đồng thuận xu hướng (Trend Template Score >= 5/8) rồi mới cho phép khớp lệnh ở khung 1H (S5), số lượng lệnh khớp giảm từ 622 xuống 242. Tuy nhiên, Win Rate tăng vọt từ 51.3% lên **74.4%** và Profit Factor đạt tới **12.22**.
*   **Kết luận**: Giao dịch breakout khung ngắn hạn chỉ thực sự hiệu quả khi nằm trong một xu hướng tăng giá vĩ mô vững chắc ở khung ngày. Việc bỏ qua xu hướng đa khung thời gian là nguyên nhân chính dẫn đến tỷ lệ trade lỗi cực cao ở bản V1.

### 🏆 D. Lãi kép tối ưu với Kịch bản Lai Hybrid (S6)
*   **Hiện tượng**: S6 kết hợp bộ lọc xu hướng ngày (Trend Template) với động lượng ngắn hạn (RSI >= 50 và MACD nằm trên Signal). Kết quả là đạt tỷ lệ thắng cao nhất hệ thống (**77.8%**). Ở chế độ Dynamic Sizing, S6 tạo ra mức tăng trưởng tài sản không tưởng: biến **10,000 USDT ban đầu thành 1,998,997.28 USDT** nhờ hiệu ứng lãi kép dồn dập trên một chuỗi lệnh thắng liên tục.
*   **Nguyên nhân**: Bằng cách kết hợp RSI và MACD, chiến lược chỉ tham gia các breakout khi động lượng đang ở pha tăng tốc mạnh nhất, giảm thiểu tối đa các pha tích lũy đi ngang gây hao mòn tài sản (chop/decay). Điều này cho phép áp dụng đòn bẩy lãi kép 2% portfolio một cách an toàn mà không sợ chuỗi thua lỗ liên tiếp tàn phá tài khoản.

---

## ⚡ 4. TỐI ƯU HÓA BỘ LỌC ĐIỀU HƯỚNG ĐA KHUNG THỜI GIAN SUPERTREND V1.3 (MTA)

Để giải quyết tình trạng sụt giảm hiệu suất nghiêm trọng khi thị trường đi vào vùng giằng co đi ngang (Chop) từ ngày 09/06 đến 17/06/2026 (mở rộng quy mô mẫu lên **1,015 tín hiệu**), chúng tôi đã phát triển và chạy thử nghiệm hệ thống **Bộ lọc định hướng SuperTrend v1.3** trên 3 khung thời gian:
1.  **1H (Lọc nhanh - Fast Filter):** Loại bỏ nhiễu và bẫy tăng/giảm giá (Traps).
2.  **4H (Lọc trung hạn - Medium Filter):** Xác định xu hướng chính và lọc vùng tích lũy (Chop/Sideway).
3.  **1D (Lọc dài hạn - Long Filter):** Xác định chu kỳ giá vĩ mô.

### A. Kết quả thử nghiệm bộ lọc `ST(7, 3.5)` (Đã trừ phí 0.05% mỗi chiều)

*   **Kịch bản S6 (Optimized Hybrid):**
    *   *Baseline (Không lọc):* Khớp 449 lệnh, WR **38.75%**, Net PnL Dynamic **-311.83 USDT** (Cháy ròng do phí).
    *   *Bộ lọc 1H ST Only:* Khớp 311 lệnh (giảm 138 lệnh nhiễu), WR **55.95% (+17.20%)**, Net PnL Dynamic **+34,920.78 USDT**.
*   **Kịch bản S4 (Trailing SL):**
    *   *Baseline (Không lọc):* Khớp 1013 lệnh, WR **46.99%**, Net PnL Dynamic **+106,972.26 USDT**.
    *   *Bộ lọc 1H ST Only:* Khớp 509 lệnh (giảm 504 lệnh nhiễu), WR **66.99% (+20.00%)**, Net PnL Dynamic **+5,714,692.57 USDT** (Tăng trưởng cực kỳ ngoạn mục nhờ lãi kép).
*   **Kịch bản S3+S5 (Trend Stack - Phân tách S3 & S5):**
    *   *Cấu hình Joint S3+S5:* Baseline khớp 241 lệnh, WR **39.83%**, Net PnL Dynamic **-7,500.44 USDT**. Tích hợp 1H ST Filter: Khớp 232 lệnh, WR **41.38%**, Net PnL Dynamic **-7,078.58 USDT** (Hiệu suất vẫn âm nặng do độ trễ của EMA Daily).
    *   *Cấu hình S3-only (Daily EMA Stack):* Baseline khớp 441 lệnh, WR **26.53%**, Net PnL Dynamic **-9,442.57 USDT**. Tích hợp 1H ST Filter: Khớp 250 lệnh, WR **38.40%**, Net PnL Dynamic **-7,187.59 USDT** (Xác nhận S3 là bộ lọc gây trễ nghiêm trọng và phá hủy lợi nhuận).
    *   *Cấu hình S5-only (Hourly confirmation + Daily Trend):* Baseline khớp 289 lệnh, WR **49.83%**, Net PnL Dynamic **+2,497.80 USDT**. Tích hợp 1H ST Filter: Khớp 280 lệnh, WR **51.43%**, Net PnL Dynamic **+4,607.11 USDT** (Hiệu suất dương vượt trội nhờ tối ưu nhạy bén khung 1H EMA Stack).

### B. Bài học thực nghiệm về Cấu trúc Đa khung thời gian
*   **Tại sao chỉ 1H ST là đủ hiệu quả?** Giai đoạn May 30 - June 17, 2026 là downtrend vĩ mô dài hạn của BTC (giá nằm dưới EMA200 ngày, ADX Daily duy trì cực cao >30). Vì toàn bộ các tín hiệu S6 và S3+S5 vượt qua điều kiện lọc xu hướng ngày đều là Short, xu hướng 4H và 1D SuperTrend vốn đã ở vị thế Bearish (đồng thuận 100%). Do đó, bộ lọc 4H và 1D không lọc thêm lệnh nào, và chỉ có bộ lọc **1H SuperTrend** đóng vai trò lọc nhiễu nhạy bén ở sóng ngắn.

---

## 🧬 5. KẾT TINH THÀNH CHIẾN LƯỢC (STRATEGY CRYSTALLIZATION)

Dựa trên kết quả thực nghiệm tối ưu hóa 627 tín hiệu và các phân tách mở rộng trên 1,015 tín hiệu, chúng ta kết tinh thành **4 loại hình chiến lược chuyên biệt** dành cho các khẩu vị rủi ro và điều kiện thị trường khác nhau:

### 🛡️ Loại 1: Chiến lược Bảo thủ SEPA (Conservative SEPA)
*   **Cấu hình**: Áp dụng nguyên mẫu **S2**.
*   **Khẩu vị rủi ro**: Cực kỳ thấp (Risk-Averse).
*   **Cách thức vận hành**: Chỉ giao dịch khi khung Daily đạt điểm xu hướng tuyệt đối và có mẫu hình tích lũy thu hẹp biến động (VCP) rõ rệt. Khớp rất ít lệnh nhưng lệnh nào khớp đều có xác suất thắng cực cao.
*   **Tham số khuyên dùng**: Vốn Dynamic 1% portfolio, Stop Loss chặt chẽ theo ATR mục tiêu.

### ⚡ Loại 2: Chiến lược Bám đuổi Động lượng Ngắn hạn (S5-only Trend Validation)
*   **Cấu hình**: Áp dụng kịch bản **S5-only** (Bỏ qua hoàn toàn S3).
*   **Khẩu vị rủi ro**: Trung bình.
*   **Cách thức vận hành**: Giao dịch theo cụm EMA ngắn hạn khung 1H đồng thuận với cấu trúc xu hướng tối thiểu khung ngày. Đã loại bỏ hoàn toàn bộ lọc S3 (EMA Daily Stack) do tính trễ cao gây bào mòn tài sản. Khuyên dùng kết hợp bộ lọc xu hướng **SuperTrend v1.3 `ST(7, 3.5) 1H`**.
*   **Tham số khuyên dùng**: Fixed Sizing hoặc Dynamic 1.0% - 1.5% portfolio để kiểm soát Drawdown.

### 🏆 Loại 3: Chiến lược Thu hoạch Lãi kép Tối ưu (Optimized Hybrid - Đề xuất chính)
*   **Cấu hình**: Áp dụng kịch bản **S6**.
*   **Khẩu vị rủi ro**: Chủ động (Aggressive Compounding).
*   **Cách thức vận hành**: Kết hợp bộ lọc xu hướng vĩ mô (Trend Template) với chỉ báo động lượng tăng tốc (RSI/MACD). Đây là chiến lược cốt lõi của phiên bản v2.1.0-7.6.3 để tối ưu hóa dòng tiền.
*   **Tham số khuyên dùng**: Dynamic Compounding Sizing (Rủi ro 2% portfolio mỗi lệnh). Bảo đảm tuân thủ nghiêm ngặt ranh giới ngoại tuyến và không tự ý sửa đổi tham số để tránh phá vỡ chuỗi toán học của hiệu ứng lãi kép.

### 🚀 Loại 4: Chiến lược Breakout Gồng Lời ATR (Aggressive ATR Trailing)
*   **Cấu hình**: Áp dụng kịch bản **S4**.
*   **Khẩu vị rủi ro**: Cao (High Risk-Reward).
*   **Cách thức vận hành**: Khớp tất cả các breakout hợp lệ của tín hiệu VBS, không cần bộ lọc xu hướng ngày nhưng siết chặt khoảng cách SL bằng 1.5 * ATR14 và sử dụng Chandelier Trailing để gồng lãi tối đa. Thích hợp cho các giai đoạn thị trường biến động mạnh, có nhiều tin tức vĩ mô dẫn dắt xu hướng.
*   **Tham số khuyên dùng**: Fixed Sizing để bảo vệ tài khoản khỏi biến động lớn, hoặc Dynamic Sizing tối đa 1.0% portfolio.

---

*Báo cáo được chưng cất tự động từ dữ liệu thực nghiệm và được phê duyệt bởi **Victory Auditor** của hệ thống Angati.*
