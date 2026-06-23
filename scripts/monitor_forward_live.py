#!/usr/bin/env python3
"""
📡 monitor_forward_live.py — Real-time Forward Test Signal Monitor
==================================================================
Watches forward_trades.db for new signals and prints live updates.
Also shows running stats: Win Rate, P&L, total signals.

Usage:
    python scripts/monitor_forward_live.py
    python scripts/monitor_forward_live.py --interval 10 --api http://localhost:5000
    python scripts/monitor_forward_live.py --db-only  # skip API, watch DB directly
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── ANSI colors ───────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BLUE = "\033[94m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "nerves" / "workers" / "trading" / "forward_trades.db"


def color_pnl(pnl: float) -> str:
    s = f"{pnl:+.4f}%"
    return f"{GREEN}{s}{RESET}" if pnl >= 0 else f"{RED}{s}{RESET}"


def color_action(action: str) -> str:
    return f"{GREEN}BUY {RESET}" if action.lower() == "buy" else f"{RED}SELL{RESET}"


def clear_line() -> None:
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


def header() -> None:
    print(f"\n{BOLD}{BLUE}{'═' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  📡 Angati Forward Test — Live Monitor  {RESET}")
    print(f"{DIM}  DB: {DB_PATH}{RESET}")
    print(f"{BOLD}{BLUE}{'═' * 70}{RESET}\n")


def get_stats(conn: sqlite3.Connection) -> dict:
    """Compute running stats from forward_trades.db."""
    cur = conn.execute("SELECT COUNT(*) as total FROM signals WHERE mode='FORWARD'")
    total = cur.fetchone()[0]

    cur = conn.execute(
        """SELECT s.id, s.symbol, s.action, s.price, s.created_at,
                  t.pnl, t.status
           FROM signals s
           LEFT JOIN trades t ON t.signal_id = s.id
           WHERE s.mode = 'FORWARD'
           ORDER BY s.id DESC LIMIT 100"""
    )
    rows = cur.fetchall()

    wins = sum(1 for r in rows if r[5] and r[5] > 0)
    losses = sum(1 for r in rows if r[5] and r[5] < 0)
    total_pnl = sum(r[5] for r in rows if r[5])
    closed = wins + losses
    win_rate = round(wins / closed * 100, 1) if closed else 0.0

    gross_profit = sum(r[5] for r in rows if r[5] and r[5] > 0)
    gross_loss = abs(sum(r[5] for r in rows if r[5] and r[5] < 0))
    pf = round(gross_profit / gross_loss, 3) if gross_loss else float("inf")

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "closed": closed,
        "win_rate": win_rate,
        "total_pnl": round(total_pnl, 4),
        "profit_factor": pf,
        "rows": rows,
    }


def print_stats(stats: dict, last_id: int) -> None:
    """Print live stats panel."""
    wr_color = GREEN if stats["win_rate"] >= 50 else RED
    pf_color = GREEN if stats["profit_factor"] >= 1.3 else RED
    pnl_color = GREEN if stats["total_pnl"] >= 0 else RED

    now = datetime.now().strftime("%H:%M:%S")

    print(
        f"\r{DIM}[{now}]{RESET}  "
        f"{CYAN}Signals: {BOLD}{stats['total']}{RESET}  │  "
        f"WR: {wr_color}{BOLD}{stats['win_rate']}%{RESET}  │  "
        f"PF: {pf_color}{BOLD}{stats['profit_factor']}{RESET}  │  "
        f"P&L: {pnl_color}{BOLD}{stats['total_pnl']:+.2f}%{RESET}  │  "
        f"W/L: {GREEN}{stats['wins']}{RESET}/{RED}{stats['losses']}{RESET}",
        end="",
        flush=True,
    )


def print_new_signal(row: tuple) -> None:
    """Print a newly detected signal."""
    sid, symbol, action, price, created_at, pnl, status = row
    ts = created_at[:16] if created_at else "?"
    print(
        f"\n{BOLD}  🆕 NEW SIGNAL [{sid}]{RESET}  "
        f"{CYAN}{symbol}{RESET}  "
        f"{color_action(action)}  "
        f"@ {YELLOW}{float(price):,.2f}{RESET}  "
        f"{DIM}{ts}{RESET}"
    )
    if pnl is not None:
        print(f"     └─ Closed: {color_pnl(pnl)} | Status: {status}")


def try_api_check(api_url: str) -> Optional[dict]:
    """Try fetching live stats from API."""
    try:
        import urllib.request
        import json

        url = f"{api_url}/trades/stats?mode=FORWARD"
        with urllib.request.urlopen(url, timeout=3) as r:  # noqa: S310
            return json.loads(r.read())
    except Exception:
        return None


def watch(db_path: Path, interval: int, api_url: Optional[str]) -> None:
    """Main watch loop."""
    header()
    print(f"  Watching: {db_path}")
    print(f"  Interval: {interval}s  │  API: {api_url or 'DB-only mode'}\n")
    print(f"  {DIM}Press Ctrl+C to stop{RESET}\n")

    if not db_path.exists():
        print(f"{RED}  ❌ forward_trades.db not found at:{RESET}")
        print(f"     {db_path}")
        print("\n  Waiting for DB to be created by server startup...")

    last_id = 0
    iteration = 0

    while True:
        try:
            iteration += 1

            if not db_path.exists():
                sys.stdout.write(
                    f"\r  ⏳ Waiting for DB... ({iteration * interval}s elapsed)"
                )
                sys.stdout.flush()
                time.sleep(interval)
                continue

            conn = sqlite3.connect(str(db_path))
            stats = get_stats(conn)

            # Detect new signals since last check
            if last_id == 0 and stats["rows"]:
                # First run — set baseline
                last_id = stats["rows"][0][0] if stats["rows"] else 0
                print(
                    f"  {DIM}Baseline: {stats['total']} existing signals (latest id={last_id}){RESET}"
                )
            elif stats["rows"] and stats["rows"][0][0] > last_id:
                # New signals detected
                new_rows = [r for r in stats["rows"] if r[0] > last_id]
                for row in reversed(new_rows):
                    print_new_signal(row)
                last_id = stats["rows"][0][0]

            conn.close()

            # Try API if available
            if api_url and iteration % 3 == 0:
                api_stats = try_api_check(api_url)
                if api_stats:
                    stats.update(api_stats)

            print_stats(stats, last_id)
            time.sleep(interval)

        except KeyboardInterrupt:
            print(f"\n\n{YELLOW}  ⚡ Monitor stopped.{RESET}\n")
            break
        except Exception as e:
            sys.stdout.write(f"\r  {DIM}Error: {e} — retrying...{RESET}")
            time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="📡 Angati Forward Test Live Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/monitor_forward_live.py
  python scripts/monitor_forward_live.py --interval 5
  python scripts/monitor_forward_live.py --api http://localhost:5000
  python scripts/monitor_forward_live.py --db nerves/workers/trading/forward_trades.db
        """,
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Poll interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--api",
        type=str,
        default=None,
        help="Server C API URL (e.g. http://localhost:5000)",
    )
    parser.add_argument(
        "--db", type=str, default=None, help="Custom path to forward_trades.db"
    )
    parser.add_argument(
        "--db-only", action="store_true", help="DB-only mode (skip API)"
    )

    args = parser.parse_args()

    db_path = Path(args.db) if args.db else DB_PATH
    api_url = None if args.db_only else args.api

    watch(db_path, args.interval, api_url)


if __name__ == "__main__":
    main()
