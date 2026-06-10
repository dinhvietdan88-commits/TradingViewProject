# 📐 ATR Risk Management Visualizer

Chúng tôi đã thiết kế và triển khai một trang công cụ trực quan hóa tham số rủi ro **ATR Risk Visualizer** vô cùng trực quan và đẹp mắt để minh họa cho phần metadata từ cảnh báo chỉ báo (Indicator Alert).

Trang trực quan hóa mới nằm tại:
[metadata_visualizer.html](file:///C:/Users/pesil/working/mj_trading/TradingViewProject/server/static/metadata_visualizer.html)

---

## 🎨 UI/UX Design Mockup

Dưới đây là thiết kế giao diện cao cấp (Glassmorphism Dark Mode) của bộ công cụ trực quan hóa này:

![ATR Risk Visualizer Mockup](file:///C:/Users/pesil/.gemini/antigravity/brain/fe439fbd-8e88-457a-bdfb-d8c2fd9c06f8/atr_risk_visualizer_mockup_1780366330224.png)

---

## 🚀 Các tính năng chính

1. **Bộ Phân Tích Metadata Tự Động (Auto Metadata Parser)**:
   - Hỗ trợ dán trực tiếp chuỗi Python Dictionary hoặc JSON từ Telegram alert:
     `{'direction': 'short', 'atr_value': '95.9298016285', 'sl': '0', 'tp': '0', 'rrr_ratio': '3.5', 'sl_mode': 'ATR', 'tp_mode': 'Fixed RRR', 'trail_stop': '0'}`
   - Hệ thống tự động chuyển đổi các ký tự nháy đơn `'` thành `"` và xử lý thành JSON chuẩn để áp dụng ngay lập tức.

2. **Biểu Đồ Trade Tương Tác Vector (Interactive SVG Chart)**:
   - Trực quan hóa 3 đường giá cốt lõi: **Entry Price** (Trắng nét đứt), **Stop Loss** (Đỏ nét liền) và **Take Profit** (Xanh lá nét liền).
   - Vùng rủi ro (Risk Zone) được bôi màu đỏ mờ và vùng lợi nhuận (Reward Zone) được bôi màu xanh lá mờ.
   - Thước đo hiển thị số điểm khoảng cách và phần trăm thay đổi so với giá vào lệnh.

3. **Bảng Tính Toán Chi Tiết (Step-by-Step Math Proof)**:
   - Trình bày công thức tính toán thời gian thực theo cấu trúc:
     - **Risk (1R)** = ATR × Multiplier
     - **Stop Loss** = Price &plusmn; Risk (tùy thuộc hướng LONG/SHORT)
     - **Reward** = Risk × RRR
     - **Take Profit** = Price &mp; Reward (tùy thuộc hướng LONG/SHORT)
   - Cảnh báo trực quan nếu khoảng cách Stop Loss vượt quá giới hạn tối đa (8% đối với BTCUSDT).

4. **Điều Chỉnh Tham Số Thời Gian Thực (Real-time Sliders)**:
   - Người dùng có thể kéo thả để điều chỉnh **Entry Price**, **ATR Value**, **SL Multiplier**, và **Risk-to-Reward Ratio (RRR)** để quan sát sự thay đổi tức thì của các đường giá trên biểu đồ và tỷ lệ phần trăm tương ứng.

---

## 🛠️ Hướng dẫn kiểm tra và sử dụng

1. Đảm bảo uvicorn server đang chạy trên cổng `5000` (hoặc khởi chạy bằng `python start_server.py`).
2. Mở trình duyệt và truy cập:
   `http://localhost:5000/static/metadata_visualizer.html`
3. Dán đoạn metadata của bạn vào khung văn bản ở góc trái và nhấn nút **Parse & Apply Metadata**. Giao diện và các đường giá sẽ được cập nhật ngay lập tức.
