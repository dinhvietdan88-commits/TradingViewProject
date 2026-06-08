"""
Unit tests targeting specifically uncovered code branches to push TradingViewProject test coverage >= 80%.
"""

import io
import os
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
import notifier
import rag
from utils.chart_generator_lw import generate_chart_lw


# ─────────────────────────────────────────────────────────────────────────────
# 1. Tests for notifier.py
# ─────────────────────────────────────────────────────────────────────────────


def test_sanitize_empty_inputs():
    """Test notifier.sanitize_for_telegram_html with None and empty string."""
    assert notifier.sanitize_for_telegram_html(None) == ""
    assert notifier.sanitize_for_telegram_html("") == ""


def test_sanitize_truncation():
    """Test notifier.sanitize_for_telegram_html inputs that exceed max length limits."""
    long_input = "A" * (notifier._MAX_TELEGRAM_MSG_LEN + 100)
    sanitized = notifier.sanitize_for_telegram_html(long_input)
    assert len(sanitized) == notifier._MAX_TELEGRAM_MSG_LEN
    assert sanitized.startswith("A")


@pytest.mark.asyncio
async def test_send_telegram_alert_http_failures():
    """Test send_telegram_alert with HTTP failure status and exceptions."""
    orig_token = config.TELEGRAM_BOT_TOKEN
    orig_chat_ids = config.TELEGRAM_CHAT_IDS
    try:
        config.TELEGRAM_BOT_TOKEN = "fake_bot_token"  # noqa: S105
        config.TELEGRAM_CHAT_IDS = ["123456"]

        # Mock aiohttp ClientSession post returning non-200 status
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session_inst = MagicMock()
        mock_session_inst.post = MagicMock(return_value=mock_context)
        mock_session_inst.__aenter__ = AsyncMock(return_value=mock_session_inst)
        mock_session_inst.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_inst):
            await notifier.send_telegram_alert("Hello world")

        # Mock aiohttp ClientSession post raising Exception
        mock_context_fail = MagicMock()
        mock_context_fail.__aenter__ = AsyncMock(
            side_effect=Exception("Network timeout")
        )
        mock_context_fail.__aexit__ = AsyncMock(return_value=None)

        mock_session_inst_fail = MagicMock()
        mock_session_inst_fail.post = MagicMock(return_value=mock_context_fail)
        mock_session_inst_fail.__aenter__ = AsyncMock(
            return_value=mock_session_inst_fail
        )
        mock_session_inst_fail.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_inst_fail):
            await notifier.send_telegram_alert("Hello world")

    finally:
        config.TELEGRAM_BOT_TOKEN = orig_token
        config.TELEGRAM_CHAT_IDS = orig_chat_ids


@pytest.mark.asyncio
async def test_edit_telegram_message_variants():
    """Test edit_telegram_message with running bot daemon, direct post, and exceptions."""
    orig_token = config.TELEGRAM_BOT_TOKEN
    try:
        config.TELEGRAM_BOT_TOKEN = "fake_bot_token"  # noqa: S105

        # 1. Bot sender is available and successfully edits
        mock_sender = AsyncMock()
        mock_sender.edit_message.return_value = True
        with patch("telegram_bot.get_sender", return_value=mock_sender):
            res = await notifier.edit_telegram_message(12345, 67890, "New Text")
            assert res is True
            mock_sender.edit_message.assert_called_once_with(
                chat_id=12345, message_id=67890, text="New Text"
            )

        # 2. Direct post fallback returning 200
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value="OK")

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session_inst = MagicMock()
        mock_session_inst.post = MagicMock(return_value=mock_context)
        mock_session_inst.__aenter__ = AsyncMock(return_value=mock_session_inst)
        mock_session_inst.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("telegram_bot.get_sender", return_value=None),
            patch("aiohttp.ClientSession", return_value=mock_session_inst),
        ):
            res = await notifier.edit_telegram_message(12345, 67890, "New Text")
            assert res is True

        # 3. Direct post fallback returning non-200
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad Request")
        with (
            patch("telegram_bot.get_sender", return_value=None),
            patch("aiohttp.ClientSession", return_value=mock_session_inst),
        ):
            res = await notifier.edit_telegram_message(12345, 67890, "New Text")
            assert res is False

        # 4. Direct post raising exception
        mock_context_fail = MagicMock()
        mock_context_fail.__aenter__ = AsyncMock(
            side_effect=Exception("Connection closed")
        )
        mock_context_fail.__aexit__ = AsyncMock(return_value=None)

        mock_session_inst_fail = MagicMock()
        mock_session_inst_fail.post = MagicMock(return_value=mock_context_fail)
        mock_session_inst_fail.__aenter__ = AsyncMock(
            return_value=mock_session_inst_fail
        )
        mock_session_inst_fail.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("telegram_bot.get_sender", return_value=None),
            patch("aiohttp.ClientSession", return_value=mock_session_inst_fail),
        ):
            res = await notifier.edit_telegram_message(12345, 67890, "New Text")
            assert res is False

    finally:
        config.TELEGRAM_BOT_TOKEN = orig_token


@pytest.mark.asyncio
async def test_send_discord_alert_failures():
    """Test send_discord_alert exception logic path."""
    orig_url = config.DISCORD_WEBHOOK_URL
    try:
        config.DISCORD_WEBHOOK_URL = "http://fake-discord.webhook"

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(
            side_effect=Exception("Discord webhook timeout")
        )
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session_inst = MagicMock()
        mock_session_inst.post = MagicMock(return_value=mock_context)
        mock_session_inst.__aenter__ = AsyncMock(return_value=mock_session_inst)
        mock_session_inst.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_inst):
            await notifier.send_discord_alert("Testing Discord alert path")

    finally:
        config.DISCORD_WEBHOOK_URL = orig_url


def test_send_telegram_message_loop_states():
    """Test send_telegram_message synchronous wrapper under different event loop states."""
    # Mock send_telegram_alert so we don't do real requests
    with patch("notifier.send_telegram_alert", new_callable=AsyncMock):
        # Case A: Loop is running
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True

        mock_future = MagicMock()
        mock_future.result.return_value = None

        with (
            patch("asyncio.get_running_loop", return_value=mock_loop),
            patch(
                "asyncio.run_coroutine_threadsafe", return_value=mock_future
            ) as mock_run_safe,
        ):
            notifier.send_telegram_message("Test loop running")
            mock_run_safe.assert_called_once()
            mock_future.result.assert_called_once_with(timeout=30)

        # Case B: Loop is not running
        with (
            patch(
                "asyncio.get_running_loop", side_effect=RuntimeError("No event loop")
            ),
            patch("asyncio.run") as mock_asyncio_run,
        ):
            notifier.send_telegram_message("Test loop not running")
            mock_asyncio_run.assert_called_once()


def test_prepare_telegram_photo():
    """Test prepare_telegram_photo handling file exceptions and formats."""
    # 1. Non-existent path returns None
    res = notifier.prepare_telegram_photo("nonexistent_path_xyz.png")
    assert res is None

    # 2. Magic bytes WebP check and conversion failure path (PIL import failure or other)
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as f:
        # Write dummy data that mimics WebP header
        f.write(b"RIFF\x00\x00\x00\x00WEBPvp8 ")
        temp_path = f.name

    try:
        # Mock PIL Image module raising import error or PIL error
        with patch(
            "PIL.Image.open", side_effect=ImportError("No PIL library installed")
        ):
            res_webp = notifier.prepare_telegram_photo(temp_path)
            # Should fallback to reading the raw bytes rather than crashing
            assert res_webp is not None
            assert res_webp.name == os.path.basename(temp_path)
            assert res_webp.read() == b"RIFF\x00\x00\x00\x00WEBPvp8 "
    finally:
        try:
            os.remove(temp_path)
        except Exception:  # noqa: S110
            pass


def test_send_telegram_photo_error_handling():
    """Test send_telegram_photo early exits, prepare fails, and post exception flows."""
    orig_token = config.TELEGRAM_BOT_TOKEN
    orig_chat_ids = config.TELEGRAM_CHAT_IDS
    orig_exists = pathlib.Path.exists

    def exists_side_effect(self, *args, **kwargs):
        if "dummy.png" in str(self):
            return True
        return orig_exists(self, *args, **kwargs)

    try:
        config.TELEGRAM_BOT_TOKEN = "fake_bot_token"  # noqa: S105
        config.TELEGRAM_CHAT_IDS = ["123456"]

        # Case 1: Photo path doesn't exist
        with patch("logging.Logger.warning") as mock_warn:
            notifier.send_telegram_photo("nonexistent.png")
            # Should have logged warning
            assert mock_warn.called

        # Case 2: prepare_telegram_photo returns None
        with (
            patch("pathlib.Path.exists", exists_side_effect),
            patch("notifier.prepare_telegram_photo", return_value=None),
            patch("logging.Logger.error") as mock_err,
        ):
            notifier.send_telegram_photo("dummy.png")
            assert mock_err.called

        # Case 3: Success run with post exception
        dummy_buf = io.BytesIO(b"dummy image bytes")
        dummy_buf.name = "dummy.png"
        with (
            patch("pathlib.Path.exists", exists_side_effect),
            patch("notifier.prepare_telegram_photo", return_value=dummy_buf),
            patch("requests.post", side_effect=Exception("Post connection failed")),
            patch("logging.Logger.error") as mock_err,
        ):
            notifier.send_telegram_photo("dummy.png")
            assert mock_err.called

    finally:
        config.TELEGRAM_BOT_TOKEN = orig_token
        config.TELEGRAM_CHAT_IDS = orig_chat_ids


# ─────────────────────────────────────────────────────────────────────────────
# 2. Tests for RAG/semantic querying
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_trading_advice_no_chunks():
    """Test generate_trading_advice early returns when rag_chunks is empty."""
    res = await rag.generate_trading_advice(
        "BTCUSDT", "buy", "100.0", {}, rag_chunks=[]
    )
    assert "Không tìm thấy kiến thức phù hợp" in res


def test_build_rag_query_conditions():
    """Test all conditions and logic paths in build_rag_query."""
    symbol = "ETHUSDT"

    # 1. Alert type: VCP
    q1 = rag.build_rag_query(symbol, "buy", {"alert_type": "VCP breakout"})
    assert "VCP Volatility Contraction Pattern" in q1

    # 2. Alert type: Trend Template
    q2 = rag.build_rag_query(symbol, "buy", {"alert_type": "trend template filter"})
    assert "Trend Template 8 tiêu chí Stage 2" in q2

    # 3. Volume spike (> 1.5x avg)
    q3 = rag.build_rag_query(
        symbol, "buy", {"alert_type": "generic", "volume": 1500, "volume_avg": 900}
    )
    assert "Volume nổ gấp đôi tăng bất thường" in q3

    # 4. Volume spike error path (invalid values)
    q4 = rag.build_rag_query(
        symbol, "buy", {"alert_type": "generic", "volume": "invalid", "volume_avg": 900}
    )
    assert "SEPA pivot breakout" in q4

    # 5. Action buy
    q5 = rag.build_rag_query(symbol, "buy", {"alert_type": "generic"})
    assert "SEPA pivot breakout" in q5

    # 6. Action sell
    q6 = rag.build_rag_query(symbol, "sell", {"alert_type": "generic"})
    assert "quản lý vị thế" in q6

    # 7. Unknown action fallback
    q7 = rag.build_rag_query(symbol, "hold", {"alert_type": "generic"})
    assert "SEPA Minervini" in q7


# ─────────────────────────────────────────────────────────────────────────────
# 3. Tests for chart_generator_lw.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_chart_lw_missing_template():
    """Test generate_chart_lw raises FileNotFoundError when static template is missing."""
    orig_exists = pathlib.Path.exists

    def exists_side_effect(self, *args, **kwargs):
        if "chart_template.html" in str(self):
            return False
        return orig_exists(self, *args, **kwargs)

    with (
        patch("pathlib.Path.exists", exists_side_effect),
        pytest.raises(FileNotFoundError) as ex,
    ):
        await generate_chart_lw("BTCUSDT", "1h", [{"time": 1234, "open": 100}])
    assert "Chart template not found" in str(ex.value)


@pytest.mark.asyncio
async def test_generate_chart_lw_no_save_path():
    """Test generate_chart_lw resolves config default screenshots directory."""
    mock_playwright = AsyncMock()
    mock_playwright.__aenter__.return_value = mock_playwright
    mock_browser = AsyncMock()
    mock_page = AsyncMock()

    mock_playwright.chromium = MagicMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_browser.new_page.return_value = mock_page
    mock_page.query_selector = AsyncMock(return_value=None)  # No rendering error
    mock_page.goto = AsyncMock()
    mock_page.evaluate = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_browser.close = AsyncMock()

    orig_screenshots_dir = config.SCREENSHOTS_DIR
    try:
        config.SCREENSHOTS_DIR = "temp_screenshots_unit_test"

        orig_exists = pathlib.Path.exists

        def exists_side_effect(self, *args, **kwargs):
            if "chart_template.html" in str(self):
                return True
            if "temp_screenshots_unit_test" in str(self):
                return False
            return orig_exists(self, *args, **kwargs)

        with (
            patch("pathlib.Path.exists", exists_side_effect),
            patch(
                "utils.chart_generator_lw.async_playwright",
                return_value=mock_playwright,
            ),
            patch("pathlib.Path.mkdir") as mock_mkdir,
        ):
            res_path = await generate_chart_lw(
                "BTCUSDT", "1h", [{"time": 1234, "open": 100}], save_path=None
            )
            assert "chart_lw_BTCUSDT_1h.png" in str(res_path)
            # Ensure screenshots directory was created
            mock_mkdir.assert_called()

    finally:
        config.SCREENSHOTS_DIR = orig_screenshots_dir
        # Clean up temporary dir if created
        try:
            import shutil

            shutil.rmtree("temp_screenshots_unit_test")
        except Exception:  # noqa: S110
            pass


@pytest.mark.asyncio
async def test_generate_chart_lw_rendering_error():
    """Test generate_chart_lw handles browser-side rendering errors correctly."""
    mock_playwright = AsyncMock()
    mock_playwright.__aenter__.return_value = mock_playwright
    mock_browser = AsyncMock()
    mock_page = AsyncMock()
    mock_element = AsyncMock()

    mock_playwright.chromium = MagicMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_browser.new_page.return_value = mock_page
    mock_page.query_selector = AsyncMock(return_value=mock_element)
    mock_element.get_attribute = AsyncMock(return_value="WebGL not supported")
    mock_page.goto = AsyncMock()
    mock_page.evaluate = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_browser.close = AsyncMock()

    orig_exists = pathlib.Path.exists

    def exists_side_effect(self, *args, **kwargs):
        if "chart_template.html" in str(self):
            return True
        return orig_exists(self, *args, **kwargs)

    # Mock Path.exists to return True for template
    with (
        patch("pathlib.Path.exists", exists_side_effect),
        patch(
            "utils.chart_generator_lw.async_playwright", return_value=mock_playwright
        ),
        pytest.raises(RuntimeError) as ex,
    ):
        await generate_chart_lw(
            "BTCUSDT", "1h", [{"time": 1234, "open": 100}], save_path="chart.png"
        )
    assert "Lightweight charts rendering error in browser: WebGL not supported" in str(
        ex.value
    )
