## [2026-06-06] QA Audit Fixes for Telegram WebP Chart
- Fixed Pytest Collection Crash: Renamed test_reprocess.py to script_reprocess.py and updated imports.
- Fixed PIL Import Bug: Moved PIL import inside WebP detection try-block in notifier.py to avoid crashes on systems lacking libwebp.
- Cleaned Git Pollution: Unstaged and ignored test_trades.log and .secrets.baseline.

## [2026-06-06] CI/CD Test Failures & Path Traversal Scars
- Fixed Flaky Sentiment Test: `test_high_confidence_triggers_trade` in `test_ai_analyzer.py` was flaky because it evaluated `SentimentAnalyzer` which produces time-dependent mock scores (using `time.time()`). If the score was >0.5, confidence was boosted to 10, failing the `assert == 9` check. Fixed by mocking `SENTIMENT_ENABLED = False` in the test config.
- Fixed Cross-OS Windows Drive Escape (CWE-22): `test_block_windows_drive_escape` failed on Linux CI runners. On Linux, Windows-style paths like `C:\Windows\...` are treated as relative path names inside `base_dir`, bypassing `Path.relative_to` containment checks and failing to raise `SecurityError`. Fixed by explicitly identifying Windows drive letters or UNC paths on non-Windows OS (`os.name != "nt"`) and raising `SecurityError` immediately in `safe_path`.
