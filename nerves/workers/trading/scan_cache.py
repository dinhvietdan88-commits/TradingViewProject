"""
scan_cache.py — Shared in-memory scan results store.

Both the FastAPI server (main.py) and the Telegram bot (telegram_bot.py)
import this module so that scan results are visible to both.

Thread/asyncio-safe: plain dict + lock-free (GIL protects simple assignments).
"""

from __future__ import annotations

from datetime import datetime, timezone, UTC
from typing import Any, Dict, List, Optional

# ── Singleton store ───────────────────────────────────────────────────────────
_store: dict[str, Any] = {
    "results": [],  # List[dict] — last scan rows
    "scanned": 0,  # int — number of symbols
    "timestamp": None,  # ISO string (UTC)
    "source": None,  # "web" | "telegram" | "scheduler"
    "symbol_list": [],  # list of symbols that were scanned
}


def save_scan_results(
    results: list[dict[str, Any]],
    source: str = "web",
    symbol_list: list[str] | None = None,
) -> None:
    """Persist a completed scan into the shared cache.

    Args:
        results:     Serialised scan rows (dicts with symbol, price, etc.)
        source:      Who triggered: "web" | "telegram" | "scheduler"
        symbol_list: The symbols that were scanned.
    """
    _store["results"] = results
    _store["scanned"] = len(results)
    _store["timestamp"] = datetime.now(UTC).isoformat()
    _store["source"] = source
    _store["symbol_list"] = symbol_list or [r.get("symbol") for r in results]


def get_last_scan() -> dict[str, Any]:
    """Return the cached scan payload (same shape as /api/scan/trigger response)."""
    return {
        "scanned": _store["scanned"],
        "timestamp": _store["timestamp"],
        "source": _store["source"],
        "symbol_list": _store["symbol_list"],
        "results": _store["results"],
    }


def has_results() -> bool:
    """True if at least one scan has been cached."""
    return bool(_store["results"])
