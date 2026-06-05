# Kiến trúc Hệ thống Telegram & MCP Client

Tài liệu này trình bày chi tiết về kiến trúc hệ thống của Trading Bot trước và sau khi được tối ưu hóa hiệu năng, cải thiện tốc độ phản hồi trên Telegram.

---

## 1. Kiến trúc Trước Nâng Cấp (Before Upgrade)

Hệ thống cũ xử lý tuần tự và đồng bộ, dẫn đến việc Event Loop của bot Telegram bị nghẽn (blocked) trong thời gian dài khi quét watchlist.

```mermaid
sequenceDiagram
    autonumber
    actor User as Telegram User
    participant Bot as Telegram Bot (Event Loop)
    participant Engine as Analysis Engine (analysis.py)
    participant MCP as MCP Client (mcp_client.py)
    participant Node as Subprocess (node cli/index.js)

    User->>Bot: Gửi lệnh /scan
    Note over Bot: Chạy cmd_scan_enhanced<br/>(Luồng bị khóa chờ kết quả)

    Bot->>Engine: await scan_symbols(symbols)

    rect rgb(240, 220, 220)
        Note over Engine, MCP: Vòng lặp tuần tự cho từng Symbol (Ví dụ: 10 mã)

        loop Cho mỗi Symbol
            Engine->>MCP: batch_run(symbol)

            MCP->>Node: Spawn: get_quote(symbol)
            Node-->>MCP: Trả về kết quả

            MCP->>Node: Spawn: get_study_values(symbol)
            Node-->>MCP: Trả về kết quả

            MCP->>Node: Spawn: get_ohlcv_summary(symbol)
            Node-->>MCP: Trả về kết quả

            MCP-->>Engine: Trả về dữ liệu Symbol (đã tốn ~1-2 giây)
        end
    end

    Engine-->>Bot: Trả về toàn bộ danh sách kết quả (sau ~15-20 giây)
    Bot->>User: Gửi tin nhắn kết quả phân tích
    Note over Bot: Giải phóng Event Loop
```

### Nhược điểm:
1. **Blocking Event Loop:** Toàn bộ lệnh quét chạy đồng bộ bằng `await` trực tiếp trong Handler của Telegram, khiến Bot không thể xử lý bất kỳ tin nhắn nào khác (như lệnh `/status`) trong suốt thời gian quét.
2. **Sequential Spawn:** Spawn tiến trình con Node.js một cách tuần tự (1 symbol chạy xong mới spawn symbol tiếp theo), đẩy tổng thời gian xử lý lên $O(N \times 3)$ tiến trình con.

---

## 2. Kiến trúc Sau Nâng Cấp (After Upgrade)

Kiến trúc mới áp dụng cơ chế xử lý bất đồng bộ hoàn toàn (Asynchronous Offloading) trên Telegram Bot, song song hóa tiến trình MCP thông qua Semaphore, và tối ưu hóa hàng đợi Semaphore ở lớp REST Fallback.

```mermaid
sequenceDiagram
    autonumber
    actor User as Telegram User
    participant Bot as Telegram Bot (Event Loop)
    participant Task as Background Task (asyncio.create_task)
    participant Engine as Analysis Engine (analysis.py)
    participant MCP as MCP Client (mcp_client.py)
    participant Node as Subprocess (node cli/index.js)

    User->>Bot: Gửi lệnh /scan
    Note over Bot: Khởi chạy cmd_scan_enhanced
    Bot->>User: Gửi ngay tin nhắn "🔄 Đang xử lý..." (trong < 1s)

    Bot->>Task: asyncio.create_task(process_task())
    Note over Bot: Giải phóng Event Loop lập tức!<br/>Bot có thể nhận lệnh khác (ví dụ: /status)

    rect rgb(220, 240, 220)
        Note over Task, MCP: Thực thi Song song với Semaphore (Tối đa 5 symbols cùng lúc)

        Task->>Engine: await scan_symbols(symbols, mcp)
        Engine->>MCP: batch_run(symbols)

        par Cho mỗi mã (trong giới hạn Semaphore 5)
            MCP->>Node: Spawn: get_quote(symbol)
            Node-->>MCP: Dữ liệu quote
        and
            MCP->>Node: Spawn: get_study_values(symbol)
            Node-->>MCP: Dữ liệu studies
        and
            MCP->>Node: Spawn: get_ohlcv_summary(symbol)
            Node-->>MCP: Dữ liệu ohlcv
        end

        MCP-->>Engine: Trả về kết quả gộp của các symbols
        Engine-->>Task: Phân tích hoàn tất
    end

    Task->>Bot: Gửi kết quả hoàn thành
    Bot->>User: context.bot.send_message(kết quả)
```

### Ưu điểm vượt trội:
1. **Telegram Phản hồi Tức thì (Offloading):** Telegram Bot phản hồi ngay tin nhắn xử lý và chuyển giao việc quét cho một `asyncio.create_task` ngầm. Điều này giải phóng luồng chính của bot, giúp bot hoạt động trơn tru không bị nghẽn.
2. **Quét Song song (MCP Parallelization):** Nhờ `asyncio.gather` và `asyncio.Semaphore(5)`, việc quét Watchlist diễn ra đồng thời. Thay vì chờ đợi từng mã một, tối đa 5 mã được xử lý song song, giảm thời gian chờ đợi tổng thể xuống còn khoảng 1/4 so với trước.
3. **Mở khóa Semaphore khi Rate Limit (REST Fallback):** Trong hàm `fetch_candles_with_retry`, Semaphore chỉ được giữ trong thời gian thực thi request (`session.get`). Nếu nhận mã lỗi `429` (Rate limited), Semaphore sẽ được **giải phóng ngay lập tức** trước khi sleep. Nhờ đó, các request của các symbol khác không bị block oan và vẫn có thể tiếp tục chạy.
