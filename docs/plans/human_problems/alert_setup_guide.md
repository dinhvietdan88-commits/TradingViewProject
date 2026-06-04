# 🎯 Hướng Dẫn Thiết Lập Alert: A007+MIS V2 → Production

## Tổng Quan 5 Scripts Trên Chart (BTCUSDT 5m)

Dưới đây là bản đồ phân tích toàn bộ 5 scripts đang chạy trên Chart của bạn:

| # | Tên Script | Loại | Có Alert? | Last Fired | Trùng lặp? |
|---|-----------|------|-----------|------------|------------|
| 1 | **A007+MIS V2** (Auto Paper) | Strategy | ✅ `MIS-Auto` | ❌ `null` | 🔴 **Trùng 80%** với #4 |
| 2 | **MIS(A7-01B.V3) Webhook** | Indicator | ✅ `Test04` | ✅ 04/06 07:05 | 🟡 Trùng phần MIS |
| 3 | **SuperTrend Flip Webhook** | Indicator | ✅ `ST Flip` | ✅ 04/06 05:55 | 🟢 Độc lập |
| 4 | **A007 FWD (ADX25+Trail)** | Strategy | ❌ Không | — | 🔴 **Trùng 80%** với #1 |
| 5 | **A007+MIS V1** (Auto Paper) | Strategy | ✅ `Test01` | ✅ 04/06 05:15 | 🔴 **Trùng 95%** với #1 |

---

## 🔴 Phân Tích Trùng Lặp Chi Tiết

### Nhóm A: Lõi A007 (MA Crossover + ADX Regime)
Scripts #1, #4, #5 **đều dùng chung lõi logic A.007**:
- Điều kiện Long: `FastMA > MedMA > SlowMA` (Bull Zone) + ADX > 20 (Trending)
- Điều kiện Short: RSI Exhaustion + MA Breakdown

**Khác biệt duy nhất:**
- **V1 (#5)**: Không có Partial TP, không có Short S1+S2
- **V2 (#1)**: Có Partial TP @ +1R (50% close) + Tight Trail + Short S1+S2
- **FWD (#4)**: Fork riêng (ADX25 + Trail), không cài Alert

> [!CAUTION]
> Nếu cả V1 (#5) và V2 (#1) cùng bắn Alert, Server sẽ nhận **2 lệnh BUY trùng** cho cùng 1 cơ hội. Trade Engine sẽ loạn (duplicate order hoặc reject).

### Nhóm B: Lõi MIS (EMA20>50>200 + RSI + MACD Cross + Volume)
Scripts #1 và #2 **đều chứa logic MIS**, nhưng:
- **#1 (Strategy)**: MIS là **điều kiện phụ** (kết hợp với A.007 qua `require_both = true`)
- **#2 (Indicator)**: MIS là **lõi chính**, có tính thêm Confidence Score, SL/TP tự động, và JSON payload chuẩn VBS

### Nhóm C: SuperTrend (Hoàn toàn độc lập)
Script #3 dùng lõi **SuperTrend Flip** với Market Regime Filter (EMA200 + ADX), **không trùng** với nhóm A hoặc B.

---

## ✅ Đề Xuất Cấu Hình Tối Ưu (Không Trùng Lặp)

Chỉ cần **2 Alerts** trên Production:

| Alert | Script | Vai trò |
|-------|--------|---------|
| **Alert 1** | A007+MIS V2 (#1) | 🎯 Main Engine — Long/Short tự động |
| **Alert 2** | SuperTrend Flip (#3) | 🛡️ Confirmation — Tín hiệu phụ trợ |

**Scripts cần TẮT ALERT (giữ Visual trên chart):**
- ❌ `Test01: A.007 strategy V1` → Xoá Alert (trùng 95% với V2)
- ❌ `Test04: MIS(A7-01B.V3) Webhook` → Xoá Alert (MIS đã nằm trong V2)
- ❌ `ST: RSI Divergence Webhook` → Xoá Alert (chưa từng fire, lãng phí quota)

---

## 🛠 Hướng Dẫn Tạo Alert Mới Cho A007+MIS V2

### Bước 1: Xoá các Alert cũ bị trùng
Trong TradingView Desktop → **Alerts Panel** → Xoá:
- `MIS-Auto` (Alert ID: 4825815782)
- `Test01: A.007 strategy` (Alert ID: 4800166430)
- `ST: RSI Divergence Webhook` (Alert ID: 4818096360)

### Bước 2: Tạo Alert mới cho A007+MIS V2

1. **Click vào biểu đồ** → Nhấn phím tắt `Alt + A` (hoặc vào menu Alert)
2. **Condition**: Chọn `A.007 + MIS v2 Combined (Auto Paper Trading)`
3. **Trigger**: Chọn `Any alert() function call` (vì script đã tự build JSON bên trong code Pine)
4. **Expiration**: Chọn `Open-ended` hoặc đặt 30 ngày

### Bước 3: Cấu hình Webhook URL

> [!IMPORTANT]
> Bản code Production hiện tại đang map route ở `/ingest` (KHÔNG PHẢI `/webhook`).
> Khi nào CI/CD deploy bản code mới có route `/webhook`, hãy đổi lại.

**URL chính xác để dán vào ô Webhook URL:**
```
https://trading.utopiavn.co/ingest?secret=9ea7c89fbfd63a8a2bc8644e99da54fc5b2c7e098fe1d9e2b10a4e320f781a7b
```

### Bước 4: Cấu hình Message Template

Vì `A007+MIS V2` là **Strategy** và đã tự gọi `alert()` với payload JSON hoàn chỉnh bên trong Pine Script, bạn có 2 lựa chọn:

**Lựa chọn A — Để trống Message (Khuyến nghị):**
Khi chọn Trigger = `Any alert() function call`, TradingView sẽ tự động gửi đúng JSON mà script đã build. Payload mẫu sẽ trông như:
```json
{
  "secret": "7086c59c...89104",
  "action": "buy",
  "symbol": "BTCUSDT",
  "price": 63266.38,
  "quoteQty": 12.5,
  "interval": "5",
  "signal": "A007+MIS_LONG"
}
```

**Lựa chọn B — Override Message (chỉ dùng nếu chọn Trigger khác):**
```
{{strategy.order.comment}}
```
Hoặc dán JSON thủ công:
```json
{
  "secret": "9ea7c89fbfd63a8a2bc8644e99da54fc5b2c7e098fe1d9e2b10a4e320f781a7b",
  "action": "{{strategy.order.action}}",
  "symbol": "{{ticker}}",
  "price": "{{close}}",
  "quoteQty": "{{strategy.order.contracts}}",
  "interval": "{{interval}}",
  "position_size": "{{strategy.position_size}}"
}
```

### Bước 5: Xác nhận Settings trên Script

Trước khi Save Alert, kiểm tra lại Input Settings của A007+MIS V2 trên Chart:

| Setting | Giá trị Khuyến Nghị | Lý do |
|---------|---------------------|-------|
| **Profile** | `Futures` | Khớp với Production Binance Futures |
| **Webhook Secret** | `7086c59c...89104` | Phải khớp với `.env` trên server |
| **require_both** | ✅ `true` | Yêu cầu CẢ A.007 VÀ MIS cùng đồng ý mới vào lệnh |
| **Enable shorts** | ✅ `true` | Cho phép Short khi S1+S2 đều xác nhận |
| **Partial TP** | ✅ `true`, `TP1 = 1.0R`, `50%` | Chốt 50% lời sớm, trail phần còn lại |
| **ATR trailing** | ✅ `true`, `mult = 2.5` (trước TP1), `1.0` (sau TP1) | Siết trail sau khi TP1 đã hit |
| **ADX regime gate** | ✅ `true`, `threshold = 20` | Chặn lệnh khi thị trường Sideway |
| **BB squeeze block** | ✅ `true`, `width < 5%` | Chặn khi volatility cực thấp |

### Bước 6: Tạo Alert cho SuperTrend Flip (Alert 2)

1. **Condition**: Chọn `SuperTrend Flip Webhook`
2. **Trigger**: `Any alert() function call`
3. **Webhook URL**: Cùng URL `/ingest` như trên
4. **Message**: Để trống (script đã tự build JSON qua thư viện `VBS_Webhook_Lib`)

---

## 🔍 Xác minh Server nhận đúng tín hiệu

Sau khi tạo Alert xong, chờ tín hiệu tiếp theo hoặc dùng lệnh test:

```powershell
# Test nhanh từ PowerShell (giả lập tín hiệu A007+MIS V2)
cd server
.\simulate_webhook.ps1 -Url "https://trading.utopiavn.co/ingest" -Action "buy" -Symbol "BTCUSDT" -Price "63266"
```

Kiểm tra Dashboard tại: `https://trading.utopiavn.co/` → Tab **Signals** để xem tín hiệu mới.

---

## ⚠️ Lưu ý quan trọng

> [!WARNING]
> **Secret trong Pine ≠ Secret trong URL Query**
> - Pine Script `A007+MIS V2` đang hardcode secret `7086c59c...89104` **vào trong JSON body** (trường `"secret"`).
> - URL Query cũng truyền secret qua `?secret=9ea7c89f...`.
> - Gateway sẽ ưu tiên lấy secret từ: Header → Query → Body (theo thứ tự).
> - Miễn là **1 trong 3** khớp với `WEBHOOK_SECRET` trong `.env`, request sẽ được xác thực thành công.
