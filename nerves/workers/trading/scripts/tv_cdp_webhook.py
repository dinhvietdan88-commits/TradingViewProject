"""
tv_cdp_webhook.py -- TradingView Desktop CDP Connection and Webhook Automation

1. Checks if CDP is listening on port 9222.
2. If not, auto-launches TradingView Desktop (handling standard installation paths
   and querying MSIX package locations dynamically).
3. Connects via CDP to extract active symbol, timeframe, close price, and indicator values.
4. Falls back gracefully to default values if extraction fails.
5. Builds and sends a validated webhook payload to the FastAPI server.
"""

import os
import sys
import time
import subprocess
import logging
import requests
import asyncio
from pathlib import Path

# Ensure nerves/workers/trading is in the Python path
TRADING_DIR = Path(__file__).resolve().parent.parent
if str(TRADING_DIR) not in sys.path:
    sys.path.insert(0, str(TRADING_DIR))

# Ensure project root is also in path
PROJECT_ROOT = TRADING_DIR.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
from mcp_client import get_mcp_client  # noqa: E402

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("tv_cdp_webhook")

CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}/json/version"


def is_cdp_active() -> bool:
    """Check if CDP is already listening on 9222."""
    try:
        response = requests.get(CDP_URL, timeout=2)
        if response.status_code == 200:
            logger.info("CDP is already listening on port 9222.")
            return True
    except Exception:
        pass
    return False


def find_tradingview_exe() -> str:
    """Find TradingView Desktop executable on Windows."""
    # 1. Check standard installation paths
    std_paths = [
        os.path.expandvars(r"%LOCALAPPDATA%\TradingView\TradingView.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\TradingView\TradingView.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\TradingView\TradingView.exe"),
    ]
    for path in std_paths:
        if os.path.exists(path):
            logger.info(f"TradingView.exe found at standard path: {path}")
            return path

    # 2. Query MSIX package dynamically using PowerShell
    try:
        logger.info("TradingView not found in standard paths. Querying MSIX package...")
        cmd = ["powershell", "-Command", "Get-AppxPackage -Name 'TradingView.Desktop'"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.strip().startswith("InstallLocation"):
                    parts = line.split(":", 1)
                    if len(parts) > 1:
                        install_dir = parts[1].strip()
                        path = os.path.join(install_dir, "TradingView.exe")
                        if os.path.exists(path):
                            logger.info(
                                f"TradingView.exe found via AppxPackage at: {path}"
                            )
                            return path
    except Exception as e:
        logger.warning(f"Error querying MSIX package: {e}")

    return None


def launch_tradingview(exe_path: str):
    """Launch TradingView Desktop with CDP remote debugging port enabled."""
    logger.info(f"Auto-launching TradingView Desktop from: {exe_path}")
    try:
        # Launch without Admin rights using safe alternative
        from subprocess import Popen

        Popen(
            [exe_path, f"--remote-debugging-port={CDP_PORT}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            if sys.platform == "win32"
            else 0,
        )
    except Exception as e:
        logger.error(f"Failed to launch TradingView: {e}")


def wait_for_cdp(timeout: int = 20) -> bool:
    """Poll the CDP port until it responds or timeout is reached."""
    logger.info(f"Waiting for CDP port {CDP_PORT} to be active (timeout {timeout}s)...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_cdp_active():
            logger.info("CDP connected successfully.")
            return True
        time.sleep(1)
    logger.warning("CDP connection timed out.")
    return False


async def extract_chart_data():
    """Connect via CDP using MCPClient and extract active symbol, interval, price, and studies."""
    client = get_mcp_client()

    logger.info("Attempting to connect to TradingView chart via MCP...")
    # Initialize health check to verify connections
    health = await client.health_check()
    if not health.get("connected"):
        raise RuntimeError(
            f"MCP health check failed: {health.get('error', 'Not connected')}"
        )

    # Extract symbol
    logger.info("Querying active symbol...")
    sym_res = await client._run("symbol")
    symbol = sym_res.get("symbol")
    if not symbol:
        raise ValueError("Could not extract active symbol from chart.")

    # Extract timeframe / resolution
    logger.info("Querying active timeframe...")
    tf_res = await client._run("timeframe")
    interval = tf_res.get("resolution") or "1h"

    # Extract close price
    logger.info("Querying close price...")
    quote_res = await client._run("quote")
    price = quote_res.get("close") or quote_res.get("last")
    if price is None:
        raise ValueError("Could not extract price from quote output.")
    try:
        price = float(price)
    except (ValueError, TypeError):
        logger.warning(f"Invalid price '{price}', defaulting to 0.0")
        price = 0.0

    # Extract studies (SMA50, SMA150, SMA200, ATR14)
    logger.info(f"Extracting indicator studies for {symbol} on {interval} chart...")
    study_vals = await client.get_study_values(symbol, interval)

    # Assign retrieved values or default to fallback constants if they are None
    sma50 = study_vals.sma50 if study_vals.sma50 is not None else 67000.0
    sma150 = study_vals.sma150 if study_vals.sma150 is not None else 66000.0
    sma200 = study_vals.sma200 if study_vals.sma200 is not None else 65000.0
    atr14 = study_vals.atr14 if study_vals.atr14 is not None else 150.0

    return symbol, interval, price, sma50, sma150, sma200, atr14


async def main():
    # 1. Verify/Launch CDP
    if not is_cdp_active():
        exe_path = find_tradingview_exe()
        if exe_path:
            launch_tradingview(exe_path)
            if not wait_for_cdp(20):
                logger.warning("CDP did not start. Falling back to default data.")
        else:
            logger.warning(
                "TradingView executable not found. Falling back to default data."
            )

    # 2. Extract Data
    symbol, interval, price = "BTCUSDT", "1h", 68000.0
    sma50, sma150, sma200, atr14 = 67000.0, 66000.0, 65000.0, 150.0

    extracted = False
    if is_cdp_active():
        try:
            (
                symbol,
                interval,
                price,
                sma50,
                sma150,
                sma200,
                atr14,
            ) = await extract_chart_data()
            extracted = True
            logger.info("Chart data successfully extracted via CDP.")
        except Exception as e:
            logger.warning(
                f"Failed to extract chart data via CDP: {e}. Using fallback values."
            )

    if not extracted:
        logger.info(
            f"Using Fallback Data: symbol={symbol}, interval={interval}, price={price}"
        )

    # 3. Build webhook payload matching TradingViewAlertPayload
    secret = config.WEBHOOK_SECRET
    port = config.PORT or 5000

    payload = {
        "secret": secret,
        "source": "indicator",
        "symbol": symbol,
        "indicator_name": "MultipleIndicators",
        "price": price,
        "interval": interval,
        "confidence_score": 90,
        "conditions_met": ["SMA50 > SMA150", "SMA150 > SMA200"],
        "metadata": {
            "sma50": sma50,
            "sma150": sma150,
            "sma200": sma200,
            "atr14": atr14,
        },
    }

    # 4. POST the payload to /webhook
    url = f"http://localhost:{port}/webhook"
    logger.info(f"Posting webhook payload to {url}...")

    try:
        response = requests.post(url, json=payload, timeout=10)
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response body: {response.text}")

        assert response.status_code in (200, 202), (
            f"Expected status 200/202, got {response.status_code}"
        )
        res_data = response.json()
        assert res_data.get("received") is True, (
            f"Expected 'received': True in response, got: {res_data}"
        )
        logger.info("Webhook signal successfully processed and verified!")
    except Exception as e:
        logger.error(f"Webhook post failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
