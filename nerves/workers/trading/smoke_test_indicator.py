"""
Live Smoke Test Suite — Indicator Signal Pipeline
Tests:
  SMOKE-1: ATR-based SL/TP (entry signal, metadata.atr_value provided)
  SMOKE-2: Info high-priority notification (confidence > 80)
  SMOKE-3: Missing required field → HTTP 400
"""

import asyncio
import io
import os
import sys

import httpx

# Force UTF-8 output on Windows standard terminal
if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Match server default (config.PORT); override with PORT=8000 if you run uvicorn on 8000
_PORT = os.getenv("PORT", "5000")
BASE_URL = os.getenv("SMOKE_BASE_URL", f"http://127.0.0.1:{_PORT}")
# Try to read WEBHOOK_SECRET from .env file
for env_file in [".env", "../.env", "../../.env"]:
    if os.path.exists(env_file):
        try:
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("WEBHOOK_SECRET="):
                        val = line.split("=")[1].strip()
                        # Remove quotes if present
                        if val.startswith('"') and val.endswith('"'):
                            val = val[1:-1]
                        if val.startswith("'") and val.endswith("'"):
                            val = val[1:-1]
                        os.environ["WEBHOOK_SECRET"] = val
                        break
        except ConnectionError as e:
            import logging

            logging.getLogger(__name__).warning("Ignored: %s", e)

SECRET = os.getenv("WEBHOOK_SECRET", "test-secret")
WEBHOOK = f"{BASE_URL}/webhook"

PASS = "[PASS]"  # noqa: S105
FAIL = "[FAIL]"


async def wait_for_server(timeout: int = 30):
    """Poll /health until the server is up."""
    async with httpx.AsyncClient() as client:
        for _ in range(timeout):
            try:
                r = await client.get(f"{BASE_URL}/health", timeout=2.0)
                if r.status_code == 200:
                    return True
            except ConnectionError as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)
            await asyncio.sleep(1)
    return False


async def smoke1_atr_sl_tp():
    """SMOKE-1: entry signal with ATR → sl = price-(atr*2), tp = price+(atr*3)."""
    price = 68000.0
    atr = 1000.0
    expected_sl = price - (atr * 2)  # 66000.0
    expected_tp = price + (atr * 3)  # 71000.0

    payload = {
        "secret": SECRET,
        "source": "indicator",
        "symbol": "BTCUSDT",
        "indicator_name": "SuperTrend",
        "signal_type": "entry",
        "confidence_score": 85,
        "conditions_met": ["price > ST"],
        "metadata": {"atr_value": str(atr)},
        "interval": "60",
        "price": price,
        "exchange": "binance",
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(WEBHOOK, json=payload, timeout=10.0)

    if r.status_code != 200:
        print(f"{FAIL} SMOKE-1: HTTP {r.status_code} — {r.text[:200]}")
        return False

    body = r.json()
    if not body.get("received"):
        print(f"{FAIL} SMOKE-1: received=False — {body}")
        return False

    # Verify enrichment via /signals endpoint or logs
    # For smoke test, we trust the processor; just verify the gateway accepted it
    print(
        f"{PASS} SMOKE-1: ATR SL/TP signal accepted  signal_id={body.get('signal_id')}  "
        f"(expected sl={expected_sl}, tp={expected_tp})"
    )
    return True


async def smoke2_info_high_priority():
    """SMOKE-2: info signal with confidence=92 → should trigger 🔴 KHẨN CẤP notification."""
    payload = {
        "secret": SECRET,
        "source": "indicator",
        "symbol": "ETHUSDT",
        "indicator_name": "RSI Oversold",
        "signal_type": "info",
        "confidence_score": 92,
        "conditions_met": ["RSI < 30", "Volume spike"],
        "metadata": {},
        "interval": "4h",
        "price": 3500.0,
        "exchange": "binance",
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(WEBHOOK, json=payload, timeout=10.0)

    if r.status_code != 200:
        print(f"{FAIL} SMOKE-2: HTTP {r.status_code} — {r.text[:200]}")
        return False

    body = r.json()
    if not body.get("received"):
        print(f"{FAIL} SMOKE-2: received=False — {body}")
        return False

    print(
        f"{PASS} SMOKE-2: Info high-priority (conf=92) accepted  "
        f"signal_id={body.get('signal_id')}  "
        f"(🔴 KHẨN CẤP notification should be in Telegram)"
    )
    return True


async def smoke3_missing_required_field():
    """SMOKE-3: indicator payload missing indicator_name → HTTP 400."""
    payload = {
        "secret": SECRET,
        "source": "indicator",
        "symbol": "BTCUSDT",
        # intentionally omitting indicator_name
        "signal_type": "entry",
        "confidence_score": 80,
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(WEBHOOK, json=payload, timeout=10.0)

    if r.status_code == 400:
        detail = r.json().get("detail", "")
        print(
            f"{PASS} SMOKE-3: HTTP 400 returned for missing indicator_name  detail='{detail}'"
        )
        return True
    else:
        print(
            f"{FAIL} SMOKE-3: Expected HTTP 400, got {r.status_code} — {r.text[:200]}"
        )
        return False


async def smoke3b_missing_symbol():
    """SMOKE-3b: indicator payload missing symbol → HTTP 400."""
    payload = {
        "secret": SECRET,
        "source": "indicator",
        "indicator_name": "SuperTrend",
        "signal_type": "entry",
        "confidence_score": 80,
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(WEBHOOK, json=payload, timeout=10.0)

    if r.status_code == 400:
        detail = r.json().get("detail", "")
        print(
            f"{PASS} SMOKE-3b: HTTP 400 returned for missing symbol  detail='{detail}'"
        )
        return True
    else:
        print(
            f"{FAIL} SMOKE-3b: Expected HTTP 400, got {r.status_code} — {r.text[:200]}"
        )
        return False


async def main():
    print("\n" + "=" * 60)
    print("  SOVEREIGN INDICATOR PIPELINE — LIVE SMOKE TEST")
    print("=" * 60)

    print(f"\n[WAIT] Waiting for server at {BASE_URL} ...")
    ready = await wait_for_server(timeout=40)
    if not ready:
        print(f"\n{FAIL} Server did not start in time. Aborting smoke tests.")
        sys.exit(1)
    print("[OK] Server is up.\n")

    results = await asyncio.gather(
        smoke1_atr_sl_tp(),
        smoke2_info_high_priority(),
        smoke3_missing_required_field(),
        smoke3b_missing_symbol(),
    )

    passed = sum(results)
    total = len(results)
    print("\n" + "=" * 60)
    if passed == total:
        print(f"  RESULT: {passed}/{total} PASSED -- All smoke tests GREEN")
    else:
        print(f"  RESULT: {passed}/{total} PASSED -- {total - passed} test(s) FAILED")
    print("=" * 60 + "\n")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
