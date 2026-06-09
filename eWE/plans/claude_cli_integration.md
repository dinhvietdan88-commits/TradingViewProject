# Plan — Kết nối Claude qua CLI Headless (subscription) + giữ Anthropic SDK

**Ngày:** 2026-05-15
**Ngữ cảnh:** Server `rag.py` đang gọi Anthropic SDK (cần `ANTHROPIC_API_KEY` → tốn credit).
Người dùng đã có subscription Claude Code (binary `claude.exe` đã login OAuth).
Mục tiêu: chuyển sang dùng CLI subscription cho free-tier, vẫn giữ SDK làm fallback,
và thêm shortcut skill để gọi nhanh từ Claude Code.

---

## A. Phương án so sánh

| # | Phương án | Cần API key? | Server gọi được? | Rate limit |
|---|-----------|--------------|------------------|------------|
| (a) Skill / Plugin / Hook | ❌ | ❌ (chỉ trong chat) | theo plan |
| (b) **`claude -p` CLI headless** | ❌ (dùng OAuth) | ✅ subprocess | theo plan (~Max plan vài trăm msg/5h) |
| (c) **Anthropic SDK** (hiện tại) | ✅ | ✅ | theo credit |

→ **Triển khai cả (b) + (c)**: provider switch `AI_PROVIDER=claude_cli|anthropic|gemini`.

---

## B. Thay đổi code

### B1. `server/config.py`
Thêm biến môi trường:
```python
CLAUDE_CLI_PATH = os.getenv("CLAUDE_CLI_PATH", "claude")  # path tới claude.exe
CLAUDE_CLI_MODEL = os.getenv("CLAUDE_CLI_MODEL", "")       # rỗng = dùng model mặc định của subscription
CLAUDE_CLI_TIMEOUT = int(os.getenv("CLAUDE_CLI_TIMEOUT", "60"))
```
Mở rộng `AI_PROVIDER` để chấp nhận `"claude_cli"`.

### B2. `server/rag.py`
Thêm nhánh provider mới trong `generate_trading_advice()`:
```python
elif provider == "claude_cli":
    advice = await _call_claude_cli(prompt)
```
Hàm `_call_claude_cli(prompt: str) -> str`:
- Dùng `asyncio.create_subprocess_exec(claude_path, "-p", prompt, "--output-format", "text")`
- Đọc stdout, timeout = `CLAUDE_CLI_TIMEOUT`
- Trả về stdout đã strip; nếu returncode != 0 hoặc timeout → log + trả message lỗi.

**Lưu ý:**
- Không truyền prompt dài qua argv (Windows giới hạn ~32KB). Dùng `stdin`:
  `claude -p --output-format text` rồi `proc.communicate(input=prompt.encode())`.
- `claude` CLI khi không có TTY sẽ tự non-interactive mode.

### B3. Health check
Thêm vào `init_vector_db()` hoặc startup: nếu `AI_PROVIDER=claude_cli` → chạy `claude --version`,
log warning nếu không tìm thấy binary.

---

## C. Skill quick-access

File: `.claude/skills/minervini-assess.md` (project-level skill)

Slash command `/minervini-assess <SYMBOL>` để:
1. Đọc chart hiện tại qua MCP `tradingview` (`chart_get_state`, `data_get_study_values`, `quote_get`)
2. Query knowledge base bằng `server/rag.py` query_knowledge (qua subprocess Python hoặc trực tiếp)
3. Sinh phân tích SEPA bằng chính phiên Claude Code đang chat (free, không gọi API)

→ User flow: ngồi trong Claude Code, gõ `/minervini-assess AAPL` → có nhận xét ngay.

---

## D. Test plan
- [ ] `AI_PROVIDER=claude_cli` + webhook test → nhận advice từ CLI
- [ ] `AI_PROVIDER=anthropic` (fallback) vẫn chạy như cũ
- [ ] Timeout 60s không treo FastAPI worker
- [ ] Skill `/minervini-assess BTCUSDT` đọc được chart + sinh phân tích

---

## E. Rủi ro
- **ToS:** Subscription dùng "personal use" — chạy server prod đa user có thể vi phạm.
  Dự án này chạy local cá nhân → OK.
- **Latency:** CLI subprocess ~2-5s overhead so với SDK trực tiếp.
- **Rate limit:** Plan Max ~ vài trăm msg/5h. Nếu nhiều webhook → cần fallback sang SDK.
