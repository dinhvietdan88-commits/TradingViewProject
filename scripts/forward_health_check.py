#!/usr/bin/env python3
"""
🏥 forward_health_check.py — Angati Forward Test Health Check
===========================================================
Runs a complete health check on the Forward Test infrastructure.
Use this to verify everything is working before/after deploy.

Usage:
    python scripts/forward_health_check.py
    python scripts/forward_health_check.py --url http://SERVER_C_IP:5000
    python scripts/forward_health_check.py --verbose
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
FWD_DB = ROOT / "nerves" / "workers" / "trading" / "forward_trades.db"
ENV_FILE = ROOT / ".env"

# ANSI
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

CHECKS_TOTAL = 0
CHECKS_PASS = 0
CHECKS_WARN = 0
CHECKS_FAIL = 0


def check(name: str, passed: bool, detail: str = "", warn: bool = False) -> bool:
    global CHECKS_TOTAL, CHECKS_PASS, CHECKS_WARN, CHECKS_FAIL
    CHECKS_TOTAL += 1
    if passed:
        CHECKS_PASS += 1
        icon = f"{GREEN}✅{RESET}"
    elif warn:
        CHECKS_WARN += 1
        icon = f"{YELLOW}⚠️ {RESET}"
    else:
        CHECKS_FAIL += 1
        icon = f"{RED}❌{RESET}"

    print(f"  {icon} {name}", end="")
    if detail:
        print(f"  {DIM}{detail}{RESET}", end="")
    print()
    return passed


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'─' * 55}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 55}{RESET}")


def http_get(url: str, timeout: int = 5) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return 0, str(e)


def http_post(url: str, payload: dict, timeout: int = 5) -> tuple[int, str]:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return 0, str(e)


def load_env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def main() -> None:
    # Fix Windows terminal encoding
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Angati Forward Test Health Check")
    parser.add_argument(
        "--url", default="http://localhost:5000", help="Server C API URL"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show full response bodies"
    )
    args = parser.parse_args()

    print(f"\n{BOLD}{CYAN}{'═' * 55}{RESET}")
    print(f"{BOLD}  🏥 Angati Forward Test — Health Check{RESET}")
    print(
        f"{DIM}  Time: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}{RESET}"
    )
    print(f"{DIM}  API:  {args.url}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 55}{RESET}")

    env = load_env()
    secret = env.get("WEBHOOK_SECRET", env.get("VBS_WEBHOOK_SECRET", "test"))

    # ── 1. File System ────────────────────────────────────────────────────────
    section("1. File System")
    check(
        "forward_trades.db exists",
        FWD_DB.exists(),
        str(FWD_DB.relative_to(ROOT)) if FWD_DB.exists() else "NOT FOUND",
    )
    check(".env exists", ENV_FILE.exists())

    core_files = [
        "nerves/workers/trading/config.py",
        "nerves/workers/trading/database.py",
        "nerves/workers/trading/gateway/webhook.py",
        "nerves/workers/trading/data/routing.py",
        "scripts/deploy_server_c.sh",
        "scripts/monitor_forward_live.py",
        "reports/dashboard_live.html",
        "docs/FORWARD_TEST_GUIDE.md",
        "docs/TRADINGVIEW_FORWARD_ALERT_SETUP.md",
    ]
    for f in core_files:
        check(f.split("/")[-1], (ROOT / f).exists(), f)

    # ── 2. .env Config ────────────────────────────────────────────────────────
    section("2. .env Configuration")
    fwd_db_path = env.get("FORWARD_DB_PATH", "")
    is_relative = fwd_db_path and not (
        fwd_db_path.startswith("C:")
        or fwd_db_path.startswith("/Users")
        or fwd_db_path.startswith("/home/")
        and "Users" in fwd_db_path
    )
    check("FORWARD_DB_PATH is relative", bool(is_relative), f"= {fwd_db_path}")
    check(
        "FORWARD_TEST_ENABLED=true",
        env.get("FORWARD_TEST_ENABLED") == "true",
        env.get("FORWARD_TEST_ENABLED", "NOT SET"),
    )
    check(
        "FORWARD_TEST_INITIAL_CAPITAL set",
        "FORWARD_TEST_INITIAL_CAPITAL" in env,
        env.get("FORWARD_TEST_INITIAL_CAPITAL", "NOT SET"),
    )
    check(
        "WEBHOOK_SECRET set",
        bool(secret and len(secret) > 8),
        "***" + secret[-4:] if len(secret) > 4 else "NOT SET",
    )

    # ── 3. Database ───────────────────────────────────────────────────────────
    section("3. Database — forward_trades.db")
    if FWD_DB.exists():
        conn = sqlite3.connect(str(FWD_DB))
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]

        check("Table 'signals' exists", "signals" in tables)
        check("Table 'trades' exists", "trades" in tables)

        sig_count = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE mode='FORWARD'"
        ).fetchone()[0]
        check("Has FORWARD signals", sig_count > 0, f"count = {sig_count}")

        if sig_count > 0:
            seq = conn.execute(
                "SELECT seq FROM sqlite_sequence WHERE name='signals'"
            ).fetchone()
            seq_val = seq[0] if seq else 0
            check("Signal seq ≥ 1,000,000", seq_val >= 1_000_000, f"seq = {seq_val:,}")

            latest = conn.execute(
                "SELECT id, symbol, mode FROM signals WHERE mode='FORWARD' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if latest:
                check(
                    "Latest signal has mode=FORWARD",
                    latest[2] == "FORWARD",
                    f"id={latest[0]:,} {latest[1]} mode={latest[2]}",
                )
                check(
                    "Latest signal id ≥ 1,000,000",
                    latest[0] >= 1_000_000,
                    f"id = {latest[0]:,}",
                )

        conn.close()
    else:
        check("Database accessible", False, "forward_trades.db not found")

    # ── 4. Server Connectivity ────────────────────────────────────────────────
    section("4. Server C API")
    status, body = http_get(f"{args.url}/tv_health_check")
    is_healthy = status == 200 and (
        "ok" in body.lower() or "healthy" in body.lower() or "status" in body.lower()
    )
    check(
        "Health endpoint responds",
        is_healthy,
        f"HTTP {status}" if status else "Connection refused",
        warn=not is_healthy,
    )

    if is_healthy:
        # Check signals API
        s2, b2 = http_get(f"{args.url}/api/signals?mode=FORWARD&limit=1")
        check("GET /api/signals?mode=FORWARD", s2 == 200, f"HTTP {s2}")

        # Smoke test webhook
        s3, b3 = http_post(
            f"{args.url}/webhook",
            {
                "secret": secret,
                "symbol": "BTCUSDT",
                "action": "buy",
                "price": "67000",
                "quoteQty": 100,
                "mode": "FORWARD",
                "exchange": "binance",
                "sl": "65000",
                "tp": "70000",
            },
        )
        webhook_ok = s3 in (200, 201, 202)
        check(
            "POST /webhook (mode=FORWARD)",
            webhook_ok,
            f"HTTP {s3}" + (f": {b3[:60]}" if args.verbose else ""),
            warn=not webhook_ok,
        )
    else:
        check(
            "API tests skipped",
            True,
            "Server offline — expected if running locally",
            warn=True,
        )
        check("Webhook test skipped", True, "Server offline", warn=True)

    # ── 5. Pine Script Library ────────────────────────────────────────────────
    section("5. Pine Script Library")
    pine_lib = ROOT / "pine" / "v2" / "vbs_webhook_lib.pine"
    if pine_lib.exists():
        content = pine_lib.read_text(encoding="utf-8", errors="ignore")
        check(
            "vbs_webhook_lib.pine has mode param",
            "string mode" in content and '"mode"' in content,
            "mode param in build_payload",
        )
        check(
            "Default mode = FORWARD",
            'mode = "FORWARD"' in content,
            'string mode = "FORWARD"',
        )
        check(
            "a007_mis_webhook.pine exists",
            (ROOT / "pine/v2/a007_mis_webhook.pine").exists(),
        )
        check(
            "supertrend_webhook.pine exists",
            (ROOT / "pine/v2/supertrend_webhook.pine").exists(),
        )
    else:
        check("Pine script library found", False, str(pine_lib))

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{BOLD}{CYAN}{'═' * 55}{RESET}")
    print(f"{BOLD}  📊 Health Check Summary{RESET}")
    print(f"  {GREEN}✅ Pass   : {CHECKS_PASS}{RESET}")
    print(f"  {YELLOW}⚠️  Warn   : {CHECKS_WARN}{RESET}")
    print(f"  {RED}❌ Fail   : {CHECKS_FAIL}{RESET}")
    print(f"  {DIM}Total    : {CHECKS_TOTAL}{RESET}")

    score = int(CHECKS_PASS / CHECKS_TOTAL * 100) if CHECKS_TOTAL else 0
    score_color = GREEN if score >= 90 else (YELLOW if score >= 70 else RED)
    print(f"\n  {BOLD}Score: {score_color}{score}%{RESET}", end="")

    if CHECKS_FAIL == 0 and CHECKS_WARN == 0:
        print(f"  {GREEN}— All systems GO! 🚀{RESET}")
    elif CHECKS_FAIL == 0:
        print(f"  {YELLOW}— Warnings detected, review above{RESET}")
    else:
        print(f"  {RED}— {CHECKS_FAIL} issue(s) need fixing{RESET}")

    print(f"{BOLD}{CYAN}{'═' * 55}{RESET}\n")
    sys.exit(0 if CHECKS_FAIL == 0 else 1)


if __name__ == "__main__":
    main()
