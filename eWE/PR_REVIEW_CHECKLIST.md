# TradingView Project - PR Review Checklist

Trước khi merge bất kỳ Pull Request nào, Reviewer và Developer bắt buộc phải kiểm tra các tiêu chuẩn sau để đảm bảo an toàn cho vốn giao dịch:

## 1. Safety & Security (An toàn Vốn & Bảo mật)
- [ ] **Lộ lọt API Keys:** Đảm bảo không có dòng code nào hardcode `BINANCE_API_KEY` hoặc `TELEGRAM_TOKEN`. Mọi thứ phải dùng `config.py` và `os.getenv`.
- [ ] **Circuit Breakers:** Bất kỳ chiến lược giao dịch mới nào cũng phải có Circuit Breaker (vd: Timeframe Filter 1H).
- [ ] **Khối lượng (Size):** Logic đặt lệnh đã kiểm tra kỹ tỷ lệ % vốn hoặc giá trị USDT (quoteQty) chưa? Tránh lỗi fat-finger.
- [ ] **Dry-Run:** Tính năng Binance Dry-Run (`BINANCE_DRY_RUN=true`) vẫn hoạt động tốt, không bị bypass bởi các chỉnh sửa mới.

## 2. Testing (Kiểm thử)
- [ ] **Unit Tests:** Mọi hàm xử lý logic mới trong `analysis.py` hoặc `database.py` phải có Unit Test đi kèm.
- [ ] **E2E Tests:** Kịch bản Webhook mới đã được thêm vào `tests/e2e/test_end_to_end.py` và dùng Mock Data chưa?
- [ ] **QA Check:** Đã chạy `server/scripts/run_qa.bat` và `run_tests.bat` 100% PASS chưa?

## 3. Code Quality (Chất lượng mã nguồn)
- [ ] Linter (Ruff) và Type Checker (Mypy) không báo lỗi.
- [ ] Tên biến rõ ràng, có docstring cho các functions phức tạp.
- [ ] Không sử dụng `print` để log. Bắt buộc dùng hệ thống `logging` của server.

## 4. Documentation (Tài liệu)
- [ ] Các cập nhật về Payload JSON đã được ghi vào `docs/TRADINGVIEW_ALERT_SETUP.md` chưa?
- [ ] Các cảnh báo về rủi ro (nếu có) đã được notes rõ ràng.
