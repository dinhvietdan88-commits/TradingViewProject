# Triển khai Phase 2: Sentiment Layer (Phân tích Tâm lý Thị trường)

Mục tiêu: Kích hoạt Lớp Tâm lý (Sentiment Layer) bằng cách tích hợp module `sentiment_analyzer.py` đã có sẵn vào hệ thống, và bổ sung thêm các nguồn dữ liệu Fear & Greed và Funding Rate/OI để làm giàu dữ liệu cho AI.

## User Review Required

> [!IMPORTANT]
> **Tái sử dụng Code:** Tôi phát hiện hệ thống đã có sẵn module `server/analyzer/sentiment_analyzer.py` chứa logic lấy Twitter, RSS (dùng `urllib` và XML gốc mà không cần cài `feedparser`), và On-chain Glassnode (hoặc mock). Tôi sẽ tái sử dụng và mở rộng file này thay vì viết mới hoàn toàn.
> **Fear & Greed:** Tôi sẽ tích hợp thêm API miễn phí `alternative.me` để lấy điểm Fear & Greed thị trường chung.
> **Funding Rate/OI:** Thay vì phụ thuộc 100% vào Glassnode, tôi sẽ thêm luồng fallback qua `ccxt` để lấy Funding Rate và OI từ sàn. Bạn đồng ý chứ?

## Open Questions

1. **Tin tức (News):** Cấu hình `RSS_FEED_URLS` hiện tại đang nằm trong `config.py` nhưng có thể bị rỗng. Bạn có muốn cấu hình mặc định là URL của CoinTelegraph và CoinDesk không?
2. **Trọng số Điểm (Weighting):** `sentiment_analyzer.py` đang kết hợp điểm (Twitter: 35%, RSS: 35%, Glassnode: 30%). Điểm kết hợp này (`combined_score`) sẽ được gửi cho RAG AI. Chúng ta có cần áp dụng **Hard Reject** nếu `combined_score` quá thấp (VD: < -0.5) hay cứ để RAG AI tự quyết định?

## Proposed Changes

---

### Tầng Dữ liệu (Data Fetchers)

#### [MODIFY] [server/analyzer/sentiment_analyzer.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/server/analyzer/sentiment_analyzer.py)
- **FearAndGreedClient**: Thêm class mới gọi API `https://api.alternative.me/fng/` lấy điểm số Fear & Greed từ 0-100 (rồi map về thang -1.0 đến 1.0).
- **ExchangeOnchainClient**: Cập nhật hàm xử lý On-Chain để sử dụng `ccxt` (Binance) lấy `Funding Rate` và `Open Interest` cho các token Alts (khi Glassnode không hỗ trợ).
- Kết hợp cả hai dữ liệu trên vào biến `combined_score`.

#### [MODIFY] [server/config.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/server/config.py)
- Thêm default fallback cho `RSS_FEED_URLS` nếu `.env` không cung cấp (vd: `https://cointelegraph.com/rss`).

---

### Tầng Tích hợp (Integration)

#### [MODIFY] [server/workers/vps_analyzer.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/server/workers/vps_analyzer.py)
- Khởi tạo instance của `SentimentAnalyzer` trong `VpsAnalyzerWorker`.
- Ngay sau bước phân tích kỹ thuật (Trend/VCP), thực hiện `await sentiment_analyzer.analyze_symbol(symbol)`.
- Đóng gói dữ liệu kết quả vào trong biến `payload["sentiment_stats"]`.

#### [MODIFY] [server/rag.py](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/server/rag.py)
- Trích xuất `sentiment_stats` từ payload và thêm vào `stats_context` trong RAG prompt.
- Format:
  ```
  - Market Sentiment (Fear & Greed): ...
  - Social & News Sentiment: ...
  - On-chain (Glassnode/Funding): ...
  ```

## Verification Plan

### Automated Tests
- Cập nhật Unit Test `test_vps_analyzer_rag_context.py` để verify rằng `sentiment_stats` đã được gọi và tiêm đúng vào context của RAG.

### Manual Verification
- Kích hoạt một tín hiệu thử nghiệm qua `/ingest`.
- Mở file log để kiểm tra prompt gửi cho LLM đã chứa trường dữ liệu "Market Sentiment" và điểm số đầy đủ.
