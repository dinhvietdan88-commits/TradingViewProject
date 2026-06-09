# Phase 2: Sentiment Layer Tasks

## Tầng Dữ liệu (Data Fetchers)
- `[ ]` Cập nhật `server/config.py`: thêm default `RSS_FEED_URLS`.
- `[ ]` Sửa `server/analyzer/sentiment_analyzer.py`:
  - `[ ]` Thêm `FearAndGreedClient` (API: `alternative.me/fng`).
  - `[ ]` Thêm luồng lấy `Funding Rate` / `Open Interest` qua CCXT (ExchangeOnchainClient).
  - `[ ]` Tính toán lại `combined_score` để bao gồm các chỉ số mới.

## Tầng Tích hợp (Integration)
- `[ ]` Sửa `server/workers/vps_analyzer.py`:
  - `[ ]` Gọi `SentimentAnalyzer.analyze_symbol` bất đồng bộ trước bước RAG.
  - `[ ]` Đóng gói dữ liệu kết quả vào `payload["sentiment_stats"]`.
- `[ ]` Sửa `server/rag.py`:
  - `[ ]` Trích xuất `sentiment_stats` và chèn vào prompt của LLM.

## Kiểm thử (Verification)
- `[ ]` Cập nhật unit tests.
- `[ ]` Cập nhật `walkthrough.md`.
