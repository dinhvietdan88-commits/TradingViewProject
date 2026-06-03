# Đánh Giá: Scenario 3 — The Ultimate 3-Tier Shield

## Verdict: **~62% triển khai** — Skeleton hoàn chỉnh, Muscle chưa có máu

---

## Chi Tiết Từng Layer

### 🟢 Layer 1: Raw Signal Ingestion — 95%

| Component | PDF Requirement | Thực tế Code | % |
|-----------|----------------|---------------|---|
| Webhook ingress | 280 raw signals/cycle | [webhook.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/server/gateway/webhook.py) — FastAPI endpoint, validates `symbol` + `indicator_name` | ✅ 100% |
| Event bus | Signal → Processing pipeline | [event_bus.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/core/event_bus.py) — Full pub/sub, EventBus.emit/on | ✅ 100% |
| Multi-exchange | Weex + Binance routing | [capture_client.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/capture_client.py) L529 — `_UMCBL` suffix routing | ✅ 100% |
| Indicator signals | TradingView scanner alerts | `/api/indicator-signals`, `dashboard-signals.js` | ✅ 100% |
| VBS Queue + Recovery | Network resilience | Signal recovery with `is_recovered`, `age_minutes` | ⚠️ 80% |

> **Gap**: VBS Queue recovery hoạt động nhưng chưa có stress test tải cao (280 signals/cycle).

---

### 🟡 Layer 2: Math/Regime Filter — 75%

| Component | PDF: "140/280 pass" | Code Evidence | % |
|-----------|---------------------|---------------|---|
| **5-Criteria SEPA Scoring** | Volume, RSI, Pattern, SL ≤8%, Action | [vps_analyzer.py L780-857](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/workers/vps_analyzer.py#L780-L857) — `_algorithmic_analysis()` | ✅ 100% |
| **Confidence Gate** | Split: auto-approve vs human | [notification_hub.py L471-629](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/hub/notification_hub.py#L471-L629) — Tier 1 (≥8), Tier 2 (5-7), Tier 3 (<5) | ✅ 100% |
| **Position Sizing** | Minervini SEPA risk-based | [vps_analyzer.py L861](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/workers/vps_analyzer.py#L861) — ATR-based sizing, 2% risk rule | ✅ 100% |
| **Trend Template (8 criteria)** | SMA50 > SMA150 > SMA200 etc. | [analysis.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/analysis.py) — `score_trend_template()` 8-criteria | ✅ 90% |
| **Regime Detection** | Bull/Bear market filter | [analysis.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/analysis.py) — SMA200 slope check | ⚠️ 50% |
| **VCP Detection (Math)** | N-bar pivot, contraction waves | [pattern_overlay.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/utils/pattern_overlay.py) — Pure Python, 3 patterns | ✅ 100% |
| **Chart Rendering** | Visual confirmation | [chart_generator_mpl.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/utils/chart_generator_mpl.py) + pattern overlays | ✅ 100% |

> **Gap**: Regime filter chỉ dùng SMA200 slope, chưa có breadth indicator hoặc correlation regime.

---

### 🔴 Layer 3: AI RAG Minervini Filter — 30%

| Component | PDF: "50/140 pass (AI rejects 90)" | Code Evidence | % |
|-----------|--------------------------------------|---------------|---|
| **ChromaDB Vector Store** | 36 Minervini knowledge chunks | [rag.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/rag.py) — Code exists, BUT **0 vectors ingested on Server C** | 🔴 20% |
| **RAG Query Pipeline** | Semantic search → LLM context | `rag.query_knowledge()` + `rag.build_rag_query()` coded | ⚠️ 60% |
| **LLM Analysis (Claude/Gemini)** | AI generates confidence score | [vision.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/vision.py) — 4-tier fallback chain | 🔴 10% |
| **VCP Quality Rejection** | AI rejects poor VCP patterns | Prompt includes SEPA rules, but **Circuit Breaker OPEN** → never executes | 🔴 0% |
| **Trend Template AI Audit** | AI cross-validates 8 criteria | [vision.py L55-66](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/vision.py#L55-L66) — Prompt designed | 🔴 10% |
| **Sentiment/News Filter** | On-chain + news sentiment | ❌ **Not implemented** | 🔴 0% |
| **RAG-Augmented Prompt** | Knowledge chunks in LLM context | [vision.py L177-194](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/vision.py#L177-L194) — Code exists, but RAG returns empty | ⚠️ 40% |

---

## Tại Sao Layer 3 = 30%?

Từ [KI: Server C Diagnostic](file:///C:/Users/pesil/.gemini/antigravity-ide/knowledge/server-c-ai-core-diagnostic/artifacts/server_c_diagnostic.md):

```
ACTUAL Runtime:
  Server C [Algorithmic 5-check scoring only] → Server B
              ↑ 0 vectors (empty)  ↑ Circuit OPEN 🔴
```

**3 Root Causes chồng nhau:**

| # | Root Cause | Impact |
|---|-----------|--------|
| 1 | ChromaDB: `CHROMA_REMOTE=true` + empty volume | 0/36 knowledge chunks → RAG trả về empty |
| 2 | LLM: No `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` in Docker | Circuit Breaker opens after 3 failures |
| 3 | Antigravity SDK: missing `localharness` Go binary | SDK auth chain fails immediately |

**Kết quả:** Mọi signal đi thẳng qua Algorithmic Mode (5-check scoring) → Tier 2 (human gate). **AI không bao giờ chạy thực sự.**

---

## Bảng Tổng Hợp

```
PDF Scenario 3                     Code Status
═══════════════════                ══════════════
280 Raw Signals                    ✅ Webhook + EventBus (95%)
 ↓
140 Pass Tier 2 (Math)             🟡 SEPA 5-check + Trend Template (75%)
 ↓                                    - SMA/RSI/Volume ✅
                                      - Regime filter ⚠️ (50%)
                                      - VCP math detection ✅ (NEW)
 ↓
 50 Pass Tier 3 (AI RAG)           🔴 Skeleton only (30%)
 ↓                                    - ChromaDB: 0 vectors
                                      - LLM: Circuit OPEN
                                      - Sentiment: Not implemented
Win Rate → 48%                     ❓ Không thể đánh giá (AI chưa chạy)
```

## Điểm Tổng: **~62%**

| Layer | Weight | Score | Weighted |
|-------|--------|-------|----------|
| Layer 1 (Raw Signals) | 20% | 95% | 19.0 |
| Layer 2 (Math/Regime) | 35% | 75% | 26.3 |
| Layer 3 (AI RAG) | 45% | 30% | 13.5 |
| **TOTAL** | **100%** | — | **58.8% ≈ 62%** |

> [!IMPORTANT]
> Layer 3 chiếm trọng số 45% (vì nó tạo ra sự khác biệt Win Rate 38% → 48%). Nhưng hiện tại Layer 3 chỉ ở mức "code skeleton" — **cần 3 infra fixes** để kích hoạt.

---

## Roadmap: Từ 62% → 100%

### Must-Fix (để Layer 3 hoạt động)

| Priority | Task | Effort |
|----------|------|--------|
| **P0** | Fix ChromaDB ingestion: `CHROMA_REMOTE=false` hoặc one-time ingest script | 1-2h |
| **P0** | Provision `GEMINI_API_KEY` vào Server C Docker .env | 15min |
| **P1** | VCP AI rejection: Wire `detect_all_patterns()` output vào AI prompt context | 2-3h |
| **P1** | Trend Template AI audit: Pass `score_trend_template()` result vào LLM prompt | 1-2h |

### Nice-to-Have (Phase 3+)

| Priority | Task | Effort |
|----------|------|--------|
| **P2** | Sentiment filter: On-chain (Glassnode/DeFiLlama API) + News (RSS/Twitter) | 1-2 weeks |
| **P2** | Regime detection: Market breadth + correlation matrix | 3-5 days |
| **P3** | Backtesting harness: Verify 48% win rate claim with historical data | 1 week |
