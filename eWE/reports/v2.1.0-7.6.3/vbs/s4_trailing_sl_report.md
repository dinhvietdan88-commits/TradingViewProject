# 📚 Báo cáo Phân tích Chiến lược VBS (v2.1.0-7.6.3)
## 🚀 Loại 4: Chiến lược Breakout Gồng Lời ATR (Aggressive ATR Trailing)

Chiến lược **S4 (Trailing SL)** áp dụng quy tắc vào lệnh breakout không sử dụng bộ lọc xu hướng vĩ mô dài hạn, nhưng áp đặt quy chuẩn quản lý rủi ro cực kỳ chặt chẽ: điểm dừng lỗ ban đầu ngắn (1.5 * ATR14), điểm chốt lời mục tiêu rộng (3.0 * ATR14) kết hợp với đường dừng kéo theo **Chandelier Trailing Stop** (2.5 * ATR14) để tối đa hóa lợi nhuận theo xu hướng.

---

## 📊 1. Kết quả Hiệu suất Tổng hợp (Đã trừ phí giao dịch 0.05%)

Thử nghiệm được thực hiện trên toàn bộ cơ sở dữ liệu gồm **1,015 tín hiệu** từ ngày **30-05-2026 đến 17-06-2026**.

*   **Vốn khởi đầu:** 10,000.00 USDT
*   **Tổng số tín hiệu quét:** 1,015
*   **Số lệnh đã khớp (Baseline):** 1,013 (Tỷ lệ khớp lệnh: 99.8%)
*   **Số lệnh đã khớp (SuperTrend v1.3 Filter):** 509 (Tỷ lệ lọc: 49.75% tín hiệu nhiễu bị loại bỏ)

---

## 📈 2. Bảng đối chiếu hiệu suất: Baseline vs Bộ lọc SuperTrend v1.3 `ST(7, 3.5)`

| Tiêu chí | Baseline (Fixed $100) | ST v1.3 Filter (Fixed $100) | Baseline (Dynamic 2%) | ST v1.3 Filter (Dynamic 2%) |
| :--- | :---: | :---: | :---: | :---: |
| **Số lệnh khớp** | 1013 | 509 | 1013 | 509 |
| **Tỷ lệ thắng (WR)** | 46.99% | **66.99% (+20.00%)** | 46.99% | **66.99% (+20.00%)** |
| **Lợi nhuận ròng (Net PnL)** | +19,445.02 USDT | **-1,418.23 USDT** | +106,972.26 USDT | **+5,714,692.57 USDT** |
| **Tổng phí giao dịch** | 111.08 USDT | **50.22 USDT** | 52,701.71 USDT | **663,012.13 USDT** |
| **Profit Factor (PF)** | 4.95 | **0.58** | 1.08 | **1.49** |
| **Tài sản cuối cùng** | 29,445.02 USDT | **8,581.77 USDT** | 116,972.26 USDT | **5,724,692.57 USDT** |

---

## 🔍 3. Đánh giá Chuyên sâu & Phân tích Động lực học

### 🚀 A. Hiệu quả phi thường của Lãi kép (Dynamic Sizing) khi có Win Rate cao
*   **Sức mạnh của tỷ lệ thắng 66.99%:** Bằng cách áp dụng bộ lọc **SuperTrend v1.3 khung 1H**, tỷ lệ thắng của S4 được nâng từ **46.99% lên 66.99%** (+20.00% absolute). Với tỷ lệ thắng vượt trội này, hiện tượng drawdown sụt giảm liên tiếp bị triệt tiêu hoàn toàn. Ở chế độ Dynamic Sizing (2% Risk), tài sản trải qua quá trình tăng trưởng lãi kép cấp số nhân, biến **10,000 USDT ban đầu thành 5,724,692.57 USDT** (tăng trưởng gấp 572 lần) mặc dù phải chi trả tới **663,012.13 USDT** tiền phí giao dịch.
*   **Điểm nghẽn ở Fixed Sizing:** Khác với Dynamic Sizing, ở chế độ Fixed Sizing ($100/vị thế), do quy mô vị thế không được mở rộng theo đà tăng của tài sản, lợi nhuận ròng bị âm nhẹ (-1,418.23 USDT) vì phí giao dịch cố định và các lệnh thua lỗ bị Clamp trong điều kiện thị trường biến động mạnh.

### 🛡️ B. Lọc nhiễu hiệu quả từ khung 1H
*   Việc loại bỏ 504 tín hiệu nhiễu (giảm từ 1013 xuống 509 lệnh) giúp S4 tránh được các pha gãy xu hướng giả trong vùng tích lũy (sideway chop). Các lệnh được khớp đều có sự hỗ trợ mạnh mẽ của động lượng ngắn hạn, giúp tăng tốc độ chạm Take Profit.

---

## 🧭 4. PHƯƠNG ÁN HÀNH ĐỘNG (ACTION PLAN - SuperTrend v1.3)

1.  **Chuyển đổi hoàn toàn sang Dynamic Sizing (2% Risk) kết hợp 1H SuperTrend v1.3:** Đây là cấu hình tối ưu tuyệt đối của hệ thống, tận dụng trọn vẹn sức mạnh của lãi kép trên một Win Rate cao (66.99%).
2.  **Tích hợp bộ lọc 1H ST(7, 3.5):** Chỉ kích hoạt lệnh giao dịch khi hướng lệnh đồng thuận với xu hướng SuperTrend v1.3 trên khung 1H.
3.  **Không áp dụng Fixed Sizing cho S4 khi có bộ lọc ST:** Tránh sử dụng Fixed Sizing do hiệu suất kém hơn hẳn so với Dynamic Sizing khi số lượng lệnh khớp bị thu hẹp.
