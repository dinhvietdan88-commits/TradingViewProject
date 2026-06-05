"""
rag_mcp.py — MCP server exposing the Minervini RAG knowledge base.

Wraps the existing ChromaDB + sentence-transformers pipeline from rag.py and
exposes it as MCP tools for Claude Desktop / other MCP clients.

Tools:
    query_minervini_kb(query, top_k)  → semantic search over 36 book chunks
    list_kb_chapters()                → list all chunks (id, topic)
    read_chunk(chunk_id)              → return full content of one chunk

Run standalone (stdio):
    python rag_mcp.py
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

# Skip HuggingFace network checks — model is cached locally after first run.
# Without this, sentence-transformers HEADs ~25 files on every cold start (~3-5 min).
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import chromadb
from chromadb.utils import embedding_functions
from mcp.server.fastmcp import FastMCP

import config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("rag_mcp")

mcp = FastMCP("minervini-rag")

_collection: Any = None


def _parse_chunk_metadata(content: str, filename: str) -> dict:
    meta = {"filename": filename, "topic": "general", "chapter": ""}
    for line in content.strip().splitlines():
        if line.startswith("# "):
            meta["topic"] = line.lstrip("# ").strip()
            break
    m = re.search(r"chunk_(\d+)", filename)
    if m:
        meta["chapter"] = m.group(1)
    return meta


def _ensure_collection() -> Any:
    """Lazy-init: open ChromaDB, embed all chunks on first call."""
    global _collection
    if _collection is not None:
        return _collection

    knowledge_dir = Path(config.KNOWLEDGE_DIR)
    if not knowledge_dir.exists():
        raise RuntimeError(f"Knowledge dir not found: {knowledge_dir}")

    chunk_files = sorted(knowledge_dir.glob("chunk_*.md"))
    if not chunk_files:
        raise RuntimeError(f"No chunk files in {knowledge_dir}")

    chroma_path = Path(config.CHROMA_DB_PATH)
    chroma_path.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(chroma_path))
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="paraphrase-multilingual-MiniLM-L12-v2"
    )
    coll = client.get_or_create_collection(
        name="minervini_knowledge",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    if coll.count() < len(chunk_files):
        log.info(f"Embedding {len(chunk_files)} chunks (first run, ~30s)...")
        docs, metas, ids = [], [], []
        for f in chunk_files:
            content = f.read_text(encoding="utf-8")
            if not content.strip():
                continue
            docs.append(content)
            metas.append(_parse_chunk_metadata(content, f.name))
            ids.append(f"minervini_{f.stem}")
        for i in range(0, len(docs), 10):
            coll.upsert(
                documents=docs[i : i + 10],
                metadatas=metas[i : i + 10],
                ids=ids[i : i + 10],
            )
        log.info(f"Embedded {len(docs)} chunks → ChromaDB at {chroma_path}")
    else:
        log.info(f"ChromaDB ready ({coll.count()} vectors)")

    _collection = coll
    return _collection


@mcp.tool()
def query_minervini_kb(query: str, top_k: int = 5) -> dict:
    """
    Semantic search over Mark Minervini's "Trade Like a Stock Market Wizard"
    knowledge base (36 chunks, ~350 pages). Supports Vietnamese and English
    queries.

    Use this for questions about: SEPA methodology, Trend Template (8 criteria),
    VCP (Volatility Contraction Pattern), Stage 1-4 analysis, position sizing,
    stop-loss rules, risk management, fundamentals, catalysts.

    Args:
        query: Question or topic to search for. Vietnamese or English.
        top_k: Number of results to return (1-10). Default 5.

    Returns:
        dict with 'results' (list of chunks with content, chapter, topic,
        relevance_score) and 'query'.
    """
    coll = _ensure_collection()
    top_k = max(1, min(top_k, 10))
    res = coll.query(query_texts=[query], n_results=min(top_k, coll.count()))
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]
    out = []
    for doc, meta, dist in zip(docs, metas, dists, strict=False):
        out.append(
            {
                "chapter": meta.get("chapter", ""),
                "topic": meta.get("topic", ""),
                "filename": meta.get("filename", ""),
                "relevance_score": round(1 - dist, 4),
                "content": doc,
            }
        )
    return {"query": query, "count": len(out), "results": out}


@mcp.tool()
def list_kb_chapters() -> dict:
    """
    List all 36 chunks in the Minervini knowledge base with their chapter
    number and topic title. Use this to browse the KB before querying.
    """
    coll = _ensure_collection()
    got = coll.get(include=["metadatas"])
    items = []
    for cid, meta in zip(got.get("ids", []), got.get("metadatas", []), strict=False):
        items.append(
            {
                "id": cid,
                "chapter": meta.get("chapter", ""),
                "topic": meta.get("topic", ""),
                "filename": meta.get("filename", ""),
            }
        )
    items.sort(key=lambda x: x["chapter"])
    return {"count": len(items), "chapters": items}


@mcp.tool()
def read_chunk(chunk_id: str) -> dict:
    """
    Return the full content of a specific chunk by id (e.g. 'minervini_chunk_007')
    or by chapter number ('007' or '7').

    Args:
        chunk_id: Either the full id like 'minervini_chunk_007' or just '7'.
    """
    coll = _ensure_collection()
    if chunk_id.isdigit():
        chunk_id = f"minervini_chunk_{int(chunk_id):03d}"
    elif not chunk_id.startswith("minervini_"):
        chunk_id = f"minervini_{chunk_id}"
    got = coll.get(ids=[chunk_id], include=["documents", "metadatas"])
    if not got.get("ids"):
        return {"error": f"Not found: {chunk_id}"}
    return {
        "id": got["ids"][0],
        "metadata": got["metadatas"][0],
        "content": got["documents"][0],
    }


def _prewarm():
    try:
        _ensure_collection()
        log.info("Pre-warm complete.")
    except Exception as e:
        log.warning(f"Pre-warm failed (will retry on first call): {e}")


if __name__ == "__main__":
    threading.Thread(target=_prewarm, daemon=True).start()
    mcp.run()
