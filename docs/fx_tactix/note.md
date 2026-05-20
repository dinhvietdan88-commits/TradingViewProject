Tóm tắt triển khai
Branch: feat/fx-tactix → commit 133ab01 (10 files, +538 dòng)

3 lớp FX Tactix Claude (chạy song song, không thay Minervini engine):

Skill .claude/skills/fx-tactix/SKILL.md — gõ /fx-tactix <mô tả> trong Claude Code (free OAuth, không tốn API credit)
Prompt docs docs/fx_tactix/README.md + 5 templates trong docs/fx_tactix/prompts/ cho Claude Desktop manual
API endpoint server/fx_tactix.py — POST /api/fx-tactix/generate với provider routing (claude_cli → anthropic → gemini), wired vào server/main.py:228
5 levels match nguyên bản: brief / strategy / indicator / backtest_review / mtf / alert. Output Pine v5 vào pine/v2/generated/ (đã thêm vào .gitignore để user review trước khi commit).

Lưu ý: commit message đoán hooks override nhẹ message gốc của tôi, nhưng nội dung file đầy đủ và chính xác. Các file modified ngoài scope (worktrees, __pycache__) tôi để nguyên không động vào.