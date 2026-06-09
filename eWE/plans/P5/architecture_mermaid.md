# Sơ đồ Kiến trúc RAG — TradingView × Minervini AI

## 1. Luồng chính (End-to-End)

```mermaid
flowchart TD
    TV["`**📈 TradingView**
    Pine Script Alert
    VCP / Trend Template / Volume`"]

    WH["`**⚡ FastAPI Webhook**
    POST /webhook
    localhost:5000`"]

    AUTH{"`🔐 Auth
    WEBHOOK_SECRET`"}

    DB[("`💾 SQLite DB
    signals + trades`")]

    subgraph RAG_SYSTEM ["🧠 RAG System — Minervini Knowledge Base"]
        direction TB
        QB["`**Query Builder**
        build_rag_query()
        Phân loại: VCP / TT / Volume / Buy / Sell`"]

        VDB[("`**ChromaDB**
        Vector Database
        36 Chunks × 384-dim vectors
        Cosine Similarity`")]

        EMB["`**Sentence Transformers**
        paraphrase-multilingual
        MiniLM-L12-v2
        Offline - Free`"]

        TOP["`**Top 3 Chunks**
        Minervini Rules
        Relevance: 0.85-0.98`"]

        LLM["`**Claude Sonnet 4.5**
        claude-sonnet-4-5
        Anthropic API
        Max 512 tokens`"]

        ADVICE["`**AI Analysis Report**
        ✅ Chất lượng tín hiệu
        📊 Phù hợp Minervini?
        🎯 Khuyến nghị hành động
        ⚠️ Cảnh báo rủi ro`"]

        QB -->|semantic query| VDB
        VDB <-->|embed + search| EMB
        VDB -->|top-k chunks| TOP
        TOP -->|Signal + Context| LLM
        LLM --> ADVICE
    end

    BIN["`**Binance API**
    Market Order
    TESTNET / LIVE`"]

    NOT["`**notifier.py**
    Multi-channel`"]

    TG["`**📱 Telegram**
    Báo cáo đầy đủ
    + Phân tích AI`"]

    DC["`**💬 Discord**
    Backup channel`"]

    TV -->|JSON payload| WH
    WH --> AUTH
    AUTH -->|❌ 401| WH
    AUTH -->|✅ OK| DB
    DB --> QB
    ADVICE --> NOT
    DB -->|buy/sell| BIN
    BIN -->|order result| NOT
    NOT --> TG
    NOT --> DC

    style RAG_SYSTEM fill:#0f172a,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
    style LLM fill:#7c3aed,stroke:#5b21b6,color:#fff
    style VDB fill:#064e3b,stroke:#10b981,color:#fff
    style EMB fill:#1e3a5f,stroke:#3b82f6,color:#fff
    style TG fill:#0369a1,stroke:#0284c7,color:#fff
    style AUTH fill:#7f1d1d,stroke:#dc2626,color:#fff
```

---

## 2. Startup Sequence (Server Khởi động)

```mermaid
sequenceDiagram
    participant SRV as FastAPI Server
    participant CFG as config.py
    participant RAG as rag.py
    participant DISK as Disk (chroma_db/)
    participant EMB as Sentence Transformers
    participant CHUNKS as Markdown Chunks (36 files)

    SRV->>CFG: Load .env variables
    CFG-->>SRV: ANTHROPIC_API_KEY, KNOWLEDGE_DIR, RAG_ENABLED

    SRV->>RAG: init_vector_db()
    RAG->>DISK: PersistentClient(chroma_db/)
    RAG->>DISK: get_or_create_collection("minervini_knowledge")
    DISK-->>RAG: collection (existing or new)

    alt Collection đã có vectors
        RAG-->>SRV: ✅ Skip re-embedding (đã có N vectors)
    else Collection trống
        RAG->>CHUNKS: glob("chunk_*.md") → 36 files
        RAG->>EMB: SentenceTransformerEmbeddingFunction()
        loop mỗi batch 10 chunks
            RAG->>EMB: encode(documents)
            EMB-->>RAG: 384-dim vectors
            RAG->>DISK: collection.upsert(docs, vectors, ids)
        end
        RAG-->>SRV: ✅ Embedded 36 chunks vào ChromaDB
    end

    SRV-->>SRV: 🚀 Server READY (port 5000)
```

---

## 3. Webhook Processing Flow (Mỗi Alert)

```mermaid
sequenceDiagram
    participant TV as TradingView
    participant API as FastAPI /webhook
    participant DB as SQLite
    participant RAG as rag.py
    participant VDB as ChromaDB
    participant CLAUDE as Claude API
    participant BOT as notifier.py
    participant TG as Telegram

    TV->>API: POST /webhook {action, symbol, price, volume...}
    API->>API: Verify WEBHOOK_SECRET
    API->>DB: insert_signal() → signal_id

    API->>RAG: build_rag_query(symbol, action, payload)
    Note over RAG: Phân loại tín hiệu:<br/>VCP? → "VCP breakout pivot..."<br/>Volume surge? → "Volume nổ gấp đôi..."<br/>Buy? → "Điểm mua tối ưu SEPA..."

    RAG->>VDB: query_knowledge(semantic_query, n=3)
    VDB-->>RAG: [chunk_007, chunk_012, chunk_003] + scores

    RAG->>CLAUDE: generate_trading_advice(signal + 3 chunks)
    Note over CLAUDE: Prompt:<br/>- Tín hiệu: BTCUSDT BUY 65000<br/>- Volume: 1500 vs avg 800<br/>- Context: [Minervini rules...]
    CLAUDE-->>RAG: "✅ Tín hiệu MẠNH - VCP xác nhận volume..."

    RAG-->>API: advice_text

    API->>BOT: notify_all(signal_msg + advice)
    BOT->>TG: 📡 Tín hiệu + 🧠 Phân tích Minervini AI
```

---

## 4. RAG Query Logic (build_rag_query)

```mermaid
flowchart TD
    IN["`Input: symbol, action, payload`"]
    C1{"`alert_type chứa
    'vcp'?`"}
    C2{"`alert_type chứa
    'trend template'?`"}
    C3{"`volume > avg × 1.5?`"}
    C4{"`action == 'buy'?`"}
    C5{"`action == 'sell'?`"}
    DEF["`Default: SEPA general query`"]

    Q1["`'VCP Volatility Contraction
    Pattern breakout điểm mua pivot'`"]
    Q2["`'Trend Template 8 tiêu chí
    Stage 2 xác nhận'`"]
    Q3["`'Volume nổ gấp đôi tăng
    bất thường xác nhận breakout'`"]
    Q4["`'Điểm mua tối ưu SEPA
    pivot breakout Stage 2'`"]
    Q5["`'Tín hiệu bán stop loss
    trailing stop quản lý vị thế'`"]

    IN --> C1
    C1 -->|Yes| Q1
    C1 -->|No| C2
    C2 -->|Yes| Q2
    C2 -->|No| C3
    C3 -->|Yes| Q3
    C3 -->|No| C4
    C4 -->|Yes| Q4
    C4 -->|No| C5
    C5 -->|Yes| Q5
    C5 -->|No| DEF

    style Q1 fill:#065f46,color:#fff
    style Q2 fill:#065f46,color:#fff
    style Q3 fill:#92400e,color:#fff
    style Q4 fill:#1e3a5f,color:#fff
    style Q5 fill:#7f1d1d,color:#fff
```

---

## 5. Phân tầng Kiến trúc (Stack Layers)

```mermaid
block-beta
    columns 3

    block:FRONTEND["🖥️ Frontend Layer"]:3
        TV["TradingView\nPine Script Alert"]
        DASH["Dashboard\n/dashboard"]
        TGC["Telegram\nClient"]
    end

    block:GATEWAY["🔌 API Gateway"]:3
        WH["POST /webhook"]
        RAQ["GET /api/rag/query"]
        RAS["GET /api/rag/status"]
    end

    block:CORE["⚙️ Core Layer"]:3
        MAIN["main.py\nFastAPI v5.0"]
        RAGPY["rag.py\nRAG Module"]
        NOTPY["notifier.py\nMulti-channel"]
    end

    block:DATA["💾 Data Layer"]:3
        SQLITE["SQLite\nTrades DB"]
        CHROMA["ChromaDB\nVector Store"]
        FILES["Markdown\n36 Chunks"]
    end

    block:EXTERNAL["🌐 External APIs"]:3
        BINAPI["Binance API\nOrder Execution"]
        ANTHAPI["Anthropic API\nClaude Sonnet"]
        TGAPI["Telegram API\nBot Notification"]
    end

    TV --> WH
    WH --> MAIN
    MAIN --> RAGPY
    RAGPY --> CHROMA
    CHROMA --> FILES
    RAGPY --> ANTHAPI
    MAIN --> NOTPY
    NOTPY --> TGAPI
    MAIN --> SQLITE
    MAIN --> BINAPI
```
