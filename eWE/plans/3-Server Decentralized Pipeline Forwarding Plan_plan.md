# 🏛️ 3-Server Decentralized Pipeline Forwarding Plan

Kiến trúc này phân rã toàn bộ hệ thống giao dịch thành 3 Server độc lập kết nối qua mạng nội bộ ảo Tailscale VPN để tối ưu hóa tài nguyên, bảo mật tối đa API Keys và chạy mượt mà các tác vụ nặng (RAG AI & Backtesting).

## 🏗️ Phân Bổ Nhiệm Vụ 3 Server

1. **SERVER A (Ingress Gateway - Linux 1U2G):**
   - Hứng tín hiệu Webhook từ TradingView 24/7 qua Cloudflare Tunnel.
   - Lưu trữ tín hiệu thô vào SQLite Queue (vbs-service).

2. **SERVER C (AI Core & Analysis & Backtest - Linux 8U16G):**
   - Chạy ChromaDB Server (Vector DB).
   - Chạy RAG Daemon poll thô từ SERVER A ──> Truy vấn ChromaDB cục bộ ──> Gọi Claude/Gemini qua Antigravity SDK.
   - Phân tích SEPA (Minervini), tính toán Position Sizing & quản lý rủi ro.
   - Chạy các script Backtesting hiệu năng cao.
   - Đẩy lệnh giao dịch hoàn chỉnh sang SERVER B.

3. **SERVER B (Execution Vault - Windows 2U4G):**
   - Bảo mật API Keys kết nối tài khoản các sàn (Bybit, Binance, Weex).
   - Mở API endpoint `/api/execute-trade` (chỉ cho phép SERVER C truy cập qua Tailscale).
   - Nhận lệnh giao dịch hoàn chỉnh từ SERVER C và đặt lệnh ngay lập tức (độ trễ thấp).
   - Ghi nhật ký vào `trades.db` và gửi thông báo Telegram/Discord.

---

## User Review Required

> [!IMPORTANT]
> **Xác nhận các thông số thiết lập mạng và phân phối:**
> 1. **Cổng Kết Nối (Ports):**
>    - ChromaDB Server trên **SERVER C**: cổng mặc định `8000`.
>    - Endpoint thực thi lệnh `/api/execute-trade` trên **SERVER B**: cổng `5000` (hoặc cổng tùy chọn).
> 2. **ChromaDB Migration:** ChromaDB trên SERVER C sẽ chạy bằng Docker (`chromadb/chroma:latest`). Dữ liệu vector sẽ được mount từ thư mục `docs/knowledge/...` để nhúng (embed) lại ban đầu.
> 3. **Vị Trí Chạy Dashboard:** Dashboard giao diện người dùng sẽ chạy trên **SERVER B** (để trực tiếp đọc `trades.db` và điều khiển bot) hay sếp muốn chạy trên cả máy Local và kết nối về SERVER B qua API?

---

## Open Questions

- **Backtesting Data Sync:** Dữ liệu lịch sử phục vụ Backtest trên SERVER C sẽ được tải trực tiếp từ Binance/Bybit API hay được đồng bộ từ file dữ liệu có sẵn?
- **CDP Automation từ Local:** Máy Local chạy TradingView Desktop + CDP automation sẽ gửi tín hiệu thẳng về SERVER A (Gateway) hay gửi trực tiếp lên SERVER C? (Khuyến nghị: Gửi về SERVER A để đi đúng luồng queue an toàn).

---

## Proposed Changes

### 1. Thành Phần AI Core & RAG (SERVER C)

#### [MODIFY] [`server/config.py`](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/server/config.py)
* Thêm cấu hình hỗ trợ ChromaDB remote client và địa chỉ đích của SERVER B:
```python
# ── ChromaDB Remote Configuration ──
CHROMA_SERVER_HOST = os.getenv("CHROMA_SERVER_HOST", "localhost")
CHROMA_SERVER_PORT = int(os.getenv("CHROMA_SERVER_PORT", "8000"))
CHROMA_REMOTE      = os.getenv("CHROMA_REMOTE", "false").lower() == "true"

# ── Pipeline Forwarding (Server C -> Server B) ──
SERVER_B_EXECUTE_URL = os.getenv("SERVER_B_EXECUTE_URL", "http://100.x.x.x:5000/api/execute-trade")
SERVER_B_SECRET      = os.getenv("SERVER_B_SECRET", "")
```

#### [MODIFY] [`server/rag.py`](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/server/rag.py)
* Cập nhật `init_vector_db()` để tự động kết nối sang remote ChromaDB server nếu `CHROMA_REMOTE=True`:
```python
if getattr(config, "CHROMA_REMOTE", False):
    import chromadb
    _chroma_client = chromadb.HttpClient(
        host=config.CHROMA_SERVER_HOST,
        port=config.CHROMA_SERVER_PORT
    )
else:
    # Fallback về persistent client cục bộ như cũ
    _chroma_client = chromadb.PersistentClient(path=str(chroma_db_path))
```

#### [NEW] `server/workers/vps_analyzer.py`
* Daemon chạy trên **SERVER C** để poll tín hiệu thô từ **SERVER A**, thực hiện phân tích RAG, đánh giá bằng AI, tính toán Position Sizing, sau đó PUSH payload đặt lệnh sạch sang **SERVER B**.
* Giao thức truyền dữ liệu: `POST SERVER_B_EXECUTE_URL` kèm theo mã Header `X-Server-B-Secret` để xác thực bảo mật.

---

### 2. Thành Phần Thực Thi Lệnh (SERVER B - Windows)

#### [NEW] `server/execution_server.py`
* FastAPI app gọn nhẹ chạy trên **SERVER B** để:
  1. Hứng payload đặt lệnh tại `POST /api/execute-trade`.
  2. Xác thực token an toàn (`X-Server-B-Secret`).
  3. Kích hoạt trực tiếp `TradeEngine` để đặt lệnh trên Bybit/Binance/Weex dựa theo API Keys lưu tại `.env` của Server B.
  4. Trả về kết quả giao dịch và phát tín hiệu Telegram/Discord.

#### [MODIFY] `docker-compose.yml` (Cho từng Server)
* Tạo cấu trúc file Compose chuyên biệt cho từng Server:
  - `docker-compose.server-a.yml`: Chỉ chạy `vbs` container.
  - `docker-compose.server-c.yml`: Chạy `chromadb` container + `vps_analyzer` worker.
  - `docker-compose.server-b.yml`: Chạy `execution_server` + Dashboard.

---

## Verification Plan

### Kiểm Tra Mạng Nội Bộ (Tailscale VPN)
```powershell
# Từ Server C, ping kiểm tra kết nối đến Server B qua IP Tailscale
ping 100.x.x.x

# Kiểm tra cổng kết nối ChromaDB từ Server B sang Server C
Test-NetConnection -ComputerName 100.y.y.y -Port 8000
```

### Kiểm Tra Luồng Tích Hợp (End-to-End Simulation)
1. **Bước 1:** Gửi tín hiệu giả lập từ TradingView đến **SERVER A** (`POST /ingest`).
2. **Bước 2:** Đảm bảo **SERVER C** nhận được tín hiệu qua polling, truy vấn ChromaDB từ xa thành công và trả về nhận định AI chi tiết.
3. **Bước 3:** **SERVER C** tính toán kích thước vị thế và đẩy lệnh sang **SERVER B**.
4. **Bước 4:** **SERVER B** thực thi giao dịch giả lập (Dry Run) trên sàn thành công, cập nhật `trades.db` và đẩy thông báo về Telegram của sếp.
