import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import json
from playwright.async_api import async_playwright

log = logging.getLogger(__name__)


async def generate_chart_lw(
    symbol: str,
    timeframe: str,
    ohlcv_data: Union[List[List[Any]], List[Dict[str, Any]]],
    drawings: Optional[List[Dict[str, Any]]] = None,
    strategy_table: Optional[Dict[str, Any]] = None,
    save_path: Optional[Union[str, Path]] = None,
    parent_timeframe: Optional[str] = None,
    parent_ohlcv: Optional[Union[List[List[Any]], List[Dict[str, Any]]]] = None,
    inset_position: str = "bottom-right",
) -> Path:
    """
    Renders a TradingView lightweight candlestick chart using Playwright headless browser.

    Parameters:
        symbol: Ticker symbol (e.g., BTCUSDT)
        timeframe: Chart interval (e.g., 1h, 15)
        ohlcv_data: OHLCV candles data.
                    Either list of dicts: [{"time": timestamp, "open": o, ...}]
                    Or list of lists: [[timestamp, open, high, low, close, volume], ...]
        drawings: Optional list of horizontal line drawings:
                  [{"price": 95100.5, "label": "Entry", "color": "#26a69a"}]
        strategy_table: Optional dict for a side/overlay table metrics:
                        {"title": "SEPA Setup", "rows": [("Trend", "Bullish"), ("ATR", "4.2")]}
        save_path: Optional file path to save the PNG image.
        parent_timeframe: Optional parent timeframe string
        parent_ohlcv: Optional parent OHLCV data
        inset_position: Position of inset chart ("bottom-right" or "top-left")

    Returns:
        Path object pointing to the generated PNG file.
    """
    if not ohlcv_data:
        raise ValueError("OHLCV data is empty")

    # Resolve the template HTML path
    current_dir = Path(__file__).resolve().parent
    template_path = current_dir.parent / "static" / "chart_template.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Chart template not found at {template_path}")

    file_url = template_path.absolute().as_uri()

    if not save_path:
        base_dir = Path(__file__).resolve().parent.parent
        screenshots_dir = base_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        save_path = screenshots_dir / f"chart_lw_{symbol}_{timeframe}.png"
    else:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

    chart_payload = {
        "symbol": symbol,
        "timeframe": timeframe,
        "ohlcv": ohlcv_data,
        "drawings": drawings or [],
        "strategy_table": strategy_table,
        "parent_timeframe": parent_timeframe,
        "parent_ohlcv": parent_ohlcv,
        "inset_position": inset_position,
    }

    log.info(f"Launching Playwright to capture lightweight chart for {symbol}...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            # Set window size to match desirable image aspect ratio (1200x700)
            await page.set_viewport_size({"width": 1200, "height": 700})

            # Load template
            await page.goto(file_url)

            # Inject render command and wait for complete signal
            await page.evaluate(f"window.renderChart({json.dumps(chart_payload)})")

            # Wait for either #chart-loaded or #chart-error to appear in DOM (regardless of visibility)
            await page.wait_for_selector(
                "#chart-loaded, #chart-error", state="attached", timeout=5000
            )

            error_el = await page.query_selector("#chart-error")
            if error_el:
                err_msg = await error_el.get_attribute("data-error")
                raise RuntimeError(
                    f"Lightweight charts rendering error in browser: {err_msg}"
                )

            # Capture the screenshot of the page
            await page.screenshot(path=str(save_path), type="png")
            log.info(
                f"Successfully generated Playwright lightweight-chart screenshot at {save_path}"
            )
        finally:
            await browser.close()

    return save_path
