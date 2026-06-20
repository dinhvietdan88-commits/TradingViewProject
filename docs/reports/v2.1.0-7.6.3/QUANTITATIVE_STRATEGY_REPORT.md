# Báo Cáo Phân Tích Định Lượng Chiến Lược (Phần A)

Báo cáo này chứa các kết quả tính toán và mô phỏng thực tế của các kỹ thuật định lượng nâng cao: **Mô phỏng Monte Carlo**, **Kiểm thử độ nhạy Trượt giá**, và **Walk-Forward Analysis**.

---

## 1. Mô Phỏng Monte Carlo (Monte Carlo Simulations)

Phân tích trên **370 lệnh giao dịch** được tạo ra từ kịch bản S6/S1:

### A. Sequence Shuffling (Type I) - 1,000 Chu kỳ mô phỏng
Đánh giá mức độ ảnh hưởng của thứ tự lệnh đến Drawdown tài khoản (vốn ban đầu 10,000 USDT, rủi ro 2%):

- **Equity Trung bình cuối kỳ**: **2597.62 USDT**
- **Equity Trung vị**: **2597.62 USDT**
- **Mức sụt giảm vốn lớn nhất (Max Drawdown) Trung bình**: **75.29%**
- **Max Drawdown tệ nhất (95th Percentile)**: **77.24%**
- **Xác suất cháy tài khoản (Ruin Probability - giảm 50% vốn)**: **100.00%**

### B. Outlier Removal (Type II) - Loại bỏ 10% lệnh thắng tốt nhất
Đánh giá mức độ phụ thuộc của chiến lược vào các lệnh thắng lớn (Outliers):

- **Kỳ vọng lợi nhuận ban đầu**: **-1.41%** per trade
- **Kỳ vọng lợi nhuận sau khi bỏ 10% lệnh thắng tốt nhất**: **-2.61%** per trade
- **Kết luận khả năng sinh lời**: ⚠️ CẢNH BÁO - Chiến lược phụ thuộc quá mức vào một vài lệnh thắng lớn để sinh lời.

---

## 2. Kiểm Thử Độ Nhạy Trượt Giá (Slippage Sensitivity Analysis)

Phân tích hiệu suất giao dịch dưới các mức trượt giá (Slippage) từ 0% đến 0.5%:

| Slippage (%) | Tổng số lệnh | Net P&L (%) | Profit Factor | Trạng thái |
| :---: | :---: | :---: | :---: | :--- |
| 0.00% | 100 | +330.18% | 1.79 | 🟢 TỐT |
| 5.00% | 100 | +321.30% | 1.76 | 🟢 TỐT |
| 10.00% | 100 | +312.43% | 1.73 | 🟢 TỐT |
| 20.00% | 100 | +294.68% | 1.68 | 🟢 TỐT |
| 50.00% | 100 | +241.45% | 1.52 | 🟢 TỐT |

*Nhận xét*: Khi trượt giá tăng lên mức 0.50%, Profit Factor giảm về **1.52**. Hệ thống cần kiểm soát độ trễ giao dịch < 500ms để giữ trượt giá thực tế dưới 0.10%.

---

## 3. Walk-Forward Analysis (WFA) Summary

# Walk-Forward Analysis (WFA) Report

Tài liệu kiểm định Walk-Forward cuốn chiếu đánh giá khả năng thích ứng của các tham số tối ưu hóa trên dữ liệu thực tế (Out-of-Sample).

## 1. Kết Quả Từng Cửa Sổ (Rolling Windows Breakdown)

| Window | In-Sample Range | Out-of-Sample Range | Optimal Parameters | IS Profit Factor | OOS Profit Factor | WFE (%) |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: |
| 1 | Signal 0 - 250 | Signal 250 - 350 | SL: 1.5x ATR, Min TT: 5 | inf | inf | 100.0% |
| 2 | Signal 100 - 350 | Signal 350 - 450 | SL: 1.5x ATR, Min TT: 5 | inf | 0.24 | 0.0% |
| 3 | Signal 200 - 450 | Signal 450 - 550 | SL: 2.0x ATR, Min TT: 5 | 3.23 | 0.00 | 0.0% |
| 4 | Signal 300 - 550 | Signal 550 - 650 | SL: 1.5x ATR, Min TT: 5 | 0.62 | 0.00 | 0.0% |

---

## 2. Kết Luận Đánh Giá (Final Verdict)
- **Walk-Forward Efficiency (WFE) Trung bình**: **25.00%**
- **Đánh giá độ tin cậy**: ⚠️ CẦN TỐI ƯU HÓA LẠI (WFE < 60%) - Có dấu hiệu Overfitting khi đổi chế độ nến.

*Báo cáo được tạo tự động bởi walk_forward_runner.py vào 2026-06-20 21:10:09*

