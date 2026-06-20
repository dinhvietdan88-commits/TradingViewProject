# 📚 Báo cáo Phân tích Chiến lược VBS (v2.1.0-7.6.3)
## ⚡ Loại 2: Chiến lược Bám đuổi Động lượng Ngắn hạn (Short-term Trend Stack) - Phân tách S3 & S5

Báo cáo này bổ sung phân tích chuyên sâu bằng cách **tách riêng biệt** hai bộ lọc của chiến lược **S3+S5 (Trend Stack)** để kiểm tra hiệu suất độc lập của từng cấu phần:
1.  **S3-only (EMA Stack - Daily):** Chỉ áp dụng lọc xu hướng khung Daily dựa trên các đường EMA xếp chồng (Giá > EMA20 > EMA50 > EMA100).
2.  **S5-only (MTF Validation - Hourly):** Chỉ áp dụng bộ lọc Daily Trend Template Score >= 5 kết hợp với Hourly EMA Stack (EMA20 > EMA50 > EMA200).

Thử nghiệm chạy trên **1,015 tín hiệu** từ ngày **30-05-2026 đến 17-06-2026** (cặp giao dịch `BTCUSDT`), phí giao dịch **0.05% per trade** (0.1% round-trip).

---

## 📊 1. Bảng đối chiếu hiệu suất phân tách S3 vs S5

Dưới đây là kết quả chi tiết của việc tách riêng S3 và S5, đối chiếu giữa cấu hình **Baseline** và cấu hình tích hợp bộ lọc **SuperTrend v1.3 `ST(7, 3.5)` trên khung 1H**:

### A. Phương án phân bổ vốn Cố định (Fixed Sizing - $100 per trade)

| Kịch bản | Bộ lọc | Tổng lệnh | Thắng / Thua | Tỷ lệ thắng (WR) | Net PnL (USDT) | Tổng phí (USDT) | Profit Factor (PF) | Max DD (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **S3+S5 (Joint)** | Baseline | 241 | 96 / 145 | 39.83% | -541.88 | 23.84 | 0.44 | - |
| **S3+S5 (Joint)** | ST v1.3 Filter | 232 | 96 / 136 | 41.38% | -480.06 | 22.97 | 0.47 | - |
| **S3-only** | Baseline | 441 | 117 / 324 | 26.53% | **-1,138.74** | 43.55 | 0.28 | 15.09% |
| **S3-only** | ST v1.3 Filter | 250 | 96 / 154 | 38.40% | **-495.22** | 24.76 | 0.46 | 8.81% |
| **S5-only** | Baseline | 289 | 144 / 145 | 49.83% | **+113.93** | 28.97 | 1.12 | 8.71% |
| **S5-only** | ST v1.3 Filter | 280 | 144 / 136 | **51.43%** | **+175.75** | 28.10 | **1.19** | **8.15%** |

### B. Phương án phân bổ vốn Động (Dynamic Sizing - Risk 2% per trade)

| Kịch bản | Bộ lọc | Tổng lệnh | Thắng / Thua | Tỷ lệ thắng (WR) | Net PnL (USDT) | Tổng phí (USDT) | Profit Factor (PF) | Max DD (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **S3+S5 (Joint)** | Baseline | 241 | 96 / 145 | 39.83% | -7,500.44 | 991.84 | 0.71 | - |
| **S3+S5 (Joint)** | ST v1.3 Filter | 232 | 96 / 136 | 41.38% | -7,078.58 | 985.29 | 0.72 | - |
| **S3-only** | Baseline | 441 | 117 / 324 | 26.53% | **-9,442.57** | 1,054.46 | 0.66 | 98.10% |
| **S3-only** | ST v1.3 Filter | 250 | 96 / 154 | 38.40% | **-7,187.59** | 998.04 | 0.72 | 90.15% |
| **S5-only** | Baseline | 289 | 144 / 145 | 49.83% | **+2,497.80** | 5,277.67 | 1.02 | 91.25% |
| **S5-only** | ST v1.3 Filter | 280 | 144 / 136 | **51.43%** | **+4,607.11** | 5,244.90 | **1.04** | **89.77%** |

---

## 🔍 2. Đánh giá Chuyên sâu & Phân tích Đứt gãy Kiến trúc

Việc phân tách hai bộ lọc S3 và S5 đã phơi bày một phát hiện kiến trúc cực kỳ quan trọng:

### ❌ S3 (Daily EMA Stack) là Bộ lọc Độc hại (Toxic Filter)
*   **Hiệu suất thảm hại:** S3-only Baseline đạt tỷ lệ thắng cực thấp chỉ **26.53%**, kéo tài khoản âm nặng nề (**-1,138.74 USDT** đối với Fixed Sizing và cháy gần hết tài khoản **-9,442.57 USDT** đối với Dynamic Sizing do chuỗi lệnh thua liên tiếp).
*   **Lý do kỹ thuật:** Lớp lọc S3 yêu cầu sự sắp xếp hoàn chỉnh của cụm EMA Daily (EMA20 > EMA50 > EMA100). Trong thực tế giao dịch động lượng ngắn hạn, khi cụm EMA khung ngày đạt sự xếp chồng đồng dạng hoàn hảo này, thị trường thường đã đi được một sóng tăng/giảm rất dài và bắt đầu suy kiệt động lượng (late entries). Vào lệnh tại thời điểm này tương tự như "mua đỉnh ngắn hạn", dẫn đến tỷ lệ dính Stop Loss cực cao.

### 🏆 S5 (Hourly EMA Stack + Daily Trend Score) là Lớp lọc Chất lượng
*   **Hiệu suất vượt mong đợi:** S5-only Baseline đạt tỷ lệ thắng tiệm cận **50%** và mang lại **lợi nhuận dương** ngay cả khi không có bộ lọc bổ trợ. Khi tích hợp thêm bộ lọc xu hướng **SuperTrend v1.3 `ST(7, 3.5)` khung 1H**, hiệu suất được cải thiện mạnh mẽ:
    *   Tỷ lệ thắng đạt **51.43%** (+1.60%).
    *   Lợi nhuận ròng (Net PnL) đạt **+175.75 USDT** (Fixed) và **+4,607.11 USDT** (Dynamic).
    *   Profit Factor tăng lên **1.19** (Fixed) và **1.04** (Dynamic).
    *   Sự kết hợp này mang lại lợi nhuận vượt trội so với phiên bản gộp S3+S5 ban đầu (vốn bị kéo âm vì S3).
*   **Lý do kỹ thuật:** S5 bỏ qua yêu cầu xếp chồng EMA chậm trên khung ngày, thay vào đó chỉ yêu cầu khung ngày có cấu trúc xu hướng tối thiểu (Trend Template Score >= 5, linh hoạt hơn) và dùng cụm EMA khung 1H (EMA20 > EMA50 > EMA200) để xác thực độ nhạy điểm vào lệnh. Điều này giúp hệ thống bắt được các điểm điều chỉnh kỹ thuật ngắn hạn (pullbacks) trong xu hướng lớn tốt hơn nhiều.

---

## 🧭 3. PHƯƠNG ÁN HÀNH ĐỘNG MỚI (NEW ACTION PLAN)

1.  **Hủy bỏ hoàn toàn bộ lọc S3:** Loại bỏ vĩnh viễn cấu hình xếp chồng EMA Daily khỏi hệ thống điều hướng tín hiệu.
2.  **Tách và nâng cấp cấu hình S5-only:** Đưa **S5-only kết hợp SuperTrend v1.3 `ST(7, 3.5) 1H`** vào danh mục Chiến lược Động lượng Ngắn hạn tiềm năng.
3.  **Khuyến nghị triển khai:**
    *   Sử dụng **S5-only + ST v1.3** làm nhân tố bổ trợ xu hướng.
    *   Khảo sát tối ưu hóa thêm tham số SL/TP dựa trên ATR cho riêng S5-only để giảm thiểu Drawdown tối đa của Dynamic Sizing (hiện tại DD của Dynamic 2% vẫn đang cao ở mức ~89.77% do phân bổ rủi ro quá lớn khi SL cách xa).
