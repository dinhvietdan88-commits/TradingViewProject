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
