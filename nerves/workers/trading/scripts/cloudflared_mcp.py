import sys
import json
import os
import subprocess
import re
import time
import signal

# Ensure stdout and stdin are treated as utf-8 or binary
sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

LOG_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../cloudflared.log")
)
PID_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../cloudflared.pid")
)


def log_debug(msg):
    # Log to stderr since stdout is used for MCP JSON-RPC
    sys.stderr.write(f"[cloudflared-mcp] {msg}\n")
    sys.stderr.flush()


def get_running_tunnel_url():
    if not os.path.exists(LOG_FILE):
        return None
    try:
        # Search backward or parse logs for the trycloudflare URL
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        matches = re.findall(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
        if matches:
            return matches[-1]
    except Exception as e:
        log_debug(f"Error reading log file: {e}")
    return None


def is_tunnel_running():
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        # Check if process exists on Windows/Linux
        if os.name == "nt":
            # Windows check
            out = subprocess.check_output(  # noqa: S602
                f'tasklist /FI "PID eq {pid}"', shell=True, text=True
            )
            return str(pid) in out
        else:
            # Unix check
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def stop_tunnel_process():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            log_debug(f"Killing process {pid}...")
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True
                )
            else:
                os.kill(pid, signal.SIGTERM)
            time.sleep(1)
        except Exception as e:
            log_debug(f"Error killing process: {e}")
        try:
            os.remove(PID_FILE)
        except ConnectionError as e:
            import logging

            logging.getLogger(__name__).warning("Ignored: %s", e)

    # Extra cleanup: kill any lingering cloudflared processes on Windows
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/IM", "cloudflared.exe", "/F"], capture_output=True
            )
        except ConnectionError as e:
            import logging

            logging.getLogger(__name__).warning("Ignored: %s", e)


def start_tunnel_process(port=5000):
    stop_tunnel_process()

    # Reset log file
    if os.path.exists(LOG_FILE):
        try:
            os.remove(LOG_FILE)
        except (OSError, FileNotFoundError) as err:
            import logging

            logging.getLogger(__name__).warning("Ignored: %s", err)

    log_debug(f"Starting cloudflared tunnel for port {port}...")
    cmd = ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"]

    # Run in background redirecting stdout/stderr to log file
    try:
        log_f = open(LOG_FILE, "w", encoding="utf-8")
        from subprocess import Popen

        proc = Popen(
            cmd,
            stdout=log_f,
            stderr=log_f,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            text=True,
        )

        # Write PID
        with open(PID_FILE, "w") as f:
            f.write(str(proc.pid))

        # Poll log file for up to 15 seconds to find the URL
        url = None
        for _ in range(30):
            time.sleep(0.5)
            url = get_running_tunnel_url()
            if url:
                break

        if url:
            log_debug(f"Tunnel started successfully: {url}")
            return True, url
        else:
            log_debug(
                "Failed to obtain trycloudflare.com URL from logs within timeout."
            )
            return (
                False,
                "Failed to get tunnel URL within 15 seconds. Please check cloudflared.log.",
            )
    except Exception as e:
        log_debug(f"Error starting tunnel: {e}")
        return False, str(e)


def handle_request(req):
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "cloudflared-mcp", "version": "1.0.0"},
            },
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "start_tunnel",
                        "description": "Start cloudflared tunnel to expose Local Server to public internet.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "port": {
                                    "type": "integer",
                                    "description": "Local server port to expose",
                                    "default": 5000,
                                }
                            },
                        },
                    },
                    {
                        "name": "stop_tunnel",
                        "description": "Stop the running cloudflared tunnel.",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "get_tunnel_status",
                        "description": "Get current status and URL of the cloudflared tunnel.",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                ]
            },
        }

    elif method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})

        if tool_name == "start_tunnel":
            port = tool_args.get("port", 5000)
            success, result = start_tunnel_process(port)
            if success:
                text = f"🟢 Cloudflare Tunnel STARTED successfully!\nURL: {result}\nWebhook endpoint: {result}/webhook"
            else:
                text = f"🔴 Failed to start tunnel: {result}"

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": text}]},
            }

        elif tool_name == "stop_tunnel":
            stop_tunnel_process()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "🔴 Cloudflare Tunnel STOPPED and cleaned up.",
                        }
                    ]
                },
            }

        elif tool_name == "get_tunnel_status":
            running = is_tunnel_running()
            url = get_running_tunnel_url() if running else None

            if running and url:
                text = f"🟢 Tunnel status: RUNNING\nURL: {url}\nWebhook endpoint: {url}/webhook"
            elif running:
                text = "🟡 Tunnel status: RUNNING (resolving URL...)"
            else:
                text = "🔴 Tunnel status: OFFLINE"

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": text}]},
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {tool_name}"},
            }

    # Default fallback
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    log_debug("MCP Server started.")
    buffer = ""
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            buffer += line
            try:
                req = json.loads(buffer)
                buffer = ""
                resp = handle_request(req)
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except json.JSONDecodeError:
                # Keep reading until we get a complete JSON object
                continue
        except KeyboardInterrupt:
            break
        except Exception as e:
            log_debug(f"Error in main loop: {e}")
            break


if __name__ == "__main__":
    main()
