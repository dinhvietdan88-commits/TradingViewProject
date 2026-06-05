# Thiết Kế Tương Tác Telegram Bot — Minervini AI Trading Bot

Tài liệu này định nghĩa cấu trúc, quy chuẩn thiết kế UI/UX và các mẫu tin nhắn (response templates) của bot Telegram, bao gồm tin nhắn phản hồi tín hiệu và thông báo lỗi hệ thống.

---

## 🎨 Nguyên Tắc Thiết Kế Trực Quan (Telegram UX Principles)

1. **Phân cấp thông tin (Information Hierarchy):** Sử dụng các biểu tượng (emoji) làm bullet points chỉ dẫn nhanh, in đậm (`bold`) tiêu đề chính và các thông số quan trọng (giá, mã giao dịch, trạng thái).
2. **Hạn chế ngập lụt thông tin:** Độ dài tối ưu của tin nhắn không quá 250 từ. Các thông số phụ được đưa vào dạng codeblock để thu gọn diện tích hiển thị.
3. **Phản hồi tương tác (Actionable Inline Buttons):** Luôn đi kèm nút bấm trực quan phía dưới tin nhắn để user ra quyết định tức thì (Duyệt lệnh, Khởi động lại service, Xem chi tiết log) mà không cần gõ lệnh.

---

## 💬 1. Khung Thiết Kế Tin Nhắn Phản Hồi (Response Templates)

### 📈 Mẫu A: Tín Hiệu Giao Dịch & Khuyến Nghị AI (Buy/Sell Signal & AI RAG)
Dùng để thông báo khi TradingView gửi alert và AI hoàn thành phân tích độ khớp với tiêu chí SEPA của Mark Minervini.

#### 📱 Giao diện hiển thị trực quan (Rendered Preview)
> 🔔 **TÍN HIỆU GIAO DỊCH CẦN DUYỆT (PENDING APPROVAL)**
> ──────────────────────────────
> 🪙 **Mã giao dịch:** #BTCUSDT
> 🚀 **Hành động:** `MUA (BUY)` | **Giá hiện tại:** `67,250.50`
> 📊 **Khung thời gian:** `1D`
>
> ⚙️ **ĐÁNH GIÁ TIÊU CHÍ MINERVINI SEPA:**
> • Trend Template: **8/8 (Stage 2 Uptrend)** ⭐
> • Volatility Contraction (VCP): **Đã xác nhận**
> • Khối lượng (Volume): `Gấp 1.8 lần trung bình 20 phiên`
>
> 🧠 **KHUYẾN NGHỊ AI (Claude 4.5 Sonnet RAG):**
> 🟢 *Chất lượng tín hiệu: Rất Mạnh.* Điểm mua Pivot breakout khỏi mẫu hình VCP hẹp (3 đợt thu hẹp) trùng khớp hoàn toàn với xu hướng Stage 2. Rủi ro thị trường chung thấp.
>
> 🛑 **Quản lý rủi ro (Risk Limits):**
> • Stop-Loss (Cắt lỗ): `62,540.00 (-7.0%)`
> • Take-Profit (Chốt lời gợi ý): `80,700.00 (+20.0%)`
> ──────────────────────────────
> *[ 🟢 Duyệt Lệnh (Confirm) ]*   *[ 🔴 Bỏ Qua (Reject) ]*
> *[ 🔍 Xem Chi Tiết Chart ]*

#### 📝 Mã nguồn Template (HTML Format)
```html
🔔 <b>TÍN HIỆU GIAO DỊCH CẦN DUYỆT (PENDING APPROVAL)</b>
──────────────────────────────
🪙 <b>Mã giao dịch:</b> #{symbol}
🚀 <b>Hành động:</b> <code>{action}</code> | <b>Giá hiện tại:</b> <code>{price}</code>
📊 <b>Khung thời gian:</b> <code>{timeframe}</code>

⚙️ <b>ĐÁNH GIÁ TIÊU CHÍ MINERVINI SEPA:</b>
• Trend Template: <b>{tt_score}/8 ({stage})</b>
• Volatility Contraction (VCP): <b>{vcp_status}</b>
• Khối lượng (Volume): <code>{volume_ratio}x avg</code>

🧠 <b>KHUYẾN NGHỊ AI ({ai_provider}):</b>
{ai_advice}

🛑 <b>Quản lý rủi ro (Risk Limits):</b>
• Stop-Loss: <code>{stop_loss} ({sl_pct}%)</code>
• Take-Profit: <code>{take_profit} ({tp_pct}%)</code>
──────────────────────────────
```
* **Inline Keyboards Configuration:**
  * Row 1: `[ 🟢 Duyệt Lệnh | callback_data="exec_trade:{id}" ]` , `[ 🔴 Bỏ Qua | callback_data="reject_trade:{id}" ]`
  * Row 2: `[ 🔍 Xem Chi Tiết Chart | callback_data="view_chart:{symbol}" ]`

---

### 📋 Mẫu B: Kết Quả Quét Watchlist Cục Bộ (`/scan`)
Dùng khi user yêu cầu bot quét nhanh trạng thái xu hướng của danh sách cổ phiếu/crypto đang theo dõi.

#### 📱 Giao diện hiển thị trực quan (Rendered Preview)
> 📊 **BÁO CÁO QUÉT THỊ TRƯỜNG (MARKET WATCHLIST SCAN)**
> ──────────────────────────────
> ⏱️ **Thời gian quét:** `16:32:00 (UTC+7)`
> 🎯 **Trạng thái xu hướng các mã đang theo dõi:**
>
> 1. ⭐ **BTCUSDT** — **Stage 2** (Score 8/8)
>    • VCP: Co thắt 2.1% ATR. Điểm Pivot: `68,100`.
> 2. 🟢 **ETHUSDT** — **Stage 1/2** (Score 6/8)
>    • Xu hướng tăng đang hình thành, Vol kiệt.
> 3. 🟡 **SOLUSDT** — **Stage 1** (Score 4/8)
>    • Đang tích lũy đi ngang trong hộp Base.
> 4. 🔴 **NVDA** — **LỖI KẾT NỐI**
>    • `HTTP 400 Bad Request on Binance (Stock Symbol)`
> ──────────────────────────────
> *[ 🔄 Quét Lại (Rescan) ]*   *[ ⚙️ Sửa Watchlist ]*

#### 📝 Mã nguồn Template (HTML Format)
```html
📊 <b>BÁO CÁO QUÉT THỊ TRƯỜNG (MARKET WATCHLIST SCAN)</b>
──────────────────────────────
⏱️ <b>Thời gian quét:</b> <code>{scan_time}</code>
🎯 <b>Trạng thái xu hướng các mã đang theo dõi:</b>

{scan_results_list}
──────────────────────────────
```

---

## 🚨 2. Khung Nhận Phản Ánh Lỗi Ghi Nhận (Incident & Error Report Alerts)

Để tránh tình trạng "alert fatigue" (ngập lụt thông báo), thông báo lỗi chỉ kích hoạt khi có sự cố ảnh hưởng tới Protected Core hoặc ngắt luồng lệnh (CDP sập, sập API kết nối sàn, OOM).

### 🔴 Mẫu C: Sự Cố Nghiêm Trọng (Critical Server Outages)

#### 📱 Giao diện hiển thị trực quan (Rendered Preview)
> 🔴 **CẢNH BÁO: SỰ CỐ HỆ THỐNG PHÂN PHỐI (CRITICAL OUTAGE)**
> ──────────────────────────────
> 💻 **Máy chủ:** `Local Windows B (Execution Vault)`
> 🏷️ **Mã sự cố:** #ERR-CDP-2620
> 📌 **Dịch vụ gặp lỗi:** `TradingView CDP Connector`
>
> 🔍 **Triệu chứng lỗi (Traceback Preview):**
> ```text
> RuntimeError: Failed to connect to TradingView CDP on port 9222.
> Connection refused by host 127.0.0.1:9222 (Process TV not running?)
> ```
>
> 🩺 **Tự động chẩn đoán & Khắc phục:**
> ⚠️ Phát hiện TradingView Desktop MSIX đã bị đóng hoặc port 9222 bị chiếm dụng bởi tiến trình Chrome khác.
>
> 🛠️ **Hành động nhanh (Quick Actions):**
> ──────────────────────────────
> *[ ⚡ Khởi Chạy Lại TV Desktop ]*
> *[ 🔄 Khởi Động Lại Server ]*   *[ 📂 Xem Logs Mới Nhất ]*

#### 📝 Mã nguồn Template (HTML Format)
```html
🔴 <b>CẢNH BÁO: SỰ CỐ HỆ THỐNG PHÂN PHỐI (CRITICAL OUTAGE)</b>
──────────────────────────────
💻 <b>Máy chủ:</b> <code>{server_name}</code>
🏷️ <b>Mã sự cố:</b> #{error_code}
📌 <b>Dịch vụ gặp lỗi:</b> <code>{service_name}</code>

🔍 <b>Triệu chứng lỗi (Traceback Preview):</b>
<pre>{error_traceback}</pre>

🩺 <b>Tự động chẩn đoán & Khắc phục:</b>
⚠️ {diagnostic_recommendation}

🛠️ <b>Hành động nhanh (Quick Actions):</b>
──────────────────────────────
```
* **Inline Keyboards Configuration:**
  * Row 1: `[ ⚡ Khởi Chạy Lại TV Desktop | callback_data="action:fix_tv" ]`
  * Row 2: `[ 🔄 Khởi Động Lại Server | callback_data="action:restart_server" ]` , `[ 📂 Xem Logs | callback_data="action:view_logs" ]`

---

### 🟡 Mẫu D: Cảnh Báo Sàn Giao Dịch (API & Execution Warnings)

#### 📱 Giao diện hiển thị trực quan (Rendered Preview)
> 🟡 **CẢNH BÁO: LỖI THỰC THI GIAO DỊCH (EXECUTION WARNING)**
> ──────────────────────────────
> 🪙 **Mã giao dịch:** #SOLUSDT
> 📢 **Sàn giao dịch:** `Binance (Testnet)`
> 🚨 **Vấn đề:** `API Rate Limit / Connection Timeout`
>
> 📋 **Thông tin chi tiết:**
> ```text
> http_status = 429 Too Many Requests
> Retry-After header = 60s
> ```
> 🩺 **Hướng giải quyết:**
> Hệ thống đang tự động kích hoạt **Circuit Breaker** (Ngắt mạch tạm thời). Tạm ngừng gửi yêu cầu đặt lệnh mới lên sàn Binance trong 60 giây tiếp theo.
> ──────────────────────────────
> *[ 🔄 Thử Lại Ngay ]*   *[ 🛡️ Bỏ Kích Hoạt Circuit Breaker ]*

#### 📝 Mã nguồn Template (HTML Format)
```html
🟡 <b>CẢNH BÁO: LỖI THỰC THI GIAO DỊCH (EXECUTION WARNING)</b>
──────────────────────────────
🪙 <b>Mã giao dịch:</b> #{symbol}
📢 <b>Sàn giao dịch:</b> <code>{exchange}</code>
🚨 <b>Vấn đề:</b> <code>{warning_detail}</code>

📋 <b>Thông tin chi tiết:</b>
<pre>{details_block}</pre>
🩺 <b>Hướng giải quyết:</b>
{fallback_action_desc}
──────────────────────────────
```
* **Inline Keyboards Configuration:**
  * Row 1: `[ 🔄 Thử Lại Ngay | callback_data="action:retry_trade:{trade_id}" ]`
  * Row 2: `[ 🛡️ Bỏ CB | callback_data="action:disable_cb:{exchange}" ]`
