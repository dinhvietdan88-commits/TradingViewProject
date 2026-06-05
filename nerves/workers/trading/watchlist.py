"""
P6 — Watchlist Management
Dynamic watchlist với JSON persistence + TradingView sync.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"

# Default symbols nếu file chưa tồn tại
_DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
]


def _load() -> list[str]:
    """Load watchlist từ JSON file."""
    if _WATCHLIST_FILE.exists():
        try:
            data = json.loads(_WATCHLIST_FILE.read_text(encoding="utf-8"))
            return [s.upper().strip() for s in data.get("symbols", []) if s.strip()]
        except Exception as e:
            logger.warning(f"Failed to load watchlist: {e}")
    return list(_DEFAULT_SYMBOLS)


def _save(symbols: list[str]) -> None:
    """Persist watchlist to JSON file."""
    _WATCHLIST_FILE.write_text(
        json.dumps({"symbols": symbols}, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def get_watchlist() -> list[str]:
    """Return current watchlist symbols."""
    return _load()


def add_symbol(symbol: str) -> dict:
    """
    Add symbol to watchlist.
    Returns {"added": bool, "symbol": str, "watchlist": list}
    """
    symbol = symbol.upper().strip()
    symbols = _load()

    if symbol in symbols:
        return {
            "added": False,
            "reason": "already_exists",
            "symbol": symbol,
            "watchlist": symbols,
        }

    symbols.append(symbol)
    _save(symbols)
    logger.info(f"Watchlist: added {symbol}")
    return {"added": True, "symbol": symbol, "watchlist": symbols}


def remove_symbol(symbol: str) -> dict:
    """
    Remove symbol from watchlist.
    Returns {"removed": bool, "symbol": str, "watchlist": list}
    """
    symbol = symbol.upper().strip()
    symbols = _load()

    if symbol not in symbols:
        return {
            "removed": False,
            "reason": "not_found",
            "symbol": symbol,
            "watchlist": symbols,
        }

    symbols.remove(symbol)
    _save(symbols)
    logger.info(f"Watchlist: removed {symbol}")
    return {"removed": True, "symbol": symbol, "watchlist": symbols}


def set_watchlist(symbols: list[str]) -> list[str]:
    """Replace entire watchlist."""
    cleaned = [s.upper().strip() for s in symbols if s.strip()]
    _save(cleaned)
    return cleaned


async def sync_from_tradingview(mcp_client) -> dict:
    """
    Sync watchlist từ TradingView Desktop (qua MCP).
    Merge với watchlist hiện tại.
    """
    try:
        raw = await mcp_client._run("watchlist", "get")
        tv_symbols = []

        if isinstance(raw, list):
            tv_symbols = [str(s).upper() for s in raw]
        elif isinstance(raw, dict) and "symbols" in raw:
            tv_symbols = [str(s).upper() for s in raw["symbols"]]

        if not tv_symbols:
            return {"synced": False, "reason": "empty_watchlist_from_tv"}

        current = _load()
        merged = list(
            dict.fromkeys(current + tv_symbols)
        )  # deduplicate, preserve order
        _save(merged)
        logger.info(
            f"Watchlist synced from TradingView: {len(tv_symbols)} symbols, total {len(merged)}"
        )
        return {
            "synced": True,
            "added": len(merged) - len(current),
            "total": len(merged),
            "watchlist": merged,
        }

    except Exception as e:
        logger.warning(f"TradingView watchlist sync failed: {e}")
        return {"synced": False, "error": str(e)}
