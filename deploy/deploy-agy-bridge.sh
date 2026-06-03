#!/bin/bash
# ════════════════════════════════════════════════════════════════
# deploy-agy-bridge.sh — Install and start agy-bridge sidecar
# Run on Server C HOST (not inside Docker)
# ════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="agy-bridge"

echo "═══════════════════════════════════════════════"
echo " agy-bridge Sidecar — Deployment Script"
echo "═══════════════════════════════════════════════"

# ── Step 1: Verify Python ──────────────────────────────────────
echo ""
echo "🔍 Step 1: Checking Python..."
PYTHON=$(command -v python3 || true)
if [ -z "$PYTHON" ]; then
    echo "❌ Python3 not found. Install it first."
    exit 1
fi
PY_VER=$($PYTHON --version 2>&1)
echo "   Python: $PY_VER"

# ── Step 2: Install dependencies ───────────────────────────────
echo ""
echo "📦 Step 2: Installing dependencies..."
$PYTHON -m pip install --user --quiet fastapi uvicorn 2>&1 | tail -2
echo "   ✅ FastAPI + Uvicorn installed"

# ── Step 3: Install google-genai (Gemini SDK — Python 3.9+) ───
echo ""
echo "📦 Step 3: Installing google-genai SDK..."
$PYTHON -m pip install --user --quiet google-genai 2>&1 | tail -3
echo "   ✅ google-genai SDK installed"

# Check for agy binary (optional — SDK is primary now)
AGY_PATH=$(command -v agy 2>/dev/null || command -v localharness 2>/dev/null || true)
if [ -z "$AGY_PATH" ]; then
    for name in agy localharness; do
        for dir in "$HOME/.local/bin" "/usr/local/bin"; do
            if [ -x "$dir/$name" ]; then
                AGY_PATH="$dir/$name"
                break 2
            fi
        done
    done
fi
if [ -n "$AGY_PATH" ]; then
    echo "   ✅ agy binary (bonus): $AGY_PATH"
else
    echo "   ℹ️ agy CLI not found — using google-genai SDK directly (OK)"
fi

# ── Step 4: Create env file ───────────────────────────────────
echo ""
echo "🔑 Step 4: Setting up auth keys..."
ENV_FILE="$SCRIPT_DIR/.env.agy"
if [ -f "$ENV_FILE" ]; then
    echo "   .env.agy already exists. Checking keys..."
    if grep -q "ANTIGRAVITY_API_KEY=" "$ENV_FILE" && \
       ! grep -q "ANTIGRAVITY_API_KEY=$" "$ENV_FILE"; then
        echo "   ✅ ANTIGRAVITY_API_KEY is set"
    else
        echo "   ⚠️ ANTIGRAVITY_API_KEY is empty. Edit $ENV_FILE to set it."
    fi
else
    # Copy from main .env if GEMINI_API_KEY exists
    GEMINI_KEY=""
    if [ -f "$SCRIPT_DIR/.env" ]; then
        GEMINI_KEY=$(grep "^GEMINI_API_KEY=" "$SCRIPT_DIR/.env" | cut -d= -f2- || true)
    fi
    cat > "$ENV_FILE" <<EOF
# agy-bridge auth keys
# ANTIGRAVITY_API_KEY takes priority; falls back to GEMINI_API_KEY
ANTIGRAVITY_API_KEY=${GEMINI_KEY:-REPLACE_ME}
GEMINI_API_KEY=${GEMINI_KEY:-REPLACE_ME}
EOF
    chmod 600 "$ENV_FILE"
    echo "   Created $ENV_FILE (mode 600)"
    if [ -n "$GEMINI_KEY" ]; then
        echo "   ✅ Auto-copied GEMINI_API_KEY from .env"
    else
        echo "   ⚠️ Edit $ENV_FILE and set your API key"
    fi
fi

# ── Step 5: Deploy systemd service ────────────────────────────
echo ""
echo "🔧 Step 5: Installing systemd service..."
UNIT_FILE="$SCRIPT_DIR/agy-bridge.service"
if [ ! -f "$UNIT_FILE" ]; then
    echo "   ❌ agy-bridge.service not found in $SCRIPT_DIR"
    exit 1
fi

sudo cp "$UNIT_FILE" /etc/systemd/system/agy-bridge.service
sudo systemctl daemon-reload
echo "   ✅ Service unit installed"

# ── Step 6: Start service ─────────────────────────────────────
echo ""
echo "🚀 Step 6: Starting agy-bridge..."
sudo systemctl enable agy-bridge
sudo systemctl restart agy-bridge
sleep 2

if systemctl is-active --quiet agy-bridge; then
    echo "   ✅ agy-bridge is RUNNING"
else
    echo "   ❌ agy-bridge FAILED to start. Check: journalctl -u agy-bridge -n 20"
    sudo journalctl -u agy-bridge -n 10 --no-pager
    exit 1
fi

# ── Step 7: Verify ────────────────────────────────────────────
echo ""
echo "🏥 Step 7: Health check..."
sleep 1
HEALTH=$(curl -s http://localhost:9100/health 2>/dev/null || echo "UNREACHABLE")
echo "   $HEALTH" | python3 -m json.tool 2>/dev/null || echo "   $HEALTH"

# ── Step 8: Firewall ──────────────────────────────────────────
echo ""
echo "🔥 Step 8: Firewall (Docker bridge access)..."
# Allow Docker containers to reach :9100 on host
# Docker bridge is typically 172.17.0.0/16 or 172.18.0.0/16
if command -v firewall-cmd &>/dev/null; then
    # Check if docker zone exists
    if firewall-cmd --get-zones 2>/dev/null | grep -q docker; then
        sudo firewall-cmd --zone=docker --add-port=9100/tcp --permanent 2>/dev/null || true
        sudo firewall-cmd --reload 2>/dev/null || true
        echo "   ✅ Port 9100 opened in docker firewall zone"
    else
        # Fallback: allow from docker bridge subnet
        sudo firewall-cmd --direct --add-rule ipv4 filter INPUT 0 \
            -s 172.16.0.0/12 -p tcp --dport 9100 -j ACCEPT --permanent 2>/dev/null || true
        sudo firewall-cmd --reload 2>/dev/null || true
        echo "   ✅ Port 9100 opened for Docker subnets"
    fi
elif command -v ufw &>/dev/null; then
    sudo ufw allow from 172.16.0.0/12 to any port 9100 proto tcp 2>/dev/null || true
    echo "   ✅ UFW: Port 9100 opened for Docker subnets"
else
    echo "   ⚠️ No firewall manager found. Verify port 9100 is accessible from Docker."
fi

# ── Step 9: Docker connectivity test ──────────────────────────
echo ""
echo "🐳 Step 9: Docker → Bridge connectivity test..."
DOCKER_TEST=$(docker exec tradingbot-analyzer \
    python -c "import urllib.request; r=urllib.request.urlopen('http://host.docker.internal:9100/health', timeout=5); print(r.read().decode())" 2>/dev/null || echo "FAIL")
if echo "$DOCKER_TEST" | grep -q "ok"; then
    echo "   ✅ Docker container can reach agy-bridge!"
else
    echo "   ⚠️ Docker → Bridge connection failed: $DOCKER_TEST"
    echo "   Check: extra_hosts in docker-compose and firewall rules"
fi

echo ""
echo "═══════════════════════════════════════════════"
echo " ✅ Deployment complete!"
echo ""
echo " Next steps:"
echo "   1. Switch AI_PROVIDER=agy in .env"
echo "   2. Restart analyzer: docker compose -f docker-compose.server-c.yml up -d"
echo "   3. Monitor: journalctl -u agy-bridge -f"
echo "   4. Verify: docker logs tradingbot-analyzer -f | grep agy"
echo "═══════════════════════════════════════════════"
