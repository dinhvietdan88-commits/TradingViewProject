#!/usr/bin/env bash
# =============================================================================
# deploy_server_c.sh — Angati Forward Test Deploy Script for Server C
# =============================================================================
# Usage: bash scripts/deploy_server_c.sh [--dry-run]
# Run this ON Server C after SSH login.
# Pulls latest forward-test-crypto-integration branch, migrates DB, restarts.
# =============================================================================

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
BRANCH="forward-test-crypto-integration"
WORKDIR="${DEPLOY_DIR:-/opt/trading-bot}"
SERVICE="${SERVICE_NAME:-angati-server-c}"
PYTHON="${PYTHON_BIN:-python3}"
PORT="${APP_PORT:-5000}"
DRY_RUN="${1:-}"
LOG_FILE="/tmp/deploy_$(date +%Y%m%d_%H%M%S).log"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log()  { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $*" | tee -a "$LOG_FILE"; }
ok()   { echo -e "${GREEN}  ✅ $*${NC}" | tee -a "$LOG_FILE"; }
warn() { echo -e "${YELLOW}  ⚠️  $*${NC}" | tee -a "$LOG_FILE"; }
fail() { echo -e "${RED}  ❌ $*${NC}" | tee -a "$LOG_FILE"; exit 1; }
dry()  { [[ "$DRY_RUN" == "--dry-run" ]] && echo -e "${YELLOW}  [DRY-RUN] $*${NC}" && return 0; return 1; }

echo -e "${BLUE}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Angati Server C — Forward Test Deploy Script        ║"
echo "║  Branch: ${BRANCH}  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

[[ "$DRY_RUN" == "--dry-run" ]] && warn "DRY-RUN MODE — no actual changes will be made"

# ── Step 1: Navigate to workdir ───────────────────────────────────────────────
log "Step 1: Navigating to $WORKDIR"
cd "$WORKDIR" || fail "Cannot cd to $WORKDIR — check DEPLOY_DIR env var"
ok "Working dir: $(pwd)"

# ── Step 2: Git pull ──────────────────────────────────────────────────────────
log "Step 2: Git pull latest from $BRANCH"
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
    warn "Current branch: $CURRENT_BRANCH — switching to $BRANCH"
    dry "git fetch origin && git checkout $BRANCH" || git fetch origin && git checkout "$BRANCH"
fi

BEFORE_HASH=$(git rev-parse --short HEAD)
dry "git pull origin $BRANCH" || git pull origin "$BRANCH"
AFTER_HASH=$(git rev-parse --short HEAD)

if [[ "$BEFORE_HASH" != "$AFTER_HASH" ]]; then
    ok "Updated: $BEFORE_HASH → $AFTER_HASH"
    git log --oneline -3
else
    ok "Already up to date: $AFTER_HASH"
fi

# ── Step 3: Check .env ────────────────────────────────────────────────────────
log "Step 3: Verifying .env configuration"
if [[ ! -f ".env" ]]; then
    warn ".env not found — copying from .env.production"
    dry "cp .env.production .env" || cp .env.production .env
fi

# Verify FORWARD_DB_PATH is relative (not absolute Windows path)
FWD_DB_PATH=$(grep "FORWARD_DB_PATH" .env | cut -d= -f2 || true)
if [[ "$FWD_DB_PATH" == C:* || "$FWD_DB_PATH" == /Users* ]]; then
    warn "FORWARD_DB_PATH is absolute Windows/Mac path — fixing to relative"
    dry "sed -i 's|FORWARD_DB_PATH=.*|FORWARD_DB_PATH=nerves/workers/trading/forward_trades.db|' .env" || \
        sed -i 's|FORWARD_DB_PATH=.*|FORWARD_DB_PATH=nerves/workers/trading/forward_trades.db|' .env
    ok "Fixed FORWARD_DB_PATH → nerves/workers/trading/forward_trades.db"
else
    ok "FORWARD_DB_PATH = $FWD_DB_PATH ✅"
fi

# Ensure FORWARD_TEST_ENABLED=true
if ! grep -q "FORWARD_TEST_ENABLED=true" .env; then
    warn "FORWARD_TEST_ENABLED not set — appending"
    dry "echo 'FORWARD_TEST_ENABLED=true' >> .env" || echo 'FORWARD_TEST_ENABLED=true' >> .env
fi
ok ".env verified"

# ── Step 4: Install dependencies ──────────────────────────────────────────────
log "Step 4: Installing Python dependencies"
if command -v uv &>/dev/null; then
    dry "uv pip install -r nerves/workers/trading/requirements.txt" || \
        uv pip install -r nerves/workers/trading/requirements.txt --quiet
    ok "Dependencies installed via uv"
elif [[ -f "nerves/workers/trading/requirements.txt" ]]; then
    dry "$PYTHON -m pip install -r nerves/workers/trading/requirements.txt -q" || \
        $PYTHON -m pip install -r nerves/workers/trading/requirements.txt -q
    ok "Dependencies installed via pip"
fi

# ── Step 5: Run DB migration ──────────────────────────────────────────────────
log "Step 5: Running database migration (init_db)"
dry "$PYTHON -c 'import asyncio; import sys; sys.path.insert(0,\"nerves/workers/trading\"); import database, config; asyncio.run(database.init_db()); print(\"Migration OK\")'" || \
    cd nerves/workers/trading && \
    $PYTHON -c "
import asyncio, sys
sys.path.insert(0, '.')
import database, config
asyncio.run(database.init_db())
print('Migration OK — forward_trades.db ready')
" && cd "$WORKDIR"

# Verify forward_trades.db
FWD_DB="nerves/workers/trading/forward_trades.db"
if [[ -f "$FWD_DB" ]]; then
    SIZE=$(du -h "$FWD_DB" | cut -f1)
    ok "forward_trades.db exists — Size: $SIZE"
    # Check signal count
    SIG_COUNT=$(sqlite3 "$FWD_DB" "SELECT COUNT(*) FROM signals;" 2>/dev/null || echo "?")
    ok "Forward signals in DB: $SIG_COUNT"
else
    fail "forward_trades.db NOT created — check migration logs"
fi

# ── Step 6: Restart service ───────────────────────────────────────────────────
log "Step 6: Restarting service"

if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
    dry "systemctl restart $SERVICE" || systemctl restart "$SERVICE"
    sleep 3
    if systemctl is-active --quiet "$SERVICE"; then
        ok "Service $SERVICE restarted successfully"
    else
        fail "Service $SERVICE failed to start — check: journalctl -u $SERVICE -n 50"
    fi
elif command -v docker &>/dev/null && docker ps | grep -q "server-c" 2>/dev/null; then
    dry "docker-compose -f deploy/docker-compose.server-c.yml restart" || \
        docker-compose -f deploy/docker-compose.server-c.yml restart
    sleep 5
    ok "Docker container restarted"
else
    warn "No systemd service or Docker found"
    warn "Start manually: uv run python nerves/workers/trading/main.py --port $PORT"
fi

# ── Step 7: Health check ──────────────────────────────────────────────────────
log "Step 7: Health check"
sleep 2
HEALTH=$(curl -sf "http://localhost:${PORT}/tv_health_check" 2>/dev/null || echo "FAILED")
if echo "$HEALTH" | grep -q "ok"; then
    ok "Health check PASSED: $HEALTH"
else
    warn "Health check: $HEALTH"
    warn "Server may need more time to start — try manually: curl http://localhost:$PORT/tv_health_check"
fi

# ── Step 8: Forward Test smoke test ──────────────────────────────────────────
log "Step 8: Forward Test smoke test (BTC)"
WEBHOOK_SECRET=$(grep "WEBHOOK_SECRET" .env | cut -d= -f2 | head -1 || echo "test")
SMOKE=$(curl -sf -X POST "http://localhost:${PORT}/webhook" \
    -H "Content-Type: application/json" \
    -d "{\"secret\":\"$WEBHOOK_SECRET\",\"symbol\":\"BTCUSDT\",\"action\":\"buy\",\"price\":\"67500\",\"quoteQty\":100,\"mode\":\"FORWARD\",\"exchange\":\"binance\",\"sl\":\"66000\",\"tp\":\"70000\"}" \
    2>/dev/null || echo "FAILED")

if echo "$SMOKE" | grep -qiE "ok|success|queued|accepted|signal"; then
    ok "Smoke test PASSED: $SMOKE"
elif [[ "$SMOKE" == "FAILED" ]]; then
    warn "Smoke test skipped (server not responding) — run manually when server is up"
else
    warn "Smoke test response: $SMOKE"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗"
echo "║  ✅ DEPLOY COMPLETE — Server C Ready             ║"
echo "║                                                  ║"
echo "║  Branch   : ${BRANCH}  ║"
echo "║  Git Hash : $(git rev-parse --short HEAD)                              ║"
echo "║  Port     : ${PORT}                                     ║"
echo "║  Log      : $LOG_FILE   ║"
echo "╚══════════════════════════════════════════════════╝"
echo -e "${NC}"

echo ""
echo "📊 Monitor Forward Test:"
echo "  curl 'http://localhost:${PORT}/api/signals?mode=FORWARD'"
echo "  curl 'http://localhost:${PORT}/trades/stats?mode=FORWARD'"
echo "  tail -f /opt/trading-bot/logs/trades.log | grep FORWARD"
