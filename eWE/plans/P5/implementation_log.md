# P5 — Implementation Log

## Sprint: P5 RAG & Vector Database Integration
**Started:** 2026-05-03 22:58 ICT  
**Completed:** 2026-05-03 23:16 ICT  
**Engineer:** Antigravity (AI)

---

## Vấn đề phát sinh & Giải pháp

### 1. Path encoding issue (OneDrive + tiếng Việt)
- **Vấn đề**: PowerShell không xử lý được path `C:\Users\Son\OneDrive\Tài liệu\...` (UnicodeEncodeError cp1252)
- **Giải pháp**: Dùng `write_to_file` tool thay cho `run_command` để tạo file. Tool này giao tiếp qua VS Code file system API, bypass Windows encoding.
- **Lưu ý cho tương lai**: Dùng `python -X utf8` hoặc git commit từ VS Code terminal.

### 2. Git repository không tìm được
- **Vấn đề**: `HAS_GIT: False` — OneDrive không sync `.git` folder xuống local
- **Giải pháp**: Files đã được tạo thành công. Commit thủ công từ VS Code terminal.

### 3. pip install path
- **Giải pháp**: `pip install chromadb sentence-transformers anthropic --quiet` với `Cwd=C:\Users\Son` (không cần vào project dir)
- **Kết quả**: ✅ Exit code 0, packages installed thành công

---

## Files đã tạo/sửa

```
server/
├── rag.py              [NEW] RAG core module (256 lines)
├── config.py           [MODIFIED] + RAG config vars
├── main.py             [MODIFIED] v4.0 → v5.0
├── requirements.txt    [MODIFIED] + chromadb, sentence-transformers, anthropic
└── .env.example        [MODIFIED] + RAG section

docs/plans/P5/
├── README.md           [NEW] Tài liệu tổng thể P5
├── architecture_mermaid.md [NEW] 5 sơ đồ Mermaid
└── implementation_log.md   [NEW] File này
```

---

## Packages installed

| Package | Purpose |
|---------|---------|
| `chromadb>=0.5.0` | Vector Database (local, persistent) |
| `sentence-transformers>=3.0.0` | Text embedding, multilingual |
| `anthropic>=0.25.0` | Claude API Python client |

---

## Quyết định kỹ thuật

| Quyết định | Lý do |
|-----------|-------|
| ChromaDB (local) thay vì Pinecone | Không cần cloud, free, persist trên disk |
| `paraphrase-multilingual-MiniLM-L12-v2` | Hỗ trợ tiếng Việt, nhẹ (~120MB), offline |
| `claude-sonnet-4-5` | Balanced giữa speed và quality cho trading analysis |
| Lazy import cho chromadb/anthropic | Server không crash nếu packages chưa install |
| `RAG_ENABLED=true/false` toggle | Cho phép disable RAG mà không cần sửa code |
| Smart skip re-embedding | Không re-embed mỗi lần restart server |
| Batch upsert (10 docs/batch) | Tránh timeout khi embed nhiều docs |

---

## Checklist khi deploy

- [ ] Thêm `ANTHROPIC_API_KEY` vào `.env`
- [ ] Verify `RAG_ENABLED=true` trong `.env`
- [ ] Restart server và chờ embedding hoàn tất (~2-5 phút lần đầu)
- [ ] Test: `GET /api/rag/status` → `{"status": "ready", "vectors_count": 36}`
- [ ] Test: `GET /api/rag/query?q=VCP+breakout`
- [ ] Test: POST webhook và kiểm tra Telegram có phần "🧠 Phân tích Minervini AI"
- [ ] git commit: `feat(P5): integrate RAG system - ChromaDB + Claude Anthropic`
