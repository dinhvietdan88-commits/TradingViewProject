import os
import sys
import time
import asyncio
import subprocess
import httpx
from pathlib import Path
from unittest.mock import AsyncMock

# Adjust sys.path to import nerves/workers/trading modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRADING_WORKER_DIR = PROJECT_ROOT / "nerves" / "workers" / "trading"
if str(TRADING_WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(TRADING_WORKER_DIR))

# Clear old test databases in scratch
scratch_dir = PROJECT_ROOT / "scratch"
scratch_dir.mkdir(exist_ok=True)
vbs_db_path = scratch_dir / "vbs_test.db"
server_c_db_path = scratch_dir / "server_c_test.db"
server_c_fwd_db_path = scratch_dir / "server_c_forward_test.db"

for path in [vbs_db_path, server_c_db_path, server_c_fwd_db_path]:
    if path.exists():
        try:
            path.unlink()
        except Exception:
            pass

# Set environment variables for VBS subprocess
vbs_env = os.environ.copy()
vbs_env["PORT"] = "9099"
vbs_env["DB_PATH"] = str(vbs_db_path)
vbs_env["BUFFER_SECRET"] = "test-secret"
vbs_env["TELEGRAM_BOT_ENABLED"] = "false"
vbs_env["PYTHONPATH"] = str(PROJECT_ROOT / "vbs")

# Start VBS subprocess
print("[E2E Validation] Starting VBS on port 9099...")
vbs_process = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "9099"],
    cwd=str(PROJECT_ROOT / "vbs"),
    env=vbs_env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

# Wait for VBS to boot
time.sleep(3)
if vbs_process.poll() is not None:
    stdout, stderr = vbs_process.communicate()
    print(f"[E2E Validation] VBS failed to start. Stdout: {stdout}\nStderr: {stderr}")
    sys.exit(1)

print("[E2E Validation] VBS booted successfully.")

async def run_validation():
    # Configure Server C settings
    import config
    import database
    from workers.vps_consumer import VpsSignalConsumer

    config.DB_PATH = str(server_c_db_path)
    config.FORWARD_DB_PATH = str(server_c_fwd_db_path)
    config.FORWARD_TEST_ENABLED = True
    config.VPS_BUFFER_URL = "http://127.0.0.1:9099"
    config.VPS_BUFFER_SECRET = "test-secret"
    config.VPS_CONSUMER_ID = "test-consumer"

    print("[E2E Validation] Initializing Server C databases...")
    await database.init_db()

    # Step 1: Send mock signal to VBS /ingest endpoint
    print("[E2E Validation] Ingesting test signal to VBS...")
    payload = {
        "symbol": "SOLUSDT",
        "action": "buy",
        "price": "145.50",
        "secret": "test-secret",
        "source": "strategy",
        "payload": {
            "sl": "135.00",
            "tp": "165.00"
        }
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post("http://127.0.0.1:9099/ingest", json=payload)
        print(f"[E2E Validation] VBS /ingest Response: {resp.status_code} - {resp.json()}")
        assert resp.status_code == 200
        assert resp.json()["queued"] is True
        queue_id = resp.json()["queue_id"]

    # Step 2: Use VpsSignalConsumer to pull and process the signal
    print("[E2E Validation] Pulling signals from VBS...")
    consumer = VpsSignalConsumer()
    
    # We patch the event bus to avoid sending actual background events/orders during dry-run
    from core.event_bus import bus as _event_bus
    original_emit = _event_bus.emit_background
    _event_bus.emit_background = AsyncMock()

    signals = await consumer.pull_signals(limit=1)
    print(f"[E2E Validation] Pulled {len(signals)} signal(s) from VBS.")
    assert len(signals) == 1
    assert signals[0]["queue_id"] == queue_id

    print("[E2E Validation] Processing signal in VpsSignalConsumer...")
    await consumer._process_signal(signals[0])

    # Restore emit
    _event_bus.emit_background = original_emit
    await consumer.close()

    # Step 3: Verify the database insertion
    print("[E2E Validation] Checking forward_trades.db for the signal...")
    import aiosqlite
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        async with db.execute(
            "SELECT id, symbol, action, mode, vbs_queue_id FROM signals WHERE vbs_queue_id = ?", (queue_id,)
        ) as cur:
            row = await cur.fetchone()
            
    assert row is not None, "Signal was not stored in forward_trades.db"
    sig_id, sym, act, mode, vq_id = row
    
    print(f"[E2E Validation] Stored signal details: ID={sig_id}, Symbol={sym}, Action={act}, Mode={mode}, VBS_Queue_ID={vq_id}")
    assert sig_id >= 1000000, f"Expected ID >= 1,000,000, got {sig_id}"
    assert mode == "FORWARD", f"Expected mode=FORWARD, got {mode}"

    print("[E2E Validation] E2E Dry-run verification PASSED successfully!")

if __name__ == "__main__":
    try:
        asyncio.run(run_validation())
    finally:
        print("[E2E Validation] Terminating VBS subprocess...")
        vbs_process.terminate()
        vbs_process.wait()
        print("[E2E Validation] Cleaned up VBS.")
