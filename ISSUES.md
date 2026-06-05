

## [2026-06-06] QA Audit Fixes for Telegram WebP Chart
- Fixed Pytest Collection Crash: Renamed test_reprocess.py to script_reprocess.py and updated imports.
- Fixed PIL Import Bug: Moved PIL import inside WebP detection try-block in notifier.py to avoid crashes on systems lacking libwebp.
- Cleaned Git Pollution: Unstaged and ignored test_trades.log and .secrets.baseline.
