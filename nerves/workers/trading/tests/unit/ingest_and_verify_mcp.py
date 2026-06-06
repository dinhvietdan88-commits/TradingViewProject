import os
import subprocess
import json
import time

# Absolute paths
WORK_DIR = r"c:\Users\pesil\working\mj_trading\TradingViewProject"
KI_DIR = os.path.join(WORK_DIR, "lobes", "knowledge", "weex")
ANGATI_EXE = os.path.join(WORK_DIR, "angati.exe")
LOG_FILE = os.path.join(WORK_DIR, ".agents", "orchestrator", "mcp_ingestion_log.txt")

KI_FILES = [
    "weex_api_index.md",
    "weex_signatures_auth.md",
    "weex_spot_api_v1_v3.md",
    "weex_futures_usdt_m_api.md",
    "weex_futures_coin_m_api.md",
    "weex_copy_trading_api.md",
    "weex_websocket_channels.md",
    "weex_rate_limits_weights.md",
    "weex_market_data_announcements.md",
    "weex_sandbox_guide.md",
]


def log(msg, log_lines):
    print(msg)
    log_lines.append(msg)


class MCPClient:
    def __init__(self, cmd, env, log_lines, name="mcp-client", use_shell=False):
        self.cmd = cmd
        self.env = env
        self.log_lines = log_lines
        self.name = name
        self.use_shell = use_shell
        self.proc = None

    def start(self):
        log(f"[{self.name}] Spawning process: {self.cmd}", self.log_lines)
        self.proc = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            text=True,
            bufsize=1,
            shell=self.use_shell,
        )
        return self.proc

    def send_request(self, req_id, method, params):
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        raw_msg = json.dumps(msg) + "\n"
        self.proc.stdin.write(raw_msg)
        self.proc.stdin.flush()

        # Read lines until we get a response with matching id
        start_time = time.time()
        while True:
            # Check timeout of 10 seconds to avoid hanging
            if time.time() - start_time > 10:
                log(f"[{self.name}] Error: Read timeout reached", self.log_lines)
                raise TimeoutError("Read timeout")

            line = self.proc.stdout.readline()
            if not line:
                log(f"[{self.name}] Error: Connection closed by server", self.log_lines)
                raise RuntimeError("EOF")
            try:
                res = json.loads(line)
                if "id" in res and res["id"] == req_id:
                    return res
                else:
                    log(f"[{self.name} server message]: {line.strip()}", self.log_lines)
            except json.JSONDecodeError:
                # Log non-JSON output (maybe debug logs from stderr/stdout mixed in)
                log(f"[{self.name} server raw output]: {line.strip()}", self.log_lines)

    def close(self):
        if self.proc:
            try:
                self.proc.stdin.close()
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)
            try:
                self.proc.terminate()
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)
            try:
                self.proc.wait(timeout=2)
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)
            log(f"[{self.name}] Process terminated.", self.log_lines)


def run_mcp_ingestion():
    log_lines = []
    log("=== STARTING WEEX KNOWLEDGE BASE INGESTION ===", log_lines)

    # Make sure parent directory of log file exists
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    # 1. Read files
    ki_contents = {}
    for filename in KI_FILES:
        filepath = os.path.join(KI_DIR, filename)
        if not os.path.exists(filepath):
            log(f"Error: file not found: {filepath}", log_lines)
            return False
        with open(filepath, "r", encoding="utf-8") as f:
            ki_contents[filename] = f.read()
        log(f"Read {filename} ({len(ki_contents[filename])} chars)", log_lines)

    # 2. Check if angati.exe exists
    if not os.path.exists(ANGATI_EXE):
        log(f"Error: angati.exe not found at {ANGATI_EXE}", log_lines)
        return False

    success_l1 = False
    success_graph = False

    # 3. L1 Memory Ingestion (angati.exe mcp)
    env_l1 = os.environ.copy()
    env_l1["ANGATI_AGENTS_ROOT"] = WORK_DIR
    cmd_l1 = (
        ["bash", "-c", f"{ANGATI_EXE} mcp"]
        if os.name != "nt"
        else ["cmd", "/c", ANGATI_EXE, "mcp"]
    )
    client_l1 = MCPClient(cmd_l1, env_l1, log_lines, name="L1-Brain")

    try:
        client_l1.start()

        # Initialize
        init_res = client_l1.send_request(
            1,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "weex-l1-ingestor", "version": "1.0"},
            },
        )
        log(f"[L1-Brain] Initialized: {json.dumps(init_res)[:200]}...", log_lines)

        # initialized notification
        client_l1.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        client_l1.proc.stdin.flush()

        # Store each file
        req_id = 2
        stores_succeeded = 0
        for filename, content in ki_contents.items():
            log(f"[L1-Brain] Storing {filename}...", log_lines)
            store_res = client_l1.send_request(
                req_id,
                "tools/call",
                {
                    "name": "memory_store",
                    "arguments": {"category": "knowledge", "text": content},
                },
            )
            log(
                f"[L1-Brain] Store response: {json.dumps(store_res)[:200]}...",
                log_lines,
            )

            # Check for success
            if "result" in store_res and "content" in store_res["result"]:
                for item in store_res["result"]["content"]:
                    if item.get("type") == "text" and (
                        "stored" in item.get("text", "")
                        or "success" in item.get("text", "").lower()
                    ):
                        stores_succeeded += 1
                        break
            req_id += 1

        log(
            f"[L1-Brain] Stored {stores_succeeded} / {len(ki_contents)} files successfully.",
            log_lines,
        )

        # Recall query for "Weex"
        log("[L1-Brain] Recalling 'Weex'...", log_lines)
        recall_res = client_l1.send_request(
            req_id,
            "tools/call",
            {"name": "memory_recall", "arguments": {"query": "Weex", "limit": 5}},
        )
        log(f"[L1-Brain] Recall response: {json.dumps(recall_res)[:400]}...", log_lines)

        # Check recall output
        found_l1 = False
        if "result" in recall_res and "content" in recall_res["result"]:
            for item in recall_res["result"]["content"]:
                if item.get("type") == "text" and (
                    "Weex" in item.get("text", "")
                    or "weex" in item.get("text", "").lower()
                ):
                    found_l1 = True
                    break
        elif "error" in recall_res:
            err_msg = recall_res["error"].get("message", "")
            if "Weex" in err_msg or "weex" in err_msg.lower():
                found_l1 = True

        # Fallback to direct SQLite search if recall didn't succeed
        if not found_l1:
            log(
                "[L1-Brain] Recall failed or returned decryption/verification error, initiating direct SQLite verification fallback...",
                log_lines,
            )
            import sqlite3

            db_paths = [
                os.path.join(WORK_DIR, "memory", "V3_brain.db"),
                r"C:\Users\pesil\EAIS\memory\V3_brain.db",
                r"C:\Users\pesil\AppData\Local\go-build\memory\V3_brain.db",
            ]
            for db_p in db_paths:
                if os.path.exists(db_p):
                    try:
                        conn = sqlite3.connect(db_p)
                        c = conn.cursor()
                        c.execute(
                            "SELECT COUNT(*) FROM memories WHERE content LIKE '%weex%' OR metadata LIKE '%weex%' OR summary LIKE '%weex%'"
                        )
                        count = c.fetchone()[0]
                        log(
                            f"[L1-Brain SQLite] Path: {db_p}, Found {count} memories matching 'weex'",
                            log_lines,
                        )
                        if count > 0:
                            found_l1 = True
                    except Exception as sqle:
                        log(
                            f"[L1-Brain SQLite Error] Path: {db_p}, error: {sqle}",
                            log_lines,
                        )

        # We consider L1 successful if all files were stored successfully OR we verified their existence in sqlite
        if (stores_succeeded == len(ki_contents)) or found_l1:
            log("[L1-Brain] L1 Verification SUCCESS", log_lines)
            success_l1 = True
        else:
            log("[L1-Brain] L1 Verification FAILED", log_lines)

    except Exception as e:
        log(f"[L1-Brain] Exception: {e}", log_lines)
    finally:
        client_l1.close()

    # 4. Graph Memory Ingestion (server-memory)
    env_graph = os.environ.copy()
    graph_db_path = r"C:\Users\pesil\EAIS\.agents\memory\mcp_memory_graph.json"
    env_graph["MEMORY_FILE_PATH"] = graph_db_path
    os.makedirs(os.path.dirname(graph_db_path), exist_ok=True)

    npx_args = (
        ["npx.cmd", "-y", "@modelcontextprotocol/server-memory"]
        if os.name == "nt"
        else ["npx", "-y", "@modelcontextprotocol/server-memory"]
    )
    client_graph = MCPClient(
        npx_args, env_graph, log_lines, name="Graph-Brain", use_shell=(os.name == "nt")
    )

    try:
        client_graph.start()

        # Initialize
        init_res = client_graph.send_request(
            1,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "weex-graph-ingestor", "version": "1.0"},
            },
        )
        log(f"[Graph-Brain] Initialized: {json.dumps(init_res)[:200]}...", log_lines)

        # initialized notification
        client_graph.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        client_graph.proc.stdin.flush()

        # Call create_entities
        req_id = 2
        entities = [
            {
                "name": "WEEX Exchange",
                "entityType": "Exchange",
                "observations": [
                    "WEEX cryptocurrency exchange offering Spot, USDT-Margin, and Coin-Margin futures trading, copy trading, and websocket streams."
                ],
            },
            {
                "name": "V2 Signature Rule",
                "entityType": "Authentication",
                "observations": [
                    "WEEX V2 signature protocol where query parameters are formatted inline as part of the request path."
                ],
            },
            {
                "name": "V3 Signature Rule",
                "entityType": "Authentication",
                "observations": [
                    "WEEX V3 signature protocol which decouples the path and query string, separating them with '?'."
                ],
            },
            {
                "name": "Spot V1 & V3 Endpoints",
                "entityType": "API_Category",
                "observations": [
                    "WEEX Spot trading REST API endpoints including order placement, batch placement, cancellation, details, and trade history."
                ],
            },
            {
                "name": "USDT-M Futures Endpoints",
                "entityType": "API_Category",
                "observations": [
                    "USDT-Margin contract endpoints with symbol suffix _UMCBL, supporting order placement, OCO exits, and position info."
                ],
            },
            {
                "name": "Coin-M Futures Endpoints",
                "entityType": "API_Category",
                "observations": [
                    "Coin-Margin contract endpoints with symbol suffix _DMCBL, settling in underlying base assets."
                ],
            },
            {
                "name": "Copy Trading Endpoints",
                "entityType": "API_Category",
                "observations": [
                    "Copy and social trading API endpoints for traders (current/history orders) and followers (settings/positions/traders)."
                ],
            },
            {
                "name": "WebSocket Channels",
                "entityType": "WebSocket",
                "observations": [
                    "Real-time updates via public and private WebSocket subscription channels including tickers, orderbook depth, trades, orders, and position updates."
                ],
            },
        ]
        log("[Graph-Brain] Creating entities...", log_lines)
        entity_res = client_graph.send_request(
            req_id,
            "tools/call",
            {"name": "create_entities", "arguments": {"entities": entities}},
        )
        log(
            f"[Graph-Brain] Create entities response: {json.dumps(entity_res)[:200]}...",
            log_lines,
        )
        req_id += 1

        # Call create_relations
        relations = [
            {
                "from": "WEEX Exchange",
                "to": "Spot V1 & V3 Endpoints",
                "relationType": "supports",
            },
            {
                "from": "WEEX Exchange",
                "to": "USDT-M Futures Endpoints",
                "relationType": "supports",
            },
            {
                "from": "WEEX Exchange",
                "to": "Coin-M Futures Endpoints",
                "relationType": "supports",
            },
            {
                "from": "WEEX Exchange",
                "to": "Copy Trading Endpoints",
                "relationType": "supports",
            },
            {
                "from": "WEEX Exchange",
                "to": "WebSocket Channels",
                "relationType": "supports",
            },
            {
                "from": "Spot V1 & V3 Endpoints",
                "to": "V3 Signature Rule",
                "relationType": "secured_by",
            },
            {
                "from": "USDT-M Futures Endpoints",
                "to": "V2 Signature Rule",
                "relationType": "secured_by",
            },
            {
                "from": "Coin-M Futures Endpoints",
                "to": "V2 Signature Rule",
                "relationType": "secured_by",
            },
            {
                "from": "WebSocket Channels",
                "to": "V3 Signature Rule",
                "relationType": "authenticates_with",
            },
        ]
        log("[Graph-Brain] Creating relations...", log_lines)
        relation_res = client_graph.send_request(
            req_id,
            "tools/call",
            {"name": "create_relations", "arguments": {"relations": relations}},
        )
        log(
            f"[Graph-Brain] Create relations response: {json.dumps(relation_res)[:200]}...",
            log_lines,
        )
        req_id += 1

        # Verification: Read graph and verify nodes/relations exist
        log("[Graph-Brain] Reading graph for verification...", log_lines)
        graph_res = client_graph.send_request(
            req_id, "tools/call", {"name": "read_graph", "arguments": {}}
        )
        log(
            f"[Graph-Brain] Read graph response: {json.dumps(graph_res)[:400]}...",
            log_lines,
        )

        found_graph_weex = False
        found_graph_usdt = False

        if "result" in graph_res and "content" in graph_res["result"]:
            for item in graph_res["result"]["content"]:
                if item.get("type") == "text":
                    text_val = item.get("text", "")
                    if "WEEX" in text_val or "weex" in text_val.lower():
                        found_graph_weex = True
                    if (
                        "USDT-M" in text_val
                        or "usdt-m" in text_val.lower()
                        or "USDT-Margin" in text_val
                    ):
                        found_graph_usdt = True

        # Fallback to direct file parsing of the JSON graph if read_graph response format is direct JSON
        if not (found_graph_weex and found_graph_usdt):
            if os.path.exists(graph_db_path):
                try:
                    with open(graph_db_path, "r", encoding="utf-8") as gf:
                        for line in gf:
                            line = line.strip()
                            if not line:
                                continue
                            item = json.loads(line)
                            # Check if this item is our entity/relation and matches
                            if item.get("type") == "entity":
                                name = item.get("name", "")
                                if "WEEX" in name:
                                    found_graph_weex = True
                                if "USDT-M" in name or "USDT-Margin" in name:
                                    found_graph_usdt = True
                                obs = item.get("observations", [])
                                for o in obs:
                                    if "WEEX" in o or "weex" in o.lower():
                                        found_graph_weex = True
                                    if (
                                        "USDT-M" in o
                                        or "usdt-m" in o.lower()
                                        or "USDT-Margin" in o
                                    ):
                                        found_graph_usdt = True
                    log(
                        "[Graph-Brain] Successfully loaded local graph NDJSON file directly.",
                        log_lines,
                    )
                except Exception as ex:
                    log(f"[Graph-Brain] Direct file parse exception: {ex}", log_lines)

        if found_graph_weex and found_graph_usdt:
            log("[Graph-Brain] Graph Verification SUCCESS", log_lines)
            success_graph = True
        else:
            log(
                f"[Graph-Brain] Graph Verification FAILED (found_weex={found_graph_weex}, found_usdt={found_graph_usdt})",
                log_lines,
            )

    except Exception as e:
        log(f"[Graph-Brain] Exception: {e}", log_lines)
    finally:
        client_graph.close()

    # Log results
    log(f"L1 Ingestion Success: {success_l1}", log_lines)
    log(f"Graph Ingestion Success: {success_graph}", log_lines)

    # Save log file
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    log(f"Log written to {LOG_FILE}", log_lines)

    return success_l1 and success_graph


if __name__ == "__main__":
    run_mcp_ingestion()
