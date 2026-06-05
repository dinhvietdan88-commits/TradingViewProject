import os
import subprocess
import json
import time

# Paths
WORK_DIR = r"c:\Users\pesil\working\mj_trading\TradingViewProject"
ANGATI_EXE = r"C:\Users\pesil\EAIS\.agents\tools\angati\angati.exe"


def run_mcp_command():
    print("=== CONNECTING TO ANGATI MCP SERVER ===")
    if not os.path.exists(ANGATI_EXE):
        print(f"Error: angati.exe not found at {ANGATI_EXE}")
        return False

    # Launch subprocess
    env = os.environ.copy()
    env["ANGATI_AGENTS_ROOT"] = r"C:\Users\pesil\EAIS\.agents"

    proc = subprocess.Popen(
        [ANGATI_EXE, "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        bufsize=1,
    )

    def send_request(req_id, method, params):
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        raw_msg = json.dumps(msg) + "\n"
        proc.stdin.write(raw_msg)
        proc.stdin.flush()
        # Read lines until we get a response with matching id
        while True:
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("EOF")
            try:
                res = json.loads(line)
                if "id" in res and res["id"] == req_id:
                    return res
            except json.JSONDecodeError:
                pass

    try:
        # 1. Initialize
        print("Sending initialize...")
        init_res = send_request(
            1,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "service-manager", "version": "1.0"},
            },
        )
        print("Initialized.")

        # Send initialized notification
        init_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        proc.stdin.write(json.dumps(init_notif) + "\n")
        proc.stdin.flush()

        # 2. Call angati_status
        print("Calling angati_status...")
        status_res = send_request(
            2, "tools/call", {"name": "angati_status", "arguments": {}}
        )

        service_to_restart = "git_nexus.py"
        is_online = False

        if "result" in status_res and "content" in status_res["result"]:
            for item in status_res["result"]["content"]:
                if item.get("type") == "text":
                    text_val = item.get("text", "")
                    try:
                        data = json.loads(text_val)
                        print("Parsed status JSON successfully.")
                        for svc in data.get("services", []):
                            print(
                                f"Service: {svc.get('name')} | Port: {svc.get('port')} | Up: {svc.get('up')}"
                            )
                            if svc.get("port") == 4747:
                                service_to_restart = svc.get("name")
                                is_online = svc.get("up", False)
                    except Exception as parse_err:
                        print(f"Error parsing status JSON: {parse_err}")

        print(f"Target service: {service_to_restart}, Online status: {is_online}")

        # 3. Restart if offline
        if not is_online:
            print(f"Restarting service {service_to_restart}...")
            restart_res = send_request(
                3,
                "tools/call",
                {"name": "service_restart", "arguments": {"name": service_to_restart}},
            )
            print("Restart Response:")
            print(json.dumps(restart_res, indent=2))

            # Wait a few seconds for startup
            print("Waiting 5 seconds for service boot...")
            time.sleep(5)

            # 4. Check status again
            print("Re-checking angati_status...")
            status_res_2 = send_request(
                4, "tools/call", {"name": "angati_status", "arguments": {}}
            )
            print("New Status Response:")
            if "result" in status_res_2 and "content" in status_res_2["result"]:
                for item in status_res_2["result"]["content"]:
                    if item.get("type") == "text":
                        text_val_2 = item.get("text", "")
                        try:
                            data_2 = json.loads(text_val_2)
                            for svc in data_2.get("services", []):
                                print(
                                    f"Service: {svc.get('name')} | Port: {svc.get('port')} | Up: {svc.get('up')}"
                                )
                        except Exception:
                            print(text_val_2)
        else:
            print("Service is already online!")

    except Exception as e:
        print(f"Error during execution: {e}")
    finally:
        proc.stdin.close()
        proc.terminate()
        proc.wait()
        print("MCP Connection Closed.")


if __name__ == "__main__":
    run_mcp_command()
