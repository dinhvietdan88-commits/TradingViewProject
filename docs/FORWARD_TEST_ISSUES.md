# Harvested Worktree Issues Log

This file documents the list of resolved issues and architectural warnings handled during the implementation of multi-select checkbox filters on the Forward Test & Live Positions dashboard.

---

## 🐛 Resolved Issues

The following issues were identified, investigated, and successfully resolved:

### 1. Silent CSS Syntax Discarding
* **Symptom**: Custom styles for `.header-checkbox-dropdown` and `.dropdown-menu` were completely ignored by the browser, despite being present in the served DOM.
* **Root Cause**: The `.sandbox-label:hover` rule (line 1381) was missing its closing curly brace `}`, causing the browser to swallow all style declarations below it as invalid syntax.
* **Fix**: Added the missing closing curly brace `}` at line 1385.

### 2. Duplicated Script Block (JS Compilation Failure)
* **Symptom**: The console threw a fatal `SyntaxError: Identifier 'entryExitLinesPlugin' has already been declared`, halting dashboard execution.
* **Root Cause**: An accidental duplicate block of 922 lines (chart drawing functions) was appended to the bottom of the script block (lines 7431-8352) during a previous branch merge.
* **Fix**: Sliced out the duplicate block using a Python script, preserving the trailing boot sequence.

### 3. Test Environment Leakage
* **Symptom**: Automated tests on sub-packages were failing because they tried to write to the production database.
* **Root Cause**: The developer's local environment config had `FORWARD_TEST_ENABLED = "true"`, which leaked into automated unit tests.
* **Fix**: Modified `conftest.py` to explicitly override and set `FORWARD_TEST_ENABLED = "false"`.

### 4. Mini-Chart Loading TypeError
* **Symptom**: Selecting certain trade detail rows in the table caused a `TypeError` crash in `initMiniChart` when loading cached entries.
* **Root Cause**: The caching logic failed to verify if `candles` data existed inside `TRADE_SIM_CACHE[signalId]` before attempting to render.
* **Fix**: Added a guard condition to ensure `.candles` data is loaded before bypassing API calls.

### 5. Row Expansion Stuck on Loading Spinner (JS Name Collision)
* **Symptom**: Clicking on a forward-test signal row to expand it leaves the loading spinner displaying indefinitely.
* **Root Cause**: Duplicate Javascript function declarations (`loadTradeDetailRow`, `renderStage1Data`, etc.) copied from the backtest tab silently overrode the signal-specific ones, attempting to query `expand_loading_${vbsId}` (which didn't exist in the signal table HTML structure) instead of `expand_sim_loading_${signalId}`, resulting in null reference aborts.
* **Fix**: Renamed signal-specific functions to `loadSignalDetailRow`, `renderSignalStage1Data`, `toggleSignalStage2`, `initSignalMiniChart`, `updateSignalScenarioIndicator`, and `switchSignalScenario`, and updated all calling sites in the file.

### 6. Signal Simulation Timestamp Outside Hourly Candle Range (Stale Candle Data)
* **Symptom**: Expanding a forward test signal row failed with a `400: Signal timestamp is outside hourly candle range` error from the API.
* **Root Cause**: The simulation endpoint `/api/simulate/{signal_id}` queried `scratch/vbs_replay.db` for daily/hourly candles, which only contains data up to `2026-06-23`. This failed for new, live forward-test signals with timestamps after that date.
* **Fix**: Updated `run_single_simulation_main` in `main.py` to route queries for signals with ID >= 1,000,000 to read live-synced candles from the tables `ohlcv_1d` and `ohlcv_1h` in the main database `trades.db`.

### 7. Flaky Integration Test Failure (Timeout)
* **Symptom**: The integration test `test_event_ingestion` in `test_angati_integration.py` failed with an assertion error.
* **Root Cause**: Subprocess launch of `angati.exe` for the first time took longer than the hardcoded 5-second polling timeout, causing the test to fail.
* **Fix**: Increased the SQLite database polling timeout in `test_event_ingestion` to 15.0 seconds.
