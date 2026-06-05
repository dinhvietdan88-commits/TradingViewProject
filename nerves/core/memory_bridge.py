#!/usr/bin/env python3
"""
Memory Bridge — ADK MemoryService-Compatible Interface

Exposes Angati's local memory stores (ChromaDB, trades.db) through
an interface compatible with Google ADK's MemoryService and
SessionService patterns.

This bridge enables:
    1. A2A tasks to query local memory via standardized API
    2. Future ADK agent integration with Angati's memory layer
    3. Memory search/add operations via HTTP endpoints

Architecture Note:
    This bridge is ISOLATED per CLAUDE.md — it only accesses local
    ChromaDB (server/rag.py) and trades.db. It does NOT touch global
    EAIS Qdrant or conv_graph.db.

Isomorphism:
    ADK MemoryService.search()  ↔  AngatiMemoryBridge.search_memories()
    ADK MemoryService.add()     ↔  AngatiMemoryBridge.add_memory()
    ADK SessionService.get()    ↔  AngatiMemoryBridge.get_session_history()

References:
    - KI: google-adk-deep-research §9 (Memory & Storage Architecture)
    - KI: v9-omni-l1-active-cache-integration (Omni Engine)
    - CLAUDE.md: Isolation boundary
"""

import json
import sqlite3
import time
import uuid
from pathlib import Path


AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent
CORTEX_DB = AGENTS_ROOT / "cortex" / "db"
TRADES_DB = CORTEX_DB / "trades.db"


# ---------------------------------------------------------------------------
# Memory Bridge Core
# ---------------------------------------------------------------------------


class AngatiMemoryBridge:
    """
    ADK MemoryService-compatible interface to Angati's local memory stores.

    Provides three core operations:
        - search_memories: Semantic search across local ChromaDB
        - add_memory: Store a new memory/lesson
        - get_session_history: Retrieve session context from trades.db

    Production Mapping:
        ADK Development          →  ADK Production            →  Angati V10
        InMemoryMemoryService    →  VertexAiMemoryBankService →  AngatiMemoryBridge
        InMemorySessionService   →  DatabaseSessionService    →  trades.db SQLite
        InMemoryArtifactService  →  GcsArtifactService        →  cortex/db/
    """

    def __init__(self, db_path: str = None, chroma_path: str = None):
        self._db_path = db_path or str(TRADES_DB)
        self._chroma_path = chroma_path or str(CORTEX_DB / "chroma_db")
        self._chroma_client = None
        self._chroma_collection = None

    def _ensure_chroma(self):
        """Lazy-load ChromaDB client."""
        if self._chroma_client is not None:
            return True

        try:
            import chromadb

            self._chroma_client = chromadb.PersistentClient(path=self._chroma_path)
            self._chroma_collection = self._chroma_client.get_or_create_collection(
                name="angati_local_memory",
                metadata={"description": "Angati V10 local memory store (ISOLATED)"},
            )
            return True
        except ImportError:
            return False
        except Exception:
            return False

    # ----- Search Memories (ADK MemoryService.search) -----

    def search_memories(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Semantic search across local memory stores.

        Maps to ADK MemoryService.search_memories().
        Uses ChromaDB for vector similarity if available,
        falls back to SQLite FTS on trades.db.

        Args:
            query: Natural language search query
            top_k: Maximum number of results

        Returns:
            List of memory dicts with keys: id, content, metadata, score
        """
        # Strategy 1: ChromaDB semantic search
        if self._ensure_chroma():
            try:
                results = self._chroma_collection.query(
                    query_texts=[query], n_results=min(top_k, 20)
                )
                memories = []
                if results and results.get("documents"):
                    docs = results["documents"][0]
                    metas = results.get("metadatas", [[]])[0]
                    distances = results.get("distances", [[]])[0]
                    ids = results.get("ids", [[]])[0]

                    for i, doc in enumerate(docs):
                        memories.append(
                            {
                                "id": ids[i] if i < len(ids) else str(uuid.uuid4()),
                                "content": doc,
                                "metadata": metas[i] if i < len(metas) else {},
                                "score": round(
                                    1.0 - (distances[i] if i < len(distances) else 0.5),
                                    4,
                                ),
                                "source": "chromadb",
                            }
                        )
                return memories[:top_k]
            except Exception:
                pass

        # Strategy 2: SQLite keyword search fallback
        return self._sqlite_search(query, top_k)

    def _sqlite_search(self, query: str, top_k: int) -> list[dict]:
        """Fallback keyword search on trades.db."""
        if not Path(self._db_path).exists():
            return []

        try:
            conn = sqlite3.connect(self._db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Search across indicator_signals table
            keywords = query.lower().split()
            conditions = " OR ".join(
                ["symbol LIKE ? OR indicator_name LIKE ?" for _ in keywords]
            )
            params = []
            for kw in keywords:
                params.extend([f"%{kw}%", f"%{kw}%"])

            if conditions:
                sql = f"""
                    SELECT id, symbol, indicator_name, interval, close, timestamp
                    FROM indicator_signals
                    WHERE {conditions}
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                params.append(top_k)
                cursor.execute(sql, params)
            else:
                cursor.execute(
                    "SELECT id, symbol, indicator_name, interval, close, timestamp "
                    "FROM indicator_signals ORDER BY timestamp DESC LIMIT ?",
                    (top_k,),
                )

            rows = cursor.fetchall()
            conn.close()

            return [
                {
                    "id": str(row["id"]),
                    "content": f"{row['symbol']} {row['indicator_name']} @ {row['close']}",
                    "metadata": {
                        "symbol": row["symbol"],
                        "indicator": row["indicator_name"],
                        "interval": row["interval"],
                        "close": row["close"],
                        "timestamp": row["timestamp"],
                    },
                    "score": 0.5,  # No semantic scoring in fallback
                    "source": "sqlite_fallback",
                }
                for row in rows
            ]
        except Exception:
            return []

    # ----- Add Memory (ADK MemoryService.add) -----

    def add_memory(self, content: str, metadata: dict = None) -> str:
        """
        Add a new memory to the local store.

        Maps to ADK MemoryService.add_memory().
        Stores in ChromaDB if available, with SQLite-based fallback
        to cortex/state/memory_ledger.jsonl.

        Args:
            content: Memory text content
            metadata: Additional metadata dict

        Returns:
            str: Memory ID
        """
        memory_id = str(uuid.uuid4())
        meta = metadata or {}
        meta["created_at"] = time.time()
        meta["epoch"] = "V10"

        # Strategy 1: ChromaDB
        if self._ensure_chroma():
            try:
                self._chroma_collection.add(
                    ids=[memory_id], documents=[content], metadatas=[meta]
                )
                return memory_id
            except Exception:
                pass

        # Strategy 2: JSONL ledger fallback (Offline-First per SCAR-012)
        ledger_path = AGENTS_ROOT / "cortex" / "state" / "memory_ledger.jsonl"
        try:
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "id": memory_id,
                "content": content,
                "metadata": meta,
                "timestamp": time.time(),
            }
            with open(ledger_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return memory_id
        except Exception:
            return memory_id

    # ----- Session History (ADK SessionService) -----

    def get_session_history(
        self, session_id: str = None, limit: int = 50
    ) -> list[dict]:
        """
        Retrieve session context / recent activity.

        Maps to ADK SessionService.get_session().
        Reads from trades.db to provide trading session history.

        Args:
            session_id: Optional session filter (unused in V10 — returns recent)
            limit: Maximum records to return

        Returns:
            List of session event dicts
        """
        if not Path(self._db_path).exists():
            return []

        try:
            conn = sqlite3.connect(self._db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Get recent trading signals as session history
            cursor.execute(
                """
                SELECT id, symbol, indicator_name, interval, close,
                       atr14, sma50, sma150, sma200, timestamp
                FROM indicator_signals
                ORDER BY timestamp DESC
                LIMIT ?
            """,
                (limit,),
            )

            rows = cursor.fetchall()
            conn.close()

            return [
                {
                    "event_type": "indicator_signal",
                    "timestamp": row["timestamp"],
                    "data": {
                        "symbol": row["symbol"],
                        "indicator": row["indicator_name"],
                        "interval": row["interval"],
                        "close": row["close"],
                        "atr14": row["atr14"],
                        "sma50": row["sma50"],
                        "sma150": row["sma150"],
                        "sma200": row["sma200"],
                    },
                }
                for row in rows
            ]
        except Exception:
            return []

    # ----- Health Check -----

    def health(self) -> dict:
        """Return health status of all memory backends."""
        chroma_ok = self._ensure_chroma()
        sqlite_ok = Path(self._db_path).exists()

        chroma_count = 0
        if chroma_ok and self._chroma_collection:
            try:
                chroma_count = self._chroma_collection.count()
            except Exception:
                pass

        return {
            "status": "healthy" if (chroma_ok or sqlite_ok) else "degraded",
            "backends": {
                "chromadb": {
                    "available": chroma_ok,
                    "path": self._chroma_path,
                    "count": chroma_count,
                },
                "sqlite": {"available": sqlite_ok, "path": self._db_path},
            },
            "epoch": "V10",
            "isolation": "ISOLATED (TradingViewProject satellite)",
        }


# ---------------------------------------------------------------------------
# HTTP Handler Mixin
# ---------------------------------------------------------------------------

# Singleton bridge instance
_memory_bridge = AngatiMemoryBridge()


class MemoryEndpointMixin:
    """
    Mixin that adds memory API endpoints to any BaseHTTPRequestHandler.

    Endpoints:
        POST /memory/search  — Semantic search
        POST /memory/add     — Add memory
        GET  /memory/session  — Get session history
        GET  /memory/health   — Health check
    """

    def try_handle_memory(self) -> bool:
        """
        Handle memory API requests. Returns True if handled.
        """
        if self.path == "/memory/health":
            return self._serve_memory_health()
        elif self.path == "/memory/session":
            return self._serve_session_history()
        elif self.path == "/memory/search" and self.command == "POST":
            return self._serve_memory_search()
        elif self.path == "/memory/add" and self.command == "POST":
            return self._serve_memory_add()
        return False

    def _serve_memory_health(self) -> bool:
        health = _memory_bridge.health()
        body = json.dumps(health, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_session_history(self) -> bool:
        history = _memory_bridge.get_session_history()
        body = json.dumps({"events": history}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_memory_search(self) -> bool:
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": "Invalid JSON"})
            return True

        query = data.get("query", "")
        top_k = data.get("top_k", 5)
        results = _memory_bridge.search_memories(query, top_k)
        body = json.dumps({"results": results}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_memory_add(self) -> bool:
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": "Invalid JSON"})
            return True

        content = data.get("content", "")
        metadata = data.get("metadata", {})
        memory_id = _memory_bridge.add_memory(content, metadata)
        body = json.dumps(
            {"id": memory_id, "status": "stored"}, ensure_ascii=False
        ).encode("utf-8")
        self.send_response(201)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
