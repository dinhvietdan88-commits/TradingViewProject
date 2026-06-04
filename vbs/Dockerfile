# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────
# VBS (VPS Buffer Service) — Lightweight Gateway Image
# ─────────────────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies with BuildKit pip cache mount
# This avoids re-downloading packages on every rebuild when requirements.txt unchanged
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy source code (separate layer — changes more often than deps)
COPY . .

# Create volume mount point for database
RUN mkdir -p /app/data

EXPOSE 5000
ENV PORT=5000 \
    HOST=0.0.0.0 \
    DB_PATH=/app/data/signal_queue.db

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

CMD ["python", "main.py"]
