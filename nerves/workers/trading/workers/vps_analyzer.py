"""
vps_analyzer.py — AI Analyzer Worker for SERVER C (V2 Hardened).

Daemon worker that runs on SERVER C in the 3-server pipeline:
  SERVER A (VBS) → SERVER C (Analyzer) → SERVER B (Executor)

V2 Changes vs V1:
  - Long Polling  : Replaces 15 s sleep-loop with /consume-long (hold up to 30 s).
                    Signal delivery latency drops from ~7.5 s to <1 s.
  - Circuit Breaker: LLMCircuitBreaker guards all generate_trading_advice() calls.
                    On timeout / 3 consecutive failures → Algorithmic Mode.
  - Dual-Mode     : Algorithmic fallback scores signals against 5 Minervini checks.
                    Trades are still forwarded even when LLM is unavailable.
  - Confidence    : ai_confidence (0-100) is attached to every trade payload.
  - Failover      : LOCAL_EXECUTE_URL → SERVER_B_EXECUTE_URL (unchanged from V1).
"""

import asyncio
import logging
import os
import re
import aiohttp
import socket
from typing import Dict, Any, List, Optional, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
import rag

# V2: Import Circuit Breaker singleton
# The module lives in server/workers/ alongside this file.
from workers.ai_circuit_breaker import llm_breaker  # noqa: E402
from logging_config import setup_logging
from fastapi import FastAPI, Request, Response
from workers.liveness_monitor import _get_servers

app = FastAPI(title="Server C Health Server")

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
        drifts = [v["drift_ms"] for v in last_drift_results.values() if v.get("drift_ms") is not None]
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

    return {
        "liveness_status_server_a": liveness_status_server_a,
        "liveness_status_server_b": liveness_status_server_b,
        "disk_usage_pct": disk_usage_pct,
        "ntp_clock_drift_ms": ntp_clock_drift_ms,
        "ntp_clock_drift_detail": ntp_clock_drift_detail,
        "circuit_breaker_status": circuit_breaker_status
    }

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
        except Exception:
            pass
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
        drifts = [v["drift_ms"] for v in last_drift_results.values() if v.get("drift_ms") is not None]
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
        else: # open
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
        "llm_breaker_fallbacks_total": float(fallbacks)
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
        f"llm_breaker_fallbacks_total {fallbacks}"
    ]
    return Response(content="\n".join(lines) + "\n", media_type="text/plain")


log = logging.getLogger(__name__)


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

    LONG_POLL_TIMEOUT    = int(os.getenv("LONG_POLL_TIMEOUT_SEC", "30"))  # seconds
    HTTP_TIMEOUT_MARGIN  = 5   # extra seconds for HTTP layer beyond long-poll hold
    ALGO_MIN_SCORE       = int(os.getenv("LLM_ALGORITHMIC_MIN_SCORE", "3"))  # /5
    BACKOFF_ON_ERROR_SEC = 5   # sleep after unexpected poll errors

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self.consumer_id = "server-c-analyzer"
        # poll_interval is kept for compatibility but only used as error back-off
        self.poll_interval = config.VPS_POLL_INTERVAL_SECONDS
        self._lock = asyncio.Lock()

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

    async def _long_poll(self) -> List[Dict[str, Any]]:
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
                    log.debug(
                        f"[VpsAnalyzer] Long-poll: empty (timeout={waited}s)"
                    )
                return signals
        except aiohttp.ServerDisconnectedError:
            log.warning("[VpsAnalyzer] Long-poll: server disconnected (reconnect)")
            return []
        except asyncio.TimeoutError:
            log.warning("[VpsAnalyzer] Long-poll: client-side timeout (reconnect)")
            return []
        except Exception as exc:
            log.warning(f"[VpsAnalyzer] Long-poll connection error: {exc}")
            return []

    # ── Main daemon loop ──────────────────────────────────────────────────────

    async def run(self):
        """Main daemon loop: long-poll → analyse → forward → ack.

        Runs until cancelled.
        """
        # Logging configuration based on environment variable LOG_JSON_FORMAT
        json_format = os.getenv("LOG_JSON_FORMAT", "false").lower() == "true" or getattr(config, "LOG_JSON_FORMAT", False)
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
                log.info("[VpsAnalyzer] RAG vector database initialized and seeded successfully.")
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
        config_uv = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
        server = uvicorn.Server(config_uv)
        server_task = asyncio.create_task(server.serve())
        log.info("[VpsAnalyzer] Health and metrics server started on port 8000.")

        # Setup graceful shutdown signal handling
        import signal
        self._shutdown_event = asyncio.Event()
        loop = asyncio.get_running_loop()

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

        # Create shutdown waiter ONCE outside loop to prevent task leak
        shutdown_task = asyncio.create_task(self._shutdown_event.wait())

        while not self._shutdown_event.is_set():
            try:
                # poll_and_analyze() wraps _long_poll + _analyze_signal_v2
                # Since poll_and_analyze is an async call that might take 30s (long polling),
                # we run it as a task and await it along with the shutdown event.
                poll_task = asyncio.create_task(self.poll_and_analyze())
                
                done, pending = await asyncio.wait(
                    {poll_task, shutdown_task},
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # Cancel only the poll_task if shutdown was triggered
                if poll_task in pending:
                    poll_task.cancel()
                    try:
                        await poll_task
                    except asyncio.CancelledError:
                        pass
                
                if self._shutdown_event.is_set():
                    break
                    
                if poll_task in done:
                    analyzed_list = poll_task.result()
                    
                    async def process_analyzed(analyzed: Dict[str, Any]):
                        queue_id = analyzed.get("queue_id")
                        dry_run = os.getenv("ANALYZER_DRY_RUN", "false").lower() == "true"
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
                                    fwd = await self.forward_to_server_b(analyzed["trade_payload"])
                                    if fwd.get("success"):
                                        await self._ack_signal(queue_id, "executed")
                                    else:
                                        err = fwd.get("error", "Server B execution failed")
                                        await self._ack_signal(queue_id, "failed", err)
                            else:
                                reason = analyzed.get("reason", "")
                                if reason:
                                    await self._ack_signal(queue_id, "rejected", reason)
                                else:
                                    await self._ack_signal(queue_id, "rejected")
                        except Exception as exc:
                            log.exception(f"[VpsAnalyzer] Error processing #{queue_id}: {exc}")
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
                                qid = analyzed_list[i].get("queue_id", "?") if i < len(analyzed_list) else "?"
                                log.error(
                                    f"[VpsAnalyzer] process_analyzed #{qid} failed: {result}"
                                )

            except asyncio.CancelledError:
                log.info("[VpsAnalyzer] Daemon loop cancelled. Shutting down.")
                break
            except Exception as exc:
                log.exception(f"[VpsAnalyzer] Unexpected error in run loop: {exc}")
                await asyncio.sleep(self.BACKOFF_ON_ERROR_SEC)

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

    # ── Signal analysis ───────────────────────────────────────────────────────

    async def _analyze_signal(self, signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """V1-compatible wrapper around _analyze_signal_v2.

        Returns the trade_payload dict directly (approved) or None (rejected),
        preserving the original interface expected by the test suite.

        Internal production code uses _analyze_signal_v2 for the full V2 dict.
        """
        result = await self._analyze_signal_v2(signal)
        if result.get("approved"):
            return result["trade_payload"]
        return None

    async def _analyze_signal_v2(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Run AI or Algorithmic analysis on a single VBS signal.

        Returns:
            {
                "approved": bool,
                "trade_payload": dict | None,
                "reason": str,           # rejection reason when not approved
                "analysis_mode": str,    # "ai" | "algorithmic"
            }
        """
        symbol   = signal.get("symbol", "")
        action   = signal.get("action", "")
        price    = signal.get("price")
        payload  = signal.get("payload", {})
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

        advice      = ""
        ai_conf     = 0
        analysis_mode = "ai"

        # ── AI Mode (primary) ─────────────────────────────────────────────────
        if llm_breaker.is_available():
            # Calculate and inject VCP Pattern & Trend Template scorecards into prompt context
            try:
                from capture_client import get_capture_client
                from analysis import score_trend_template
                from utils.pattern_overlay import detect_all_patterns

                # Fetch daily OHLCV candles (limit to 365 to calculate SMA200 and 52-week High/Low)
                ohlcv = await get_capture_client().fetch_ohlcv(symbol, timeframe="D", limit=365)
                if ohlcv and len(ohlcv) >= 10:
                    closes = [c[4] for c in ohlcv]
                    highs = [c[2] for c in ohlcv]
                    lows = [c[3] for c in ohlcv]
                    
                    latest_close = closes[-1]
                    sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
                    sma150 = sum(closes[-150:]) / 150 if len(closes) >= 150 else None
                    sma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
                    
                    # SMA200 slope (trend) over past 20 days
                    sma200_20_ago = sum(closes[-220:-20]) / 200 if len(closes) >= 220 else None
                    sma200_slope = (sma200 - sma200_20_ago) if (sma200 is not None and sma200_20_ago is not None) else None
                    
                    high_52w = max(highs[-365:]) if len(highs) >= 365 else max(highs)
                    low_52w = min(lows[-365:]) if len(lows) >= 365 else min(lows)
                    
                    # Calculate rs_ratio relative to BTC benchmark (or default to 1.01)
                    rs_ratio = 1.01
                    btc_symbol = "BTCUSDT_UMCBL" if symbol.endswith("_UMCBL") else "BTCUSDT"
                    if symbol != btc_symbol:
                        try:
                            btc_ohlcv = await get_capture_client().fetch_ohlcv(btc_symbol, timeframe="D", limit=365)
                            if btc_ohlcv and len(btc_ohlcv) >= 50 and len(closes) >= 50:
                                symbol_perf = closes[-1] / closes[-50]
                                btc_closes = [c[4] for c in btc_ohlcv]
                                btc_perf = btc_closes[-1] / btc_closes[-50]
                                rs_ratio = symbol_perf / btc_perf
                        except Exception as e:
                            log.warning(f"[VpsAnalyzer] Could not fetch/calculate RS ratio vs benchmark: {e}")
                    
                    tt_res = score_trend_template(
                        price=latest_close,
                        sma50=sma50,
                        sma150=sma150,
                        sma200=sma200,
                        high_52w=high_52w,
                        low_52w=low_52w,
                        sma200_slope=sma200_slope,
                        rs_ratio=rs_ratio
                    )
                    
                    payload["trend_stats"] = {
                        "score": tt_res.score,
                        "stage": tt_res.stage,
                        "summary": tt_res.summary,
                        "criteria": tt_res.criteria
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
                                    "duration_bars": c.duration_bars
                                }
                                for c in patterns.vcp.contractions
                            ],
                            "pivot_line": patterns.vcp.pivot_line_price,
                            "quality_score": patterns.vcp.quality_score
                        }
                    else:
                        payload["vcp_stats"] = {"detected": False}
                else:
                    payload["trend_stats"] = {"error": "Insufficient OHLCV data to calculate Trend Template"}
                    payload["vcp_stats"] = {"detected": False}
            except Exception as exc:
                log.warning(f"[VpsAnalyzer] Gracefully handled pattern detection error for {symbol}: {exc}")
                payload["trend_stats"] = {"error": f"Pattern detection exception: {exc}"}
                payload["vcp_stats"] = {"detected": False}

            try:
                rag_query  = rag.build_rag_query(symbol, action, payload)
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
            except asyncio.TimeoutError:
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
            log.info(
                f"[VpsAnalyzer] ⚡ Circuit OPEN → Algorithmic for #{queue_id}"
            )

        # ── Algorithmic Fallback ───────────────────────────────────────────────
        if analysis_mode == "algorithmic":
            advice, ai_conf = self._algorithmic_analysis(signal)
            # Reject if score below minimum threshold
            score = round(ai_conf / 100 * 5)  # confidence → score (0-5)
            if score < self.ALGO_MIN_SCORE:
                return {
                    "approved": False,
                    "reason": (
                        f"Algorithmic score {score}/{self.ALGO_MIN_SCORE} — "
                        "insufficient Minervini criteria"
                    ),
                    "analysis_mode": analysis_mode,
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
                }
            # 1. Prefix-based checks (high priority)
            starts_with_reject = False
            for kw in ["rejected", "wait", "avoid", "không nên", "không mua", "chờ thêm", "⚠️"]:
                if advice_lower.startswith(kw):
                    starts_with_reject = True
                    break
                    
            starts_with_approve = False
            for kw in ["approved", "mua", "buy", "bán", "sell", "mạnh", "strong"]:
                if advice_lower.startswith(kw):
                    starts_with_approve = True
                    break
            
            # 2. Substring/word boundary checking
            rejected_kw = ["⚠️", "chờ thêm", "không nên", "không mua", "rejected", "wait", "avoid"]
            approved_kw = ["mua", "buy", "bán", "sell", "mạnh", "strong", "approved"]
            
            def has_keyword(text, kw):
                if kw == "⚠️":
                    return kw in text
                if kw.isalnum():
                    pattern = rf"\b{re.escape(kw)}\b"
                    return bool(re.search(pattern, text))
                else:
                    return kw in text

            is_rejected = starts_with_reject or any(has_keyword(advice_lower, kw) for kw in rejected_kw)
            is_approved = starts_with_approve or any(has_keyword(advice_lower, kw) for kw in approved_kw)
            
            if is_rejected or not is_approved:
                return {
                    "approved": False,
                    "reason": "AI analysis rejected signal" if is_rejected else "AI analysis did not approve signal",
                    "analysis_mode": analysis_mode,
                }

        # ── Position sizing ────────────────────────────────────────────────────
        qty              = self._calculate_position_size(price_val, action, signal=signal)
        sl_price, tp_price = self._calculate_sl_tp(price_val, action, signal=signal)

        # ── Programmatic Guardrails ───────────────────────────────────────────
        # 1. Trend Template score < 5/8
        tt_score = payload.get("trend_stats", {}).get("score")
        if tt_score is not None and isinstance(tt_score, (int, float)) and tt_score < 5:
            return {
                "approved": False,
                "reason": f"Programmatic guardrail: Trend Template score {tt_score}/8 is below minimum threshold (5/8)",
                "analysis_mode": analysis_mode,
            }

        # 2. Stop-Loss > 8%
        if sl_price > 0 and price_val > 0:
            risk_pct = abs(price_val - sl_price) / price_val * 100
            if round(risk_pct, 4) > 8.0:
                return {
                    "approved": False,
                    "reason": f"Programmatic guardrail: Stop Loss risk {risk_pct:.2f}% exceeds maximum threshold (8%)",
                    "analysis_mode": analysis_mode,
                }

        trade_payload = {
            "symbol":          symbol,
            "action":          action,
            "price":           price_val,
            "qty":             qty,
            "sl":              sl_price,
            "tp":              tp_price,
            "analysis":        advice,
            "ai_confidence":   ai_conf,
            "analysis_mode":   analysis_mode,
            "risk_per_trade":  config.RISK_PER_TRADE,
            "stop_loss_pct":   config.STOP_LOSS_PCT,
            "exchange":        payload.get("exchange", config.DEFAULT_EXCHANGE),
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

    async def _notify_analysis_telegram(self, analyzed: Dict[str, Any]):
        """Send AI analysis result to Telegram.

        Fire-and-forget: Telegram errors won't block the trade pipeline.
        """
        try:
            from notifier import send_telegram_alert
        except ImportError:
            return  # notifier not available

        queue_id = analyzed.get("queue_id", "?")
        approved = analyzed.get("approved", False)
        mode = analyzed.get("analysis_mode", "unknown")
        reason = analyzed.get("reason", "")
        tp = analyzed.get("trade_payload", {})

        symbol = tp.get("symbol", analyzed.get("symbol", "?"))
        action = tp.get("action", analyzed.get("action", "?"))
        price = tp.get("price", 0)
        conf = tp.get("ai_confidence", 0)
        analysis = tp.get("analysis", "")

        # Status icon
        if approved:
            status = "✅ APPROVED"
            hold = tp.get("hold_for_approval", False)
            if hold:
                status = "⏳ HOLD (chờ duyệt)"
        else:
            status = "❌ REJECTED"

        # Mode icon
        mode_icon = "🧠" if mode == "ai" else "📊"

        # Build message
        lines = [
            f"{'━' * 28}",
            f"{mode_icon} <b>AI Core Analysis #{queue_id}</b>",
            f"{'━' * 28}",
            "",
            f"📌 <b>{symbol}</b> | <code>{action.upper()}</code> @ <code>{price:,.2f}</code>" if price >= 1 else f"📌 <b>{symbol}</b> | <code>{action.upper()}</code> @ <code>{price:.6f}</code>",
            f"🎯 Confidence: <b>{conf}%</b>  |  Mode: <b>{mode.upper()}</b>",
            f"📋 Status: <b>{status}</b>",
        ]

        if approved and tp:
            qty = tp.get("qty", 0)
            sl = tp.get("sl", 0)
            tp_price = tp.get("tp", 0)
            risk = tp.get("risk_per_trade", 0)
            lines.extend([
                "",
                "💰 <b>Position:</b>",
                f"   • Qty: <code>{qty}</code>",
                f"   • SL: <code>{sl:,.2f}</code>  |  TP: <code>{tp_price:,.2f}</code>" if sl >= 1 else f"   • SL: <code>{sl:.6f}</code>  |  TP: <code>{tp_price:.6f}</code>",
                f"   • Risk/Trade: <code>{risk:.1%}</code>",
            ])

        if not approved and reason:
            lines.extend([
                "",
                f"📝 <b>Reason:</b> {reason[:200]}",
            ])

        # AI advice excerpt (max 300 chars)
        if analysis:
            excerpt = analysis[:300].replace("\n", " ")
            if len(analysis) > 300:
                excerpt += "…"
            lines.extend([
                "",
                f"💬 <b>AI:</b> {excerpt}",
            ])

        lines.append(f"\n{'━' * 28}")

        message = "\n".join(lines)

        try:
            await send_telegram_alert(message)
            log.info(f"[VpsAnalyzer] Telegram notification sent for #{queue_id}")
        except Exception as e:
            log.warning(f"[VpsAnalyzer] Telegram notification failed for #{queue_id}: {e}")

    # ── Algorithmic analysis (Minervini SEPA) ─────────────────────────────────

    def _algorithmic_analysis(self, signal: Dict[str, Any]) -> Tuple[str, int]:
        """Score signal against 5 Minervini Trend Template criteria.

        Returns:
            (advice_text, confidence_0_to_100)
        """
        payload = signal.get("payload", {})
        action  = signal.get("action", "")
        price   = float(signal.get("price") or 0)

        checks: List[str] = []
        score = 0
        total = 5

        # 1. Volume surge (>150% of average = Breakout confirmation)
        volume     = float(payload.get("volume", 0) or 0)
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

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _calculate_position_size(self, price: float, action: str, signal: Optional[Dict[str, Any]] = None) -> float:
        """Minervini SEPA risk-based position sizing."""
        if price <= 0:
            return 0.0
        portfolio  = float(getattr(config, "MAX_QUOTE_QTY",  1000))
        risk_pct   = float(getattr(config, "RISK_PER_TRADE",  0.02))
        
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
            sl_pct = float(getattr(config, "STOP_LOSS_PCT",   0.08))

        risk_amount = portfolio * risk_pct
        qty = risk_amount / (price * sl_pct) if sl_pct > 0 else 0.0
        
        # Cap total quote value
        quote_value = qty * price
        if quote_value > portfolio:
            qty = portfolio / price
        return round(qty, 8)

    def _calculate_sl_tp(self, price: float, action: str, signal: Optional[Dict[str, Any]] = None) -> Tuple[float, float]:
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

        sl_pct = float(getattr(config, "STOP_LOSS_PCT",    0.08))
        tp_pct = float(getattr(config, "TAKE_PROFIT_PCT",  0.20))
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

    async def forward_to_server_b(self, trade_payload: Dict[str, Any]) -> Dict[str, Any]:
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
                    local_url, json=trade_payload, headers=local_headers, timeout=timeout
                ) as resp:
                    body = await resp.json()
                    if resp.status == 200:
                        log.info(
                            f"[VpsAnalyzer] LOCAL executed: "
                            f"{trade_payload['symbol']} {trade_payload['action']}"
                        )
                        return {
                            "success": True, "status": resp.status,
                            "data": body, "executed_on": "local",
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
                except Exception:
                    pass

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
            async with session.post(url, json=trade_payload, headers=headers, timeout=timeout) as resp:
                body = await resp.json()
                if resp.status == 200:
                    log.info(
                        f"[VpsAnalyzer] Server B accepted: "
                        f"{trade_payload['symbol']} {trade_payload['action']}"
                    )
                    return {
                        "success": True, "status": resp.status,
                        "data": body, "executed_on": "server_b",
                    }
                log.error(
                    f"[VpsAnalyzer] Server B rejected (HTTP {resp.status}): {body}"
                )
                return {
                    "success": False, "status": resp.status,
                    "error": body.get("detail", str(body)),
                }
        except aiohttp.ContentTypeError:
            log.error("[VpsAnalyzer] Server B returned non-JSON response")
            return {"success": False, "status": 500, "error": "Non-JSON from Server B"}
        except Exception as exc:
            log.error(f"[VpsAnalyzer] Error forwarding to Server B: {exc}")
            return {"success": False, "status": 0, "error": str(exc)}

    # ── ACK ───────────────────────────────────────────────────────────────────

    async def _ack_signal(self, queue_id: int, status: str, error_msg: str = "") -> bool:
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
        body = {"acks": [{"queue_id": queue_id, "status": status, "error_msg": error_msg}]}
        try:
            session = await self.get_session()
            async with session.post(url, json=body, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    log.info(f"[VpsAnalyzer] ACK #{queue_id} → {status}")
                    return True
                text = await resp.text()
                log.error(f"[VpsAnalyzer] ACK #{queue_id} failed (HTTP {resp.status}): {text[:200]}")
                return False
        except Exception as exc:
            log.error(f"[VpsAnalyzer] ACK #{queue_id} connection error: {exc}")
            return False

    # ── Legacy compatibility: poll + analyze (kept for tests) ─────────────────

    async def poll_and_analyze(self) -> List[Dict[str, Any]]:
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

        async def analyze_single(signal: Dict[str, Any]) -> Dict[str, Any]:
            queue_id = signal.get("queue_id")
            try:
                # Call _analyze_signal (V1 wrapper) — tests mock this directly.
                # Returns: None (rejected) | dict without "approved" key (trade_payload) |
                #          dict with "approved" key (V2 format if mocked that way)
                analyzed = await self._analyze_signal(signal)

                if analyzed is None:
                    # V1: rejected
                    return {
                        "queue_id": queue_id,
                        "approved": False,
                        "reason": "RAG analysis rejected signal — does not meet Minervini criteria",
                    }
                elif isinstance(analyzed, dict) and "approved" in analyzed:
                    # V2 dict returned by a test mock or V2-aware caller
                    if analyzed["approved"]:
                        return {
                            "queue_id": queue_id,
                            "approved": True,
                            "trade_payload": analyzed["trade_payload"],
                        }
                    else:
                        return {
                            "queue_id": queue_id,
                            "approved": False,
                            "reason": analyzed.get("reason", "Analysis rejected signal"),
                        }
                else:
                    # V1: plain trade_payload dict → approved
                    return {
                        "queue_id": queue_id,
                        "approved": True,
                        "trade_payload": analyzed,
                    }

            except Exception as exc:
                log.exception(f"[VpsAnalyzer] Error in poll_and_analyze #{queue_id}: {exc}")
                return {
                    "queue_id": queue_id,
                    "approved": False,
                    "reason": f"Analysis error: {str(exc)[:200]}",
                }

        results = await asyncio.gather(*(analyze_single(sig) for sig in raw_signals))
        return list(results)


if __name__ == "__main__":
    json_format = os.getenv("LOG_JSON_FORMAT", "false").lower() == "true" or getattr(config, "LOG_JSON_FORMAT", False)
    setup_logging(json_format=json_format)
    # Trigger deployment and check Server C clean state
    worker = VpsAnalyzerWorker()
    asyncio.run(worker.run())

