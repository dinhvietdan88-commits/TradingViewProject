## [2026-06-27] Mini-MDASH Security Remediations (TVP-005 & STA-002)
- Remediated CWE-22 Potential Path Traversal: Sanitized the `symbol` parameter using `sanitize_symbol` in `chart_generator_mpl.py` before constructing file paths to prevent directory traversal attacks.
- Remediated STA-002 Subprocess Popen: Added the inline `# nosec` comment to suppress the false-positive warning in `start_server.py`.
- Cleaned up Git Workspace: Deleted stale local branches `dev/ai/server-c-ai-core` and `dev/ai/easy-access-dashboard` to avoid merge drift, and synchronized all git worktrees to the latest `develop` state.

## [2026-06-26] UI Synchronization, Sticky Sidebar & Mini-Chart Load Fixes
- Fixed Mini-Chart Crash: Resolved a `TypeError` in `initMiniChart` on row expansion by verifying that the cached simulation summary contains full `candles` data before skipping the API fetch.
- Implemented Bi-directional Chart-Table Sync: Wired chart crosshair hover, visible time range changes, and marker clicks to dynamically highlight and auto-scroll corresponding table rows.
- Refined Sticky Layout: Adjusted `.right-sticky-col` offset to `top: 86px` and `max-height: calc(100vh - 102px)` to prevent sidebar elements from scrolling behind the sticky header.
- Handled Preset Buttons: Dynamic glow highlights preset groups on selection, clearing them automatically when individual scenario checkboxes are manually modified.
- Test Environment Isolation: Overrode `FORWARD_TEST_ENABLED = "false"` in `tests/conftest.py` to isolate test runs from developer's `.env` files.

## [2026-06-06] QA Audit Fixes for Telegram WebP Chart
- Fixed Pytest Collection Crash: Renamed test_reprocess.py to script_reprocess.py and updated imports.
- Fixed PIL Import Bug: Moved PIL import inside WebP detection try-block in notifier.py to avoid crashes on systems lacking libwebp.
- Cleaned Git Pollution: Unstaged and ignored test_trades.log and .secrets.baseline.

## [2026-06-06] CI/CD Test Failures & Path Traversal Scars
- Fixed Flaky Sentiment Test: `test_high_confidence_triggers_trade` in `test_ai_analyzer.py` was flaky because it evaluated `SentimentAnalyzer` which produces time-dependent mock scores (using `time.time()`). If the score was >0.5, confidence was boosted to 10, failing the `assert == 9` check. Fixed by mocking `SENTIMENT_ENABLED = False` in the test config.
- Fixed Cross-OS Windows Drive Escape (CWE-22): `test_block_windows_drive_escape` failed on Linux CI runners. On Linux, Windows-style paths like `C:\Windows\...` are treated as relative path names inside `base_dir`, bypassing `Path.relative_to` containment checks and failing to raise `SecurityError`. Fixed by explicitly identifying Windows drive letters or UNC paths on non-Windows OS (`os.name != "nt"`) and raising `SecurityError` immediately in `safe_path`.
