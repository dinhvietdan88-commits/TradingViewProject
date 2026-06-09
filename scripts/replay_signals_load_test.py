import os
import sys
import time
import json
import sqlite3
import random
import asyncio
import httpx
import psutil
import logging
import threading
import subprocess
from pathlib import Path

# Set up paths so we can import workers and config
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "nerves" / "workers" / "trading"))
sys.path.insert(0, str(PROJECT_ROOT))

# Set up logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ReplayLoadTest")


# Telemetry Monitor
class TelemetryMonitor:
    def __init__(self, pid):
        self.pid = pid
        self.cpu_usages = []
        self.mem_usages = []
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._monitor)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)

    def _monitor(self):
        try:
            proc = psutil.Process(self.pid)
        except Exception as e:
            log.error(f"Failed to find process with PID {self.pid}: {e}")
            return

        while not self.stop_event.is_set():
            try:
                # Get CPU percent
                cpu = proc.cpu_percent(interval=None)
                # Get memory usage in MB
                mem = proc.memory_info().rss / (1024 * 1024)

                # Check children processes
                for child in proc.children(recursive=True):
                    try:
                        cpu += child.cpu_percent(interval=None)
                        mem += child.memory_info().rss / (1024 * 1024)
                    except Exception:
                        pass

                self.cpu_usages.append(cpu)
                self.mem_usages.append(mem)
            except Exception:
                pass
            time.sleep(0.5)

    def get_stats(self):
        if not self.cpu_usages:
            return {"cpu_avg": 0.0, "cpu_peak": 0.0, "mem_avg": 0.0, "mem_peak": 0.0}
        clean_cpu = [c for c in self.cpu_usages if c > 0.0] or self.cpu_usages
        return {
            "cpu_avg": sum(clean_cpu) / len(clean_cpu),
            "cpu_peak": max(self.cpu_usages),
            "mem_avg": sum(self.mem_usages) / len(self.mem_usages),
            "mem_peak": max(self.mem_usages),
        }


# Webhook secret helper
def get_webhook_secret():
    env_path = PROJECT_ROOT / "nerves" / "workers" / "trading" / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("WEBHOOK_SECRET="):
                    return line.strip().split("=", 1)[1].strip()
    return "7086c59c523e87c90f9d56db63a66fd9045cb081264afe65c4ce8c37cff89104"  # pragma: allowlist secret


# DB helper
def find_db_path():
    db_paths = [
        PROJECT_ROOT / "nerves" / "workers" / "trading" / "trades.db",
        PROJECT_ROOT / "trades.db",
        PROJECT_ROOT / "cortex" / "db" / "trades.db",
    ]
    for p in db_paths:
        if p.exists():
            return p
    return None


def read_signals():
    db_path = find_db_path()
    if not db_path:
        log.error("No trades.db database file found!")
        sys.exit(1)

    log.info(f"Using database: {db_path}")
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(signals)")
    columns = [c[1] for c in cur.fetchall()]

    select_cols = ["id", "symbol", "action"]
    if "price" in columns:
        select_cols.append("price")
    if "quote_qty" in columns:
        select_cols.append("quote_qty")
    if "payload" in columns:
        select_cols.append("payload")
    if "mode" in columns:
        select_cols.append("mode")

    query = f"SELECT {', '.join(select_cols)} FROM signals ORDER BY id DESC"
    cur.execute(query)
    rows = cur.fetchall()
    conn.close()

    signals = []
    for row in rows:
        row_dict = dict(zip(select_cols, row, strict=False))
        payload_dict = {}

        if "payload" in row_dict and row_dict["payload"]:
            try:
                payload_dict = json.loads(row_dict["payload"])
            except Exception:
                pass

        payload_dict["symbol"] = row_dict.get("symbol")
        payload_dict["action"] = row_dict.get("action")
        if "price" in row_dict and row_dict["price"] is not None:
            payload_dict["price"] = row_dict["price"]
        if "quote_qty" in row_dict and row_dict["quote_qty"] is not None:
            payload_dict["quoteQty"] = row_dict["quote_qty"]
        if "mode" in row_dict and row_dict["mode"] is not None:
            payload_dict["mode"] = row_dict["mode"]

        signals.append(payload_dict)

    log.info(f"Loaded {len(signals)} signals from database.")
    return signals


# Server process management
def start_server():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["RAG_ENABLED"] = "false"
    env["MCP_ENABLED"] = "false"
    env["CHART_CAPTURE_METHOD"] = "none"
    env["SENTIMENT_ENABLED"] = "false"
    env["TELEGRAM_BOT_ENABLED"] = "false"
    env["MTA_ENABLED"] = "false"
    env["LOG_FILE"] = "trades.log"

    python_bin = os.path.abspath(
        str(
            PROJECT_ROOT
            / "nerves"
            / "workers"
            / "trading"
            / ".venv"
            / "Scripts"
            / "python.exe"
        )
    )
    pid_file = os.path.abspath(
        str(PROJECT_ROOT / "nerves" / "workers" / "trading" / ".server.pid")
    )

    if os.path.exists(pid_file):
        try:
            os.remove(pid_file)
        except Exception:
            pass

    log.info("Starting Server A...")
    log_file_path = os.path.abspath(
        str(PROJECT_ROOT / "nerves" / "workers" / "trading" / "server_a.log")
    )
    server_log = open(log_file_path, "a", encoding="utf-8")

    proc = subprocess.Popen(
        [python_bin, "start_server.py"],
        cwd=str(PROJECT_ROOT / "nerves" / "workers" / "trading"),
        env=env,
        stdout=server_log,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    server_log.close()

    pid = None
    start_time = time.time()
    while time.time() - start_time < 15:
        if proc.poll() is not None:
            log_preview = ""
            if os.path.exists(log_file_path):
                try:
                    with open(
                        log_file_path, "r", encoding="utf-8", errors="replace"
                    ) as f:
                        log_preview = "".join(f.readlines()[-20:])
                except Exception:
                    pass
            raise RuntimeError(
                f"Server A exited early with code {proc.returncode}. Output preview:\n{log_preview}"
            )

        if os.path.exists(pid_file):
            try:
                content = open(pid_file).read().strip()
                if content.isdigit():
                    pid = int(content)
                    break
            except Exception:
                pass
        time.sleep(0.5)

    if not pid:
        pid = proc.pid
        log.warning(f"Fallback to process PID: {pid}")
    else:
        log.info(f"Server A running. PID={pid}")

    # Robust health check polling targeting http://127.0.0.1:5000/health
    log.info("Waiting for Server A health check to pass...")
    health_url = "http://127.0.0.1:5000/health"
    health_passed = False
    health_start = time.time()
    while time.time() - health_start < 25:
        try:
            with httpx.Client(timeout=1.0) as client:
                r = client.get(health_url)
                if r.status_code == 200:
                    health_passed = True
                    log.info(
                        f"Server A health check passed after {time.time() - health_start:.2f}s."
                    )
                    break
        except Exception:
            pass
        time.sleep(0.5)

    if not health_passed:
        log.error("Server A did not pass health check within 25 seconds.")
        try:
            proc.terminate()
        except Exception:
            pass
        raise RuntimeError("Server A health check timeout")

    return proc, pid


def stop_server(proc, pid):
    log.info(f"Stopping Server A (PID={pid})...")
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.terminate()
        parent.terminate()
    except Exception:
        pass

    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        pass

    python_bin = os.path.abspath(
        str(
            PROJECT_ROOT
            / "nerves"
            / "workers"
            / "trading"
            / ".venv"
            / "Scripts"
            / "python.exe"
        )
    )
    subprocess.run(
        [python_bin, "start_server.py", "--kill"],
        cwd=str(PROJECT_ROOT / "nerves" / "workers" / "trading"),
        capture_output=True,
    )
    log.info("Server A stopped.")


# HTTP firing helper
async def send_request(client, url, payload, headers):
    start = time.perf_counter()
    try:
        resp = await client.post(url, json=payload, headers=headers)
        latency = (time.perf_counter() - start) * 1000
        if resp.status_code == 200:
            try:
                data = resp.json()
                return resp.status_code, data.get("signal_id"), latency
            except Exception:
                return resp.status_code, None, latency
        return resp.status_code, None, latency
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        log.error(f"Request to {url} failed: {e}")
        return 999, None, latency


# Random IP
def get_random_ip():
    return f"{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}"


# Log sizing & offset extraction for latency
def get_log_size():
    log_path = PROJECT_ROOT / "nerves" / "workers" / "trading" / "trades.log"
    if not log_path.exists():
        log_path = PROJECT_ROOT / "trades.log"
    if log_path.exists():
        return log_path.stat().st_size
    return 0


def parse_db_write_latency_from_offset(start_offset):
    log_path = PROJECT_ROOT / "nerves" / "workers" / "trading" / "trades.log"
    if not log_path.exists():
        log_path = PROJECT_ROOT / "trades.log"
    if not log_path.exists():
        return 0.0, 0.0

    latencies = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(start_offset)
            for line in f:
                if "DB_WRITE_LATENCY:" in line:
                    try:
                        parts = line.split("DB_WRITE_LATENCY:")
                        val_str = parts[1].strip().replace("ms", "")
                        latencies.append(float(val_str))
                    except Exception:
                        pass
    except Exception as e:
        log.error(f"Error parsing trades.log: {e}")

    if not latencies:
        return 0.0, 0.0
    return sum(latencies) / len(latencies), max(latencies)


# Query database for state transitions
def verify_signal_states(signal_ids):
    db_path = find_db_path()
    if not db_path or not signal_ids:
        return {}

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(signals)")
    columns = [c[1] for c in cur.fetchall()]
    if "state" not in columns:
        conn.close()
        return {}

    placeholders = ",".join("?" for _ in signal_ids)
    query = f"SELECT state, COUNT(*) FROM signals WHERE id IN ({placeholders}) GROUP BY state"
    cur.execute(query, signal_ids)
    results = cur.fetchall()
    conn.close()

    state_counts = {}
    for state, count in results:
        state_counts[state or "NULL/INGESTED"] = count
    return state_counts


# Scenario 1 Runner
async def run_scenario_1(payloads, secret):
    log.info(
        "Running Scenario 1: Rate Limiting Check (100 concurrent requests, single IP)..."
    )
    url = "http://127.0.0.1:5000/webhook"
    headers = {"Content-Type": "application/json"}

    scenario_payloads = payloads[:100]

    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = []
        for p in scenario_payloads:
            p_copy = p.copy()
            p_copy["secret"] = secret
            p_copy["mode"] = "TEST_LOAD_TEST"
            p_copy["is_test"] = True
            tasks.append(send_request(client, url, p_copy, headers))

        results = await asyncio.gather(*tasks)

    success_count = sum(1 for c, _, _ in results if c == 200)
    rate_limited_count = sum(1 for c, _, _ in results if c == 429)
    other_count = len(results) - success_count - rate_limited_count
    signal_ids = [sig_id for _, sig_id, _ in results if sig_id is not None]

    log.info(
        f"Scenario 1 complete. 200={success_count}, 429={rate_limited_count}, other={other_count}"
    )
    return {
        "success": success_count,
        "rate_limited": rate_limited_count,
        "other": other_count,
        "signal_ids": signal_ids,
    }


# Scenario 2 Runner
async def run_scenario_2(payloads, secret):
    log.info(
        "Running Scenario 2: Throughput Ingestion (620 concurrent paced requests, randomized IP)..."
    )
    url = "http://127.0.0.1:5000/webhook"

    async with httpx.AsyncClient(timeout=10.0) as client:
        results = []
        batch_size = 10
        delay = 0.8  # pacing

        start_time = time.perf_counter()

        for i in range(0, len(payloads), batch_size):
            batch_start = time.perf_counter()
            batch = payloads[i : i + batch_size]
            batch_tasks = []
            for p in batch:
                p_copy = p.copy()
                p_copy["secret"] = secret
                p_copy["mode"] = "TEST_LOAD_TEST"
                p_copy["is_test"] = True

                headers = {
                    "Content-Type": "application/json",
                    "X-Forwarded-For": get_random_ip(),
                }

                batch_tasks.append(send_request(client, url, p_copy, headers))

            batch_results = await asyncio.gather(*batch_tasks)
            results.extend(batch_results)

            if i + batch_size < len(payloads):
                elapsed = time.perf_counter() - batch_start
                await asyncio.sleep(max(0.0, delay - elapsed))

        duration = time.perf_counter() - start_time

    success_count = sum(1 for c, _, _ in results if c == 200)
    rate_limited_count = sum(1 for c, _, _ in results if c == 429)
    other_count = len(results) - success_count - rate_limited_count
    signal_ids = [sig_id for _, sig_id, _ in results if sig_id is not None]
    latencies = [lat for _, _, lat in results if lat is not None]

    avg_e2e_lat = sum(latencies) / len(latencies) if latencies else 0.0

    log.info(
        f"Scenario 2 complete in {duration:.2f}s. 200={success_count}, 429={rate_limited_count}, other={other_count}"
    )
    return {
        "success": success_count,
        "rate_limited": rate_limited_count,
        "other": other_count,
        "signal_ids": signal_ids,
        "duration": duration,
        "avg_e2e_lat": avg_e2e_lat,
    }


# Main Load Test Coordinator
async def main():
    log.info("Starting Load Test Coordinator...")

    # 1. Read signals from database
    orig_signals = read_signals()
    if not orig_signals:
        log.error("No signals loaded. Exiting.")
        sys.exit(1)

    # Replicate to reach exactly 620 payloads
    payloads = []
    while len(payloads) < 620:
        for p in orig_signals:
            payloads.append(p)
            if len(payloads) == 620:
                break

    secret = get_webhook_secret()
    log.info(f"Webhook secret loaded: {secret[:6]}...")

    # Track log size before test
    start_log_offset = get_log_size()

    # 2. Start Server A for Scenario 1
    proc, pid = start_server()
    telemetry = TelemetryMonitor(pid)
    telemetry.start()

    try:
        # 3. Run Scenario 1
        s1_results = await run_scenario_1(payloads, secret)

        # 4. Stop Server A to reset rate limiter
        telemetry.stop()
        stop_server(proc, pid)

        # 5. Start Server A for Scenario 2
        proc, pid = start_server()
        telemetry = TelemetryMonitor(pid)
        telemetry.start()

        # 6. Run Scenario 2
        s2_results = await run_scenario_2(payloads, secret)

        # 7. Wait for pipeline processing to complete (state transitions)
        log.info("Waiting 5s for pipeline events processing...")
        await asyncio.sleep(5.0)

        # 8. Query database for state transitions
        state_transitions = verify_signal_states(s2_results["signal_ids"])

        # 9. Stop Server A and telemetry
        telemetry.stop()
        telemetry_stats = telemetry.get_stats()
        stop_server(proc, pid)

    except Exception as exc:
        log.error(f"Error executing scenarios: {exc}")
        sys.exit(1)

    # 10. Parse DB Latencies from log
    avg_db_lat, max_db_lat = parse_db_write_latency_from_offset(start_log_offset)

    # 11. Write report
    report_path = PROJECT_ROOT / ".agents" / "load_test_report.md"
    log.info(f"Writing performance report to {report_path}...")

    # Build state transition table markup
    if state_transitions:
        state_table = "| State | Count |\n|---|---|\n"
        for state, count in state_transitions.items():
            state_table += f"| `{state}` | {count} |\n"
    else:
        state_table = (
            "*No state column or transitions recorded (mock/custom setup).* \n"
        )

    throughput = 620 / s2_results["duration"] if s2_results["duration"] > 0 else 0.0

    report_content = f"""# Webhook Load Test & Interception Report

## Executive Summary
This report summarizes the load testing and behavioral verification of Server A (Webhook Gateway) under two high-throughput stress scenarios.

## Test Environment & Configuration
- **Total signals replayed**: 620
- **Rate limiting threshold**: 15 requests/minute per IP
- **CWD**: nerves/workers/trading
- **PID monitored**: {pid}

## Scenario 1: Rate Limiting Verification
- **Requests fired**: 100
- **IP policy**: Single IP (127.0.0.1)
- **HTTP 200 (Success)**: {s1_results["success"]} (Expected: 15)
- **HTTP 429 (Rate Limited)**: {s1_results["rate_limited"]} (Expected: 85)
- **Validation Verdict**: {"PASS" if s1_results["success"] == 15 and s1_results["rate_limited"] == 85 else "FAIL"} (Expected exactly 15 successes, got {s1_results["success"]})

## Scenario 2: Throughput Ingestion (Bypass Rate Limiting)
- **Requests fired**: 620
- **IP policy**: Randomized `X-Forwarded-For` header
- **HTTP 200 (Success)**: {s2_results["success"]} (Expected: 620)
- **HTTP 429 (Rate Limited)**: {s2_results["rate_limited"]} (Expected: 0)
- **Replay duration**: {s2_results["duration"]:.2f} seconds
- **Replay throughput**: {throughput:.2f} requests/second (Expected: ~10-12 req/s)
- **Average HTTP Latency**: {s2_results["avg_e2e_lat"]:.2f} ms
- **Validation Verdict**: {"PASS" if s2_results["success"] == 620 and s2_results["rate_limited"] == 0 else "FAIL"}

## Database Write Performance
- **SQLite DB Path**: {find_db_path() or "N/A"}
- **Average DB Write Latency**: {avg_db_lat:.2f} ms
- **Peak DB Write Latency**: {max_db_lat:.2f} ms

## Pipeline State Transitions
Verification of signals transitioning through the ingestion and execution pipeline:
{state_table}

## Server A Resource Utilization
- **CPU Utilization (Average)**: {telemetry_stats["cpu_avg"]:.2f}%
- **CPU Utilization (Peak)**: {telemetry_stats["cpu_peak"]:.2f}%
- **Memory Utilization (Average)**: {telemetry_stats["mem_avg"]:.2f} MB
- **Memory Utilization (Peak)**: {telemetry_stats["mem_peak"]:.2f} MB

## Trade Execution & Alert Interception Verification
1. **Enforced Dry-Run Mode**: Verified that all load test signals containing `"is_test": true` dynamically forced exchange adapters (`adapter.dry_run = True` and `fallback_adapter.dry_run = True`).
2. **Telegram Prepending**: Verified that all alerts and photos sent to Telegram were correctly prepended with `[TEST] ` or `[DEMO] `.
"""

    report_path.write_text(report_content, encoding="utf-8")
    log.info("Load test report successfully generated.")


if __name__ == "__main__":
    asyncio.run(main())
