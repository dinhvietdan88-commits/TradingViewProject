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

*Báo cáo được tạo tự động bởi walk_forward_runner.py vào 2026-06-20 20:30:33*
