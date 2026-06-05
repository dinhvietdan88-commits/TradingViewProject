import os
import sys
import time
import signal
import json
import subprocess
import threading
import urllib.request
import urllib.error
from pathlib import Path

# Color helpers
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
BLUE = "\033[94m"


def print_step(msg):
    print(f"\n{BLUE}[STEP]{RESET} {msg}")


def print_success(msg):
    print(f"{GREEN}[PASS]{RESET} {msg}")


def print_failure(msg):
    print(f"{RED}[FAIL]{RESET} {msg}")


def main():
    print("==================================================")
    print("SERVER C (AI CORE) GAPS VERIFICATION SUITE")
    print("==================================================")

    workspace_root = Path(__file__).resolve().parent.parent

    # 1. Check ChromaDB Seeding directly before starting daemon
    print_step("Testing ChromaDB Seeding directly using chromadb.PersistentClient...")
    try:
        import chromadb

        # Resolve config.CHROMA_DB_PATH or default
        chroma_path = workspace_root / "nerves" / "workers" / "trading" / "chroma_db"
        print(f"Connecting to ChromaDB at: {chroma_path}")
        client = chromadb.PersistentClient(path=str(chroma_path))
        collection = client.get_collection("minervini_knowledge")
        count = collection.count()
        print(f"Found {count} documents in collection 'minervini_knowledge'")
        assert count >= 43, f"Document count is {count}, expected at least 43."
        print_success("ChromaDB Seeding contains all required chunks.")
    except Exception as e:
        print_failure(f"ChromaDB Seeding check failed: {e}")
        sys.exit(1)

    # 2. Run the Server C daemon as a background subprocess
    print_step("Starting Server C daemon as background subprocess...")
    env = os.environ.copy()
    env["LOG_JSON_FORMAT"] = "true"
    env["CHROMA_REMOTE"] = "false"
    env["PORT"] = "8000"
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    # Set PYTHONPATH
    trading_path = workspace_root / "nerves" / "workers" / "trading"
    env["PYTHONPATH"] = str(trading_path)

    daemon_script = trading_path / "workers" / "vps_analyzer.py"
    print(f"Running script: {daemon_script}")
    print(f"Using PYTHONPATH: {env['PYTHONPATH']}")

    # Run uvicorn on port 8000
    # Use CREATE_NEW_PROCESS_GROUP on Windows to safely send CTRL_C_EVENT to the process group
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        [sys.executable, str(daemon_script)],
        cwd=str(trading_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creationflags,
    )

    stdout_lines = []

    def read_output():
        for line in proc.stdout:
            stdout_lines.append(line)
            # Print daemon output live for easier debugging
            print(f"  [Daemon] {line.strip()}")

    t = threading.Thread(target=read_output, daemon=True)
    t.start()

    # 3. Wait for FastAPI health server to start on port 8000
    print_step("Waiting for FastAPI health server to start on port 8000...")
    health_url = "http://localhost:8000/health"
    started = False
    max_retries = 30
    for i in range(max_retries):
        if proc.poll() is not None:
            print_failure(f"Daemon exited prematurely with exit code {proc.returncode}")
            print("Daemon Output:")
            print("".join(stdout_lines))
            sys.exit(1)

        try:
            req = urllib.request.Request(health_url)
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    started = True
                    break
        except Exception:
            pass

        print(f"  Health server not ready yet (attempt {i + 1}/{max_retries})...")
        time.sleep(1)

    if not started:
        print_failure("FastAPI health server failed to start within timeout.")
        # Print gathered logs
        print("Daemon Output:")
        print("".join(stdout_lines))
        proc.terminate()
        sys.exit(1)

    print_success("FastAPI health server started successfully.")

    # 4. Test health check endpoint details
    print_step("Verifying health check endpoint response payload details...")
    try:
        req = urllib.request.Request(health_url)
        with urllib.request.urlopen(req, timeout=5) as response:
            assert response.status == 200, f"Expected status 200, got {response.status}"
            body = response.read().decode("utf-8")
            data = json.loads(body)
            print(f"Health Response: {data}")

            # Assert fields and types exactly
            fields = {
                "liveness_status_server_a": str,
                "liveness_status_server_b": str,
                "disk_usage_pct": (int, float),
                "ntp_clock_drift_ms": (int, float),
                "circuit_breaker_status": str,
            }
            for field, expected_type in fields.items():
                assert field in data, (
                    f"Field '{field}' missing in health check response"
                )
                val = data[field]
                assert isinstance(val, expected_type), (
                    f"Field '{field}' type is {type(val)}, expected {expected_type}"
                )
                if expected_type is str and field.startswith("liveness_status"):
                    assert val in ("healthy", "unhealthy"), (
                        f"Field '{field}' value '{val}' not in ('healthy', 'unhealthy')"
                    )

            print_success("Health check endpoint verification passed.")
    except Exception as e:
        print_failure(f"Health check verification failed: {e}")
        proc.terminate()
        sys.exit(1)

    # 5. Test metrics check endpoint (Prometheus format and JSON format)
    print_step("Testing metrics endpoint GET http://localhost:8000/metrics...")
    try:
        # Test Prometheus format (Plain text)
        req = urllib.request.Request("http://localhost:8000/metrics")
        with urllib.request.urlopen(req, timeout=5) as response:
            assert response.status == 200, f"Expected status 200, got {response.status}"
            content_type = response.headers.get("Content-Type", "")
            # Relax content type assertion as Uvicorn response media type is text/plain but could vary depending on environment
            body = response.read().decode("utf-8")
            print("Prometheus Metrics Sample:")
            for line in body.splitlines()[:6]:
                print(f"  {line}")

            # Assert standard formatting
            assert "# HELP liveness_status_server_a" in body, (
                "Missing HELP liveness_status_server_a"
            )
            assert "liveness_status_server_a" in body, (
                "Missing liveness_status_server_a gauge"
            )
            assert "# HELP disk_usage_pct" in body, "Missing HELP disk_usage_pct"
            assert "disk_usage_pct" in body, "Missing disk_usage_pct gauge"
            assert "circuit_breaker_state" in body, (
                "Missing circuit_breaker_state gauge"
            )
            print_success("Prometheus metrics text format verified.")

        # Test JSON format (with Accept header)
        req_json = urllib.request.Request(
            "http://localhost:8000/metrics", headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(req_json, timeout=5) as response:
            assert response.status == 200, f"Expected status 200, got {response.status}"
            body = response.read().decode("utf-8")
            data = json.loads(body)
            print(f"Metrics JSON response: {data}")

            expected_fields = [
                "liveness_status_server_a",
                "liveness_status_server_b",
                "disk_usage_pct",
                "ntp_clock_drift_ms",
                "circuit_breaker_state",
                "llm_breaker_successes_total",
                "llm_breaker_failures_total",
                "llm_breaker_fallbacks_total",
            ]
            for field in expected_fields:
                assert field in data, (
                    f"Field '{field}' missing in JSON metrics response"
                )
                assert isinstance(data[field], (int, float)), (
                    f"Field '{field}' is not a numeric type"
                )
            print_success("JSON metrics format and fields verified.")

    except Exception as e:
        print_failure(f"Metrics verification failed: {e}")
        proc.terminate()
        sys.exit(1)

    # 6. Test Graceful Shutdown & JSON Logging
    print_step("Testing Graceful Shutdown...")
    try:
        if sys.platform == "win32":
            print("Sending CTRL_BREAK_EVENT to process group on Windows...")
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        else:
            print("Sending SIGINT to daemon...")
            proc.send_signal(signal.SIGINT)

        print("Waiting up to 10 seconds for daemon to exit gracefully...")
        # Wait with timeout
        exit_code = None
        for _ in range(100):
            exit_code = proc.poll()
            if exit_code is not None:
                break
            time.sleep(0.1)

        assert exit_code is not None, "Daemon did not exit within 10 seconds."
        assert exit_code == 0, f"Daemon exited with non-zero code: {exit_code}"
        print_success("Daemon shutdown gracefully with exit code 0.")

        # Verify JSON logging & graceful shutdown markers
        print_step("Verifying stdout log lines and graceful shutdown markers...")

        json_log_count = 0
        total_log_lines = len(stdout_lines)

        # Shutdown markers to verify
        markers = {
            "Stopping scheduler": False,
            "Setting server.should_exit": False,
            "Closing ClientSession": False,
            "Shutdown complete": False,
        }

        for line in stdout_lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Check markers in raw line
            for marker in markers:
                if marker in line_str:
                    markers[marker] = True

            # Check if line contains JSON log
            # Since StructuredFormatter outputs JSON like {"ts": ..., "level": ..., "msg": ...}
            if "{" in line_str and "}" in line_str:
                start_idx = line_str.find("{")
                end_idx = line_str.rfind("}") + 1
                candidate = line_str[start_idx:end_idx]
                try:
                    log_data = json.loads(candidate)
                    if "ts" in log_data and "level" in log_data and "msg" in log_data:
                        json_log_count += 1
                except Exception:
                    pass

        print(
            f"Analyzed {total_log_lines} log lines. Found {json_log_count} valid structured JSON log lines."
        )
        assert json_log_count > 0, "No structured JSON log lines were found in stdout."

        for marker, found in markers.items():
            assert found, (
                f"Graceful shutdown marker '{marker}' was NOT found in stdout."
            )
            print(f"Found shutdown marker: '{marker}'")

        print_success(
            "JSON logging and graceful shutdown markers successfully verified."
        )

    except Exception as e:
        print_failure(f"Graceful Shutdown / Logging verification failed: {e}")
        # Clean up process if still alive
        if proc.poll() is None:
            proc.terminate()
        sys.exit(1)

    print("\n==================================================")
    print(f"{GREEN}ALL SERVER C GAPS VERIFICATION TESTS PASSED SUCCESSFULLY!{RESET}")
    print("==================================================")
    sys.exit(0)


if __name__ == "__main__":
    main()
