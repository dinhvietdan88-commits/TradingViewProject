# 🧠 Deep-Think: OHLCV Chart Data — Multi-Layer Cache Architecture

## Tóm tắt vấn đề

`/api/klines` hiện chỉ proxy Binance với `limit=300` nến × 1h = **~12.5 ngày lùi lại**.
Signals FORWARD bắt đầu từ **30/05/2026** → vùng mù **~10 ngày** không có data chart.

---

## ⚠️ Option A — Smart Backfill: Khi nào nguy hiểm?

### Bảng chi phí theo số lượng request Binance

| Khoảng thời gian | Nến 1h | Requests | Latency ước tính |
|---|---|---|---|
| **1 tháng** | 720 | **1** | ~0.3s ✅ |
| **3 tháng** | 2,160 | **3** | ~1.1s ✅ |
| **6 tháng** | 4,320 | **5** | ~1.8s ⚠️ |
| **1 năm** | 8,760 | **9** | ~3.1s ⚠️ |
| **2 năm** | 17,520 | **18** | ~6.3s ❌ |
| **BTC genesis (2009)** | 148,920 | **149** | ~52s 💀 |

> **Kết luận Option A**: Nếu **không có hard cap**, user có thể trigger 149 Binance requests liên tiếp.
> Binance sẽ rate-limit IP sau ~20-30 requests/min → toàn bộ hệ thống bị block.

### Rủi ro cụ thể nếu không giới hạn:
1. **Binance IP Ban**: Weight limit 6000/min. Mỗi klines request = 1-10 weight. 149 requests = ~1490 weight → bị throttle
2. **Memory spike**: 148,920 nến × 50 bytes ≈ **7 MB** chỉ cho 1 symbol/1 chart load
3. **Latency không chấp nhận**: >52s wait time → timeout, user thoát
4. **Không có persistent cache** → mỗi lần mở lại phải fetch lại toàn bộ

### ✅ Option A khả thi nếu có:
- **Hard cap**: `MAX_LOOKBACK = 90 ngày` (tuyệt đối không vượt)
- **Pagination guard**: Tối đa 3 requests/chart load
- **DB persistence**: Sau lần đầu fetch → lưu vào SQLite, không fetch lại

---

## 🗄️ Option B — Multi-Layer Cache Architecture

### Kiến trúc 4 tầng (L0 → L3)

```
User mở chart signal từ 30/05
         ↓
┌─────────────────────────────────────────────────────────┐
│  L0: Frontend — IndexedDB (Browser Cache)               │
│  Key: "klines:BTCUSDT:1h:2026-05"                       │
│  TTL: Completed candles = ∞ | Current candle = 60s      │
│  Size: ~50MB/browser | Latency: 0ms (instant)           │
└──────────────────────────┬──────────────────────────────┘
                           │ MISS
                           ↓
┌─────────────────────────────────────────────────────────┐
│  L1: Backend — Python LRU In-Memory Cache               │
│  lib: cachetools.TTLCache (không cần Redis)             │
│  Key: "klines:{symbol}:{interval}:{start_day}"          │
│  TTL: 5 phút | Max: 1000 entries (~50MB RAM)            │
│  Latency: <1ms | Shared across all users                │
└──────────────────────────┬──────────────────────────────┘
                           │ MISS  
                           ↓
┌─────────────────────────────────────────────────────────┐
│  L2: Backend — SQLite ohlcv Cache (trades.db)           │
│  Table: ohlcv_1h (cần tạo mới)                         │
│  Existing: ohlcv_1d đã có từ Oct 2025 → nay ✅         │
│  Latency: 5-20ms | Persistent qua restart               │
└──────────────────────────┬──────────────────────────────┘
                           │ MISS (chỉ khi chưa có data)
                           ↓
┌─────────────────────────────────────────────────────────┐
│  L3: Binance Public API (Ground Truth)                  │
│  Max lookback: 90 ngày hard cap                         │
│  Max: 3 requests per chart load (= 3000 nến = ~125 ngày)│
│  Sau fetch → lưu vào L2 → populate L1 & L0             │
└─────────────────────────────────────────────────────────┘
```

---

## Cách 1 — Frontend Cache (IndexedDB)

### Cơ chế hoạt động:

```javascript
// Trong forward_test.html
const CACHE_DB_NAME = 'ohlcv_cache';
const CACHE_VERSION = 1;

async function openCacheDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(CACHE_DB_NAME, CACHE_VERSION);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      // Store: key = "BTCUSDT:1h:2026-05-30", value = candles[]
      db.createObjectStore('candles', { keyPath: 'key' });
    };
    req.onsuccess = e => resolve(e.target.result);
    req.onerror = reject;
  });
}

async function getCachedCandles(symbol, interval, startTime) {
  const db = await openCacheDB();
  const dayKey = new Date(startTime).toISOString().slice(0, 10); // "2026-05-30"
  const key = `${symbol}:${interval}:${dayKey}`;
  return new Promise(resolve => {
    const tx = db.transaction('candles', 'readonly');
    const req = tx.objectStore('candles').get(key);
    req.onsuccess = e => resolve(e.target.result?.candles || null);
    req.onerror = () => resolve(null);
  });
}

async function setCachedCandles(symbol, interval, startTime, candles) {
  const db = await openCacheDB();
  const dayKey = new Date(startTime).toISOString().slice(0, 10);
  const key = `${symbol}:${interval}:${dayKey}`;
  const isHistorical = Date.now() - startTime > 2 * 3600 * 1000; // >2h cũ
  
  return new Promise(resolve => {
    const tx = db.transaction('candles', 'readwrite');
    tx.objectStore('candles').put({
      key,
      candles,
      cachedAt: Date.now(),
      ttl: isHistorical ? Infinity : 60_000  // Historical: ∞ | Current: 60s
    });
    tx.oncomplete = resolve;
  });
}
```

### Load chart với Frontend Cache:

```javascript
async function loadSignalChart(symbol, signalTimestamp) {
  if (!signalChart) return;
  currentChartSymbol = symbol;
  
  // Tính startTime từ signal (lùi 2 ngày để có context)
  const startTime = signalTimestamp 
    ? Math.max(signalTimestamp - 2 * 86400 * 1000, Date.now() - 90 * 86400 * 1000)
    : Date.now() - 300 * 3600 * 1000;  // fallback: 300h
  
  try {
    // L0: Check IndexedDB first
    let candles = await getCachedCandles(symbol, '1h', startTime);
    
    if (!candles) {
      // L1/L2/L3: Fetch from backend (backend sẽ tự cache)
      const res = await get(
        `/api/klines?symbol=${symbol}&interval=1h&limit=1000&startTime=${startTime}`, 
        20000
      );
      if (res?.success && res.candles?.length > 0) {
        candles = res.candles;
        // Lưu vào IndexedDB
        await setCachedCandles(symbol, '1h', startTime, candles);
      }
    }
    
    if (candles?.length > 0) {
      window.currentChartCandles = candles;
      signalCandleSeries.setData(candles);
      signalVolumeSeries.setData(candles.map(c => ({
        time: c.time, value: c.volume,
        color: c.close >= c.open ? 'rgba(38,166,154,0.25)' : 'rgba(239,83,80,0.25)'
      })));
      signalChart.timeScale().fitContent();
      addForwardSignalMarkers(symbol);
    }
  } catch (e) {
    console.warn('Chart load failed:', e);
  }
}
```

### Ưu / Nhược điểm Frontend Cache:

| | |
|---|---|
| ✅ **Zero latency** cho lần 2+ | ❌ Per-browser, không share giữa users |
| ✅ Không tốn RAM server | ❌ Max ~50-100MB IndexedDB (đủ dùng) |
| ✅ Offline capable | ❌ Bị clear khi user xóa browser data |
| ✅ Không cần Redis | ❌ Cần implement invalidation logic |

---

## Cách 2 — Backend In-Memory Cache (Python TTLCache)

> ❗ **Không cần Redis** cho use case này. `cachetools.TTLCache` đủ mạnh và đã có sẵn hoặc cài 1 lệnh.

### Backend implementation trong `main.py`:

```python
from cachetools import TTLCache
import asyncio

# L1 In-Memory Cache: 500 entries, 5 phút TTL (historical data)
# Historical candles không thay đổi → có thể TTL dài hơn
_klines_cache: TTLCache = TTLCache(maxsize=500, ttl=300)
_klines_lock = asyncio.Lock()

@app.get("/api/klines")
async def get_klines(
    symbol: str = Query(...),
    interval: str = Query("1h"),
    start_time: int | None = Query(None, alias="startTime"),
    limit: int = Query(300, ge=1, le=1000),
):
    """Smart OHLCV endpoint: L1 Memory → L2 SQLite → L3 Binance (max 90d lookback)."""
    import httpx
    
    symbol_clean = symbol.upper().replace(":", "")
    
    # Hard cap: tối đa 90 ngày lookback
    MAX_LOOKBACK_MS = 90 * 24 * 3600 * 1000
    now_ms = int(time.time() * 1000)
    
    if start_time:
        # Enforce hard cap
        start_time = max(start_time, now_ms - MAX_LOOKBACK_MS)
    
    # L1: Check in-memory cache
    cache_key = f"{symbol_clean}:{interval}:{start_time or 'latest'}:{limit}"
    async with _klines_lock:
        if cache_key in _klines_cache:
            log.debug(f"Klines L1 HIT: {cache_key}")
            return {"success": True, "candles": _klines_cache[cache_key], 
                    "symbol": symbol_clean, "source": "memory_cache"}
    
    # L2: Check SQLite ohlcv cache
    candles_from_db = await _fetch_klines_from_db(symbol_clean, interval, start_time, limit)
    if candles_from_db and len(candles_from_db) >= limit * 0.8:  # 80% data present
        async with _klines_lock:
            _klines_cache[cache_key] = candles_from_db
        log.debug(f"Klines L2 HIT: {symbol_clean} {len(candles_from_db)} candles from DB")
        return {"success": True, "candles": candles_from_db, 
                "symbol": symbol_clean, "source": "db_cache"}
    
    # L3: Fetch from Binance (với pagination guard: max 3 requests)
    candles = await _fetch_binance_paginated(symbol_clean, interval, start_time, limit)
    
    if candles:
        # Lưu vào L2 SQLite (background)
        asyncio.create_task(_save_klines_to_db(symbol_clean, interval, candles))
        # Lưu vào L1 Memory
        async with _klines_lock:
            _klines_cache[cache_key] = candles
    
    return {"success": bool(candles), "candles": candles or [], 
            "symbol": symbol_clean, "source": "binance_api"}


async def _fetch_binance_paginated(symbol, interval, start_time, limit, max_requests=3):
    """Fetch candles from Binance with pagination (max 3 requests = ~125 days for 1h)."""
    import httpx
    all_candles = []
    current_start = start_time
    requests_made = 0
    
    async with httpx.AsyncClient(timeout=15) as client:
        while requests_made < max_requests:
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": 1000,
            }
            if current_start:
                params["startTime"] = current_start
            
            resp = await client.get("https://api.binance.com/api/v3/klines", params=params)
            resp.raise_for_status()
            raw = resp.json()
            requests_made += 1
            
            if not raw:
                break
            
            batch = [{
                "time": int(k[0]) // 1000,
                "open": float(k[1]), "high": float(k[2]),
                "low": float(k[3]), "close": float(k[4]),
                "volume": float(k[5]),
            } for k in raw]
            
            all_candles.extend(batch)
            
            # Nếu đã đủ data hoặc đây là batch cuối
            if len(raw) < 1000 or len(all_candles) >= limit:
                break
            
            # Advance startTime để page tiếp theo
            current_start = int(raw[-1][0]) + 1
    
    return all_candles[-limit:] if len(all_candles) > limit else all_candles
```

### Ưu / Nhược điểm Backend Cache:

| | |
|---|---|
| ✅ **Shared** giữa tất cả users/browsers | ❌ Mất khi restart server (dùng TTLCache) |
| ✅ Không cần Redis/external service | ❌ Tốn ~50MB RAM server |
| ✅ Cài 1 lệnh: `pip install cachetools` | ❌ Cần `cachetools` dependency |
| ✅ Fast (~1ms lookup) | |

---

## 🏆 Quyết định cuối cùng: Kiến trúc kết hợp tối ưu

### Cho use case này (Trading Dashboard, 1 user chính):

```
Signal mở chart
     ↓
[L0] Browser IndexedDB ──HIT──→ Render ngay (0ms)
     │MISS
     ↓
[L1] Backend TTLCache ────HIT──→ Response <1ms  
     │MISS
     ↓
[L2] SQLite ohlcv_1d ────HIT──→ Response 5-20ms ← **TRICK: ohlcv_1d đã có từ Oct 2025!**
     │MISS (chỉ cho 1h candles chưa có)
     ↓
[L3] Binance API (max 3 requests, max 90d) → Lưu L2→L1→L0
```

### 🔑 Key insight: Tận dụng ohlcv_1d đã có sẵn

`ohlcv_1d` trong `trades.db` đã có **262 rows từ Oct 2025 → nay** cho BTCUSDT.
→ Chart có thể hiển thị **daily candles** cho signal bất kỳ từ Oct 2025 mà **KHÔNG cần fetch Binance**.
→ Khi user zoom vào hourly thì mới trigger L3 Binance fetch (với hard cap 90 ngày).

### Thứ tự implement (Quick Win trước):

| Priority | Task | Effort | Impact |
|---|---|---|---|
| **P0** | Frontend truyền `startTime` vào `/api/klines` | 5 phút | Giải quyết 90% vấn đề |
| **P1** | Backend: Sử dụng ohlcv_1d làm fallback | 1h | Coverage Oct 2025 → nay |
| **P2** | Frontend: IndexedDB cache cho candles | 2h | Zero latency reload |
| **P3** | Backend: TTLCache + pagination guard | 2h | Protect Binance rate limit |
| **P4** | Tạo ohlcv_1h table + background sync | 4h | Full persistent cache |

---

## ⚡ Quick Win ngay bây giờ (P0 — 5 phút)

**Vấn đề**: Frontend đang gọi:
```js
/api/klines?symbol=BTCUSDT&interval=1h&limit=300
```
→ Chỉ lấy 300 nến mới nhất (từ ~10/06).

**Fix**: Truyền `startTime` từ signal timestamp:
```js
// Trong loadSignalChart(symbol), thêm tham số signalTimestamp
const startMs = signalTimestamp 
  ? signalTimestamp - 2 * 86400 * 1000   // 2 ngày trước signal
  : Date.now() - 300 * 3600 * 1000;      // fallback hiện tại

// Binance đã hỗ trợ, backend đã hỗ trợ (line 1365 main.py)
const url = `/api/klines?symbol=${symbol}&interval=1h&limit=1000&startTime=${startMs}`;
```

Backend đã có `startTime` parameter (line 1365 `main.py`), **chỉ cần frontend truyền vào**.

---

## Quyết định: Bạn muốn implement gì?

1. **[Quick Win P0]** — Chỉ sửa frontend truyền `startTime` (5 phút, giải quyết ngay)
2. **[P0 + P1]** — P0 + tận dụng `ohlcv_1d` làm fallback (1-2h, coverage Oct 2025)
3. **[Full Stack P0→P3]** — Toàn bộ 4 tầng cache, pagination guard, IndexedDB (4-6h)
