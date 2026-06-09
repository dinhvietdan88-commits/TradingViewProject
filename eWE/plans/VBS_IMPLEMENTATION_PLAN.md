# VPS Buffer Server — Master Implementation Plan

Hệ thống hứng tín hiệu TradingView 24/7 trên VPS, tự động queue khi Local offline,
và Local Bot PULL + ACK khi khởi động để không bao giờ bỏ lỡ tín hiệu giao dịch.

> **Architecture Doc:** [VPS_BUFFER_ARCHITECTURE.md](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/docs/plans/VPS_BUFFER_ARCHITECTURE.md)  
> **Estimated Total Time:** ~6 giờ  
> **Risk Level:** 🟠 MEDIUM — Backward compatible, không break codebase cũ

---

## User Review Required

> [!IMPORTANT]
> **Xác nhận các quyết định sau trước khi bắt đầu:**
> 1. **TTL:** Signal hết hạn sau `4 giờ` (mặc định). Sếp muốn tùy chỉnh theo loại signal không?
> 2. **VPS OS:** Ubuntu/Debian? Docker đã cài chưa?
> 3. **Domain:** `bot.yourdomain.com` đã trỏ Cloudflare Tunnel về VPS chưa?
> 4. **Telegram:** Dùng chung Bot Token hiện tại hay tạo Bot phụ cho VBS?

> [!CAUTION]
> **Breaking Changes:** KHÔNG có. Tất cả thay đổi trên Local Bot là additive (thêm mới, không sửa code cũ). `WEBHOOK_SECRET` hiện tại giữ nguyên. `BUFFER_SECRET` là secret mới hoàn toàn riêng biệt.

---

## Open Questions

- TTL mặc định `4h` có phù hợp với chiến lược giao dịch? (BUY/SELL breakout thường stale sau 1h)
- Khi Local pull 5+ signals cùng lúc: xử lý **tuần tự** (safe) hay **song song** (fast)?
- Queue overflow khi > 1000 signals: **reject mới** hay **xóa cũ nhất**?

---

## Proposed Changes

### Phase 1: VPS Buffer Service *(~3 giờ)*

Service mới hoàn toàn, deploy độc lập trên VPS bằng Docker.

---

#### [NEW] `vbs/main.py`
FastAPI app entry point cho VPS Buffer Service.
```python
# Key: lifespan context manager khởi tạo DB + scheduler
# Endpoints: /ingest, /consume, /ack, /queue-status, /health
```

#### [NEW] `vbs/router.py`
5 API endpoints chính:
- `POST /ingest` — nhận tín hiệu từ TradingView (qua CF Tunnel)
- `GET /consume` — Local Bot PULL signals PENDING
- `POST /ack` — Local Bot xác nhận đã xử lý
- `GET /queue-status` — trạng thái queue cho Dashboard
- `GET /health` — health check cho monitoring

#### [NEW] `vbs/database.py`
SQLite async layer (aiosqlite) cho VPS.

Schema mới `signal_queue`:
```sql
CREATE TABLE signal_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at   TEXT NOT NULL DEFAULT (datetime('now')),
    dispatched_at TEXT,
    acked_at      TEXT,
    expires_at    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'PENDING',
    symbol        TEXT NOT NULL,
    action        TEXT NOT NULL,
    price         REAL,
    quote_qty     REAL,
    interval      TEXT,
    exchange      TEXT NOT NULL DEFAULT 'binance',
    sl            TEXT,
    tp            TEXT,
    source        TEXT,
    payload_json  TEXT NOT NULL,
    consumer_id   TEXT,
    retry_count   INTEGER NOT NULL DEFAULT 0,
    ack_status    TEXT,
    error_msg     TEXT
);
```

Schema mới `signal_audit_log`:
```sql
CREATE TABLE signal_audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id   INTEGER NOT NULL,
    event      TEXT NOT NULL,
    event_at   TEXT NOT NULL DEFAULT (datetime('now')),
    consumer_id TEXT,
    detail     TEXT
);
```

#### [NEW] `vbs/scheduler.py`
APScheduler background jobs:
- **Cleanup job** (mỗi 15 phút): PENDING/DISPATCHED → STALE khi `expires_at < NOW()`
- **Re-queue job** (mỗi 5 phút): DISPATCHED timeout → PENDING (retry_count += 1, max 3)
- **Audit cleanup** (mỗi ngày): xóa audit_log cũ hơn 7 ngày

#### [NEW] `vbs/notifier.py`
Telegram push notification:
- Signal queued: `📥 Signal Queued: {symbol} {action.upper()}`
- Signal stale: `❌ Signal STALE: {N} signals expired`
- Recovery: `✅ Local reconnected, {N} signals dispatched`

#### [NEW] `vbs/models.py`
Pydantic models:
- `IngestRequest` — payload từ TradingView
- `ConsumeResponse` — list signals trả về cho Local
- `AckRequest` / `AckItem` — xác nhận đã xử lý
- `QueueStatusResponse` — snapshot dashboard

#### [NEW] `vbs/config.py`
Env config cho VBS:
```dotenv
BUFFER_SECRET=<secrets.token_hex(32)>
SIGNAL_TTL_HOURS=4
DISPATCH_TIMEOUT_MINUTES=5
MAX_QUEUE_SIZE=1000
CLEANUP_INTERVAL_MINUTES=15
AUDIT_RETENTION_DAYS=7
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DB_PATH=/app/data/signal_queue.db
```

#### [NEW] `vbs/requirements.txt`
```
fastapi==0.115.0
uvicorn[standard]==0.30.0
aiosqlite==0.20.0
apscheduler==3.10.4
httpx==0.27.0
pydantic==2.8.0
python-dotenv==1.0.1
```

#### [NEW] `vbs/Dockerfile`
Multi-stage build, non-root user, health check.

#### [NEW] `docker-compose.vbs.yml`
Compose file riêng cho VBS (không mix với trading-bot):
```yaml
services:
  vbs:
    build: ./vbs
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - vbs-data:/app/data
    env_file: vbs/.env
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
volumes:
  vbs-data:
    name: vbs-signal-queue
```

---

### Phase 2: Local Bot Consumer Worker *(~2 giờ)*

Tích hợp vào Local Bot hiện tại theo pattern **additive only** — không thay đổi code cũ.

---

#### [NEW] `server/workers/vps_consumer.py`
`VpsSignalConsumer` class với 3 methods:

```python
class VpsSignalConsumer:
    async def on_startup(self):
        """Hook vào FastAPI lifespan — kéo signals PENDING khi boot."""
        pending = await self.pull(limit=config.VPS_STARTUP_PULL_LIMIT)
        for signal in pending:
            await self._process_and_ack(signal)

    async def poll_loop(self):
        """Background task — poll mỗi 30 giây."""
        while True:
            await asyncio.sleep(config.VPS_POLL_INTERVAL_SECONDS)
            signals = await self.pull(limit=5)
            for signal in signals:
                await self._process_and_ack(signal)

    async def _process_and_ack(self, signal):
        """Idempotency check → emit EventBus → ACK."""
        # 1. Stale check: age > MAX_SIGNAL_AGE_MINUTES
        # 2. Duplicate check: vbs_queue_id in trades table
        # 3. Emit SignalReceived to existing EventBus
        # 4. POST /ack với status executed/skipped_stale/failed
```

**Key design:** Worker emit vào EventBus hiện có (`core.event_bus`) — **không** tự gọi TradeEngine trực tiếp, đảm bảo toàn bộ pipeline hiện tại (RAG, Telegram approval, Binance) vẫn chạy bình thường.

#### [MODIFY] [`server/config.py`](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/server/config.py)
Thêm env vars ở cuối file (backward compatible — có default values):
```python
# ── VPS Buffer Consumer (Phase VBS) ───────────────────
VPS_BUFFER_ENABLED       = os.getenv("VPS_BUFFER_ENABLED", "false").lower() == "true"
VPS_BUFFER_URL           = os.getenv("VPS_BUFFER_URL", "")
VPS_BUFFER_SECRET        = os.getenv("VPS_BUFFER_SECRET", "")
VPS_CONSUMER_ID          = os.getenv("VPS_CONSUMER_ID", "local-01")
VPS_POLL_INTERVAL_SECONDS= int(os.getenv("VPS_POLL_INTERVAL_SECONDS", "30"))
VPS_STARTUP_PULL_LIMIT   = int(os.getenv("VPS_STARTUP_PULL_LIMIT", "50"))
MAX_SIGNAL_AGE_MINUTES   = int(os.getenv("MAX_SIGNAL_AGE_MINUTES", "240"))
```

#### [MODIFY] [`server/main.py`](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/server/main.py)
2 thay đổi nhỏ trong lifespan:
1. Khởi tạo `VpsSignalConsumer` khi `VPS_BUFFER_ENABLED=true`
2. Gọi `consumer.on_startup()` + tạo background task `consumer.poll_loop()`

```python
# Trong lifespan (startup block):
if config.VPS_BUFFER_ENABLED:
    consumer = VpsSignalConsumer()
    await consumer.on_startup()
    asyncio.create_task(consumer.poll_loop())
```

#### [MODIFY] [`server/database.py`](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/server/database.py)
Thêm migration backward-compatible trong `init_db()`:
```python
# Thêm vbs_queue_id vào trades table (idempotency tracking)
try:
    await db.execute("ALTER TABLE trades ADD COLUMN vbs_queue_id INTEGER")
    await db.commit()
except Exception:
    pass  # Column already exists
```

#### [MODIFY] `.env.production`
Thêm section mới ở cuối (template):
```dotenv
# ── VPS Buffer Consumer ─────────────────────────────────
VPS_BUFFER_ENABLED=true
VPS_BUFFER_URL=https://bot.yourdomain.com
VPS_BUFFER_SECRET=CHANGE_ME_SAME_AS_VBS_BUFFER_SECRET
VPS_CONSUMER_ID=local-01
VPS_POLL_INTERVAL_SECONDS=30
VPS_STARTUP_PULL_LIMIT=50
MAX_SIGNAL_AGE_MINUTES=240
```

---

### Phase 3: Dashboard & Observability *(~1 giờ)*

Hiển thị trạng thái VPS Queue trực tiếp trên Dashboard.

---

#### [MODIFY] [`server/main.py`](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/server/main.py)
Thêm 1 endpoint mới:
```python
@app.get("/api/queue-status")
async def get_queue_status():
    """Proxy lên VPS Buffer để lấy queue status."""
    if not config.VPS_BUFFER_ENABLED:
        return {"enabled": False}
    # httpx GET VPS_BUFFER_URL/queue-status
    # Return: pending_count, dispatched_count, oldest_age_minutes, signals[]
```

#### [MODIFY] `server/static/js/dashboard.js` *(hoặc dashboard-features.js)*
Thêm queue status panel tự refresh mỗi 30s:
```javascript
// Badge hiển thị số lượng PENDING
// Click để xem chi tiết danh sách signals đang chờ
// Color: xanh (0 pending) → vàng (1-5) → đỏ (>5)
```

#### [MODIFY] `server/static/index.html`
Thêm widget "Signal Queue" vào sidebar Dashboard.

---

## Verification Plan

### Automated Tests

```bash
# 1. VBS Health Check
curl https://bot.yourdomain.com/health
# Expected: {"status":"healthy","db":"ok","pending_count":0}

# 2. Ingest Test
curl -X POST https://bot.yourdomain.com/ingest \
  -H "X-Buffer-Secret: $BUFFER_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"action":"buy","symbol":"BTCUSDT","price":"68420","exchange":"binance"}'
# Expected: {"queued":true,"queue_id":1,"status":"PENDING"}

# 3. Consume Test
curl "https://bot.yourdomain.com/consume?consumer_id=test&limit=1" \
  -H "X-Buffer-Secret: $BUFFER_SECRET"
# Expected: {"signals":[{...}],"count":1}

# 4. ACK Test
curl -X POST https://bot.yourdomain.com/ack \
  -H "X-Buffer-Secret: $BUFFER_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"acks":[{"queue_id":1,"status":"executed"}]}'
# Expected: {"acked":1}

# 5. Queue Status
curl "https://bot.yourdomain.com/queue-status" \
  -H "X-Buffer-Secret: $BUFFER_SECRET"
# Expected: {"summary":{"pending":0,"acked_today":1,...}}
```

### Stale Signal Test
```bash
# Đặt TTL = 1 phút trong VBS .env để test nhanh
SIGNAL_TTL_HOURS=0.017  # ~1 phút
# Gửi signal → đợi 2 phút → kiểm tra status = STALE
```

### Boot Recovery Test
```bash
# 1. Tắt Local Bot
# 2. Gửi 3 signals từ TradingView (hoặc curl /ingest)
# 3. Bật Local Bot lên
# 4. Kiểm tra log: "[VpsConsumer] Pulled 3 pending signals on boot"
# 5. Kiểm tra VBS: GET /queue-status → pending=0, acked_today=3
```

### Manual Verification
- [ ] Telegram nhận notification `📥 Signal Queued` khi ingest
- [ ] Telegram nhận notification `❌ Signal STALE` sau TTL
- [ ] Dashboard hiển thị queue badge đúng màu theo số lượng PENDING
- [ ] Local Bot log `[VpsConsumer]` entries khi startup
- [ ] `trades` table có cột `vbs_queue_id` sau migration
