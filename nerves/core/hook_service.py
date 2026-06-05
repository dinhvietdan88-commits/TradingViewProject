#!/usr/bin/env python3
"""
SRA Hybrid Hook Server — Declarative Architecture (V2)

HTTP server running on :9105 that intercepts Antigravity IDE tool calls
via /pre-tool, /post-tool, and /on-error endpoints.

V2 Architecture:
    - Inline if/elif gates REPLACED by guardrail_registry.evaluate_guardrails()
    - B+C+A _scar_consult_fast() stays here for in-process performance
    - Dependencies injected into guardrails via context dict
    - ADK telemetry export via adk_callback_bridge.py

References:
    - guardrail_registry.py: Declarative policy definitions
    - adk_callback_bridge.py: ADK Event/Context adapters
"""

import sys

# Configure sys.stdout and sys.stderr to ignore encoding errors (SCAR-019)
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
        sys.stderr.reconfigure(encoding="utf-8", errors="ignore")
    except Exception:
        pass

import json
import time as _time
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingTCPServer

AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(AGENTS_ROOT))
sys.path.insert(0, str(AGENTS_ROOT / "nerves" / "core"))

# ── Eagerly load core libraries ──────────────────────────────
try:
    import core_scar_memory as scar_memory
    import core_reflex as reflex

    if scar_memory:
        print(
            "[SRA Server] Eagerly warming up FastEmbed model in RAM...", file=sys.stderr
        )
        scar_memory._get_embedding_model()
        print("[SRA Server] FastEmbed model loaded successfully.", file=sys.stderr)
except Exception as e:
    print(f"[SRA Server] Eager loading warning: {e}", file=sys.stderr)
    scar_memory = None
    reflex = None

# ── Load guardrail registry ──────────────────────────────────
try:
    from guardrail_registry import evaluate_guardrails

    print("[SRA Server] Guardrail registry loaded.", file=sys.stderr)
except Exception as e:
    print(f"[SRA Server] Guardrail registry load error: {e}", file=sys.stderr)
    evaluate_guardrails = None

# ── Load ADK telemetry exporter ───────────────────────────────
try:
    from adk_callback_bridge import AngatiCallbackContext, ADKTelemetryExporter

    _telemetry = ADKTelemetryExporter(
        output_path=str(AGENTS_ROOT / "memory" / "hook_events.jsonl")
    )
    print("[SRA Server] ADK telemetry exporter loaded.", file=sys.stderr)
except Exception as e:
    print(f"[SRA Server] ADK telemetry warning: {e}", file=sys.stderr)
    _telemetry = None
    AngatiCallbackContext = None


_VERBOSE = False

# ── Scar Consult B+C+A ───────────────────────────────────────
# B: In-process fastembed (already warm) + direct Qdrant search
# C: TTL cache by command prefix (5 min)
# A: Fallback to angati.exe subprocess

_scar_cache = {}  # {cmd_prefix: (timestamp, advisory_str | None)}
_SCAR_CACHE_TTL = 300  # 5 minutes
_SCAR_SCORE_THRESHOLD = 0.82
_qdrant_client_cached = None

# Stats counters
_stats = {
    "pre_tool_calls": 0,
    "post_tool_calls": 0,
    "on_error_calls": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "blocks": 0,
    "advisories": 0,
    "start_time": _time.time(),
}


def _cmd_prefix(cmd_line: str) -> str:
    """
    Extract parameterized cache key from command for precise grouping.
    Prioritizes file paths or extensions first, falling back to non-option words.
    """
    tokens = cmd_line.strip().split()
    if not tokens:
        return ""
    binary = tokens[0].lower()

    if "/" in binary or "\\" in binary:
        binary = Path(binary).name

    target = ""
    # Phase 1: Look for any token that looks like a file path or has an extension
    for t in tokens[1:]:
        if not t.startswith("-") and ("/" in t or "\\" in t or "." in t):
            if "/" in t or "\\" in t:
                target = Path(t).name
            else:
                target = t
            break

    # Phase 2: Fallback to the first non-option token longer than 3 chars
    if not target:
        for t in tokens[1:]:
            if not t.startswith("-") and len(t) > 3:
                target = t
                break

    return f"{binary}:{target}".lower()


def _scar_cache_invalidate(action: str):
    """Invalidate scar cache for a command prefix. Called from on-error."""
    prefix = _cmd_prefix(action)
    _scar_cache.pop(prefix, None)


def _scar_consult_fast(cmd_line: str) -> str:
    """
    Scar consult with TTL cache + dual-path search.

    Path priority:
        1. C: Check cache (0ms) → hit? return immediately
        2. B: In-process embed + Qdrant search (~100ms)
        3. A: Fallback to angati.exe subprocess (~300ms)
        4. C: Store result in cache (5min TTL)

    Returns advisory string or "" if no relevant scars.
    """
    global _qdrant_client_cached

    if not scar_memory:
        return ""

    # ── C: Cache check ──
    prefix = _cmd_prefix(cmd_line)
    now = _time.time()
    if prefix in _scar_cache:
        ts, cached_advisory = _scar_cache[prefix]
        if now - ts < _SCAR_CACHE_TTL:
            _stats["cache_hits"] += 1
            return cached_advisory or ""

    _stats["cache_misses"] += 1

    # ── B: Try in-process embed + Qdrant (fastest) ──
    try:
        vector = scar_memory._embed(cmd_line)

        if _qdrant_client_cached is None:
            _qdrant_client_cached = scar_memory._get_client()

        results = _qdrant_client_cached.search(
            collection_name=scar_memory.COLLECTION_NAME,
            query_vector=vector,
            limit=3,
            score_threshold=_SCAR_SCORE_THRESHOLD,
        )

        if results:
            rules = []
            for r in results:
                payload = r.payload or {}
                rule = payload.get("prevention_rule", "")
                if rule:
                    rules.append(rule)

            if rules:
                advisory = " | ".join(rules[:2])
                _scar_cache[prefix] = (now, advisory)
                return advisory

        # No match via Qdrant — cache miss
        _scar_cache[prefix] = (now, None)
        return ""

    except Exception as exc_b:
        # B failed (e.g., no Qdrant connection) — fall through to A
        print(
            f"[SRA Server] Scar consult B (in-process) failed: {exc_b}, falling back to A (subprocess)",
            file=sys.stderr,
        )

    # ── A: Fallback to angati.exe subprocess (~300ms) ──
    try:
        scars = scar_memory.consult(cmd_line, top_k=3)
        if scars:
            relevant = [s for s in scars if s.get("score", 0) >= _SCAR_SCORE_THRESHOLD]
            if relevant:
                rules = [
                    s.get("prevention_rule", "")
                    for s in relevant
                    if s.get("prevention_rule")
                ]
                if rules:
                    advisory = " | ".join(rules[:2])
                    _scar_cache[prefix] = (now, advisory)
                    return advisory

        _scar_cache[prefix] = (now, None)
        return ""

    except Exception as exc_a:
        print(
            f"[SRA Server] Scar consult A (subprocess) also failed: {exc_a}",
            file=sys.stderr,
        )
        _scar_cache[prefix] = (now, None)
        return ""


# ── Build guardrail context ──────────────────────────────────


def _build_context(**extra) -> dict:
    """Build context dict for guardrail handlers with injected dependencies."""
    ctx = {
        "scar_memory": scar_memory,
        "reflex": reflex,
        "scar_consult_fast": _scar_consult_fast,
        "cache_invalidator": _scar_cache_invalidate,
    }
    ctx.update(extra)
    return ctx


# ── HTTP Server ───────────────────────────────────────────────


class ThreadingHTTPServer(ThreadingTCPServer, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    allow_reuse_port = True

    def handle_error(self, request, client_address):
        # Silence connection reset exceptions when clients exit abruptly
        import traceback

        tb = traceback.format_exc()
        if (
            "ConnectionResetError" in tb
            or "ConnectionAbortedError" in tb
            or "BrokenPipeError" in tb
            or "WinError 10054" in tb
        ):
            pass
        else:
            super().handle_error(request, client_address)


class SRAHookHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            # Client closed connection or exited, which is normal for CLI hook invocations
            pass

    def log_message(self, format, *args):
        # Silence default request logs to avoid cluttering output
        pass

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"status": "healthy"}).encode("utf-8")
            self._send_json(200, body)
        elif self.path == "/stats":
            uptime = _time.time() - _stats["start_time"]
            stats_data = {
                **_stats,
                "uptime_seconds": round(uptime, 1),
                "cache_size": len(_scar_cache),
                "guardrails_loaded": evaluate_guardrails is not None,
                "scar_memory_loaded": scar_memory is not None,
                "reflex_loaded": reflex is not None,
                "telemetry_loaded": _telemetry is not None,
            }
            # Remove non-serializable start_time
            stats_data.pop("start_time", None)
            body = json.dumps(stats_data, indent=2).encode("utf-8")
            self._send_json(200, body)
        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, status: int, body: bytes):
        """Send a JSON response with proper headers."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            input_data = json.loads(post_data.decode("utf-8"))
        except Exception as e:
            body = json.dumps({"error": f"Invalid JSON: {e}"}).encode("utf-8")
            self._send_json(400, body)
            return

        if self.path == "/pre-tool":
            response_data = self.handle_pre_tool(input_data)
        elif self.path == "/post-tool":
            response_data = self.handle_post_tool(input_data)
        elif self.path == "/on-error":
            response_data = self.handle_on_error(input_data)
        elif self.path == "/shutdown":
            body = json.dumps({"status": "shutdown"}).encode("utf-8")
            self._send_json(200, body)
            threading.Thread(target=self.server.shutdown).start()
            return
        else:
            self.send_response(404)
            self.end_headers()
            return

        body = json.dumps(response_data).encode("utf-8")
        self._send_json(200, body)

    def handle_pre_tool(self, input_data):
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        _stats["pre_tool_calls"] += 1

        if _VERBOSE:
            print(f"[SRA Server] PreToolUse intercepting: {tool_name}", file=sys.stderr)

        # ── Declarative guardrail evaluation ──
        if evaluate_guardrails and tool_input:
            context = _build_context()
            result = evaluate_guardrails("before_tool", tool_name, tool_input, context)

            # Emit ADK telemetry
            if _telemetry and AngatiCallbackContext:
                try:
                    ctx = AngatiCallbackContext.from_hook_data(
                        input_data, lifecycle="before_tool"
                    )
                    event = ctx.to_guardrail_event(result)
                    _telemetry.record(event)
                except Exception:
                    pass

            # Log verdicts
            for v in result.get("verdicts", []):
                verdict = v.get("verdict", "")
                name = v.get("guardrail", "")
                if verdict == "BLOCK":
                    print(
                        f"[SRA Server] BLOCKED by {name}: {v.get('reason', '')}",
                        file=sys.stderr,
                    )
                    _stats["blocks"] += 1
                elif verdict == "WARN":
                    print(
                        f"[SRA Server] WARN from {name}: {v.get('reason', '')}",
                        file=sys.stderr,
                    )
                    _stats["advisories"] += 1
                elif v.get("advisory"):
                    print(
                        f"[SRA Server] Advisory from {name}: {v['advisory']}",
                        file=sys.stderr,
                    )

            if result["decision"] == "deny":
                return {
                    "decision": "deny",
                    "message": result.get("message", "Blocked by guardrail"),
                }

            # Return advisory message if any
            message = result.get("message", "")
            if message:
                return {"decision": "allow", "message": f"[SCAR ADVISORY] {message}"}

        return {"decision": "allow"}

    def handle_post_tool(self, input_data):
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        tool_output = input_data.get("tool_output", "")
        _stats["post_tool_calls"] += 1

        if _VERBOSE:
            print(f"[SRA Server] PostToolUse processing: {tool_name}", file=sys.stderr)

        # ── Declarative guardrail evaluation ──
        if evaluate_guardrails and tool_input:
            context = _build_context(tool_output=tool_output)
            result = evaluate_guardrails("after_tool", tool_name, tool_input, context)

            # Log actions
            for v in result.get("verdicts", []):
                action = v.get("action", "")
                if action:
                    print(f"[SRA Server] Post-tool action: {action}", file=sys.stderr)

        return {"status": "ok"}

    def handle_on_error(self, input_data):
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        tool_output = input_data.get("tool_output", "")
        error_msg = input_data.get("error", "") or str(tool_output)[:500]
        _stats["on_error_calls"] += 1

        print(f"[SRA Server] OnError processing: {tool_name}", file=sys.stderr)

        # ── Declarative guardrail evaluation ──
        if evaluate_guardrails:
            context = _build_context(
                error=error_msg,
                tool_output=tool_output,
            )
            result = evaluate_guardrails("on_error", tool_name, tool_input, context)

            # Emit ADK telemetry
            if _telemetry and AngatiCallbackContext:
                try:
                    ctx = AngatiCallbackContext.from_hook_data(
                        input_data, lifecycle="on_error"
                    )
                    event = ctx.to_guardrail_event(result)
                    _telemetry.record(event)
                except Exception:
                    pass

            for v in result.get("verdicts", []):
                action = v.get("action", "")
                if action:
                    print(f"[SRA Server] On-error action: {action}", file=sys.stderr)

        return {"status": "ok"}


# ── Version Check ─────────────────────────────────────────────


def check_angati_version_async():
    """Runs asynchronously in a daemon thread to check version compatibility of local and brain angati.exe."""

    def run_check():
        import os
        import hashlib

        # 1. Resolve local path
        local_path = None
        env_local = os.environ.get("ANGATI_LOCAL_EXE_PATH")
        if env_local:
            local_path = Path(env_local)
        else:
            cand1 = AGENTS_ROOT / "tools" / "angati" / "angati.exe"
            cand2 = AGENTS_ROOT / "angati.exe"
            if cand1.exists():
                local_path = cand1
            else:
                local_path = cand2

        # 2. Resolve brain path
        brain_path = None
        env_brain = os.environ.get("ANGATI_BRAIN_EXE_PATH")
        if env_brain:
            brain_path = Path(env_brain)
        else:
            home = Path.home()
            candidates = [
                home / "EAIS" / "test_scaffold" / "angati.exe",
                home / "EAIS" / "spine" / "angati" / "angati.exe",
                home / ".gemini" / "antigravity" / "tools" / "angati" / "angati.exe",
            ]
            for cand in candidates:
                if cand.exists():
                    brain_path = cand
                    break
            if not brain_path:
                brain_path = candidates[-1]

        # 3. Check exists
        if not local_path.exists() or not brain_path.exists():
            return

        # 4. Compute hashes chunked
        def get_sha256(p):
            sha = hashlib.sha256()
            try:
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        sha.update(chunk)
                return sha.hexdigest()
            except Exception:
                return None

        local_hash = get_sha256(local_path)
        brain_hash = get_sha256(brain_path)

        if not local_hash or not brain_hash:
            return

        # 5. Warn on mismatch
        if local_hash != brain_hash:
            print(
                "[SRA Server] WARNING: Local angati.exe version mismatch detected! Please manually restart the hook server to synchronize the binary.",
                file=sys.stderr,
            )

    t = threading.Thread(target=run_check, daemon=True)
    t.start()
    return t


def main():
    check_angati_version_async()
    port = 9105
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            try:
                port = int(sys.argv[i + 1])
            except ValueError:
                pass
    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, SRAHookHandler)
    print(
        f"[SRA Server] Running SRA Hybrid Hook Server on port {port}...",
        file=sys.stderr,
    )
    print(
        "[SRA Server] Endpoints: /pre-tool, /post-tool, /on-error, /health, /stats, /shutdown",
        file=sys.stderr,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    print("[SRA Server] Stopping server...", file=sys.stderr)


if __name__ == "__main__":
    main()
