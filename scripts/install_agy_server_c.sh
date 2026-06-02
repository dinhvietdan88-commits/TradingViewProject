#!/bin/bash
# ════════════════════════════════════════════════════════════════
# Install agy CLI + agy-bridge on Server C (Oracle Linux 9)
# ════════════════════════════════════════════════════════════════
# Usage:  sudo bash scripts/install_agy_server_c.sh
#
# Prerequisites:
#   - Oracle Linux 9 with Python 3.9+
#   - Docker and docker-compose-plugin installed
#   - User 'opt_admin' exists with docker group membership
#
# What this script does:
#   1. Installs agy CLI binary for opt_admin
#   2. Creates global symlink at /usr/local/bin/agy
#   3. Installs Python dependencies for agy-bridge
#   4. Deploys agy-bridge FastAPI service
#   5. Enables and starts systemd service
#
# NOTE: OAuth authentication requires interactive browser flow.
#       After running this script, SSH into server and run `agy`
#       once manually to complete the OAuth setup.
# ════════════════════════════════════════════════════════════════

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}   $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err()   { echo -e "${RED}[ERR]${NC}  $1"; }

# ── Pre-flight checks ──
if [[ $EUID -ne 0 ]]; then
    log_err "This script must be run as root (sudo)"
    exit 1
fi

if ! id -u opt_admin &>/dev/null; then
    log_err "User 'opt_admin' does not exist. Create it first."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BRIDGE_SRC="$SCRIPT_DIR/agy_bridge"
BRIDGE_DEST="/opt/trading/agy-bridge"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  agy CLI + agy-bridge Installation for Server C"
echo "════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Install agy CLI ──
log_info "[1/5] Installing agy CLI for opt_admin..."

if sudo -u opt_admin bash -c 'command -v agy &>/dev/null'; then
    AGY_VERSION=$(sudo -u opt_admin agy help 2>&1 | head -1 || echo "unknown")
    log_ok "agy already installed: $AGY_VERSION"
else
    # Try repository install first (preferred for OL9)
    if command -v dnf &>/dev/null; then
        log_info "Attempting repository install..."
        mkdir -p /etc/yum.repos.d/
        cat << 'REPO_EOF' > /etc/yum.repos.d/antigravity.repo
[antigravity]
name=Antigravity CLI
baseurl=https://us-central1-yum.pkg.dev/projects/antigravity-auto-updater-dev/antigravity-rpm
enabled=1
gpgcheck=0
REPO_EOF
        if dnf install -y antigravity 2>/dev/null; then
            log_ok "agy installed via dnf repository"
        else
            log_warn "Repository install failed. Falling back to install script..."
            rm -f /etc/yum.repos.d/antigravity.repo
            sudo -u opt_admin bash -c 'curl -fsSL https://antigravity.google/cli/install.sh | bash'
            log_ok "agy installed via install script"
        fi
    else
        sudo -u opt_admin bash -c 'curl -fsSL https://antigravity.google/cli/install.sh | bash'
        log_ok "agy installed via install script"
    fi
fi

# Create global symlink (accessible by ALL users, including botuser)
AGY_USER_BIN="/home/opt_admin/.local/bin/agy"
if [[ -f "$AGY_USER_BIN" ]]; then
    # Make binary readable + executable by all users
    chmod 755 "$AGY_USER_BIN"
    ln -sf "$AGY_USER_BIN" /usr/local/bin/agy
    log_ok "Symlink: /usr/local/bin/agy → $AGY_USER_BIN (accessible by all users)"
elif command -v agy &>/dev/null; then
    log_ok "agy already in PATH: $(which agy)"
else
    log_err "agy binary not found after installation"
    exit 1
fi

# Verify for opt_admin
agy help &>/dev/null && log_ok "agy CLI verified for opt_admin ✓" || log_warn "agy help returned non-zero (may need auth)"

# Verify for botuser (if exists)
if id -u botuser &>/dev/null 2>&1; then
    if sudo -u botuser /usr/local/bin/agy help &>/dev/null 2>&1; then
        log_ok "agy CLI verified for botuser ✓"
    else
        log_warn "botuser cannot run agy — check binary permissions"
        log_warn "Note: botuser needs ANTIGRAVITY_API_KEY in its environment"
    fi
else
    log_info "botuser does not exist (agy accessible via /usr/local/bin/agy for any future user)"
fi

# ── Step 2: Auth Setup ──
log_info "[2/5] Authentication Setup..."
echo ""
log_warn "═══════════════════════════════════════════════════════"
log_warn "  AUTH OPTIONS (choose one):"
log_warn ""
log_warn "  OPTION A — ANTIGRAVITY_API_KEY (PREFERRED for headless):"
log_warn "    1. Get API key from https://aistudio.google.com/apikey"
log_warn "    2. Set env var in systemd override:"
log_warn "       sudo mkdir -p /etc/systemd/system/agy-bridge.service.d"
log_warn "       echo '[Service]' | sudo tee /etc/systemd/system/agy-bridge.service.d/override.conf"
log_warn "       echo 'Environment=ANTIGRAVITY_API_KEY=AIza...' | sudo tee -a /etc/systemd/system/agy-bridge.service.d/override.conf"
log_warn "       sudo systemctl daemon-reload && sudo systemctl restart agy-bridge"
log_warn ""
log_warn "  OPTION B — OAuth (requires browser, one-time setup):"
log_warn "    ssh -L 8080:localhost:8080 opt_admin@server-c"
log_warn "    agy    # First run triggers OAuth in browser"
log_warn ""
log_warn "  NOTE: ANTIGRAVITY_API_KEY bypasses OAuth entirely."
log_warn "  MUST use Tier 1 (pay-as-you-go) to avoid quota exhaustion."
log_warn "═══════════════════════════════════════════════════════"
echo ""

# ── Step 3: Install Python dependencies ──
log_info "[3/5] Installing agy-bridge Python dependencies..."

# Check if pip3 is available
if ! command -v pip3 &>/dev/null; then
    dnf install -y python3-pip
fi

pip3 install --quiet fastapi uvicorn aiohttp pydantic 2>/dev/null \
    || pip3 install --quiet --break-system-packages fastapi uvicorn aiohttp pydantic

log_ok "Python dependencies installed"

# ── Step 4: Deploy agy-bridge ──
log_info "[4/5] Deploying agy-bridge service..."

mkdir -p "$BRIDGE_DEST"

# Copy bridge server
if [[ -f "$BRIDGE_SRC/server.py" ]]; then
    cp "$BRIDGE_SRC/server.py" "$BRIDGE_DEST/server.py"
    log_ok "Copied server.py → $BRIDGE_DEST/"
else
    log_err "Bridge source not found: $BRIDGE_SRC/server.py"
    exit 1
fi

# Set ownership
chown -R opt_admin:opt_admin "$BRIDGE_DEST"

# Install systemd service
if [[ -f "$BRIDGE_SRC/agy-bridge.service" ]]; then
    cp "$BRIDGE_SRC/agy-bridge.service" /etc/systemd/system/agy-bridge.service
    systemctl daemon-reload
    systemctl enable agy-bridge
    log_ok "systemd service installed and enabled"
else
    log_warn "systemd service file not found, creating minimal service..."
    cat << 'SVC_EOF' > /etc/systemd/system/agy-bridge.service
[Unit]
Description=agy-bridge
After=network.target

[Service]
Type=simple
User=opt_admin
WorkingDirectory=/opt/trading/agy-bridge
ExecStart=/usr/bin/python3 -m uvicorn server:app --host 127.0.0.1 --port 9100
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SVC_EOF
    systemctl daemon-reload
    systemctl enable agy-bridge
    log_ok "Minimal systemd service created and enabled"
fi

# Start the service
systemctl start agy-bridge || {
    log_warn "agy-bridge failed to start (may need OAuth setup first)"
    log_warn "Run manually after OAuth: systemctl start agy-bridge"
}

# ── Step 5: Verify ──
log_info "[5/5] Verification..."
sleep 2

if systemctl is-active --quiet agy-bridge; then
    log_ok "agy-bridge service is ACTIVE"

    # Test health endpoint
    HEALTH=$(curl -s http://127.0.0.1:9100/health 2>/dev/null || echo "{}")
    echo "  Health response: $HEALTH"

    if echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('status') else 1)" 2>/dev/null; then
        log_ok "Health endpoint responding ✓"
    else
        log_warn "Health endpoint not responding yet (service may still be starting)"
    fi
else
    log_warn "agy-bridge is not running yet"
    log_warn "Complete OAuth setup, then: systemctl start agy-bridge"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Installation Complete"
echo "════════════════════════════════════════════════════════"
echo ""
echo "  Next steps:"
echo "  1. SSH: ssh -L 8080:localhost:8080 opt_admin@server-c"
echo "  2. Auth: agy  (first run → OAuth browser flow)"
echo "  3. Test: curl http://127.0.0.1:9100/health"
echo "  4. Deploy: cd deploy && docker compose -f docker-compose.server-c.yml up -d"
echo ""
