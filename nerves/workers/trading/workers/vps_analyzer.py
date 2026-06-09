"""
vps_analyzer.py — AI Analyzer Worker for SERVER C (V3 Multi-Strategy).

Daemon worker that runs on SERVER C in the 3-server pipeline:
  SERVER A (VBS) → SERVER C (Analyzer) → SERVER B (Executor)

V3 Changes vs V2:
  - Multi-Strategy : Routes algorithmic fallback to the correct criteria set
                     based on signal name/source (A.007, SuperTrend, Indicator, Minervini).
  - Strategy Groups: A.007 (MA+ADX), SuperTrend (ST Flip), Indicator (passthrough),
                     Minervini SEPA (default).
V2 Changes vs V1:
  - Long Polling  : Replaces 15 s sleep-loop with /consume-long (hold up to 30 s).
                    Signal delivery latency drops from ~7.5 s to <1 s.
  - Circuit Breaker: LLMCircuitBreaker guards all generate_trading_advice() calls.
                    On timeout / 3 consecutive failures → Algorithmic Mode.
  - Dual-Mode     : Algorithmic fallback scores signals (V3: strategy-aware criteria).
                    Trades are still forwarded even when LLM is unavailable.
  - Confidence    : ai_confidence (0-100) is attached to every trade payload.
  - Failover      : LOCAL_EXECUTE_URL → SERVER_B_EXECUTE_URL (unchanged from V1).
"""

import asyncio
import logging
import os
import re
import socket
import sys
from pathlib import Path
from typing import Any

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request, Response

import config
import rag
from analyzer.sentiment_analyzer import SentimentAnalyzer
from logging_config import setup_logging

# V2: Import Circuit Breaker singleton
# The module lives in server/workers/ alongside this file.
from workers.ai_circuit_breaker import llm_breaker  # noqa: E402
from workers.liveness_monitor import _get_servers

app = FastAPI(title="Server C Health Server")


@app.on_event("startup")
async def startup_event():
    import rag

    await rag.init_vector_db()


@app.get("/health")
async def get_health():
    # 1. Liveness Status A and B
    liveness_status_server_a = "unhealthy"
    liveness_status_server_b = "unhealthy"
    try:
        servers = _get_servers()
        for s in servers:
            if "SERVER_A" in s.name.upper():
                liveness_status_server_a = "healthy" if s.is_healthy else "unhealthy"
            elif "SERVER_B" in s.name.upper():
                liveness_status_server_b = "healthy" if s.is_healthy else "unhealthy"
    except Exception as e:
        log.warning(f"Error reading liveness status: {e}")

    # 2. Disk Usage Pct
    disk_usage_pct = 0.0
    try:
        import shutil

        total, used, free = shutil.disk_usage("/")
        disk_usage_pct = round((used / total) * 100, 1)
    except Exception as e:
        log.warning(f"Error checking disk usage: {e}")

    # 3. NTP clock drift
    ntp_clock_drift_ms = 0.0
    ntp_clock_drift_detail = {}
    try:
        from workers.ntp_monitor import last_drift_results

        ntp_clock_drift_detail = last_drift_results
        drifts = [
            v["drift_ms"]
            for v in last_drift_results.values()
            if v.get("drift_ms") is not None
        ]
        if drifts:
            ntp_clock_drift_ms = float(max(drifts))
    except Exception as e:
        log.warning(f"Error checking NTP clock drift: {e}")

    # 4. Circuit Breaker Status
    circuit_breaker_status = "closed"
    try:
        circuit_breaker_status = llm_breaker.state.value
    except Exception as e:
        log.warning(f"Error checking circuit breaker status: {e}")

    # 5. RAG / ChromaDB vector count — verifies issue #56 fix at runtime
    rag_vector_count = -1  # -1 = not initialized, 0 = empty (bug), >0 = OK
    rag_status = "unknown"
    try:
        import rag as _rag

        if _rag._collection is not None:
            rag_vector_count = _rag._collection.count()
            rag_status = "ok" if rag_vector_count > 0 else "empty"
        else:
            rag_status = "not_initialized"
    except Exception as e:
        log.error(f"Error checking RAG status: {e}")
        rag_status = "error"

    return {
        "liveness_status_server_a": liveness_status_server_a,
        "liveness_status_server_b": liveness_status_server_b,
        "disk_usage_pct": disk_usage_pct,
        "ntp_clock_drift_ms": ntp_clock_drift_ms,
        "ntp_clock_drift_detail": ntp_clock_drift_detail,
        "circuit_breaker_status": circuit_breaker_status,
        "rag_vector_count": rag_vector_count,
        "rag_status": rag_status,
    }


# ── RAG Verification Endpoint (Issue #56) ──────────────────────────────────────
@app.post("/admin/rag-verify")
async def rag_verify():
    """Post-deploy verification endpoint for ChromaDB ingestion (issue #56).

    Called by:
      - CI/CD pipeline after Tier 2 deploy (curl -X POST http://localhost:8000/admin/rag-verify)
      - agy-bridge /admin/verify delegation (non-sandbox path)
      - Manual health check from Server C host for runtime evidence

    Returns status: 'ok' | 're-ingested' | 'empty' | 'error'
    vector_count must be > 0 to confirm fix is working.

    Usage:
      curl -s -X POST http://localhost:8000/admin/rag-verify | python3 -m json.tool
    """
    import rag as _rag

    result = {
        "vector_count": -1,
        "status": "unknown",
        "action_taken": "check-only",
        "rag_initialized": False,
    }

    try:
        # Step 1: Check current state
        if _rag._collection is not None:
            count = _rag._collection.count()
            result["rag_initialized"] = True
            result["vector_count"] = count

            if count > 0:
                result["status"] = "ok"
                log.info(f"[rag-verify] RAG OK: {count} vectors in ChromaDB")
                return result

            # Collection exists but empty — trigger re-ingestion
            log.warning("[rag-verify] ChromaDB empty — triggering re-ingestion...")
            result["action_taken"] = "re-ingestion"
        else:
            log.warning("[rag-verify] RAG collection not initialized — running init...")
            result["action_taken"] = "init-and-ingest"

        # Step 2: Re-run init_vector_db()
        ok = await _rag.init_vector_db()

        # Step 3: Re-check after init
        if _rag._collection is not None:
            new_count = _rag._collection.count()
            result["vector_count"] = new_count
            result["rag_initialized"] = True
            if new_count > 0:
                result["status"] = "re-ingested"
                log.info(f"[rag-verify] Re-ingestion SUCCESS: {new_count} vectors")
            else:
                result["status"] = "empty"
                result["error"] = f"init returned {ok} but still 0 vectors"
                log.error("[rag-verify] Re-ingestion FAILED: still 0 vectors")
        else:
            result["status"] = "error"
            result["error"] = "Collection still None after init"

    except Exception as e:
        result["status"] = "error"
        result["error"] = "An internal error occurred during verification."
        log.exception(f"[rag-verify] Exception: {e}")

    return result


# ── V3: Server Announce (Smart Offline) ────────────────────────────────────────


@app.post("/api/server-announce")
async def server_announce(request: Request):
    """Server B calls this when it starts up to resume health monitoring."""
    from workers.liveness_monitor import announce_server_online

    body = await request.json()
    server_name = body.get("server", "")
    if not server_name:
        return {"status": "error", "message": "'server' field required"}
    result = announce_server_online(server_name)
    if result.get("status") == "ok":
        try:
            from notifier import notify_all

            await notify_all(
                f"🟢 <b>SERVER ONLINE</b>\n\n"
                f"Server: <b>{result['server']}</b>\n"
                f"Health monitoring resumed."
            )
        except ValueError as e:
            import logging

            logging.getLogger(__name__).warning("Ignored error: %s", e)
    return result


@app.get("/api/server-status")
async def server_status():
    """Get current health monitoring status of all servers."""
    from workers.liveness_monitor import get_server_status

    return {"servers": get_server_status()}


@app.get("/metrics")
async def get_metrics(request: Request):
    accept_header = request.headers.get("accept", "")

    # Check liveness status
    la_val = 0.0
    lb_val = 0.0
    try:
        servers = _get_servers()
        for s in servers:
            if "SERVER_A" in s.name.upper():
                la_val = 1.0 if s.is_healthy else 0.0
            elif "SERVER_B" in s.name.upper():
                lb_val = 1.0 if s.is_healthy else 0.0
    except Exception as e:
        log.warning(f"Error reading liveness status for metrics: {e}")

    # Disk usage
    disk_usage_pct = 0.0
    try:
        import shutil

        total, used, free = shutil.disk_usage("/")
        disk_usage_pct = round((used / total) * 100, 1)
    except Exception as e:
        log.warning(f"Error checking disk usage for metrics: {e}")

    # NTP drift
    max_drift = 0.0
    try:
        from workers.ntp_monitor import last_drift_results

        drifts = [
            v["drift_ms"]
            for v in last_drift_results.values()
            if v.get("drift_ms") is not None
        ]
        if drifts:
            max_drift = float(max(drifts))
    except Exception as e:
        log.warning(f"Error checking NTP drift for metrics: {e}")

    # Circuit state
    cb_val = 0.0
    try:
        cb_state_str = llm_breaker.state.value
        if cb_state_str == "closed":
            cb_val = 0.0
        elif cb_state_str == "half_open":
            cb_val = 0.5
        else:  # open
            cb_val = 1.0
    except Exception as e:
        log.warning(f"Error checking circuit state for metrics: {e}")

    successes = 0
    failures = 0
    fallbacks = 0
    try:
        successes = llm_breaker.total_successes
        failures = llm_breaker.total_failures
        fallbacks = llm_breaker.total_fallbacks
    except Exception as e:
        log.warning(f"Error checking breaker counters for metrics: {e}")

    metrics_data = {
        "liveness_status_server_a": la_val,
        "liveness_status_server_b": lb_val,
        "disk_usage_pct": disk_usage_pct,
        "ntp_clock_drift_ms": max_drift,
        "circuit_breaker_state": cb_val,
        "llm_breaker_successes_total": float(successes),
        "llm_breaker_failures_total": float(failures),
        "llm_breaker_fallbacks_total": float(fallbacks),
    }

    if "application/json" in accept_header:
        return metrics_data

    # Return Prometheus formatted gauge text
    lines = [
        "# HELP liveness_status_server_a Liveness status of Server A (1.0 = healthy, 0.0 = unhealthy)",
        "# TYPE liveness_status_server_a gauge",
        f"liveness_status_server_a {la_val}",
        "# HELP liveness_status_server_b Liveness status of Server B (1.0 = healthy, 0.0 = unhealthy)",
        "# TYPE liveness_status_server_b gauge",
        f"liveness_status_server_b {lb_val}",
        "# HELP disk_usage_pct Disk usage percentage of root partition",
        "# TYPE disk_usage_pct gauge",
        f"disk_usage_pct {disk_usage_pct}",
        "# HELP ntp_clock_drift_ms NTP clock drift in milliseconds",
        "# TYPE ntp_clock_drift_ms gauge",
        f"ntp_clock_drift_ms {max_drift}",
        "# HELP circuit_breaker_state Circuit breaker state (0.0 = closed, 0.5 = half_open, 1.0 = open)",
        "# TYPE circuit_breaker_state gauge",
        f"circuit_breaker_state {cb_val}",
        "# HELP llm_breaker_successes_total Total successful LLM calls",
        "# TYPE llm_breaker_successes_total counter",
        f"llm_breaker_successes_total {successes}",
        "# HELP llm_breaker_failures_total Total failed LLM calls",
        "# TYPE llm_breaker_failures_total counter",
        f"llm_breaker_failures_total {failures}",
        "# HELP llm_breaker_fallbacks_total Total LLM circuit breaker fallbacks",
        "# TYPE llm_breaker_fallbacks_total counter",
        f"llm_breaker_fallbacks_total {fallbacks}",
    ]
    return Response(content="\n".join(lines) + "\n", media_type="text/plain")


log = logging.getLogger(__name__)


# ── Sentiment Telegram Formatting Helpers ─────────────────────────────────────
def _score_to_label(
    score: float,
    pos_thresh: float,
    neg_thresh: float,
    pos_str="Tích cực",
    neg_str="Tiêu cực",
    neut_str="Trung lập",
) -> str:
    """Map numeric score to sentiment label or emoji."""
    if score >= pos_thresh:
        return pos_str
    if score <= neg_thresh:
        return neg_str
    return neut_str


def _format_volume_amount(val: float | None) -> str:
    """Format volume or open interest with k/M suffixes."""
    if val is None or not isinstance(val, (int, float)):
        return "N/A"
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"{val / 1_000:.1f}k"
    return str(int(val))


def _format_price(price: float) -> str:
    """Format price with decimal precision based on magnitude."""
    return f"{price:,.2f}" if price >= 1 else f"{price:.6f}"


def _format_status_label(approved: bool, hold: bool) -> str:
    """Get status label for Telegram alert."""
    if approved:
        if hold:
            return "⏳ HOLD (chờ duyệt)"
        return "✅ APPROVED"
    return "❌ REJECTED"


def _format_mode_label(mode: str, provider_detail: str | None) -> str:
    """Format execution mode client description."""
    if mode == "ai":
        if provider_detail == "agy-cli":
            return "AI (agy-cli / OAuth 🔑)"
        if provider_detail == "google-genai":
            return "AI (Gemini SDK / API 📡)"
        if provider_detail == "gemini-direct":
            return "AI (Gemini Direct / Fallback ⚠️)"
        if provider_detail == "gemini-fallback":
            return "AI (Gemini Fallback ⚠️)"
        if provider_detail:
            return f"AI ({provider_detail})"
        return "AI"
    if mode == "algorithmic":
        return "Algorithmic (No AI ⚙️)"
    return mode.upper()


# ─────────────────────────────────────────────────────────────────────────────
# Worker
# ─────────────────────────────────────────────────────────────────────────────


class VpsAnalyzerWorker:
    """AI Analyzer Worker for SERVER C (V2 Hardened).

    Flow per cycle:
      1. Long-poll /consume-long on SERVER A (blocks up to 30 s)
      2. For each signal:
         a. AI Mode (Circuit CLOSED):
              RAG query ChromaDB → generate_trading_advice() with 2 s timeout
         b. Algorithmic Mode (Circuit OPEN or timeout):
              Score signal against 5 Minervini criteria
      3. Forward approved trades to LOCAL → SERVER B (failover)
      4. ACK processed signals back to SERVER A
    """

    LONG_POLL_TIMEOUT = int(os.getenv("LONG_POLL_TIMEOUT_SEC", "30"))  # seconds
    HTTP_TIMEOUT_MARGIN = 5  # extra seconds for HTTP layer beyond long-poll hold
    ALGO_MIN_SCORE = int(os.getenv("LLM_ALGORITHMIC_MIN_SCORE", "3"))  # /5
    BACKOFF_ON_ERROR_SEC = 5  # sleep after unexpected poll errors

    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        self.consumer_id = "server-c-analyzer"
        # poll_interval is kept for compatibility but only used as error back-off
        self.poll_interval = config.VPS_POLL_INTERVAL_SECONDS
        self._lock = asyncio.Lock()
        self.sentiment_analyzer = SentimentAnalyzer()

    # ── Session management ────────────────────────────────────────────────────

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or initialise the persistent aiohttp ClientSession."""
        if not self._session or self._session.closed:
            async with self._lock:
                if not self._session or self._session.closed:
                    conn = aiohttp.TCPConnector(family=socket.AF_INET)
                    self._session = aiohttp.ClientSession(connector=conn)
        return self._session

    async def close(self):
        """Close the ClientSession gracefully."""
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Long Polling ──────────────────────────────────────────────────────────

    async def _long_poll(self) -> list[dict[str, Any]]:
        """Call SERVER A's /consume-long.

        The HTTP connection is held for up to LONG_POLL_TIMEOUT + HTTP_TIMEOUT_MARGIN
        seconds. Returns immediately if signals are available; otherwise waits
        until a signal is ingested or the server-side timeout fires.

        Returns:
            List of raw signal dicts from VBS (may be empty on timeout).
        """
        url = f"{config.VPS_BUFFER_URL}/consume-long"
        params = {
            "consumer_id": self.consumer_id,
            "limit": 5,
            "timeout": self.LONG_POLL_TIMEOUT,
        }
        # Configurable: set EXCLUDE_INDICATOR_SIGNALS=true to skip indicator signals
        if os.getenv("EXCLUDE_INDICATOR_SIGNALS", "false").lower() == "true":
            params["exclude_source"] = "indicator"
        headers = {"X-Buffer-Secret": config.VPS_BUFFER_SECRET}

        # HTTP timeout = server hold time + margin to avoid premature client close
        http_timeout = aiohttp.ClientTimeout(
            connect=10,
            total=self.LONG_POLL_TIMEOUT + self.HTTP_TIMEOUT_MARGIN,
        )

        try:
            session = await self.get_session()
            async with session.get(
                url, params=params, headers=headers, timeout=http_timeout
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.error(
                        f"[VpsAnalyzer] /consume-long HTTP {resp.status}: {body[:200]}"
                    )
                    return []
                data = await resp.json()
                signals = data.get("signals", [])
                waited = data.get("waited_seconds", "?")
                if signals:
                    log.info(
                        f"[VpsAnalyzer] Long-poll: {len(signals)} signal(s) "
                        f"(waited {waited}s)"
                    )
                else:
                    log.debug(f"[VpsAnalyzer] Long-poll: empty (timeout={waited}s)")
                return signals
        except aiohttp.ServerDisconnectedError:
            log.warning("[VpsAnalyzer] Long-poll: server disconnected (reconnect)")
            return []
        except TimeoutError:
            log.warning("[VpsAnalyzer] Long-poll: client-side timeout (reconnect)")
            return []
        except Exception as exc:
            log.warning(f"[VpsAnalyzer] Long-poll connection error: {exc}")
            return []

    # ── Main daemon loop ──────────────────────────────────────────────────────

    async def _startup(self):
        # Logging configuration based on environment variable LOG_JSON_FORMAT
        json_format = os.getenv(
            "LOG_JSON_FORMAT", "false"
        ).lower() == "true" or getattr(config, "LOG_JSON_FORMAT", False)
        setup_logging(json_format=json_format)

        log.info(
            f"[VpsAnalyzer] V2 Starting (consumer={self.consumer_id}, "
            f"long_poll_timeout={self.LONG_POLL_TIMEOUT}s, "
            f"circuit_threshold={llm_breaker.failure_threshold})"
        )

        # Initialize vector database
        try:
            db_ok = await rag.init_vector_db()
            if db_ok:
                log.info(
                    "[VpsAnalyzer] RAG vector database initialized and seeded successfully."
                )
            else:
                log.error("[VpsAnalyzer] RAG vector database failed to initialize.")
        except Exception as exc:
            log.error(f"[VpsAnalyzer] Failed to initialize RAG vector database: {exc}")

        # Wire up circuit-breaker Telegram alerts once notifier is importable
        try:
            from notifier import send_telegram_alert

            llm_breaker.alert_hook = send_telegram_alert
        except Exception as exc:
            log.warning(f"[VpsAnalyzer] Could not wire circuit-breaker alert: {exc}")

        # Start APScheduler jobs
        try:
            from scheduler import start_scheduler

            start_scheduler()
            log.info("[VpsAnalyzer] APScheduler started.")
        except Exception as exc:
            log.error(f"[VpsAnalyzer] Failed to start scheduler: {exc}")

        # Start uvicorn health server in background
        import uvicorn

        config_uv = uvicorn.Config(
            app,
            host=os.getenv("HOST", "0.0.0.0"),  # noqa: S104
            port=int(os.getenv("PORT", "8000")),
            log_level="info",
        )
        server = uvicorn.Server(config_uv)
        server_task = asyncio.create_task(server.serve())
        log.info("[VpsAnalyzer] Health and metrics server started on port 8000.")
        return server, server_task

    async def _shutdown(self, server, server_task):
        print("[DEBUG] Starting graceful shutdown cleanup...", flush=True)
        log.info("[VpsAnalyzer] Starting graceful shutdown cleanup...")

        # Stop scheduler
        try:
            from scheduler import stop_scheduler

            print("[DEBUG] Stopping scheduler...", flush=True)
            stop_scheduler()
            print("[DEBUG] Scheduler stopped.", flush=True)
        except Exception as e:
            log.warning(f"[VpsAnalyzer] Error stopping scheduler: {e}")

        # Stop uvicorn server task
        print("[DEBUG] Setting server.should_exit = True...", flush=True)
        server.should_exit = True
        print("[DEBUG] Cancelling server_task...", flush=True)
        server_task.cancel()
        try:
            print("[DEBUG] Awaiting server_task...", flush=True)
            await server_task
            print("[DEBUG] Awaited server_task.", flush=True)
        except asyncio.CancelledError:
            print("[DEBUG] Caught CancelledError for server_task.", flush=True)
            pass
        log.info("[VpsAnalyzer] Health server stopped.")

        # Close ClientSession
        print("[DEBUG] Closing ClientSession...", flush=True)
        await self.close()
        print("[DEBUG] ClientSession closed.", flush=True)

        # Flush logs
        print("[DEBUG] Shutting down logging...", flush=True)
        logging.shutdown()
        print("[DEBUG] Logging shut down.", flush=True)

        log.info("[VpsAnalyzer] Shutdown complete.")
        print("[DEBUG] Shutdown complete.", flush=True)

    def _setup_signals(self, loop):
        import signal

        def handle_signal(sig, frame):
            sig_name = "SIGINT"
            if sig == signal.SIGTERM:
                sig_name = "SIGTERM"
            elif hasattr(signal, "SIGBREAK") and sig == signal.SIGBREAK:
                sig_name = "SIGBREAK"
            log.warning(f"Caught signal {sig_name}. Triggering graceful shutdown...")
            loop.call_soon_threadsafe(self._shutdown_event.set)

        signals_to_catch = [signal.SIGINT, signal.SIGTERM]
        if hasattr(signal, "SIGBREAK"):
            signals_to_catch.append(signal.SIGBREAK)

        for sig in signals_to_catch:
            try:
                signal.signal(sig, handle_signal)
            except Exception as e:
                log.warning(f"Could not register signal handler for {sig}: {e}")

    async def run(self):
        """Main daemon loop: long-poll → analyse → forward → ack.

        Runs until cancelled.
        """
        server, server_task = await self._startup()

        # Setup graceful shutdown signal handling
        self._shutdown_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        self._setup_signals(loop)

        # Fix #54 Bug 1: Create shutdown_task fresh each iteration.
        # Creating it once outside the loop caused asyncio.wait() to return immediately
        # on subsequent iterations because the done Task stayed in the set.

        while not self._shutdown_event.is_set():
            try:
                # poll_and_analyze() wraps _long_poll + _analyze_signal_v2
                # Since poll_and_analyze is an async call that might take 30s (long polling),
                # we run it as a task and await it along with the shutdown event.
                poll_task = asyncio.create_task(self.poll_and_analyze())
                shutdown_task = asyncio.create_task(self._shutdown_event.wait())

                done, pending = await asyncio.wait(
                    {poll_task, shutdown_task}, return_when=asyncio.FIRST_COMPLETED
                )

                # Cancel whichever task didn't finish first
                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass

                if self._shutdown_event.is_set():
                    break

                if poll_task in done:
                    analyzed_list = poll_task.result()

                    async def process_analyzed(analyzed: dict[str, Any]):
                        queue_id = analyzed.get("queue_id")
                        dry_run = (
                            os.getenv("ANALYZER_DRY_RUN", "false").lower() == "true"
                        )
                        try:
                            # ── Send AI analysis to Telegram ──────────────
                            await self._notify_analysis_telegram(analyzed)

                            if analyzed.get("approved"):
                                if dry_run:
                                    log.info(
                                        f"[VpsAnalyzer] 🧪 DRY RUN #{queue_id}: "
                                        f"would forward {analyzed['trade_payload']['symbol']} "
                                        f"{analyzed['trade_payload']['action']} — skipping execution"
                                    )
                                    await self._ack_signal(queue_id, "dry_run")
                                else:
                                    fwd = await self.forward_to_server_b(
                                        analyzed["trade_payload"]
                                    )
                                    if fwd.get("success"):
                                        await self._ack_signal(queue_id, "executed")
                                    else:
                                        err = fwd.get(
                                            "error", "Server B execution failed"
                                        )
                                        await self._ack_signal(queue_id, "failed", err)
                            else:
                                reason = analyzed.get("reason", "")
                                if reason:
                                    await self._ack_signal(queue_id, "rejected", reason)
                                else:
                                    await self._ack_signal(queue_id, "rejected")
                        except Exception as exc:
                            log.exception(
                                f"[VpsAnalyzer] Error processing #{queue_id}: {exc}"
                            )
                            await self._ack_signal(queue_id, "failed", str(exc)[:200])

                    if analyzed_list:
                        # return_exceptions=True prevents one failed signal from
                        # crashing the entire batch (was causing crash loop)
                        results = await asyncio.gather(
                            *(process_analyzed(a) for a in analyzed_list),
                            return_exceptions=True,
                        )
                        # Log any individual failures without crashing the loop
                        for i, result in enumerate(results):
                            if isinstance(result, Exception):
                                qid = (
                                    analyzed_list[i].get("queue_id", "?")
                                    if i < len(analyzed_list)
                                    else "?"
                                )
                                log.error(
                                    f"[VpsAnalyzer] process_analyzed #{qid} failed: {result}"
                                )

            except asyncio.CancelledError:
                log.info("[VpsAnalyzer] Daemon loop cancelled. Shutting down.")
                break
            except Exception as exc:
                log.exception(f"[VpsAnalyzer] Unexpected error in run loop: {exc}")
                await asyncio.sleep(self.BACKOFF_ON_ERROR_SEC)

        await self._shutdown(server, server_task)

    # ── Signal analysis ───────────────────────────────────────────────────────

    async def _analyze_signal(self, signal: dict[str, Any]) -> dict[str, Any] | None:
        """V1-compatible wrapper around _analyze_signal_v2.

        Returns the trade_payload dict directly (approved) or None (rejected),
        preserving the original interface expected by the test suite.

        Internal production code uses _analyze_signal_v2 for the full V2 dict.
        """
        result = await self._analyze_signal_v2(signal)
        if result.get("approved"):
            return result["trade_payload"]
        return None

    async def _analyze_signal_v2(self, signal: dict[str, Any]) -> dict[str, Any]:
        """Run AI or Algorithmic analysis on a single VBS signal.

        Returns:
            {
                "approved": bool,
                "trade_payload": dict | None,
                "reason": str,           # rejection reason when not approved
                "analysis_mode": str,    # "ai" | "algorithmic"
            }
        """
        symbol = signal.get("symbol", "")
        action = signal.get("action", "")
        price = signal.get("price")
        payload = signal.get("payload", {})
        queue_id = signal.get("queue_id")

        log.info(f"[VpsAnalyzer] Analysing #{queue_id}: {symbol} {action} @ {price}")

        # ── Validate basics ────────────────────────────────────────────────────
        try:
            price_val = float(price) if price is not None else 0.0
        except (ValueError, TypeError):
            price_val = 0.0

        if price_val <= 0:
            return {
                "approved": False,
                "reason": f"Invalid price: {price}",
                "analysis_mode": "validation",
            }

        advice = ""
        ai_conf = 0
        analysis_mode = "ai"

        # ── AI Mode (primary) ─────────────────────────────────────────────────
        if llm_breaker.is_available():
            # Calculate and inject VCP Pattern & Trend Template scorecards into prompt context
            try:
                from analysis import score_trend_template
                from capture_client import get_capture_client
                from utils.pattern_overlay import detect_all_patterns

                # Fetch daily OHLCV candles (limit to 365 to calculate SMA200 and 52-week High/Low)
                ohlcv = await get_capture_client().fetch_ohlcv(
                    symbol, timeframe="D", limit=365
                )
                if ohlcv and len(ohlcv) >= 10:
                    closes = [c[4] for c in ohlcv]
                    highs = [c[2] for c in ohlcv]
                    lows = [c[3] for c in ohlcv]

                    latest_close = closes[-1]
                    sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
                    sma150 = sum(closes[-150:]) / 150 if len(closes) >= 150 else None
                    sma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None

                    # SMA200 slope (trend) over past 20 days
                    sma200_20_ago = (
                        sum(closes[-220:-20]) / 200 if len(closes) >= 220 else None
                    )
                    sma200_slope = (
                        (sma200 - sma200_20_ago)
                        if (sma200 is not None and sma200_20_ago is not None)
                        else None
                    )

                    high_52w = max(highs[-365:]) if len(highs) >= 365 else max(highs)
                    low_52w = min(lows[-365:]) if len(lows) >= 365 else min(lows)

                    # Calculate rs_ratio relative to BTC benchmark (or default to 1.01)
                    rs_ratio = 1.01
                    btc_symbol = (
                        "BTCUSDT_UMCBL" if symbol.endswith("_UMCBL") else "BTCUSDT"
                    )
                    if symbol != btc_symbol:
                        try:
                            btc_ohlcv = await get_capture_client().fetch_ohlcv(
                                btc_symbol, timeframe="D", limit=365
                            )
                            if btc_ohlcv and len(btc_ohlcv) >= 50 and len(closes) >= 50:
                                symbol_perf = closes[-1] / closes[-50]
                                btc_closes = [c[4] for c in btc_ohlcv]
                                btc_perf = btc_closes[-1] / btc_closes[-50]
                                rs_ratio = symbol_perf / btc_perf
                        except Exception as e:
                            log.warning(
                                f"[VpsAnalyzer] Could not fetch/calculate RS ratio vs benchmark: {e}"
                            )

                    tt_res = score_trend_template(
                        price=latest_close,
                        sma50=sma50,
                        sma150=sma150,
                        sma200=sma200,
                        high_52w=high_52w,
                        low_52w=low_52w,
                        sma200_slope=sma200_slope,
                        rs_ratio=rs_ratio,
                    )

                    payload["trend_stats"] = {
                        "score": tt_res.score,
                        "stage": tt_res.stage,
                        "macro_regime": tt_res.macro_regime,
                        "summary": tt_res.summary,
                        "criteria": tt_res.criteria,
                    }

                    patterns = detect_all_patterns(ohlcv)
                    if patterns.vcp.detected:
                        payload["vcp_stats"] = {
                            "detected": True,
                            "contractions_count": len(patterns.vcp.contractions),
                            "contractions": [
                                {
                                    "high": c.pivot_high_price,
                                    "low": c.trough_price,
                                    "depth_pct": c.depth_pct,
                                    "duration_bars": c.duration_bars,
                                }
                                for c in patterns.vcp.contractions
                            ],
                            "pivot_line": patterns.vcp.pivot_line_price,
                            "quality_score": patterns.vcp.quality_score,
                        }
                    else:
                        payload["vcp_stats"] = {"detected": False}
                else:
                    payload["trend_stats"] = {
                        "error": "Insufficient OHLCV data to calculate Trend Template"
                    }
                    payload["vcp_stats"] = {"detected": False}
            except Exception as exc:
                log.warning(
                    f"[VpsAnalyzer] Gracefully handled pattern detection error for {symbol}: {exc}"
                )
                payload["trend_stats"] = {
                    "error": f"Pattern detection exception: {exc}"
                }
                payload["vcp_stats"] = {"detected": False}

            try:
                # Sentiment Analysis Integration
                try:
                    sentiment_stats = await self.sentiment_analyzer.analyze_symbol(
                        symbol
                    )
                    payload["sentiment_stats"] = sentiment_stats
                except Exception as exc:
                    log.warning(
                        f"[VpsAnalyzer] Sentiment analysis error for {symbol}: {exc}"
                    )
                    payload["sentiment_stats"] = {
                        "enabled": False,
                        "combined_score": 0.0,
                        "breakdown": {},
                    }
                signal["payload"] = payload

                rag_query = rag.build_rag_query(symbol, action, payload)
                rag_chunks = rag.query_knowledge(rag_query, n_results=config.RAG_TOP_K)

                advice = await asyncio.wait_for(
                    rag.generate_trading_advice(
                        symbol=symbol,
                        action=action,
                        price=str(price_val),
                        payload=payload,
                        rag_chunks=rag_chunks,
                    ),
                    timeout=llm_breaker.call_timeout_sec,
                )
                ai_conf = self._extract_confidence(advice)
                llm_breaker.record_success()
                log.info(
                    f"[VpsAnalyzer] AI advice #{queue_id} "
                    f"(conf={ai_conf}%): {advice[:80]}..."
                )
            except TimeoutError:
                llm_breaker.record_failure(
                    f"LLM timeout (>{llm_breaker.call_timeout_sec}s)"
                )
                log.warning(
                    f"[VpsAnalyzer] ⏰ LLM timeout for #{queue_id} → Algorithmic"
                )
                analysis_mode = "algorithmic"
            except Exception as exc:
                llm_breaker.record_failure(str(exc))
                log.warning(
                    f"[VpsAnalyzer] ❌ LLM error for #{queue_id}: {exc} → Algorithmic"
                )
                analysis_mode = "algorithmic"
        else:
            analysis_mode = "algorithmic"
            log.info(f"[VpsAnalyzer] ⚡ Circuit OPEN → Algorithmic for #{queue_id}")

        # ── Algorithmic Fallback (Multi-Strategy Router) ─────────────────────
        if analysis_mode == "algorithmic":
            advice, ai_conf = self._route_algorithmic_analysis(signal)
            # Reject if score below minimum threshold
            score = round(ai_conf / 100 * 5)  # confidence → score (0-5)
            if score < self.ALGO_MIN_SCORE:
                strategy_name = self._detect_strategy_group(signal)
                return {
                    "approved": False,
                    "reason": (
                        f"Algorithmic score {score}/{self.ALGO_MIN_SCORE} — "
                        f"insufficient {strategy_name} criteria"
                    ),
                    "analysis_mode": analysis_mode,
                    "symbol": symbol,
                    "action": action,
                    "price": price_val,
                    "trade_payload": {
                        "symbol": symbol,
                        "action": action,
                        "price": price_val,
                        "analysis": advice,
                        "ai_confidence": ai_conf,
                        "analysis_mode": analysis_mode,
                    },
                }

        # ── Parse AI approval if in AI mode ───────────────────────────────────
        if analysis_mode == "ai":
            advice_lower = advice.lower()
            # Advice starting with error prefix → reject
            if advice.startswith("⚠️"):
                return {
                    "approved": False,
                    "reason": f"RAG error: {advice[:100]}",
                    "analysis_mode": analysis_mode,
                    "symbol": symbol,
                    "action": action,
                    "price": price_val,
                    "trade_payload": {
                        "symbol": symbol,
                        "action": action,
                        "price": price_val,
                        "analysis": advice,
                        "ai_confidence": ai_conf,
                        "analysis_mode": analysis_mode,
                    },
                }

            # Hard reject if AI confidence is too low (< 30)
            if ai_conf < 30:
                return {
                    "approved": False,
                    "reason": f"Hard Reject: AI confidence too low ({ai_conf} < 30)",
                    "analysis_mode": analysis_mode,
                    "symbol": symbol,
                    "action": action,
                    "price": price_val,
                    "trade_payload": {
                        "symbol": symbol,
                        "action": action,
                        "price": price_val,
                        "analysis": advice,
                        "ai_confidence": ai_conf,
                        "analysis_mode": analysis_mode,
                    },
                }

            # 1. Prefix-based checks (high priority)
            starts_with_reject = False
            for kw in [
                "rejected",
                "wait",
                "avoid",
                "không nên",
                "không mua",
                "chờ thêm",
                "⚠️",
            ]:
                if advice_lower.startswith(kw):
                    starts_with_reject = True
                    break

            starts_with_approve = False
            for kw in ["approved", "mua", "buy", "bán", "sell", "mạnh", "strong"]:
                if advice_lower.startswith(kw):
                    starts_with_approve = True
                    break

            # 2. Substring/word boundary checking
            rejected_kw = [
                "⚠️",
                "chờ thêm",
                "không nên",
                "không mua",
                "rejected",
                "wait",
                "avoid",
            ]
            approved_kw = ["mua", "buy", "bán", "sell", "mạnh", "strong", "approved"]

            def has_keyword(text, kw):
                if kw == "⚠️":
                    return kw in text
                if kw.isalnum():
                    pattern = rf"\b{re.escape(kw)}\b"
                    return bool(re.search(pattern, text))
                else:
                    return kw in text

            is_rejected = starts_with_reject or any(
                has_keyword(advice_lower, kw) for kw in rejected_kw
            )
            is_approved = starts_with_approve or any(
                has_keyword(advice_lower, kw) for kw in approved_kw
            )

            if is_rejected or not is_approved:
                return {
                    "approved": False,
                    "reason": "AI analysis rejected signal"
                    if is_rejected
                    else "AI analysis did not approve signal",
                    "analysis_mode": analysis_mode,
                    "symbol": symbol,
                    "action": action,
                    "price": price_val,
                    "trade_payload": {
                        "symbol": symbol,
                        "action": action,
                        "price": price_val,
                        "analysis": advice,
                        "ai_confidence": ai_conf,
                        "analysis_mode": analysis_mode,
                    },
                }

        # ── Position sizing ────────────────────────────────────────────────────
        qty = self._calculate_position_size(price_val, action, signal=signal)
        sl_price, tp_price = self._calculate_sl_tp(price_val, action, signal=signal)

        # ── Programmatic Guardrails ───────────────────────────────────────────
        # 1. Trend Template score < 5/8
        tt_score = payload.get("trend_stats", {}).get("score")
        if (
            action.lower() in ("buy", "long")
            and tt_score is not None
            and isinstance(tt_score, (int, float))
            and tt_score < 5
        ):
            return {
                "approved": False,
                "reason": f"Programmatic guardrail: Trend Template score {tt_score}/8 is below minimum threshold (5/8)",
                "analysis_mode": analysis_mode,
                "symbol": symbol,
                "action": action,
                "price": price_val,
                "trade_payload": {
                    "symbol": symbol,
                    "action": action,
                    "price": price_val,
                    "qty": qty,
                    "sl": sl_price,
                    "tp": tp_price,
                    "analysis": advice,
                    "ai_confidence": ai_conf,
                    "analysis_mode": analysis_mode,
                },
            }

        # 2. Stop-Loss > 8%
        if sl_price > 0 and price_val > 0:
            risk_pct = abs(price_val - sl_price) / price_val * 100
            if round(risk_pct, 4) > 8.0:
                return {
                    "approved": False,
                    "reason": f"Programmatic guardrail: Stop Loss risk {risk_pct:.2f}% exceeds maximum threshold (8%)",
                    "analysis_mode": analysis_mode,
                    "symbol": symbol,
                    "action": action,
                    "price": price_val,
                    "trade_payload": {
                        "symbol": symbol,
                        "action": action,
                        "price": price_val,
                        "qty": qty,
                        "sl": sl_price,
                        "tp": tp_price,
                        "analysis": advice,
                        "ai_confidence": ai_conf,
                        "analysis_mode": analysis_mode,
                    },
                }

        trade_payload = {
            "symbol": symbol,
            "action": action,
            "price": price_val,
            "qty": qty,
            "sl": sl_price,
            "tp": tp_price,
            "analysis": advice,
            "ai_confidence": ai_conf,
            "analysis_mode": analysis_mode,
            "risk_per_trade": config.RISK_PER_TRADE,
            "stop_loss_pct": config.STOP_LOSS_PCT,
            "exchange": payload.get("exchange", config.DEFAULT_EXCHANGE),
            "hold_for_approval": (50 <= ai_conf <= 79),
        }

        log.info(
            f"[VpsAnalyzer] #{queue_id} APPROVED [{analysis_mode}]: "
            f"{symbol} {action} qty={qty} sl={sl_price} tp={tp_price} "
            f"conf={ai_conf}%"
        )

        return {
            "approved": True,
            "trade_payload": trade_payload,
            "analysis_mode": analysis_mode,
        }

    # ── Telegram notification for AI analysis ──────────────────────────────────

    async def _render_chart_for_signal(self, analyzed: dict[str, Any]) -> str | None:
        """Render a Matplotlib chart with Entry/SL/TP overlay for a signal.

        Returns the file path to the generated PNG, or None on failure.
        """
        try:
            from capture_client import get_capture_client

            tp = analyzed.get("trade_payload") or {}
            payload = analyzed.get("payload") or tp.get("payload") or {}

            symbol = analyzed.get("symbol") or tp.get("symbol")
            if not symbol or symbol == "?":
                return None

            analyzed.get("action") or tp.get("action") or "buy"
            price = analyzed.get("price") or tp.get("price")

            # Build drawings from price levels
            drawings = []
            if price:
                try:
                    price_val = float(str(price).replace(",", ""))
                    if price_val > 0:
                        drawings.append(
                            {"price": price_val, "label": "Entry", "color": "#26a69a"}
                        )
                except (ValueError, TypeError):
                    pass

            # Try to get SL/TP from trade_payload or original payload
            sl = tp.get("sl") or payload.get("sl")
            if sl:
                try:
                    sl_val = float(str(sl).replace(",", ""))
                    if sl_val > 0:
                        drawings.append(
                            {"price": sl_val, "label": "SL", "color": "#ef5350"}
                        )
                except (ValueError, TypeError):
                    pass

            tp_price = tp.get("tp") or payload.get("tp")
            if tp_price:
                try:
                    tp_val = float(str(tp_price).replace(",", ""))
                    if tp_val > 0:
                        drawings.append(
                            {"price": tp_val, "label": "TP", "color": "#2962ff"}
                        )
                except (ValueError, TypeError):
                    pass

            # Build strategy table from payload/trend_stats/vcp_stats
            strategy_table = None
            rows = []

            trend_stats = payload.get("trend_stats") or {}
            vcp_stats = payload.get("vcp_stats") or {}

            tt_score = trend_stats.get("score")
            if tt_score is not None:
                rows.append(("TT Score", f"{tt_score}/8"))

            tt_stage = trend_stats.get("stage")
            if tt_stage:
                rows.append(("Stage", str(tt_stage)))

            vcp_detected = vcp_stats.get("detected")
            if vcp_detected is not None:
                rows.append(("VCP", "Detected ✅" if vcp_detected else "Not found"))

            volume = payload.get("volume")
            volume_avg = payload.get("volume_avg")
            if volume and volume_avg:
                try:
                    vol_ratio = float(volume) / float(volume_avg)
                    rows.append(("Vol Ratio", f"{vol_ratio:.1f}x"))
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

            if rows:
                strategy_table = {"title": "SEPA Analysis", "rows": rows}

            # Resolve timeframe
            timeframe = payload.get("timeframe") or payload.get("interval") or "D"

            client = get_capture_client()
            result = await client.capture_screenshot(
                symbol=symbol,
                timeframe=timeframe,
                drawings=drawings or None,
                strategy_table=strategy_table,
                method="mplfinance",
            )

            if result.success and result.file_path:
                log.info(
                    f"[VpsAnalyzer] 📊 Chart rendered for {symbol} → {result.file_path}"
                )
                return result.file_path
            else:
                log.warning(
                    f"[VpsAnalyzer] Chart render failed for {symbol}: {result.error}"
                )
        except Exception as exc:
            log.warning(f"[VpsAnalyzer] Chart rendering skipped for {symbol}: {exc}")

        return None

    def _format_telegram_sentiment(
        self, sentiment_stats: dict[str, Any], symbol: str, exchange_name: str
    ) -> list[str]:
        """Construct visual sentiment metrics breakdown (Option B)."""
        if not sentiment_stats or not sentiment_stats.get("enabled"):
            return []

        combined_score = sentiment_stats.get("combined_score", 0.0)
        breakdown = sentiment_stats.get("breakdown", {})
        sources = sentiment_stats.get("sources", {})
        raw_metrics = sentiment_stats.get("raw_metrics", {})

        # Slider: [🔴───🎯───🟢]
        val_norm = (combined_score + 1.0) / 2.0
        idx = max(0, min(6, int(round(val_norm * 6))))
        track = ["─"] * 7
        track[idx] = "🎯"
        slider = f"[🔴{''.join(track)}🟢]"

        sent_label = _score_to_label(combined_score, 0.25, -0.25)

        lines = [
            "",
            f"📊 <b>Tâm lý:</b> <code>{slider} {combined_score:+.2f} ({sent_label})</code>",
        ]

        # Twitter
        t_score = breakdown.get("twitter", 0.0)
        t_label = _score_to_label(t_score, 0.15, -0.15)
        lines.append(
            f"├── 🐦 <b>Social (Twitter):</b> <code>{t_score:+.2f}</code> ({t_label})"
        )

        # RSS News
        r_score = breakdown.get("rss", 0.0)
        r_label = _score_to_label(r_score, 0.15, -0.15)
        lines.append(
            f"├── 📰 <b>News (RSS Feeds):</b> <code>{r_score:+.2f}</code> ({r_label})"
        )

        # Fear & Greed
        fng_val = raw_metrics.get("fng_value")
        if fng_val is not None:
            fng_class = str(raw_metrics.get("classification", "Neutral"))
            if "mock" in fng_class.lower():
                fng_class = fng_class.replace("Mock ", "").replace("mock ", "")
            fng_emoji = _score_to_label(
                fng_val, 55, 45, pos_str="🟢", neg_str="🔴", neut_str="🟡"
            )
            lines.append(
                f"├── 📈 <b>Fear & Greed:</b> {fng_emoji} {fng_class} ({int(fng_val)})"
            )

        # Glassnode
        clean_symbol = symbol.split(":")[-1].split(".")[0].split("_")[0].upper()
        base_symbol = clean_symbol.replace("USDT", "")
        glassnode_active = sources.get(
            "glassnode"
        ) != "glassnode_not_applicable" and base_symbol in ("BTC", "ETH")
        if glassnode_active:
            g_score = breakdown.get("glassnode", 0.0)
            g_emoji = _score_to_label(
                g_score, 0.4, -0.2, pos_str="🟢", neg_str="🔴", neut_str="🟡"
            )
            lines.append(
                f"├── 🔍 <b>Glassnode NUPL:</b> {g_emoji} <code>{g_score:+.2f}</code>"
            )

        # CCXT Market Funding (always last)
        funding_rate = raw_metrics.get("funding_rate", 0.0) or 0.0
        oi_val = raw_metrics.get("open_interest")
        bias_emoji = _score_to_label(
            funding_rate, 0.0001, -0.0001, pos_str="🟢", neg_str="🔴", neut_str="🟡"
        )
        bias_text = _score_to_label(
            funding_rate,
            0.0001,
            -0.0001,
            pos_str="Long Bias",
            neg_str="Short Bias",
            neut_str="Neutral",
        )

        oi_str = _format_volume_amount(oi_val)
        lines.append(
            f"└── 💳 <b>Market Funding:</b> {bias_emoji} {bias_text} ({exchange_name}: {funding_rate * 100:.4f}% / OI: {oi_str})"
        )
        return lines

    async def _notify_analysis_telegram(self, analyzed: dict[str, Any]):
        """Send AI analysis result to Telegram.

        Fire-and-forget: Telegram errors won't block the trade pipeline.
        """
        try:
            from notifier import send_telegram_alert, send_telegram_photo
        except ImportError:
            return  # notifier not available

        queue_id = analyzed.get("queue_id", "?")
        approved = analyzed.get("approved", False)
        tp = analyzed.get("trade_payload", {})
        mode = analyzed.get("analysis_mode", tp.get("analysis_mode", "unknown"))
        reason = analyzed.get("reason", "")

        symbol = tp.get("symbol", analyzed.get("symbol", "?"))
        action = tp.get("action", analyzed.get("action", "?"))
        price = tp.get("price", analyzed.get("price", 0))
        conf = tp.get("ai_confidence", 0)
        analysis = tp.get("analysis", "")

        # Extract provider detail from advice suffix
        provider_detail = None
        if analysis:
            import re as _re

            match = _re.search(r"\[Provider: (.*?)\]$", analysis)
            if match:
                provider_detail = match.group(1)
                analysis = _re.sub(r"\n\n\[Provider: (.*?)\]$", "", analysis)

        # Status & Mode formatting via helpers
        hold = tp.get("hold_for_approval", False)
        status = _format_status_label(approved, hold)
        mode_icon = "🧠" if mode == "ai" else "📊"
        mode_label = _format_mode_label(mode, provider_detail)
        formatted_price = _format_price(price)

        # Build message
        lines = [
            f"{'━' * 28}",
            f"{mode_icon} <b>AI Core Analysis #{queue_id}</b>",
            f"{'━' * 28}",
            "",
            f"📌 <b>{symbol}</b> | <code>{action.upper()}</code> @ <code>{formatted_price}</code>",
            f"🎯 Confidence: <b>{conf}%</b>  |  Client: <b>{mode_label}</b>",
            f"📋 Status: <b>{status}</b>",
        ]

        # Sentiment Layer (Option B: Visual Metrics)
        exchange_name = tp.get("exchange", config.DEFAULT_EXCHANGE).upper()
        sentiment_lines = self._format_telegram_sentiment(
            analyzed, symbol, exchange_name
        )
        if sentiment_lines:
            lines.extend(sentiment_lines)

        if approved and tp:
            qty = tp.get("qty", 0)
            sl = tp.get("sl", 0)
            tp_price = tp.get("tp", 0)
            risk = tp.get("risk_per_trade", 0)
            formatted_sl = _format_price(sl)
            formatted_tp = _format_price(tp_price)
            lines.extend(
                [
                    "",
                    "💰 <b>Position:</b>",
                    f"   • Qty: <code>{qty}</code>",
                    f"   • SL: <code>{formatted_sl}</code>  |  TP: <code>{formatted_tp}</code>",
                    f"   • Risk/Trade: <code>{risk:.1%}</code>",
                ]
            )

        if not approved and reason:
            lines.extend(
                [
                    "",
                    f"📝 <b>Reason:</b> {reason[:200]}",
                ]
            )

        # AI advice excerpt (max 300 chars)
        if analysis:
            excerpt = analysis[:300].replace("\n", " ")
            if len(analysis) > 300:
                excerpt += "…"
            lines.extend(
                [
                    "",
                    f"💬 <b>AI:</b> {excerpt}",
                ]
            )

        lines.append(f"\n{'━' * 28}")

        message = "\n".join(lines)

        try:
            chart_path = await self._render_chart_for_signal(analyzed)
            if chart_path:
                await asyncio.to_thread(send_telegram_photo, chart_path, message)
                log.info(
                    f"[VpsAnalyzer] Telegram photo notification sent for #{queue_id}"
                )
            else:
                await send_telegram_alert(message)
                log.info(
                    f"[VpsAnalyzer] Telegram text notification sent for #{queue_id}"
                )
        except Exception as e:
            log.warning(
                f"[VpsAnalyzer] Telegram notification failed for #{queue_id}: {e}"
            )

    # ── Algorithmic analysis (Minervini SEPA) ─────────────────────────────────

    def _algorithmic_analysis(self, signal: dict[str, Any]) -> tuple[str, int]:
        """Score signal against 5 Minervini Trend Template criteria.

        Returns:
            (advice_text, confidence_0_to_100)
        """
        payload = signal.get("payload", {})
        action = signal.get("action", "")
        price = float(signal.get("price") or 0)

        checks: list[str] = []
        score = 0
        total = 5

        # 1. Volume surge (>150% of average = Breakout confirmation)
        volume = float(payload.get("volume", 0) or 0)
        volume_avg = float(payload.get("volume_avg", 0) or 0)
        if volume_avg > 0 and volume > volume_avg * 1.5:
            checks.append("✅ Volume >150% trung bình (Breakout confirmation)")
            score += 1
        elif volume_avg > 0:
            checks.append(f"⚠️ Volume = {volume / volume_avg * 100:.0f}% trung bình")
        else:
            checks.append("⬜ Volume data không có")

        # 2. RSI momentum (50–80 = positive zone)
        rsi = float(payload.get("rsi", 0) or 0)
        if 50 < rsi < 80:
            checks.append(f"✅ RSI = {rsi:.0f} (Vùng momentum tích cực)")
            score += 1
        elif rsi >= 80:
            checks.append(f"⚠️ RSI = {rsi:.0f} (Quá mua — cẩn thận)")
        elif rsi > 0:
            checks.append(f"⬜ RSI = {rsi:.0f} (Chưa đủ momentum)")

        # 3. Pattern type (VCP / Breakout preferred)
        alert_type = (payload.get("alert_type") or "").lower()
        if "vcp" in alert_type or "breakout" in alert_type:
            checks.append("✅ Pattern: VCP/Breakout detected")
            score += 1
        elif "trend" in alert_type:
            checks.append("✅ Pattern: Trend Template confirmed")
            score += 1
        else:
            checks.append(f"⬜ Pattern: {alert_type or 'generic'}")

        # 4. Stop-loss distance ≤ 8% (Minervini rule)
        sl = float(payload.get("sl", 0) or 0)
        if sl > 0 and price > 0:
            risk_pct = abs(price - sl) / price * 100
            if risk_pct <= 8:
                checks.append(f"✅ Risk = {risk_pct:.1f}% (≤ 8% Minervini rule)")
                score += 1
            else:
                checks.append(f"⚠️ Risk = {risk_pct:.1f}% (> 8% — vượt ngưỡng)")

        # 5. Valid action
        if action.lower() in ("buy", "sell"):
            checks.append(f"✅ Action = {action.upper()} (hợp lệ)")
            score += 1

        confidence = int(score / total * 100) if total > 0 else 50

        verdict = (
            "✅ PASS — Đủ điều kiện đặt lệnh"
            if score >= self.ALGO_MIN_SCORE
            else "❌ FAIL — Chưa đủ tiêu chí"
        )
        advice = (
            f"⚡ **ALGORITHMIC MODE** (LLM unavailable)\n\n"
            f"📊 Điểm: {score}/{total} ({confidence}%)\n\n"
            + "\n".join(checks)
            + f"\n\n{verdict}"
        )

        return advice, confidence

    # ── Multi-Strategy Router (V3) ────────────────────────────────────────────

    def _detect_strategy_group(self, signal: dict[str, Any]) -> str:
        """Detect which strategy group a signal belongs to.

        Returns a human-readable group name for logging/rejection messages.
        """
        payload = signal.get("payload", {})
        if isinstance(payload, str):
            import json as _json

            try:
                payload = _json.loads(payload)
            except Exception:
                payload = {}

        signal_name = str(
            signal.get("signal", "") or payload.get("signal", "") or ""
        ).upper()
        source = str(
            signal.get("source", "") or payload.get("source", "") or ""
        ).lower()
        indicator_name = str(
            payload.get("indicator_name", "") or payload.get("indicator", "") or ""
        ).upper()

        # Group A: A.007 (MA Crossover + ADX Regime)
        if any(k in signal_name for k in ["A007", "MIS_AUTO", "ADX", "FWD"]):
            return "A.007 (MA Crossover + ADX)"

        # Group C: SuperTrend
        if any(
            k in signal_name for k in ["SUPERTREND", "ST_FLIP", "ST_BULL", "ST_BEAR"]
        ):
            return "SuperTrend"
        if "SUPERTREND" in indicator_name:
            return "SuperTrend"

        # Group B: MIS Indicator
        if source == "indicator":
            return f"Indicator ({indicator_name or 'unknown'})"
        if "MIS" in signal_name and "AUTO" not in signal_name:
            return "MIS Indicator"

        # Group E: Default = Minervini SEPA
        return "Minervini SEPA"

    def _route_algorithmic_analysis(self, signal: dict[str, Any]) -> tuple[str, int]:
        """Route to the correct algorithmic criteria based on signal source.

        V3 Multi-Strategy Router: Instead of always applying 5 Minervini
        checks, identifies the signal's strategy group and applies
        appropriate sanity checks.

        Returns:
            (advice_text, confidence_0_to_100)
        """
        group = self._detect_strategy_group(signal)

        if group.startswith("A.007"):
            return self._algo_a007(signal)
        if group.startswith("SuperTrend"):
            return self._algo_supertrend(signal)
        if group.startswith("Indicator") or group.startswith("MIS Indicator"):
            return self._algo_indicator_passthrough(signal)

        # Default: Minervini SEPA (original logic)
        return self._algorithmic_analysis(signal)

    def _algo_a007(self, signal: dict[str, Any]) -> tuple[str, int]:
        """A.007 (MA Crossover + ADX): Strategy-level sanity check.

        The Pine strategy already enforces MA cross + ADX > threshold + BB
        squeeze block + time stop.  In Algorithmic Mode we only verify the
        payload integrity fields that the webhook actually sends.

        Returns:
            (advice_text, confidence_0_to_100)
        """
        payload = signal.get("payload", {})
        if isinstance(payload, str):
            import json as _json

            try:
                payload = _json.loads(payload)
            except Exception:
                payload = {}

        action = signal.get("action", "") or payload.get("action", "")
        price = float(signal.get("price") or payload.get("price") or 0)
        interval = str(signal.get("interval", "") or payload.get("interval", "") or "")
        position_size = payload.get("position_size", payload.get("quoteQty"))

        checks: list[str] = []
        score = 0
        total = 4

        # 1. Valid action
        if action.lower() in ("buy", "sell", "long", "short"):
            checks.append(f"✅ Action = {action.upper()}")
            score += 1
        else:
            checks.append(f"⚠️ Action = '{action}' (không hợp lệ)")

        # 2. Price > 0
        if price > 0:
            checks.append(f"✅ Price = {price:,.2f}")
            score += 1
        else:
            checks.append("⚠️ Price ≤ 0")

        # 3. Interval present
        if interval:
            checks.append(f"✅ Interval = {interval}")
            score += 1
        else:
            checks.append("⬜ Interval missing")

        # 4. Position size present
        if position_size is not None:
            checks.append(f"✅ Position Size = {position_size}")
            score += 1
        else:
            checks.append("⬜ Position Size not provided (will use default)")
            score += 1  # Not required — strategy computes it

        confidence = int(score / total * 100) if total > 0 else 60
        verdict = (
            "✅ PASS — A.007 Strategy pre-validated by Pine Script"
            if score >= 3
            else "⚠️ WARN — Payload incomplete"
        )
        advice = (
            f"⚡ **A.007 ALGORITHMIC MODE** (LLM unavailable)\n\n"
            f"📊 Payload Check: {score}/{total} ({confidence}%)\n\n"
            + "\n".join(checks)
            + f"\n\n{verdict}\n"
            f"ℹ️ Entry conditions (MA cross + ADX + BB) enforced by Pine strategy."
        )
        return advice, confidence

    def _algo_supertrend(self, signal: dict[str, Any]) -> tuple[str, int]:
        """SuperTrend: Strategy-level sanity check.

        SuperTrend Flip signals are generated by indicator with VBS_Webhook_Lib.
        They carry ATR-based SL/TP in metadata.  In Algorithmic Mode we verify
        the payload integrity and confidence from source.

        Returns:
            (advice_text, confidence_0_to_100)
        """
        payload = signal.get("payload", {})
        if isinstance(payload, str):
            import json as _json

            try:
                payload = _json.loads(payload)
            except Exception:
                payload = {}

        action = signal.get("action", "") or payload.get("action", "")
        price = float(signal.get("price") or payload.get("price") or 0)
        metadata = payload.get("metadata", {})
        if isinstance(metadata, str):
            import json as _json

            try:
                metadata = _json.loads(metadata)
            except Exception:
                metadata = {}

        checks: list[str] = []
        score = 0
        total = 4

        # 1. Valid action
        if action.lower() in ("buy", "sell", "long", "short"):
            checks.append(f"✅ Action = {action.upper()}")
            score += 1
        else:
            checks.append(f"⚠️ Action = '{action}'")

        # 2. Price > 0
        if price > 0:
            checks.append(f"✅ Price = {price:,.2f}")
            score += 1
        else:
            checks.append("⚠️ Price ≤ 0")

        # 3. SL present (from ATR calculation)
        sl = metadata.get("sl") or payload.get("sl")
        if sl is not None:
            try:
                sl_val = float(str(sl).replace(",", ""))
                if sl_val > 0:
                    checks.append(f"✅ SL = {sl_val:,.2f} (ATR-based)")
                    score += 1
                else:
                    checks.append("⬜ SL = 0")
            except (ValueError, TypeError):
                checks.append(f"⬜ SL = {sl} (cannot parse)")
        else:
            checks.append("⬜ SL not in payload (will use default)")
            score += 1  # Not critical — indicator may omit

        # 4. Source confidence
        conf_score = payload.get("confidence_score")
        if conf_score is not None:
            try:
                cv = int(conf_score)
                if cv >= 50:
                    checks.append(f"✅ Source Confidence = {cv}%")
                    score += 1
                else:
                    checks.append(f"⚠️ Source Confidence = {cv}% (low)")
            except (ValueError, TypeError):
                checks.append(f"⬜ Source Confidence = {conf_score}")
        else:
            checks.append("⬜ Source Confidence not provided")
            score += 1  # Strategy signals may not carry this

        confidence = int(score / total * 100) if total > 0 else 60
        verdict = (
            "✅ PASS — SuperTrend Flip validated"
            if score >= 3
            else "⚠️ WARN — Payload incomplete"
        )
        advice = (
            f"⚡ **SUPERTREND ALGORITHMIC MODE** (LLM unavailable)\n\n"
            f"📊 Payload Check: {score}/{total} ({confidence}%)\n\n"
            + "\n".join(checks)
            + f"\n\n{verdict}\n"
            f"ℹ️ Entry conditions (ST flip + regime + RSI zone) enforced by Pine indicator."
        )
        return advice, confidence

    def _algo_indicator_passthrough(self, signal: dict[str, Any]) -> tuple[str, int]:
        """Indicator signals: pass-through with source confidence.

        Indicator alerts (source='indicator') are monitor-only signals that
        feed the Dashboard Signals tab.  They should NOT be evaluated against
        trade-execution criteria like Minervini.  We pass through using the
        confidence_score embedded in the payload.

        Returns:
            (advice_text, confidence_0_to_100)
        """
        payload = signal.get("payload", {})
        if isinstance(payload, str):
            import json as _json

            try:
                payload = _json.loads(payload)
            except Exception:
                payload = {}

        indicator_name = (
            payload.get("indicator_name") or payload.get("indicator") or "unknown"
        )
        conf = payload.get("confidence_score")
        try:
            confidence = int(conf) if conf is not None else 60
        except (ValueError, TypeError):
            confidence = 60

        # Clamp to 0-100
        confidence = max(0, min(100, confidence))

        action = signal.get("action", "") or payload.get("action", "")
        symbol = signal.get("symbol", "") or payload.get("symbol", "")

        advice = (
            f"⚡ **INDICATOR PASSTHROUGH** (LLM unavailable)\n\n"
            f"📊 Chỉ báo: {indicator_name}\n"
            f"📈 Symbol: {symbol} | Action: {action.upper()}\n"
            f"🎯 Confidence from source: {confidence}%\n\n"
            f"ℹ️ Indicator signals flow to Dashboard Signals tab.\n"
            f"ℹ️ Trade decisions are NOT made from indicator alerts."
        )
        return advice, confidence

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _calculate_position_size(
        self, price: float, action: str, signal: dict[str, Any] | None = None
    ) -> float:
        """Minervini SEPA risk-based position sizing."""
        if price <= 0:
            return 0.0
        portfolio = float(getattr(config, "MAX_QUOTE_QTY", 1000))
        risk_pct = float(getattr(config, "RISK_PER_TRADE", 0.02))

        atr = None
        if isinstance(signal, dict):
            payload = signal.get("payload", {})
            if isinstance(payload, dict):
                atr = payload.get("atr_value") or payload.get("atr")
            if atr is None:
                atr = signal.get("atr_value") or signal.get("atr")

        try:
            atr_val = float(atr) if atr is not None else 0.0
        except (ValueError, TypeError):
            atr_val = 0.0

        use_atr = False
        if atr_val > 0:
            if action.lower() in ("buy", "long"):
                sl = price - (2 * atr_val)
                tp = price + (5 * atr_val)
            else:
                sl = price + (2 * atr_val)
                tp = price - (5 * atr_val)
            if sl > 0 and tp > 0:
                use_atr = True

        if use_atr:
            sl_pct = (2 * atr_val) / price
        else:
            sl_pct = float(getattr(config, "STOP_LOSS_PCT", 0.08))

        risk_amount = portfolio * risk_pct
        qty = risk_amount / (price * sl_pct) if sl_pct > 0 else 0.0

        # Cap total quote value
        quote_value = qty * price
        if quote_value > portfolio:
            qty = portfolio / price
        return round(qty, 8)

    def _calculate_sl_tp(
        self, price: float, action: str, signal: dict[str, Any] | None = None
    ) -> tuple[float, float]:
        """Compute SL and TP based on ATR if present, otherwise configured percentages."""
        atr = None
        if isinstance(signal, dict):
            payload = signal.get("payload", {})
            if isinstance(payload, dict):
                atr = payload.get("atr_value") or payload.get("atr")
            if atr is None:
                atr = signal.get("atr_value") or signal.get("atr")

        try:
            atr_val = float(atr) if atr is not None else 0.0
        except (ValueError, TypeError):
            atr_val = 0.0

        if atr_val > 0:
            if action.lower() in ("buy", "long"):
                sl = round(price - (2 * atr_val), 8)
                tp = round(price + (5 * atr_val), 8)
            else:
                sl = round(price + (2 * atr_val), 8)
                tp = round(price - (5 * atr_val), 8)

            if sl > 0 and tp > 0:
                return sl, tp

            log.warning(
                f"[VpsAnalyzer] ATR-based SL ({sl}) or TP ({tp}) is non-positive. "
                f"Falling back to percentage-based calculation."
            )

        sl_pct = float(getattr(config, "STOP_LOSS_PCT", 0.08))
        tp_pct = float(getattr(config, "TAKE_PROFIT_PCT", 0.20))
        if action.lower() in ("buy", "long"):
            sl = round(price * (1 - sl_pct), 8)
            tp = round(price * (1 + tp_pct), 8)
        else:
            sl = round(price * (1 + sl_pct), 8)
            tp = round(price * (1 - tp_pct), 8)
        return sl, tp

    def _extract_confidence(self, advice: str) -> int:
        """Heuristic confidence extraction from AI text."""
        lower = advice.lower()
        if "mạnh" in lower or "strong" in lower:
            return 85
        if "trung bình" in lower or "medium" in lower:
            return 60
        if "yếu" in lower or "weak" in lower:
            return 30
        return 50

    # ── Forward to execution ──────────────────────────────────────────────────

    async def forward_to_server_b(
        self, trade_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Forward approved trade payload: Local first, then SERVER B fallback.

        Args:
            trade_payload: Complete trade dict (symbol, action, price, qty, sl, tp, …)

        Returns:
            {success: bool, status: int, data: dict, executed_on: str} or error dict.
        """
        # ── Try LOCAL execution first ──────────────────────────────────────────
        if config.LOCAL_EXECUTE_URL:
            local_url = f"{config.LOCAL_EXECUTE_URL}/api/execute-trade"
            local_headers = {
                "X-Server-B-Secret": config.LOCAL_EXECUTE_SECRET,
                "Content-Type": "application/json",
            }
            log.info(f"[VpsAnalyzer] Attempting LOCAL execution: {local_url}")
            try:
                session = await self.get_session()
                timeout = aiohttp.ClientTimeout(connect=5, total=10)
                async with session.post(
                    local_url,
                    json=trade_payload,
                    headers=local_headers,
                    timeout=timeout,
                ) as resp:
                    body = await resp.json()
                    if resp.status == 200:
                        log.info(
                            f"[VpsAnalyzer] LOCAL executed: "
                            f"{trade_payload['symbol']} {trade_payload['action']}"
                        )
                        return {
                            "success": True,
                            "status": resp.status,
                            "data": body,
                            "executed_on": "local",
                        }
                    log.warning(
                        f"[VpsAnalyzer] LOCAL rejected trade "
                        f"(HTTP {resp.status}): {body}. Falling back to Server B."
                    )
            except Exception as exc:
                log.warning(
                    f"[VpsAnalyzer] LOCAL offline/error: {exc}. Falling back to Server B."
                )
                try:
                    from notifier import send_telegram_alert

                    await send_telegram_alert(
                        f"⚠️ <b>Local Windows Offline</b>\n"
                        f"Lỗi: <code>{str(exc)[:150]}</code>\n"
                        f"→ Chuyển sang <b>Server B (Cloud Backup)</b>"
                    )
                except ValueError as e:
                    import logging

                    logging.getLogger(__name__).warning("Ignored error: %s", e)

        # ── Fallback: SERVER B ─────────────────────────────────────────────────
        url = f"{config.SERVER_B_EXECUTE_URL}/api/execute-trade"
        headers = {
            "X-Server-B-Secret": config.SERVER_B_SECRET,
            "Content-Type": "application/json",
        }
        log.info(f"[VpsAnalyzer] Forwarding to Server B: {url}")
        try:
            session = await self.get_session()
            timeout = aiohttp.ClientTimeout(connect=5, total=10)
            async with session.post(
                url, json=trade_payload, headers=headers, timeout=timeout
            ) as resp:
                body = await resp.json()
                if resp.status == 200:
                    log.info(
                        f"[VpsAnalyzer] Server B accepted: "
                        f"{trade_payload['symbol']} {trade_payload['action']}"
                    )
                    return {
                        "success": True,
                        "status": resp.status,
                        "data": body,
                        "executed_on": "server_b",
                        "route_verified": True,
                    }
                log.error(
                    f"[VpsAnalyzer] Server B rejected (HTTP {resp.status}): {body}"
                )
                return {
                    "success": False,
                    "status": resp.status,
                    "error": body.get("detail", str(body)),
                }
        except aiohttp.ContentTypeError:
            log.error("[VpsAnalyzer] Server B returned non-JSON response")
            return {"success": False, "status": 500, "error": "Non-JSON from Server B"}
        except Exception as exc:
            log.error(f"[VpsAnalyzer] Error forwarding to Server B: {exc}")
            return {"success": False, "status": 0, "error": str(exc)}

    # ── ACK ───────────────────────────────────────────────────────────────────

    async def _ack_signal(
        self, queue_id: int, status: str, error_msg: str = ""
    ) -> bool:
        """ACK a processed signal back to SERVER A's VBS.

        Args:
            queue_id : VBS queue ID.
            status   : "executed" | "failed" | "rejected" | "skipped_stale"
            error_msg: Optional description.

        Returns:
            True if ACK succeeded.
        """
        url = f"{config.VPS_BUFFER_URL}/ack"
        headers = {
            "X-Buffer-Secret": config.VPS_BUFFER_SECRET,
            "Content-Type": "application/json",
        }
        body = {
            "acks": [{"queue_id": queue_id, "status": status, "error_msg": error_msg}]
        }
        try:
            session = await self.get_session()
            async with session.post(
                url, json=body, headers=headers, timeout=10
            ) as resp:
                if resp.status == 200:
                    log.info(f"[VpsAnalyzer] ACK #{queue_id} → {status}")
                    return True
                text = await resp.text()
                log.error(
                    f"[VpsAnalyzer] ACK #{queue_id} failed (HTTP {resp.status}): {text[:200]}"
                )
                return False
        except Exception as exc:
            log.error(f"[VpsAnalyzer] ACK #{queue_id} connection error: {exc}")
            return False

    # ── Legacy compatibility: poll + analyze (kept for tests) ─────────────────

    async def poll_and_analyze(self) -> list[dict[str, Any]]:
        """Poll VBS and analyse all signals. Returns analyzed result dicts.

        V1-compatible interface — the test suite mocks _analyze_signal with V1
        semantics (return trade_payload dict or None). V2 internal code uses
        _analyze_signal returning {"approved": bool, ...}.

        Handles both:
          - V1 mock: _analyze_signal returns dict (trade_payload) → approved=True
          - V1 mock: _analyze_signal returns None               → approved=False
          - V2 real: _analyze_signal returns {"approved": bool, ...}

        Return format:
          [{"queue_id": int, "approved": bool, "trade_payload": dict | "reason": str}, ...]
        """
        raw_signals = await self._long_poll()
        if not raw_signals:
            return []

        async def analyze_single(signal: dict[str, Any]) -> dict[str, Any]:
            queue_id = signal.get("queue_id")
            try:
                # Check if _analyze_signal is mocked or overwritten
                is_original = (
                    hasattr(self._analyze_signal, "__func__")
                    and self._analyze_signal.__func__
                    is VpsAnalyzerWorker._analyze_signal
                )
                is_mocked = not is_original

                if not is_mocked:
                    v2_res = await self._analyze_signal_v2(signal)
                else:
                    v2_res = None

                # Call _analyze_signal (for compatibility / side effects if mocked)
                # Fix #54 Bug 2: Use .get() to avoid KeyError when signal is rejected
                # (rejected results have approved=False and no 'trade_payload' key)
                analyzed = (
                    await self._analyze_signal(signal)
                    if is_mocked
                    else (
                        v2_res.get("trade_payload") if v2_res.get("approved") else None
                    )
                )

                # Extract payload safely
                payload = signal.get("payload", {})
                if isinstance(payload, str):
                    try:
                        import json as _json

                        payload = _json.loads(payload)
                    except Exception:
                        payload = {}

                if analyzed is None:
                    # rejected
                    if v2_res:
                        reason = v2_res.get("reason")
                        mode = v2_res.get("analysis_mode", "algorithmic")
                    else:
                        strategy_name = self._detect_strategy_group(signal)
                        reason = f"RAG analysis rejected signal — does not meet {strategy_name} criteria"
                        mode = "algorithmic" if not llm_breaker.is_available() else "ai"

                    res_dict = {
                        "queue_id": queue_id,
                        "approved": False,
                        "reason": reason,
                        "symbol": signal.get("symbol", "?"),
                        "action": signal.get("action", "?"),
                        "price": signal.get("price", 0),
                        "exchange": payload.get("exchange")
                        or signal.get("exchange")
                        or getattr(config, "DEFAULT_EXCHANGE", "BINANCE"),
                        "analysis_mode": mode,
                        "payload": payload,
                        "trade_payload": v2_res.get("trade_payload")
                        if v2_res
                        else None,
                    }
                elif isinstance(analyzed, dict) and "approved" in analyzed:
                    # V2 dict returned by a test mock or V2-aware caller
                    if analyzed["approved"]:
                        res_dict = {
                            "queue_id": queue_id,
                            "approved": True,
                            "trade_payload": analyzed["trade_payload"],
                            "analysis_mode": analyzed.get("analysis_mode")
                            or analyzed["trade_payload"].get("analysis_mode", "ai"),
                        }
                    else:
                        res_dict = {
                            "queue_id": queue_id,
                            "approved": False,
                            "reason": analyzed.get(
                                "reason", "Analysis rejected signal"
                            ),
                            "symbol": analyzed.get("symbol")
                            or signal.get("symbol", "?"),
                            "action": analyzed.get("action")
                            or signal.get("action", "?"),
                            "price": analyzed.get("price") or signal.get("price", 0),
                            "exchange": analyzed.get("exchange")
                            or payload.get("exchange")
                            or signal.get("exchange")
                            or getattr(config, "DEFAULT_EXCHANGE", "BINANCE"),
                            "analysis_mode": analyzed.get("analysis_mode", "ai"),
                            "payload": analyzed.get("payload") or payload,
                            "trade_payload": analyzed.get("trade_payload"),
                        }
                else:
                    # V1: plain trade_payload dict → approved
                    res_dict = {
                        "queue_id": queue_id,
                        "approved": True,
                        "trade_payload": analyzed,
                        "analysis_mode": analyzed.get("analysis_mode", "ai"),
                    }

                res_dict["sentiment_stats"] = signal.get("payload", {}).get(
                    "sentiment_stats"
                )
                return res_dict

            except Exception as exc:
                log.exception(
                    f"[VpsAnalyzer] Error in poll_and_analyze #{queue_id}: {exc}"
                )
                return {
                    "queue_id": queue_id,
                    "approved": False,
                    "reason": f"Analysis error: {str(exc)[:200]}",
                    "symbol": signal.get("symbol", "?"),
                    "action": signal.get("action", "?"),
                    "price": signal.get("price", 0),
                    "exchange": signal.get("payload", {}).get("exchange")
                    or signal.get("exchange")
                    or getattr(config, "DEFAULT_EXCHANGE", "BINANCE"),
                    "analysis_mode": "algorithmic"
                    if not llm_breaker.is_available()
                    else "ai",
                    "payload": signal.get("payload", {}),
                }

        results = await asyncio.gather(*(analyze_single(sig) for sig in raw_signals))
        return list(results)


if __name__ == "__main__":
    json_format = os.getenv("LOG_JSON_FORMAT", "false").lower() == "true" or getattr(
        config, "LOG_JSON_FORMAT", False
    )
    setup_logging(json_format=json_format)
    # Trigger deployment and check Server C clean state
    worker = VpsAnalyzerWorker()
    asyncio.run(worker.run())
