"""
P6 — MCP Client
Wrapper gọi TradingView MCP CLI (tradingview-mcp) qua subprocess.
TradingView Desktop phải đang chạy với --remote-debugging-port=9222
"""

import json
import asyncio
import base64
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import os

import config

logger = logging.getLogger(__name__)

# Path to MCP CLI
_MCP_DIR = Path(__file__).resolve().parent.parent.parent.parent / "tradingview-mcp"
_MCP_CLI = _MCP_DIR / "src" / "cli" / "index.js"


@dataclass
class QuoteData:
    symbol: str
    close: float
    open: float
    high: float
    low: float
    volume: float
    change_pct: float


@dataclass
class StudyValues:
    sma50: Optional[float] = None
    sma150: Optional[float] = None
    sma200: Optional[float] = None
    volume_avg20: Optional[float] = None
    atr14: Optional[float] = None
    rs_line: Optional[float] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None


class MCPClient:
    """Async wrapper for TradingView MCP CLI."""

    def __init__(self):
        self.enabled = config.MCP_ENABLED
        self.cdp_port = config.MCP_CDP_PORT
        self.node_path = config.MCP_NODE_PATH or "node"
        self._connected: Optional[bool] = None
        self._sem = asyncio.Semaphore(5)
        self.lock = asyncio.Lock()

    async def _run(self, *args, timeout: int = 15) -> dict:
        """Run MCP CLI command and return parsed JSON."""
        if not _MCP_CLI.exists():
            raise RuntimeError(
                f"TradingView MCP not found at {_MCP_CLI}. "
                "Run: git submodule update --init tradingview-mcp && cd tradingview-mcp && npm install"
            )

        cmd = [self.node_path, str(_MCP_CLI)] + list(args) + ["--json"]

        async with self._sem:
            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(_MCP_DIR),
                    env={**os.environ, "TV_CDP_PORT": str(self.cdp_port)},
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )

                if proc.returncode != 0:
                    err = stderr.decode("utf-8", errors="replace").strip()
                    raise RuntimeError(f"MCP CLI error: {err}")

                raw = stdout.decode("utf-8", errors="replace").strip()
                # CLI emits pretty-printed JSON; try the full payload first,
                # then fall back to scanning for a single-line JSON value.
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    pass
                for line in raw.split("\n"):
                    line = line.strip()
                    if line.startswith("{") or line.startswith("["):
                        try:
                            return json.loads(line)
                        except json.JSONDecodeError:
                            continue
                raise RuntimeError(
                    f"MCP CLI returned non-JSON output: {raw[:200]}"
                ) from None

            except asyncio.TimeoutError as err:
                raise RuntimeError(f"MCP CLI timeout after {timeout}s") from err
            finally:
                if proc is not None and proc.returncode is None:
                    try:
                        proc.kill()
                        await proc.wait()
                    except Exception as kill_err:
                        logger.warning(f"Failed to kill subprocess: {kill_err}")

    # ── Health Check ──────────────────────────────────────────────────────────

    async def health_check(self) -> dict:
        """Check if TradingView Desktop is connected via CDP."""
        try:
            result = await self._run("status", timeout=5)
            self._connected = bool(
                result.get("cdp_connected") or result.get("connected")
            )
            return {
                "connected": self._connected,
                "cdp_port": self.cdp_port,
                "mcp_cli_found": _MCP_CLI.exists(),
                "detail": result,
            }
        except Exception as e:
            self._connected = False
            return {
                "connected": False,
                "cdp_port": self.cdp_port,
                "mcp_cli_found": _MCP_CLI.exists(),
                "error": str(e),
            }

    # ── Market Data ───────────────────────────────────────────────────────────

    async def _get_quote_unlocked(self, symbol: str) -> QuoteData:
        raw = await self._run("quote")
        return QuoteData(
            symbol=symbol,
            close=float(raw.get("close", 0)),
            open=float(raw.get("open", 0)),
            high=float(raw.get("high", 0)),
            low=float(raw.get("low", 0)),
            volume=float(raw.get("volume", 0)),
            change_pct=float(raw.get("change_percent", 0)),
        )

    async def get_quote(self, symbol: str) -> QuoteData:
        """Get current price + OHLCV for a symbol."""
        async with self.lock:
            await self._run("symbol", symbol)
            return await self._get_quote_unlocked(symbol)

    async def _get_ohlcv_summary_unlocked(self) -> dict:
        return await self._run("ohlcv", "--summary")

    async def get_ohlcv_summary(self, symbol: str, timeframe: str = "D") -> dict:
        """Get compact OHLCV stats (summary mode = 500B)."""
        async with self.lock:
            await self._run("symbol", symbol)
            await self._run("timeframe", timeframe)
            return await self._get_ohlcv_summary_unlocked()

    async def _get_study_values_unlocked(self) -> StudyValues:
        raw = await self._run("values")

        # Parse indicator values — key names depend on what's on chart
        values = raw if isinstance(raw, dict) else {}
        indicators = {}
        if values.get("indicators"):
            indicators = values["indicators"]
        elif "studies" in values:
            for study in values.get("studies", []):
                name = study.get("name", "")
                s_vals = study.get("values")
                if isinstance(s_vals, dict):
                    for k, v in s_vals.items():
                        indicators[f"{name} {k}"] = v
                        indicators[name] = v
                else:
                    indicators[name] = s_vals
        elif isinstance(values, dict):
            # If values is a flat dict already, just use it
            indicators = values
        else:
            indicators = {}

        def _find(keys: list) -> Optional[float]:
            for k in keys:
                for ikey, ival in indicators.items():
                    if k.lower() in ikey.lower():
                        try:
                            return float(ival)
                        except (TypeError, ValueError):
                            pass
            return None

        return StudyValues(
            sma50=_find(["sma 50", "sma50", "ma 50", "ma50", "average 50"]),
            sma150=_find(["sma 150", "sma150", "ma 150", "ma150", "average 150"]),
            sma200=_find(["sma 200", "sma200", "ma 200", "ma200", "average 200"]),
            volume_avg20=_find(["vol ma", "volume ma", "vol avg", "vma"]),
            atr14=_find(["atr", "average true range"]),
            high_52w=_find(["52w high", "52 week high", "yearly high"]),
            low_52w=_find(["52w low", "52 week low", "yearly low"]),
        )

    async def get_study_values(self, symbol: str, timeframe: str = "D") -> StudyValues:
        """
        Read indicator values from chart.
        Assumes Minervini indicators (SMA50/150/200, Volume MA) are added on chart.
        """
        async with self.lock:
            await self._run("symbol", symbol)
            await self._run("timeframe", timeframe)
            return await self._get_study_values_unlocked()

    # ── Screenshot ────────────────────────────────────────────────────────────

    @staticmethod
    def _crop_chart_area(img_path: Path, save_path: Path) -> bool:
        """
        Crop TradingView screenshot to chart-only area using Pillow.
        Removes: top toolbar (~60px), left sidebar (~60px),
                 right side panel (~280px), bottom bar (~30px).
        Returns True if crop succeeded.
        """
        try:
            from PIL import Image

            img = Image.open(img_path)
            w, h = img.size

            # TradingView layout crop offsets (% based for resolution-independence)
            top = int(h * 0.07)  # ~60px on 1080p — toolbar
            left = int(w * 0.045)  # ~60px — symbol sidebar
            right = int(w * 0.21)  # ~280px — right panel (watchlist/indicators)
            bottom = int(h * 0.04)  # ~30px — bottom bar

            box = (left, top, w - right, h - bottom)
            cropped = img.crop(box)

            # Upscale for sharpness (2x) if image is small
            if cropped.width < 800:
                cropped = cropped.resize(
                    (cropped.width * 2, cropped.height * 2), Image.LANCZOS
                )

            cropped.save(save_path, format="PNG", optimize=False)
            logger.info(
                f"Cropped chart: {img.size} -> {cropped.size} saved to {save_path.name}"
            )
            return True
        except ImportError:
            logger.warning(
                "Pillow not available — using full screenshot (install: pip install Pillow)"
            )
            return False
        except Exception as e:
            logger.warning(f"Crop failed: {e}")
            return False

    async def _resolve_active_chart_cdp(self) -> tuple[Optional[str], Optional[str]]:
        """
        Authentic CDP DOM parsing strategy to fetch the active chart's symbol and timeframe
        directly from the TradingView UI via Chrome DevTools Protocol Runtime.evaluate.
        """
        import aiohttp
        import json

        try:
            async with aiohttp.ClientSession() as session:
                # 1. Discover the TradingView page CDP websocket URL
                async with session.get(
                    f"http://127.0.0.1:{self.cdp_port}/json", timeout=3
                ) as resp:
                    pages = await resp.json()

                # Prioritize TradingView page, otherwise take first available
                page = next(
                    (
                        p
                        for p in pages
                        if p.get("type") == "page"
                        and "TradingView" in p.get("title", "")
                    ),
                    None,
                )
                if not page:
                    page = next((p for p in pages if p.get("type") == "page"), None)

                if not page or "webSocketDebuggerUrl" not in page:
                    return None, None

                ws_url = page["webSocketDebuggerUrl"]

                # 2. Connect via WebSocket to issue Runtime.evaluate
                async with session.ws_connect(ws_url, timeout=3) as ws:
                    js_expr = """
                    (() => {
                        try {
                            if (window.tvWidget) {
                                const chart = window.tvWidget.activeChart();
                                return { symbol: chart.symbol(), timeframe: chart.resolution() };
                            }
                        } catch (e) {}

                        try {
                            // DOM fallback parsing for TradingView Desktop
                            const symNode = document.querySelector('.js-widget-title, .title-3sKkivG, [data-name="legend-source-title"]');
                            const tfNode = document.querySelector('.js-button-text, .text-3sKkivG, [data-name="legend-source-interval"]');
                            let sym = symNode ? symNode.innerText.trim() : null;
                            let tf = tfNode ? tfNode.innerText.trim() : null;
                            return { symbol: sym, timeframe: tf };
                        } catch (e) {
                            return { symbol: null, timeframe: null };
                        }
                    })()
                    """

                    req_id = 1001
                    await ws.send_json(
                        {
                            "id": req_id,
                            "method": "Runtime.evaluate",
                            "params": {"expression": js_expr, "returnByValue": True},
                        }
                    )

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if data.get("id") == req_id:
                                res = (
                                    data.get("result", {})
                                    .get("result", {})
                                    .get("value", {})
                                )
                                return res.get("symbol"), res.get("timeframe")

        except Exception as e:
            logger.warning(f"CDP resolve active chart failed: {e}")

        return None, None

    async def capture_screenshot(
        self,
        symbol: str = "active",
        timeframe: str = "D",
        region: str = "chart",
        save_path: Optional[Path] = None,
        active_only: bool = False,
        crop: bool = True,
        drawings: Optional[list] = None,
        strategy_table: Optional[dict] = None,
    ) -> Optional[Path]:
        """
        Capture chart screenshot, then auto-crop to chart area.
        Uses fast local rendering (lightweight-charts/mplfinance) or daemon by default,
        and falls back to legacy subprocess mode on failure.
        """
        async with self.lock:
            # Resolve active symbol/timeframe dynamically via CDP
            target_symbol = symbol
            target_timeframe = timeframe
            if symbol == "active" or timeframe == "active":
                cdp_sym, cdp_tf = await self._resolve_active_chart_cdp()
                if not cdp_sym or not cdp_tf:
                    raise RuntimeError("Failed to resolve active chart via CDP")
                if symbol == "active":
                    target_symbol = cdp_sym
                if timeframe == "active":
                    target_timeframe = cdp_tf

            # Try fast local/daemon capture first
            try:
                from capture_client import get_capture_client

                client = get_capture_client()

                res = await client.capture_screenshot(
                    symbol=target_symbol,
                    timeframe=target_timeframe,
                    region=region,
                    crop=crop,
                    save_path=save_path,
                    drawings=drawings,
                    strategy_table=strategy_table,
                )
                if res.success and res.file_path:
                    return Path(res.file_path)
                logger.warning(
                    f"Fast capture client returned success=False ({res.error}), falling back to legacy subprocess..."
                )
            except Exception as e:
                logger.warning(
                    f"Fast capture client failed: {e}. Falling back to legacy subprocess..."
                )

            try:
                if not active_only:
                    if symbol != "active":
                        await self._run("symbol", symbol)
                    if timeframe != "active":
                        await self._run("timeframe", timeframe)

                # Try screenshot with region first, fall back without
                try:
                    raw = await self._run("screenshot", "-r", region, timeout=20)
                except Exception:
                    raw = await self._run("screenshot", timeout=20)

                if save_path is None:
                    import re

                    safe_symbol = re.sub(r"[^A-Za-z0-9_\-]", "", symbol)
                    save_path = (
                        Path(__file__).parent
                        / "screenshots"
                        / f"{safe_symbol}_{timeframe}.png"
                    )
                save_path.parent.mkdir(parents=True, exist_ok=True)

                raw_path: Optional[Path] = None

                # MCP returns base64 or file path
                if "base64" in raw:
                    img_data = base64.b64decode(raw["base64"])
                    raw_path = save_path.parent / f"_raw_{save_path.name}"
                    raw_path.write_bytes(img_data)
                elif "file_path" in raw:
                    raw_path = Path(raw["file_path"])
                elif "path" in raw:
                    raw_path = Path(raw["path"])

                if raw_path and raw_path.exists():
                    if crop and region == "chart":
                        # Auto-crop to remove TradingView UI chrome
                        cropped = self._crop_chart_area(raw_path, save_path)
                        if not cropped:
                            # Fallback: just copy raw as-is
                            import shutil

                            shutil.copy2(raw_path, save_path)
                    else:
                        import shutil

                        shutil.copy2(raw_path, save_path)

                    # Clean up temp raw file
                    if raw_path != save_path and raw_path.name.startswith("_raw_"):
                        raw_path.unlink(missing_ok=True)

                    return save_path

            except Exception as e:
                logger.warning(f"Screenshot failed for {symbol}: {e}")
            return None

    # ── Chart Control ─────────────────────────────────────────────────────────

    async def set_symbol(self, symbol: str, timeframe: str = "D") -> bool:
        """Switch chart to symbol + timeframe."""
        async with self.lock:
            try:
                await self._run("symbol", symbol)
                await self._run("timeframe", timeframe)
                return True
            except Exception as e:
                logger.warning(f"set_symbol failed: {e}")
                return False

    async def batch_run(self, symbols: list[str], timeframe: str = "D") -> list[dict]:
        """
        Run quote + study_values for each symbol sequentially.
        Returns list of raw data dicts.
        """
        results = []
        for sym in symbols:
            try:
                async with self.lock:
                    # Switch symbol & timeframe
                    await self._run("symbol", sym)
                    await self._run("timeframe", timeframe)

                    # Sleep slightly to let the chart load and indicators update
                    await asyncio.sleep(0.5)

                    # Fetch the data
                    quote = await self._get_quote_unlocked(sym)
                    studies = await self._get_study_values_unlocked()
                    ohlcv = await self._get_ohlcv_summary_unlocked()

                results.append(
                    {
                        "symbol": sym,
                        "quote": quote,
                        "studies": studies,
                        "ohlcv_summary": ohlcv,
                        "error": None,
                    }
                )
            except Exception as e:
                logger.warning(f"batch_run error for {sym}: {e}")
                results.append({"symbol": sym, "error": str(e)})

        return results


# Singleton
_mcp_client: Optional[MCPClient] = None


def get_mcp_client() -> MCPClient:
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client
