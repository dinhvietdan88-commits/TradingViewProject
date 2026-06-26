# Branch Issues Log: dev/infra/v1.007-regime

This file documents the issues resolved, features implemented, and testing details for the **Regime Detection & Replay Infra V1.007** (`dev/infra/v1.007-regime`) development stream.

---

## 🚀 Features & Changes

### 1. Market Regime Detection
* **Goal**: Dynamically adapt strategy parameters based on current market regime (Trending vs. Ranging).
* **Implementation**:
  * **ADX Filter**: Active trend check when ADX >= 25 (Trending regime).
  * **Bollinger Bands Squeeze Filter**: Detects low-volatility compression phases (consolidation/squeezes) before breakout expansion.
  * **Time Stop**: Automatically closes trades if price remains flat inside a range after a predefined time limit (preventing capital lockup).
  * Structured and split code logic into three clean separate modules under `nerves/core/strategy/`.
* **Commits**: `84bc218 feat(v1.007): regime detection (ADX + BB squeeze + time stop) - tách 3 file`

### 2. Combined Strategies (A.007 + MIS v1/v2)
* **Goal**: Merge Minervini SEPA (MIS) filters with the new Regime Detection indicators.
* **Implementation**:
  * Enabled cross-indicator consensus: trades are executed only if both the macro regime (ADX/BB) and micro entry setup (VCP/MIS) align.
  * Added backtest simulation replay infrastructure to review composite indicators.
* **Commits**: `cceed5c feat(strategy): A.007 + MIS v1/v2 combined strategies + replay test infra`

### 3. Forward Test Log Scaffold
* **Goal**: Create structural data schema and logging stubs for tracking regime filters during live forward testing.
* **Implementation**:
  * Configured `forward_trades.db` logs to record active ADX/BB metrics at the exact timestamp of signal arrival.
* **Commits**: `396eb71 docs(v1.007): forward test log scaffold for ADX25+Trail config`

---

## 🐛 Resolved Issues

* **Regime Lag Latency**: Resolved entry delays caused by lagging ADX indicators. Implemented a fast-EMA smoothed ADX calculation method to improve signal responsiveness.
* **Time-Stop Execution Failure**: Fixed a bug in the background scheduler where trades closed via time-stop did not trigger the rollback database status update, leaving position states as "OPEN" in the engine. Added status synchronization loops to the replay harness.
