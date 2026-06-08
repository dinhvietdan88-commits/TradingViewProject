#!/usr/bin/env python3
"""
A2A Task Handler — JSON-RPC 2.0 Agent-to-Agent Protocol

Implements the core A2A task lifecycle:
    - tasks/send    → Accept a task from an external agent
    - tasks/get     → Query task status
    - tasks/cancel  → Cancel a running task

Architecture:
    This handler receives JSON-RPC 2.0 envelopes and dispatches them
    to the appropriate skill handler based on the task's skill_id.
    It maps A2A task requests to existing Angati satellite capabilities
    (webhook processing, trade execution, scar memory queries).

Isomorphism:
    A2A Protocol (tasks/send)  ↔  Satellite Protocol v1.4 (ingest.go)
    A2A Protocol (tasks/get)   ↔  Satellite Protocol v1.4 (query.go)

References:
    - A2A Spec: https://google.github.io/a2a-spec/
    - KI: google-adk-deep-research §6 (A2A Protocol)
"""

import json
import threading
import time
import uuid
from enum import Enum

# ---------------------------------------------------------------------------
# Task State Machine
# ---------------------------------------------------------------------------


class TaskState(Enum):
    """A2A-compliant task states."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class TaskStatus:
    """Represents the current status of an A2A task."""

    def __init__(self, task_id: str, state: TaskState, message: str = ""):
        self.task_id = task_id
        self.state = state
        self.message = message
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.task_id,
            "state": self.state.value,
            "message": self.message,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# In-Memory Task Store (Sovereign — no external dependency)
# ---------------------------------------------------------------------------


class TaskStore:
    """
    Thread-safe in-memory task store.

    Production Note:
        For production deployment, this should be backed by SQLite
        (cortex/db/tasks.db) to survive process restarts. The in-memory
        store is sufficient for the V10 integration prototype.
    """

    def __init__(self, max_tasks: int = 1000):
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._max_tasks = max_tasks

    def create(self, task_id: str, skill_id: str, payload: dict) -> dict:
        """Create a new task entry."""
        with self._lock:
            if len(self._tasks) >= self._max_tasks:
                self._evict_completed()

            task = {
                "id": task_id,
                "skill_id": skill_id,
                "payload": payload,
                "status": TaskStatus(task_id, TaskState.SUBMITTED).to_dict(),
                "result": None,
                "created_at": time.time(),
            }
            self._tasks[task_id] = task
            return task

    def get(self, task_id: str) -> dict | None:
        """Retrieve a task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def update_status(
        self, task_id: str, state: TaskState, message: str = "", result: dict = None
    ):
        """Update task status."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task["status"] = TaskStatus(task_id, state, message).to_dict()
                if result is not None:
                    task["result"] = result

    def cancel(self, task_id: str) -> bool:
        """Cancel a task if it's not already completed."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            current_state = task["status"].get("state", "")
            if current_state in (
                TaskState.COMPLETED.value,
                TaskState.FAILED.value,
                TaskState.CANCELED.value,
            ):
                return False
            task["status"] = TaskStatus(
                task_id, TaskState.CANCELED, "Canceled by external request"
            ).to_dict()
            return True

    def _evict_completed(self):
        """Remove oldest completed/failed/canceled tasks to free space."""
        completed = [
            (tid, t["created_at"])
            for tid, t in self._tasks.items()
            if t["status"].get("state")
            in (
                TaskState.COMPLETED.value,
                TaskState.FAILED.value,
                TaskState.CANCELED.value,
            )
        ]
        completed.sort(key=lambda x: x[1])
        for tid, _ in completed[: max(1, len(completed) // 2)]:
            del self._tasks[tid]


# ---------------------------------------------------------------------------
# Skill Dispatchers (Route A2A tasks to Angati capabilities)
# ---------------------------------------------------------------------------


def _dispatch_webhook_signal(payload: dict) -> dict:
    """
    Dispatch a webhook signal processing task.

    Maps A2A task → existing webhook ingress logic.
    In production, this would call the FastAPI /webhook endpoint internally.
    """
    symbol = payload.get("symbol", "")
    indicator_name = payload.get("indicator_name", "")

    if not symbol:
        return {"error": "Missing required field: symbol", "code": "INVALID_INPUT"}
    if not indicator_name:
        return {
            "error": "Missing required field: indicator_name",
            "code": "INVALID_INPUT",
        }

    # Simulate signal processing (in production: POST to internal /webhook)
    return {
        "status": "processed",
        "symbol": symbol,
        "indicator_name": indicator_name,
        "action": "Signal received and queued for processing",
        "note": "V10 A2A bridge — full integration requires FastAPI webhook routing",
    }


def _dispatch_scar_query(payload: dict) -> dict:
    """
    Dispatch a scar memory query task.

    Maps A2A task → local ChromaDB scar_memory search.
    """
    query = payload.get("query", "")
    top_k = payload.get("top_k", 5)

    if not query:
        return {"error": "Missing required field: query", "code": "INVALID_INPUT"}

    # Attempt to use local scar memory
    try:
        import sys
        from pathlib import Path

        agents_root = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agents_root / "nerves" / "core"))
        import core_scar_memory as scar_memory

        results = scar_memory.search_scars(query, top_k=top_k)
        return {
            "status": "success",
            "query": query,
            "results": results if results else [],
            "source": "chromadb_local",
        }
    except Exception as e:
        return {
            "status": "degraded",
            "query": query,
            "results": [],
            "error": f"Scar memory unavailable: {e}",
            "source": "none",
        }


SKILL_DISPATCHERS = {
    "webhook-signal-processor": _dispatch_webhook_signal,
    "trade-executor": lambda p: {
        "error": "Trade executor requires human approval",
        "code": "INPUT_REQUIRED",
    },
    "scar-memory-query": _dispatch_scar_query,
    "indicator-dashboard": lambda p: {
        "error": "Dashboard is read-only via HTTP GET",
        "code": "METHOD_NOT_ALLOWED",
    },
}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 A2A Handler
# ---------------------------------------------------------------------------


class A2AHandler:
    """
    JSON-RPC 2.0 handler implementing A2A task lifecycle.

    Methods:
        tasks/send   — Create and execute a new task
        tasks/get    — Query task status and result
        tasks/cancel — Cancel a pending/working task
    """

    def __init__(self):
        self.task_store = TaskStore()

    def handle_request(self, raw_body: bytes) -> dict:
        """
        Process a JSON-RPC 2.0 request and return a response envelope.

        Args:
            raw_body: Raw HTTP request body (JSON-RPC 2.0 envelope)

        Returns:
            dict: JSON-RPC 2.0 response envelope
        """
        try:
            request = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return self._error_response(None, -32700, f"Parse error: {e}")

        # Validate JSON-RPC 2.0 structure
        if request.get("jsonrpc") != "2.0":
            return self._error_response(
                request.get("id"), -32600, "Invalid Request: jsonrpc must be '2.0'"
            )

        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        # Dispatch to handler
        if method == "tasks/send":
            return self._handle_send(req_id, params)
        elif method == "tasks/get":
            return self._handle_get(req_id, params)
        elif method == "tasks/cancel":
            return self._handle_cancel(req_id, params)
        else:
            return self._error_response(req_id, -32601, f"Method not found: {method}")

    def _handle_send(self, req_id, params: dict) -> dict:
        """Handle tasks/send — create and execute a task."""
        skill_id = params.get("skill_id", "")
        payload = params.get("payload", {})

        if not skill_id:
            return self._error_response(
                req_id, -32602, "Missing required param: skill_id"
            )

        dispatcher = SKILL_DISPATCHERS.get(skill_id)
        if not dispatcher:
            return self._error_response(
                req_id,
                -32602,
                f"Unknown skill: {skill_id}. Available: {list(SKILL_DISPATCHERS.keys())}",
            )

        # Create task
        task_id = str(uuid.uuid4())
        task = self.task_store.create(task_id, skill_id, payload)

        # Execute synchronously (V10 prototype — async in production)
        self.task_store.update_status(task_id, TaskState.WORKING, "Processing")

        try:
            result = dispatcher(payload)

            # Check if input is required (e.g., trade executor needs approval)
            if result.get("code") == "INPUT_REQUIRED":
                self.task_store.update_status(
                    task_id, TaskState.INPUT_REQUIRED, result.get("error", ""), result
                )
            elif result.get("code") in ("INVALID_INPUT", "METHOD_NOT_ALLOWED"):
                self.task_store.update_status(
                    task_id, TaskState.FAILED, result.get("error", ""), result
                )
            else:
                self.task_store.update_status(
                    task_id, TaskState.COMPLETED, "Task completed", result
                )
        except Exception as e:
            self.task_store.update_status(
                task_id, TaskState.FAILED, f"Execution error: {e}"
            )

        # Return current task state
        task = self.task_store.get(task_id)
        return self._success_response(req_id, task)

    def _handle_get(self, req_id, params: dict) -> dict:
        """Handle tasks/get — retrieve task status."""
        task_id = params.get("task_id", "")
        if not task_id:
            return self._error_response(
                req_id, -32602, "Missing required param: task_id"
            )

        task = self.task_store.get(task_id)
        if not task:
            return self._error_response(req_id, -32602, f"Task not found: {task_id}")

        return self._success_response(req_id, task)

    def _handle_cancel(self, req_id, params: dict) -> dict:
        """Handle tasks/cancel — cancel a pending/working task."""
        task_id = params.get("task_id", "")
        if not task_id:
            return self._error_response(
                req_id, -32602, "Missing required param: task_id"
            )

        success = self.task_store.cancel(task_id)
        if not success:
            return self._error_response(
                req_id,
                -32602,
                f"Cannot cancel task {task_id}: not found or already terminal",
            )

        task = self.task_store.get(task_id)
        return self._success_response(req_id, task)

    @staticmethod
    def _success_response(req_id, result) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _error_response(req_id, code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }


# ---------------------------------------------------------------------------
# HTTP Handler Mixin (for embedding into BaseHTTPRequestHandler)
# ---------------------------------------------------------------------------

# Singleton handler instance
_a2a_handler = A2AHandler()


class A2AHandlerMixin:
    """
    Mixin that adds A2A JSON-RPC 2.0 task handling to any BaseHTTPRequestHandler.

    Usage:
        class MyHandler(A2AHandlerMixin, AgentCardMixin, BaseHTTPRequestHandler):
            def do_POST(self):
                if not self.try_handle_a2a():
                    # handle other routes
                    ...
    """

    _a2a_path = "/a2a"

    def try_handle_a2a(self) -> bool:
        """
        If the request path is /a2a, handle as JSON-RPC 2.0 A2A request.
        Returns True if handled, False otherwise.
        """
        if self.path == self._a2a_path:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)

            response = _a2a_handler.handle_request(raw_body)
            body = json.dumps(response, ensure_ascii=False).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        return False
