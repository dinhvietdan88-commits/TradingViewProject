import asyncio
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database
from exchanges.registry import init_registry, get_registry
from capture_client import PythonCaptureClient

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("weex_trial")


async def run_trial():
    log.info("=== STEP 1: INITIALIZE DATABASE AND REGISTRY ===")
    await database.init_db()
    init_registry()

    log.info("=== STEP 2: TEST WEEX CANDLE DATA SCANNING ===")
    client = PythonCaptureClient()
    try:
        # Fetching 5 candles for BTCUSDT_UMCBL (mapped to cmt_btcusdt)
        ohlcv = await client._get_ohlcv_data("BTCUSDT_UMCBL", "1h", limit=5)
        log.info(
            f"Successfully scanned Weex candle data! Returned {len(ohlcv)} candles:"
        )
        for idx, candle in enumerate(ohlcv):
            log.info(
                f"  [{idx}] Time: {candle[0]} | O: {candle[1]} | H: {candle[2]} | L: {candle[3]} | C: {candle[4]} | V: {candle[5]}"
            )

        # Verify order of timestamps is ascending
        if len(ohlcv) >= 2:
            assert ohlcv[0][0] < ohlcv[-1][0], (
                "Candles must be in ascending chronological order!"
            )
            log.info("Verified: Candles are in ascending chronological order.")

        latest_price = ohlcv[-1][4] if ohlcv else 67500.0
    except Exception as e:
        log.error(f"Failed to scan Weex candle data: {e}")
        latest_price = 67500.0

    log.info("=== STEP 3: TEST WEEX TRIAL ORDER PLACEMENT (DRY-RUN) ===")
    registry = get_registry()
    adapter = registry.get_adapter("weex")
    if not adapter:
        log.error("WeexAdapter not found in registry!")
        return

    log.info(
        f"WeexAdapter loaded. Dry Run: {adapter.is_dry_run} | Testnet: {adapter.is_testnet}"
    )

    # Calculate SL and TP
    sl_price = latest_price * 0.95
    tp_price = latest_price * 1.10

    log.info("Sending Smart Order to Weex:")
    log.info("  Symbol: BTC/USDT (routed as BTCUSDT_UMCBL)")
    log.info("  Side: BUY")
    log.info(f"  Entry Target: {latest_price}")
    log.info(f"  Stop Loss: {sl_price:.2f}")
    log.info(f"  Take Profit: {tp_price:.2f}")

    order_result = await adapter.execute_smart_order(
        symbol="BTC/USDT",
        side="BUY",
        entry_price=latest_price,
        sl_price=sl_price,
        tp_price=tp_price,
        quote_qty=100.0,
    )

    log.info("Order Execution Result:")
    log.info(f"  Success: {order_result.success}")
    log.info(f"  Exchange: {order_result.exchange}")
    log.info(f"  Dry Run: {order_result.dry_run}")
    if order_result.success:
        log.info(f"  Entry Order: {order_result.entry_order}")
        log.info(f"  OCO exits: {order_result.oco_order}")
        log.info(f"  Risk params: {order_result.risk}")
    else:
        log.error(f"  Error: {order_result.error}")


if __name__ == "__main__":
    asyncio.run(run_trial())
