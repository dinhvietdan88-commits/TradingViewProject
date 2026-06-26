#!/usr/bin/env python3
"""
🔁 replay_backtest_to_forward.py — Bulk Replay Backtest → Forward Test DB
=========================================================================
Reads historical signals from pattern_archive.json / trades_data.json
and replays them as FORWARD mode signals via webhook POST.

This lets you seed the forward_trades.db with realistic paper trades
before real TradingView signals start flowing.

Usage:
    python scripts/replay_backtest_to_forward.py
    python scripts/replay_backtest_to_forward.py --limit 50 --url http://localhost:5000
    python scripts/replay_backtest_to_forward.py --dry-run
    python scripts/replay_backtest_to_forward.py --db-direct  # bypass webhook, write to DB
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent

GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"
CYAN = "\033[96m"; BOLD = "\033[1m"; DIM = "\033[2m"; RESET = "\033[0m"


def load_source_trades() -> list[dict]:
    """Load trades from pattern_archive.json + trades_data.json."""
    all_trades = []

    # Source 1: pattern_archive.json
    archive = ROOT / "trades" / "pattern_archive.json"
    if archive.exists():
        with open(archive, encoding="utf-8") as f:
            data = json.load(f)
        trades = data.get("trades", [])
        # Map to standard format
        for t in trades:
            all_trades.append({
                "id": t.get("id", "?"),
                "symbol": t.get("symbol", "BTCUSDT"),
                "action": "buy" if t.get("side", "BUY").upper() == "BUY" else "sell",
                "entry_price": t.get("entry_price", 67000),
                "sl_price": t.get("sl", 0),
                "tp_price": t.get("tp", 0),
                "outcome": t.get("outcome", "?"),
                "pnl": t.get("pnl", 0),
                "source": "pattern_archive",
            })
        print(f"  📂 pattern_archive.json: {len(trades)} trades loaded")

    # Source 2: trades_data.json
    trades_json = ROOT / "reports" / "trades_data.json"
    if trades_json.exists():
        with open(trades_json, encoding="utf-8") as f:
            data = json.load(f)
        trades2 = data.get("trades", [])
        for t in trades2:
            all_trades.append({
                "id": t.get("id", "?"),
                "symbol": t.get("symbol", "BTCUSDT"),
                "action": "buy" if t.get("side", "BUY").upper() == "BUY" else "sell",
                "entry_price": t.get("entry_price", 67000),
                "sl_price": t.get("sl_price", 0),
                "tp_price": t.get("tp_price", 0),
                "outcome": t.get("outcome", "?"),
                "pnl": t.get("pnl", 0),
                "source": "trades_data",
            })
        print(f"  📂 trades_data.json: {len(trades2)} trades loaded")

    return all_trades


def replay_via_webhook(
    trades: list[dict],
    url: str,
    secret: str,
    delay: float,
    dry_run: bool,
) -> tuple[int, int]:
    """POST each trade as FORWARD signal to webhook."""
    import urllib.request, urllib.error

    ok_count = 0
    fail_count = 0

    SYMBOL_MAP = {
        "BTCUSDT": {"name": "BTC", "base_price": 67000},
        "ETHUSDT": {"name": "ETH", "base_price": 3500},
        "SOLUSDT": {"name": "SOL", "base_price": 150},
    }

    for i, t in enumerate(trades, 1):
        symbol = t.get("symbol", "BTCUSDT")
        if symbol not in SYMBOL_MAP:
            symbol = "BTCUSDT"

        price = t.get("entry_price") or SYMBOL_MAP[symbol]["base_price"]
        sl = t.get("sl_price") or price * 0.92
        tp = t.get("tp_price") or price * 1.18

        payload = json.dumps({
            "secret": secret,
            "symbol": symbol,
            "action": t.get("action", "buy"),
            "price": str(round(float(price), 2)),
            "quoteQty": 100.0,
            "interval": "15",
            "mode": "FORWARD",
            "exchange": "binance",
            "sl": str(round(float(sl), 2)),
            "tp": str(round(float(tp), 2)),
            "replay_source": t.get("source", "replay"),
            "original_id": str(t.get("id", i)),
        }).encode("utf-8")

        status_icon = "📤" if not dry_run else "📋"
        print(f"  {status_icon} [{i:>3}/{len(trades)}] {symbol} {t['action'].upper()}"
              f" @ {float(price):,.2f}"
              f"  sl={float(sl):,.2f}  tp={float(tp):,.2f}", end="")

        if dry_run:
            print(f"  {DIM}[DRY-RUN]{RESET}")
            ok_count += 1
            continue

        try:
            req = urllib.request.Request(
                f"{url}/webhook",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode()
                print(f"  {GREEN}✅{RESET} {body[:60]}")
                ok_count += 1
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:80]
            print(f"  {RED}❌ HTTP {e.code}: {body}{RESET}")
            fail_count += 1
        except Exception as e:
            print(f"  {YELLOW}⚠️ {e}{RESET}")
            fail_count += 1

        time.sleep(delay)

    return ok_count, fail_count


def replay_db_direct(trades: list[dict], db_path: Path, dry_run: bool) -> tuple[int, int]:
    """Write directly to forward_trades.db bypassing webhook."""
    if not db_path.exists():
        print(f"{RED}  ❌ DB not found: {db_path}{RESET}")
        return 0, len(trades)

    conn = sqlite3.connect(str(db_path))
    ok_count = 0
    fail_count = 0

    # Get current max id
    cur = conn.execute("SELECT MAX(id) FROM signals WHERE id >= 1000000")
    row = cur.fetchone()
    next_id = (row[0] + 1) if row[0] else 1000100

    now_ts = datetime.now(tz=timezone.utc).isoformat()

    for i, t in enumerate(trades, 1):
        symbol = t.get("symbol", "BTCUSDT")
        action = t.get("action", "buy")
        price = t.get("entry_price", 67000)
        signal_id = next_id + i

        print(f"  💾 [{i:>3}/{len(trades)}] id={signal_id} {symbol} {action.upper()} @ {float(price):,.2f}", end="")

        if dry_run:
            print(f"  {DIM}[DRY-RUN]{RESET}")
            ok_count += 1
            continue

        try:
            conn.execute(
                """INSERT INTO signals
                   (id, created_at, symbol, action, price, quote_qty, mode, processed, state)
                   VALUES (?, ?, ?, ?, ?, ?, 'FORWARD', 1, 'COMPLETED')""",
                (signal_id, now_ts, symbol, action, str(price), 100.0),
            )
            conn.commit()
            print(f"  {GREEN}✅{RESET}")
            ok_count += 1
        except Exception as e:
            print(f"  {RED}❌ {e}{RESET}")
            fail_count += 1

    conn.close()
    return ok_count, fail_count


def load_env_secret() -> str:
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("WEBHOOK_SECRET="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("WEBHOOK_SECRET", "test_secret")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="🔁 Replay backtest trades as Forward Test signals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--limit", type=int, default=50, help="Max signals to replay (default: 50)")
    parser.add_argument("--url", type=str, default="http://localhost:5000", help="Webhook URL")
    parser.add_argument("--secret", type=str, default=None, help="Webhook secret (auto-loaded from .env)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests in seconds (default: 0.3)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be sent without sending")
    parser.add_argument("--db-direct", action="store_true", help="Write directly to DB (bypass webhook)")
    parser.add_argument("--symbol", type=str, default=None, help="Filter by symbol (BTCUSDT/ETHUSDT/SOLUSDT)")
    args = parser.parse_args()

    secret = args.secret or load_env_secret()

    print(f"\n{BOLD}{CYAN}{'═'*60}{RESET}")
    print(f"{BOLD}  🔁 Angati — Backtest → Forward Test Replay{RESET}")
    print(f"{DIM}  Mode: {'DB-direct' if args.db_direct else f'Webhook {args.url}'}")
    print(f"  Limit: {args.limit} signals | Dry-run: {args.dry_run}{RESET}")
    print(f"{BOLD}{CYAN}{'═'*60}{RESET}\n")

    # Load source data
    print(f"{CYAN}📂 Loading source trades...{RESET}")
    trades = load_source_trades()

    if not trades:
        print(f"{RED}  ❌ No trades found in pattern_archive.json or trades_data.json{RESET}")
        sys.exit(1)

    # Filter by symbol if requested
    if args.symbol:
        trades = [t for t in trades if t.get("symbol", "").upper() == args.symbol.upper()]
        print(f"  Filtered to {args.symbol}: {len(trades)} trades")

    # Limit
    trades = trades[: args.limit]
    print(f"  {GREEN}Replaying {len(trades)} trades...{RESET}\n")

    # Execute
    if args.db_direct:
        db_path = ROOT / "nerves" / "workers" / "trading" / "forward_trades.db"
        ok, fail = replay_db_direct(trades, db_path, args.dry_run)
    else:
        ok, fail = replay_via_webhook(trades, args.url, secret, args.delay, args.dry_run)

    # Summary
    print(f"\n{BOLD}{CYAN}{'═'*60}{RESET}")
    print(f"{BOLD}  📊 Replay Complete{RESET}")
    print(f"  {GREEN}✅ OK   : {ok}{RESET}")
    print(f"  {RED}❌ Fail : {fail}{RESET}")
    if ok > 0 and not args.dry_run:
        print(f"\n  Check results:")
        print(f"  curl '{args.url}/api/signals?mode=FORWARD'")
        print(f"  curl '{args.url}/trades/stats?mode=FORWARD'")
    print(f"{BOLD}{CYAN}{'═'*60}{RESET}\n")


if __name__ == "__main__":
    main()
