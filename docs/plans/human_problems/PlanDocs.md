Tóm tắt thay đổi
📄 Plan doc

docs/plans/claude_cli_integration.md — so sánh phương án, sơ đồ thay đổi code, test plan, rủi ro ToS
🔧 Code (b) + (c) provider switch

server/config.py:89-94 — thêm CLAUDE_CLI_PATH, CLAUDE_CLI_MODEL, CLAUDE_CLI_TIMEOUT
server/rag.py — thêm _call_claude_cli() async subprocess (prompt qua stdin, tránh giới hạn argv Windows) + nhánh provider == "claude_cli" trong generate_trading_advice()
Bật bằng env:


$env:AI_PROVIDER = "claude_cli"   # subscription, free
# hoặc
$env:AI_PROVIDER = "anthropic"    # SDK fallback, cần API key
⚡ Quick-access skill

.claude/skills/minervini-assess/SKILL.md — gõ /minervini-assess <SYMBOL> trong Claude Code → đọc chart qua MCP tradingview + tra Minervini KB local + sinh phân tích SEPA (không qua server, không tốn credit)
