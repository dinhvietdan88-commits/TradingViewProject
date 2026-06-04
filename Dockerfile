# syntax=docker/dockerfile:1.7
# ════════════════════════════════════════════════════════════════
# Minervini AI Trading Bot — Docker Image
# Split-Image Architecture: Phase 6.5
# ════════════════════════════════════════════════════════════════

# ──── Stage 1: Builder Base ────────────────────────────────────
FROM python:3.11-slim AS builder-base
# PIP_NO_CACHE_DIR=off means pip WILL write to ~/.cache/pip (used by BuildKit --mount=type=cache)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# ──── Stage 2: Builder Execution ────────────────────────────────
FROM builder-base AS builder-execution
COPY nerves/workers/trading/requirements-execution.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install -r requirements-execution.txt

# ──── Stage 3: Builder Analyzer ─────────────────────────────────
FROM builder-base AS builder-analyzer
COPY nerves/workers/trading/requirements.txt .
# Note: torch CPU-only is ~250 MB installed; pip cache mount avoids re-download on rebuild
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --prefix=/install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# ── Stage 4: Runtime Base ──────────────────────────────────────
FROM python:3.11-slim AS runtime-base
LABEL maintainer="PessiloGroup" \
      version="7.3" \
      description="Minervini AI Trading Bot — Multi-stage Split Image"
RUN groupadd -r trader && useradd -r -g trader -d /app -s /sbin/nologin trader
WORKDIR /app
RUN mkdir -p /app/data /app/screenshots /app/logs && \
    chown -R trader:trader /app
ENV HOST=0.0.0.0 \
    DB_PATH=/app/data/trades.db \
    LOG_FILE=/app/logs/trades.log \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ── Stage 5: Runtime Execution ─────────────────────────────────
FROM runtime-base AS runtime-execution
COPY --from=builder-execution /install /usr/local
COPY nerves/workers/trading/ ./
RUN chown -R trader:trader /app
ENV PORT=5002
EXPOSE 5002
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5002/health')" || exit 1
USER trader
CMD ["python", "-m", "uvicorn", "execution_server:app", \
     "--host", "0.0.0.0", \
     "--port", "5002", \
     "--workers", "1", \
     "--log-level", "info", \
     "--access-log"]

# ── Stage 6: Runtime Analyzer ──────────────────────────────────
FROM runtime-base AS runtime-analyzer
COPY --from=builder-analyzer /install /usr/local
COPY nerves/workers/trading/ ./
COPY docs/knowledge/ /app/knowledge/
RUN chown -R trader:trader /app
ENV PORT=8000 \
    CHROMA_DB_PATH=/app/data/chroma_db \
    KNOWLEDGE_DIR=/app/knowledge/trading_wizard/chunks
EXPOSE 8000
# Pre-download the sentence-transformers model during build
# BuildKit cache mount preserves HuggingFace cache between rebuilds (~120 MB model)
RUN --mount=type=cache,target=/root/.cache/huggingface \
    HF_HOME=/root/.cache/huggingface \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
USER trader
CMD ["python", "workers/vps_analyzer.py"]

# ── Stage 7: Runtime Dev/Legacy (Default) ─────────────────────
# Inherits from runtime-analyzer to keep all AI/ML libs and knowledge base,
# but runs main:app on port 5000 for 100% backward compatibility.
FROM runtime-analyzer AS runtime
ENV PORT=5000 \
    CHROMA_DB_PATH=/app/data/chroma_db \
    KNOWLEDGE_DIR=/app/knowledge/trading_wizard/chunks
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1
CMD ["python", "-m", "uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "5000", \
     "--workers", "1", \
     "--log-level", "info", \
     "--access-log"]
