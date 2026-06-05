import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import config
from brief import generate_morning_brief
from analysis import ScanResult, TrendTemplateResult, VCPResult
from capture_client import CaptureResult


@pytest.mark.asyncio
async def test_morning_brief_fallback_to_mplfinance():
    # 1. Setup mock scan results
    mock_scan_result = ScanResult(
        symbol="BTCUSDT",
        price=65000.0,
        change_pct=1.5,
        trend_template=TrendTemplateResult(
            score=8, criteria={}, stage="Stage 2 ⭐", summary="Score 8/8"
        ),
        vcp=VCPResult(
            detected=True,
            volume_ratio=0.3,
            range_ratio=0.4,
            pivot_level=65500.0,
            vol_breakout=False,
            note="VCP confirmed",
        ),
        volume=1000.0,
        volume_avg=3000.0,
        exchange="binance",
    )

    # 2. Patch dependencies
    with (
        patch("brief.get_watchlist", return_value=["BTCUSDT"]) as mock_watchlist,
        patch("brief.get_mcp_client") as mock_get_mcp,
        patch("brief.scan_symbols", new_callable=AsyncMock) as mock_scan_symbols,
        patch("brief.query_knowledge", return_value=[]) as mock_query,
        patch(
            "brief.generate_trading_advice",
            new_callable=AsyncMock,
            return_value="Mock advice",
        ) as mock_advice,
        patch("brief.send_telegram_photo") as mock_send_photo,
        patch("brief.send_telegram_message") as mock_send_msg,
        patch("brief.database.insert_brief", new_callable=AsyncMock) as mock_insert_db,
    ):
        # Mock MCP client as disconnected
        mock_mcp = MagicMock()
        mock_mcp.health_check = AsyncMock(return_value={"connected": False})
        mock_get_mcp.return_value = mock_mcp

        # Mock scan_symbols
        mock_scan_symbols.return_value = [mock_scan_result]

        # Patch PythonCaptureClient to return a successful local render
        mock_capture_res = CaptureResult(
            success=True,
            file_path="mock_screenshots/brief_BTCUSDT.png",
            method="mplfinance",
        )

        with (
            patch(
                "capture_client.PythonCaptureClient.capture_screenshot",
                new_callable=AsyncMock,
                return_value=mock_capture_res,
            ) as mock_local_capture,
            patch("pathlib.Path.exists", return_value=True),
        ):
            # Temporarily force MCP enabled
            original_mcp_enabled = config.MCP_ENABLED
            config.MCP_ENABLED = True

            try:
                # 3. Trigger brief generation
                brief = await generate_morning_brief()

                # 4. Assertions
                assert brief is not None
                assert brief["success"] is True
                assert Path(brief["screenshot"]) == Path(
                    "mock_screenshots/brief_BTCUSDT.png"
                )

                # Verify that local capture_screenshot was called with method='mplfinance'
                mock_local_capture.assert_called_once()
                call_kwargs = mock_local_capture.call_args[1]
                assert call_kwargs["symbol"] == "BTCUSDT"
                assert call_kwargs["method"] == "mplfinance"
                assert len(call_kwargs["drawings"]) == 1
                assert call_kwargs["drawings"][0]["price"] == 65500.0
                assert call_kwargs["strategy_table"]["title"] == "Minervini Specs"

                # Verify telegram methods are called
                mock_send_photo.assert_called_once()
            finally:
                config.MCP_ENABLED = original_mcp_enabled
