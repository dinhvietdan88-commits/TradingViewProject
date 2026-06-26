# Branch Issues Log: dev/ai/easy-access-dashboard

This file documents the issues resolved, features implemented, and testing details for the **Telegram Dashboard Auth** (`dev/ai/easy-access-dashboard`) development stream.

---

## 🚀 Features & Changes

### 1. Telegram Dashboard Auth (`/login` command)
* **Goal**: Enable quick and secure dashboard authentication directly via the Telegram bot.
* **Implementation**:
  * Users send `/login` to the bot, which generates a short-lived token.
  * The bot responds with a quick-auth URL linking back to the dashboard.
* **Commits**: `4ed4650 feat(P10): Telegram Dashboard Auth — quick login via /login bot command`

### 2. Direct Login Link Fallback & E2E Test Fixes
* **Goal**: Ensure reliable authentication flow even if the websocket/polling channel fails, and fix E2E tests checking the login sequence.
* **Implementation**:
  * Added direct link fallback redirection logic when token verification completes.
  * Patched E2E tests in the authentication suite to match the updated redirection contract.
* **Commits**: `6fbe692 feat(telegram): add direct login link fallback and fix e2e tests`

### 3. Live Smoke Tests for Auth Endpoints
* **Goal**: Automate verification of authorization endpoints under live simulation.
* **Implementation**:
  * Created `scripts/smoke_test_auth.py` to trigger `/login` workflows and assert token validity/expiry behavior.
* **Commits**: `1bd73bd test(P10): add live smoke test script for auth endpoints`

### 4. tradingview-mcp Submodule Status Ignore
* **Goal**: Prevent dirty Git state warnings in the main workspace caused by local environment status changes within the `tradingview-mcp` submodule.
* **Implementation**:
  * Configured submodule parameters to ignore dirty files and status updates.
* **Commits**: `dbb27e5 chore: configure tradingview-mcp submodule to ignore all status changes`

---

## 🐛 Resolved Issues

* **E2E Auth Timing Crash**: Fixes intermittent test failures during login flows where headless browser tests would timeout waiting for webhooks. Resolved by adding a direct link fallback.
* **Submodule Git Pollution**: Resolved constant untracked/modified files alerts from `tradingview-mcp/` by setting ignore configurations.
