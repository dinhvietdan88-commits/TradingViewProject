import asyncio
import logging
import os
import sys
from pathlib import Path

from aiohttp import web

# Set up paths so we can import workers and config
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "nerves" / "workers" / "trading"))
sys.path.insert(0, str(PROJECT_ROOT))

# Set environment variables for the test mocks BEFORE importing config
os.environ["VPS_BUFFER_ENABLED"] = "true"
os.environ["VPS_BUFFER_URL"] = "http://localhost:9101"
os.environ["VPS_BUFFER_SECRET"] = "mock_secret_a"  # noqa: S105
os.environ["SERVER_B_EXECUTE_URL"] = "http://localhost:9102"
os.environ["SERVER_B_SECRET"] = "mock_secret_b"  # noqa: S105
os.environ["VPS_CONSUMER_ID"] = "sim-consumer-01"
os.environ["RAG_ENABLED"] = "false"  # Use Algorithmic mode


# Set logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("SimulatePipeline")

# Global mocks data
server_a_queue = []
server_a_acks = []
server_b_received_trades = []


# --- Server A Mock ---
async def consume_long_handler(request):
    auth_header = request.headers.get("X-Buffer-Secret")
    if auth_header != "mock_secret_a":
        return web.json_response({"error": "Unauthorized"}, status=401)

    limit = int(request.query.get("limit", 5))
    timeout = int(request.query.get("timeout", 30))

    # Simple long-polling simulation
    elapsed = 0.0
    while elapsed < timeout:
        if server_a_queue:
            batch = server_a_queue[:limit]
            del server_a_queue[:limit]
            log.info(f"[Server A Mock] Dispatched {len(batch)} signals to consumer")
            return web.json_response({"signals": batch})
        await asyncio.sleep(0.5)
        elapsed += 0.5

    return web.json_response({"signals": []})


async def ack_handler(request):
    auth_header = request.headers.get("X-Buffer-Secret")
    if auth_header != "mock_secret_a":
        return web.json_response({"error": "Unauthorized"}, status=401)

    data = await request.json()
    acks = data.get("acks", [])
    for ack in acks:
        log.info(
            f"[Server A Mock] Received ACK for signal {ack.get('queue_id')} with status {ack.get('status')}"
        )
        server_a_acks.append(ack)

    return web.json_response({"acked": len(acks)})


# --- Server B Mock ---
async def execute_trade_handler(request):
    auth_header = request.headers.get("X-Server-B-Secret")
    if auth_header != "mock_secret_b":
        return web.json_response({"error": "Unauthorized"}, status=401)

    data = await request.json()
    log.info(f"[Server B Mock] Received trade execution request: {data}")
    server_b_received_trades.append(data)

    return web.json_response({"success": True, "order_id": "SIM-ORDER-12345"})


async def health_handler(request):
    return web.json_response({"status": "healthy"})


# Setup mock servers
async def start_mock_servers():
    # Server A
    app_a = web.Application()
    app_a.router.add_get("/consume-long", consume_long_handler)
    app_a.router.add_post("/ack", ack_handler)
    runner_a = web.AppRunner(app_a)
    await runner_a.setup()
    site_a = web.TCPSite(runner_a, "localhost", 9101)
    await site_a.start()

    # Server B
    app_b = web.Application()
    app_b.router.add_post("/api/execute-trade", execute_trade_handler)
    app_b.router.add_get("/health", health_handler)
    runner_b = web.AppRunner(app_b)
    await runner_b.setup()
    site_b = web.TCPSite(runner_b, "localhost", 9102)
    await site_b.start()

    log.info("[Mocks] Started Server A (port 9101) and Server B (port 9102)")
    return runner_a, runner_b


# Main simulation loop
async def main():
    # Initialize SQLite database
    import database

    await database.init_db()

    # Start mock servers
    runner_a, runner_b = await start_mock_servers()

    try:
        # Populate Server A queue with a valid breakout long signal
        # Includes `atr` parameter to trigger new dynamic SL/TP and position sizing logic
        test_signal = {
            "queue_id": 999,
            "symbol": "BTCUSDT",
            "action": "buy",
            "price": 100.0,
            "interval": "1h",
            "payload": {
                "ema_50": 90.0,
                "ema_150": 80.0,
                "volume": 2000.0,
                "volume_avg": 1000.0,
                "rsi": 65.0,
                "alert_type": "vcp",
                "sl": 95.0,  # 5% risk, <= 8% Minervini rule
                "atr": 2.5,  # ATR parameter
            },
        }
        server_a_queue.append(test_signal)
        log.info(f"[Simulation] Queued test signal on Server A: {test_signal}")

        # Instantiate VPS Analyzer Worker (from Server C)
        from workers.vps_analyzer import VpsAnalyzerWorker

        analyzer = VpsAnalyzerWorker()
        analyzer.LONG_POLL_TIMEOUT = 5  # short timeout for simulation

        # Force Algorithmic Mode by setting the LLM circuit breaker state to OPEN
        from workers.ai_circuit_breaker import CircuitState, llm_breaker

        llm_breaker.state = CircuitState.OPEN
        llm_breaker.is_available = lambda: False

        log.info(
            "[Simulation] Starting VpsAnalyzerWorker loop step (Forced Algorithmic)..."
        )
        # Run one iteration of poll_and_analyze and process
        analyzed_list = await analyzer.poll_and_analyze()
        log.info(f"[Simulation] Analyzed list: {analyzed_list}")

        # Verify analysis output and correct ATR SL/TP calculations
        assert len(analyzed_list) == 1, "Should have analyzed 1 signal"
        analyzed = analyzed_list[0]
        assert analyzed["approved"] is True, (
            "Signal should be approved by Algorithmic mode"
        )

        trade_payload = analyzed["trade_payload"]
        # Expected dynamic calculation with ATR = 2.5:
        # Price = 100.0
        # sl = Price - 2 * ATR = 100 - 5 = 95.0
        # tp = Price + 5 * ATR = 100 + 12.5 = 112.5
        # sl_pct = 2 * ATR / Price = 5 / 100 = 0.05
        # risk_amount = portfolio (1000) * risk_pct (0.02) = 20
        # qty = risk_amount / (Price * sl_pct) = 20 / 5 = 4.0
        assert trade_payload["sl"] == 95.0, (
            f"Expected SL 95.0, got {trade_payload['sl']}"
        )
        assert trade_payload["tp"] == 112.5, (
            f"Expected TP 112.5, got {trade_payload['tp']}"
        )
        assert trade_payload["qty"] == 4.0, (
            f"Expected qty 4.0, got {trade_payload['qty']}"
        )

        log.info(
            "[Simulation] ATR Stop Loss, Take Profit, and Position sizing calculations verified successfully!"
        )

        # Forward approved signal to Server B
        log.info("[Simulation] Forwarding approved signal to Server B...")
        fwd = await analyzer.forward_to_server_b(trade_payload)
        assert fwd.get("success") is True, "Forwarding to Server B should succeed"

        # ACK signal back to Server A
        log.info("[Simulation] Sending ACK back to Server A...")
        await analyzer._ack_signal(999, "executed")

        # Final assertions
        assert len(server_b_received_trades) == 1, (
            "Server B should have received exactly 1 trade execution request"
        )
        assert len(server_a_acks) == 1, (
            "Server A should have received exactly 1 ACK confirmation"
        )
        assert server_a_acks[0]["queue_id"] == 999
        assert server_a_acks[0]["status"] == "executed"

        log.info("[Simulation] E2E Pipeline Simulation Completed Successfully!")
        log.info("[Simulation] Server A -> Server C -> Server B flow fully verified!")

    finally:
        # Cleanup
        try:
            await analyzer.close()
        except ValueError as e:
            import logging

            logging.getLogger(__name__).warning("Ignored: %s", e)
        await runner_a.cleanup()
        await runner_b.cleanup()
        log.info("[Simulation] Mock servers stopped.")


if __name__ == "__main__":
    asyncio.run(main())
