# ════════════════════════════════════════════════════════════════
# Minervini AI Trading Bot — Docker Image
# Sprint 7.3: Production Deployment
# ════════════════════════════════════════════════════════════════
# Build:  docker build -t trading-bot .
# Run:    docker compose up -d
# ════════════════════════════════════════════════════════════════

# ── Stage 1: Builder ──────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build deps (some Python packages need gcc)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker layer cache)
COPY nerves/workers/trading/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu


# ── Stage 2: Runtime ─────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Labels
LABEL maintainer="PessiloGroup" \
      version="7.3" \
      description="Minervini AI Trading Bot — TradingView Webhook + Binance OCO"

# Create non-root user
RUN groupadd -r trader && useradd -r -g trader -d /app -s /sbin/nologin trader

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY nerves/workers/trading/ ./
COPY docs/knowledge/ /app/knowledge/

# Create directories for persistent data
RUN mkdir -p /app/data /app/screenshots /app/logs && \
    chown -R trader:trader /app

# Environment defaults (override via .env or docker-compose)
ENV HOST=0.0.0.0 \
    PORT=5000 \
    DB_PATH=/app/data/trades.db \
    LOG_FILE=/app/logs/trades.log \
    CHROMA_DB_PATH=/app/data/chroma_db \
    KNOWLEDGE_DIR=/app/knowledge/trading_wizard/chunks \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Expose port
EXPOSE 5000

# Health check (Docker native)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

# Switch to non-root user
USER trader

# Run with uvicorn (production)
CMD ["python", "-m", "uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "5000", \
     "--workers", "1", \
     "--log-level", "info", \
     "--access-log"]
