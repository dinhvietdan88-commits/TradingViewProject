# Khai thác triệt để Hệ thống Báo cáo Test & Pine Scripts (Strategy Genealogy)

Dự án hiện đang sở hữu một kho tàng dữ liệu backtest khổng lồ và một chuỗi tiến hóa mã nguồn Pine Script (từ V10 đến V16 cho dòng MIS, và V1.000 đến V1.005 cho dòng MTT). Việc "khai thác triệt để" tài nguyên này không chỉ là lập chỉ mục, mà là **Rút trích Lợi thế Giao dịch (Winning Edge)** và tìm ra công thức tối ưu nhất để đưa vào hệ thống Auto-Trading.

## User Review Required
> [!IMPORTANT]
> Kế hoạch này sẽ tổng hợp và đánh giá lại toàn bộ các báo cáo backtest cũ. Vui lòng xác nhận xem mục tiêu cuối cùng của bạn là:
> 1. Chỉ tạo ra tài liệu tổng hợp (Documentation/Genealogy)?
> 2. Hay muốn trích xuất bộ tham số chiến thắng (Winning Parameters) để tinh chỉnh mã Pine Script cuối cùng (v2) và tích hợp vào hệ thống webhook hiện tại?

## Proposed Changes

### 1. Phân tích & Lập bản đồ Tiến hóa (Strategy Genealogy)
Dòng đời của các chiến lược đã phân nhánh rất nhiều. Chúng ta sẽ đọc tất cả các file trong `pine/v1/` và `docs/reports/` để nối kết chúng lại:

- **MIS (Multi-Indicator Strategy) Evolution:**
  - `v10` → `v10_ADX` → `v11A` → `v12B` (SEPA full test) → `v13C` → `v15` → `v16`.
  - Kết nối với các báo cáo như `MIS_v10_subexperiments_AB.md`, `MIS_v12B_SEPA_full_test.md`, v.v.
- **MTT (Minervini Trend Template) Evolution:**
  - `v1.000` → `v1.004` (A/B) → `v1.005` (MA tuning).
  - Khảo sát sự khác biệt giữa `v1.A004`, `v1.B004`, `v1.A005`, `v1.B005`.

#### [NEW] `docs/reports/STRATEGY_GENEALOGY.md`
Tạo một ma trận phả hệ chiến lược, ghi rõ:
- **Phiên bản (Version)**
- **Điểm mới cốt lõi (Core Feature Added)** (VD: thêm ADX filter, tối ưu MA)
- **Hiệu suất (Win Rate, Drawdown, Profit Factor)** (Trích xuất từ reports)
- **Bài học (Lessons Learned)** tại sao phiên bản đó bị loại bỏ hoặc được nâng cấp.

### 2. Rút trích "Winning Edge" (Tham số Tối ưu)
Đọc kỹ các báo cáo tổng hợp như `strategy_MTT_macro_TF_full_matrix_report.md` và `timeframe_comparison_report_MIS_v1.md`.
- Trích xuất khung thời gian (Timeframe) tốt nhất (VD: báo cáo `timeframe_comparison_report_MIS_v1.md` đã chỉ rõ 1h thắng tuyệt đối, 4h thất bại).
- Trích xuất các tham số Stop-loss, Take-profit, ATR multipliers tối ưu nhất.

#### [NEW] `docs/knowledge/trading_wizard/OPTIMIZED_PARAMETERS_MATRIX.md`
Tập hợp toàn bộ các thông số "Vàng" đã được kiểm chứng qua backtest để làm nguồn dữ liệu tĩnh cho hệ thống cấu hình webhook hoặc server.

### 3. Hợp nhất Mã nguồn (V2 Pine Script Refactoring)
Sau khi có cái nhìn toàn cảnh, chúng ta sẽ xem xét file `pine/v2/minervini_strategy.pine` để đảm bảo nó đã kế thừa TẤT CẢ các điểm mạnh nhất từ v16 (MIS) và v1.005 (MTT), đồng thời lược bỏ các code thừa.

## Verification Plan

### Manual Verification
- Đọc lướt (view_file) qua ít nhất 4 báo cáo backtest lớn nhất và 4 file pine-script mang tính bước ngoặt (như v12B, v16, v1.005).
- Đảm bảo `STRATEGY_GENEALOGY.md` phản ánh đúng dữ liệu (không hallucinate số liệu PnL hay Win Rate).
- Hỏi ý kiến user xem bộ thông số trích xuất đã chuẩn xác để đưa vào production chưa.
