"""
start_server.py -- Sovereign Server Launcher with SO_REUSEADDR + UTF-8
Prevents zombie socket conflicts and UnicodeEncodeError on Windows cp1252.
Usage: python start_server.py [--port 5000] [--kill]

SCAR-TVP-001: Never use Start-Process powershell for uvicorn.
              Always run this script directly in the terminal.
SCAR-TVP-002: Always kill existing process on port before binding.
              Old process = stale code in memory → fixes 401/409 zombie bugs.
"""

import io
import os
import socket
import subprocess
import sys

# ── Force UTF-8 output BEFORE any imports that might log with emoji ──────────
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
# Force Hugging Face offline mode to load local models instantly (0.1s instead of 3.5m)
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

port = 5000
kill_only = False
for i, arg in enumerate(sys.argv):
    if arg == "--port" and i + 1 < len(sys.argv):
        port = int(sys.argv[i + 1])
    if arg == "--kill":
        kill_only = True


def _kill_port(p: int) -> None:
    """Kill any process currently listening on port p (Windows + Linux)."""
    killed = False
    try:
        # Windows: netstat + taskkill
        out = subprocess.check_output(
            ["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL
        )
        for line in out.splitlines():
            if f":{p} " in line and "LISTENING" in line:
                parts = line.split()
                proc_id = parts[-1].strip()
                if proc_id.isdigit():
                    subprocess.run(
                        ["cmd", "/c", "taskkill", "/PID", proc_id, "/F"],
                        capture_output=True,
                        check=False,
                    )
                    print(
                        f"[Sovereign Launcher] Killed stale PID {proc_id} on :{p}",
                        flush=True,
                    )
                    killed = True
    except Exception as e:
        print(f"[Sovereign Launcher] kill_port warning: {e}", flush=True)
    if not killed:
        print(f"[Sovereign Launcher] No stale process on :{p}", flush=True)


def _kill_stale_pid() -> None:
    """Read .server.pid and kill the stale process if it exists and is python.exe."""
    pid_file = Path(".server.pid")
    if pid_file.exists():
        try:
            old_pid = pid_file.read_text().strip()
            if old_pid.isdigit():
                # Check if process is running and is python
                out = subprocess.check_output(
                    [
                        "cmd",
                        "/c",
                        "tasklist",
                        "/FI",
                        f"PID eq {old_pid}",
                        "/FI",
                        "IMAGENAME eq python.exe",
                        "/NH",
                    ],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                if "python.exe" in out.lower():
                    subprocess.run(
                        ["cmd", "/c", "taskkill", "/PID", old_pid, "/F"],
                        capture_output=True,
                        check=False,
                    )
                    print(
                        f"[Sovereign Launcher] Killed zombie PID {old_pid} from .server.pid",
                        flush=True,
                    )
                else:
                    print(
                        f"[Sovereign Launcher] PID {old_pid} from .server.pid is not python or not running.",
                        flush=True,
                    )
        except Exception as e:
            print(f"[Sovereign Launcher] kill_stale_pid warning: {e}", flush=True)
        finally:
            # Clean up the file
            try:
                pid_file.unlink()
            except ValueError as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)


# ── SCAR-TVP-002: Kill stale server before binding ───────────────────────────
from pathlib import Path  # noqa: E402

_kill_stale_pid()
_kill_port(port)

if kill_only:
    print("[Sovereign Launcher] --kill done. Exiting.", flush=True)
    sys.exit(0)

import asyncio  # noqa: E402

# Pre-create socket with SO_REUSEADDR to bypass zombie socket on Windows
import time as _time  # noqa: E402

import uvicorn  # noqa: E402 — must come after encoding fix

_time.sleep(0.5)  # brief pause after kill for OS to release port
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", port))
sock.set_inheritable(True)

print(
    f"[Sovereign Launcher] Port {port} bound with SO_REUSEADDR + UTF-8 OK", flush=True
)

config = uvicorn.Config("main:app", host="127.0.0.1", port=port, log_level="info")
server = uvicorn.Server(config)

# Write PID to .server.pid
try:
    Path(".server.pid").write_text(str(os.getpid()))
    print(f"[Sovereign Launcher] Wrote PID {os.getpid()} to .server.pid", flush=True)
except Exception as e:
    print(f"[Sovereign Launcher] Warning: failed to write .server.pid: {e}", flush=True)


async def serve():
    config.load()
    server.lifespan = config.lifespan_class(config)

    # Spawn live dashboard proxy on port 8080 in background
    proxy_proc = None
    try:
        proxy_script = Path(__file__).resolve().parent / "live_dashboard_server.py"
        print(
            f"[Sovereign Launcher] Starting live dashboard proxy from {proxy_script}...",
            flush=True,
        )
        _kill_port(8080)
        proxy_proc = subprocess.Popen(  # nosec
            [sys.executable, str(proxy_script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(
            f"[Sovereign Launcher] Proxy server started with PID {proxy_proc.pid} on port 8080",
            flush=True,
        )
    except Exception as proxy_err:
        print(
            f"[Sovereign Launcher] Failed to start proxy server: {proxy_err}",
            flush=True,
        )

    try:
        await server.startup(sockets=[sock])
        await server.main_loop()
        await server.shutdown()
    finally:
        if proxy_proc:
            try:
                proxy_proc.terminate()
                proxy_proc.wait(timeout=3)
                print(
                    "[Sovereign Launcher] Proxy server stopped gracefully.", flush=True
                )
            except Exception:
                try:
                    proxy_proc.kill()
                    print("[Sovereign Launcher] Proxy server killed.", flush=True)
                except Exception:  # noqa: S110
                    pass


try:
    asyncio.run(serve())
except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
    print(
        "\n[Sovereign Launcher] Server stopped gracefully by user (Ctrl+C).", flush=True
    )
