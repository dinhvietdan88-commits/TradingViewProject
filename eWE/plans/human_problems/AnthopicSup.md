Phân tích vấn đề
Hiện server đang gọi Anthropic API (cần ANTHROPIC_API_KEY) → tốn tiền + cần key. Bạn muốn "ăn ké" subscription Claude Code/Desktop đang có sẵn.

So sánh phương án
1. Skill (Claude Code Skill)
Bản chất: Markdown instructions + assets, được Claude đọc khi cần trong phiên chat của bạn.
Luồng: User gõ /minervini-assess SYMBOL trong Claude Code → skill chạy → Claude (chính phiên đang chat) sinh phân tích.
Ưu: Không cần API key, dùng đúng subscription. Tích hợp tự nhiên với MCP tradingview sẵn có.
Nhược: Chỉ chạy được khi user đang ngồi trong Claude Code. Server backend không thể "gọi" skill từ webhook/cron.
2. Plugin / Hook
Hook: Trigger shell command vào sự kiện (PreToolUse, Stop, UserPromptSubmit...). Không sinh nội dung AI — chỉ chạy script.
Plugin: Bundle skills + hooks + MCP + commands. Vẫn nằm trong Claude Code session.
Kết luận: Hook không thay thế được API call vì hook không gọi LLM. Plugin chỉ là cách đóng gói skill — cùng giới hạn như (1).
3. Claude Agent SDK / CLI headless (phương án bị bỏ sót)

claude -p "Phân tích SEPA cho AAPL..." --output-format json
Bản chất: Gọi claude CLI ở chế độ non-interactive, dùng OAuth token của subscription (không phải API key).
Ưu: Server có thể subprocess.run(["claude", "-p", prompt]) → nhận JSON → trả về frontend. Không tốn API credit.
Nhược:
Vẫn cần claude binary cài trên máy server + đã claude login.
Rate limit theo subscription (Max plan ~ vài trăm message/5h).
Anthropic ToS: subscription dành cho "personal use" — chạy server production có thể vi phạm. Tự host trên máy cá nhân thì OK.
Khuyến nghị
Vì server của bạn chạy local (TradingViewProject trên máy Windows này, không phải prod đa người dùng), phương án phù hợp nhất là kết hợp:

Use case	Phương án
User chủ động phân tích trong Claude Code	Skill /minervini-assess — gọi MCP tradingview + dùng Claude trực tiếp
Server backend cần AI (webhook signal đến)	CLI headless claude -p với OAuth subscription
Tự động hoá định kỳ	Scheduled agent (/schedule skill) hoặc cron + CLI headless
Bạn muốn tôi:

(a) Dựng skill /minervini-assess trước (nhanh, không đụng server code), hay
(b) Refactor server/rag.py để gọi claude -p CLI thay cho Anthropic SDK?
