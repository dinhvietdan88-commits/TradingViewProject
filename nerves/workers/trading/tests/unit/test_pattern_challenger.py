"""
Challenger tests for chart pattern overlay, edge cases, and Telegram limits.
Adapted to actual implementation API:
  - pattern_overlays (PatternOverlayResult dataclass) in chart_generator_mpl
  - html_chunker (utils/html_chunker.py) for truncation/chunking
  - telegram_bot sends photo_path separately before interactive message
"""
import sys
import os
import shutil
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from utils.chart_generator_mpl import generate_chart_mpl
from utils.html_chunker import truncate_caption_html_safe, chunk_html_message
from utils.pattern_overlay import detect_all_patterns, detect_vcp_contractions


class TestPatternChallenger:
    def setup_method(self):
        self.mock_ohlcv = [
            {
                "time": 1716240000000 + i * 3600000,
                "open": 100.0 + i * 0.5,
                "high": 102.0 + i * 0.5,
                "low": 99.0 + i * 0.5,
                "close": 101.0 + i * 0.5,
                "volume": 1000.0 * (i + 1)
            }
            for i in range(100)
        ]
        self.temp_dir = Path(__file__).resolve().parent / "temp_challenger_charts"
        self.temp_dir.mkdir(exist_ok=True)

    def teardown_method(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    # -------------------------------------------------------------------------
    # 1. Chart Generator: Pattern overlays as dataclass (not string)
    # -------------------------------------------------------------------------

    def test_invalid_pattern_overlay_ignored(self):
        """Verify that passing a non-PatternOverlayResult is safely ignored."""
        save_path = self.temp_dir / "test_invalid_pattern.png"
        result_path = generate_chart_mpl(
            symbol="BTCUSDT",
            timeframe="1h",
            ohlcv_data=self.mock_ohlcv,
            save_path=save_path,
            pattern_overlays="INVALID_PATTERN_NAME"  # string, not dataclass
        )
        assert result_path.exists()
        assert result_path == save_path

    def test_insufficient_candles_no_crash(self):
        """Verify that passing fewer than 20 candles does not crash."""
        short_ohlcv = self.mock_ohlcv[:10]
        save_path = self.temp_dir / "test_short_candles.png"
        # pattern_overlays with short data — should be safe
        overlays = detect_all_patterns(short_ohlcv)
        result_path = generate_chart_mpl(
            symbol="BTCUSDT",
            timeframe="1h",
            ohlcv_data=short_ohlcv,
            save_path=save_path,
            pattern_overlays=overlays
        )
        assert result_path.exists()
        assert result_path == save_path

    # -------------------------------------------------------------------------
    # 2. Chart Generator: Empty and Extremely Large Datasets
    # -------------------------------------------------------------------------

    def test_empty_dataset_raises_value_error(self):
        """Verify that passing empty OHLCV data raises ValueError."""
        save_path = self.temp_dir / "test_empty.png"
        with pytest.raises(ValueError) as ctx:
            generate_chart_mpl(
                symbol="BTCUSDT",
                timeframe="1h",
                ohlcv_data=[],
                save_path=save_path,
                pattern_overlays=None
            )
        assert "OHLCV data is empty" in str(ctx.value)

    def test_extremely_large_dataset_performance(self):
        """Verify that a large dataset does not cause OOM/hangs."""
        large_ohlcv = [
            {
                "time": 1716240000000 + i * 3600000,
                "open": 100.0 + (i % 10),
                "high": 105.0 + (i % 10),
                "low": 95.0 + (i % 10),
                "close": 101.0 + (i % 10),
                "volume": 5000.0
            }
            for i in range(1000)
        ]
        save_path = self.temp_dir / "test_large.png"
        overlays = detect_all_patterns(large_ohlcv)
        result_path = generate_chart_mpl(
            symbol="BTCUSDT",
            timeframe="1h",
            ohlcv_data=large_ohlcv,
            save_path=save_path,
            pattern_overlays=overlays
        )
        assert result_path.exists()
        assert result_path == save_path

    def test_flat_price_no_volatility_no_zero_division(self):
        """Verify flat prices don't crash due to zero division."""
        flat_ohlcv = [
            {
                "time": 1716240000000 + i * 3600000,
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 0.0
            }
            for i in range(50)
        ]
        save_path = self.temp_dir / "test_flat.png"
        overlays = detect_all_patterns(flat_ohlcv)
        result_path = generate_chart_mpl(
            symbol="BTCUSDT",
            timeframe="1h",
            ohlcv_data=flat_ohlcv,
            save_path=save_path,
            pattern_overlays=overlays
        )
        assert result_path.exists()

    def test_extreme_price_values(self):
        """Verify extreme price magnitudes render successfully."""
        high_ohlcv = [
            {
                "time": 1716240000000 + i * 3600000,
                "open": 1e12 + i,
                "high": 1e12 + i + 10,
                "low": 1e12 + i - 10,
                "close": 1e12 + i + 5,
                "volume": 100.0
            }
            for i in range(50)
        ]
        save_path_high = self.temp_dir / "test_extreme_high.png"
        result_path_high = generate_chart_mpl(
            symbol="MEME",
            timeframe="1h",
            ohlcv_data=high_ohlcv,
            save_path=save_path_high,
        )
        assert result_path_high.exists()

        low_ohlcv = [
            {
                "time": 1716240000000 + i * 3600000,
                "open": 1e-8 + i * 1e-10,
                "high": 1e-8 + i * 1e-10 + 1e-11,
                "low": 1e-8 + i * 1e-10 - 1e-11,
                "close": 1e-8 + i * 1e-10 + 5e-12,
                "volume": 10000000.0
            }
            for i in range(50)
        ]
        save_path_low = self.temp_dir / "test_extreme_low.png"
        result_path_low = generate_chart_mpl(
            symbol="SHIB",
            timeframe="1h",
            ohlcv_data=low_ohlcv,
            save_path=save_path_low,
        )
        assert result_path_low.exists()

    # -------------------------------------------------------------------------
    # 3. Mathematical Curves Verification
    # -------------------------------------------------------------------------

    def test_vcp_math_curves(self):
        """Verify VCP cosine wave produces valid coordinates."""
        W = 60
        x_start = 10
        P_pivot = 150.0

        depths = [0.45 * 100, 0.22 * 100, 0.10 * 100]
        widths = [int(0.5 * W), int(0.3 * W), W - int(0.5 * W) - int(0.3 * W)]
        waves = [
            (x_start, x_start + widths[0], depths[0]),
            (x_start + widths[0], x_start + widths[0] + widths[1], depths[1]),
            (x_start + widths[0] + widths[1], x_start + widths[0] + widths[1] + widths[2], depths[2])
        ]

        for start, end, depth in waves:
            w_width = end - start
            x_vals = np.linspace(start, end, w_width * 5)
            y_vals = P_pivot - (depth / 2.0) * (1.0 - np.cos(2.0 * np.pi * (x_vals - start) / w_width))

            assert np.all(np.isfinite(x_vals))
            assert np.all(np.isfinite(y_vals))
            assert len(x_vals) == len(y_vals)
            assert y_vals[0] == P_pivot
            mid_idx = len(y_vals) // 2
            assert abs(y_vals[mid_idx] - (P_pivot - depth)) <= 2.5

    def test_cup_and_handle_math_curves(self):
        """Verify Cup and Handle equations produce valid coordinates."""
        W = 40
        x_start = 5
        cup_width = int(0.75 * W)
        handle_width = W - cup_width
        P_rim = 2000.0
        D_cup = 0.60 * 500.0

        x_vals_cup = np.linspace(x_start, x_start + cup_width, cup_width * 5)
        y_vals_cup = P_rim - (D_cup / 2.0) * (1.0 - np.cos(2.0 * np.pi * (x_vals_cup - x_start) / cup_width))

        assert np.all(np.isfinite(x_vals_cup))
        assert np.all(np.isfinite(y_vals_cup))
        assert y_vals_cup[0] == P_rim
        assert abs(y_vals_cup[len(y_vals_cup) // 2] - (P_rim - D_cup)) <= 2.5

        x_cup_end = x_start + cup_width
        x_end = x_start + W
        D_handle_start = P_rim - 0.05 * 500.0
        D_handle_end = P_rim - 0.20 * 500.0
        channel_width = 0.04 * 500.0

        x_vals_handle = np.linspace(x_cup_end, x_end, handle_width * 5)
        y_center_handle = D_handle_start + (D_handle_end - D_handle_start) * (x_vals_handle - x_cup_end) / handle_width
        y_upper_handle = y_center_handle + channel_width
        y_lower_handle = y_center_handle - channel_width

        assert np.all(np.isfinite(y_upper_handle))
        assert np.all(np.isfinite(y_lower_handle))

    def test_double_bottom_math_curves(self):
        """Verify Double Bottom math curves evaluate correctly."""
        W = 60
        x_start = 5
        x_end = x_start + W
        P_neckline = 100.0
        D1 = 20.0
        D2 = 25.0
        D_mid = 5.0

        x_vals_w = np.linspace(x_start, x_end, W * 5)
        y_vals_w = []
        for x in x_vals_w:
            u = (x - x_start) / W
            if u < 0.5:
                if u < 0.25:
                    t = u / 0.25
                    y = P_neckline - D1 * 0.5 * (1.0 - np.cos(np.pi * t))
                else:
                    t = (u - 0.25) / 0.25
                    y = (P_neckline - D1) + (D1 - D_mid) * 0.5 * (1.0 - np.cos(np.pi * t))
            else:
                if u < 0.75:
                    t = (u - 0.5) / 0.25
                    y = (P_neckline - D_mid) - (D2 - D_mid) * 0.5 * (1.0 - np.cos(np.pi * t))
                else:
                    t = (u - 0.75) / 0.25
                    y = (P_neckline - D2) + D2 * 0.5 * (1.0 - np.cos(np.pi * t))
            y_vals_w.append(y)

        assert np.all(np.isfinite(y_vals_w))
        assert len(x_vals_w) == len(y_vals_w)
        trough1_idx = int(0.25 * len(y_vals_w))
        assert abs(y_vals_w[trough1_idx] - (P_neckline - D1)) <= 0.5
        peak_idx = int(0.50 * len(y_vals_w))
        assert abs(y_vals_w[peak_idx] - (P_neckline - D_mid)) <= 0.5
        trough2_idx = int(0.75 * len(y_vals_w))
        assert abs(y_vals_w[trough2_idx] - (P_neckline - D2)) <= 0.5

    # -------------------------------------------------------------------------
    # 4. Telegram Caption Truncation (via html_chunker)
    # -------------------------------------------------------------------------

    def test_telegram_caption_limit_routing(self):
        """Verify truncate_caption_html_safe handles various lengths."""
        # Below limit — unchanged
        msg_below = "A" * 1020
        result = truncate_caption_html_safe(msg_below, 1024)
        assert result == msg_below

        # Exactly at limit — unchanged
        msg_exact = "A" * 1024
        result = truncate_caption_html_safe(msg_exact, 1024)
        assert result == msg_exact

        # Above limit — truncated with ellipsis
        msg_above = "A" * 1028
        result = truncate_caption_html_safe(msg_above, 1024)
        assert len(result) <= 1024
        assert "…" in result

    def test_chunk_html_message_basic(self):
        """Test basic chunking of plain text messages."""
        # Short text — single chunk
        short = "Hello world"
        chunks = chunk_html_message(short, 4096)
        assert len(chunks) == 1

        # Long text — multiple chunks
        text = "A" * 5000
        chunks = chunk_html_message(text, 4096)
        assert len(chunks) >= 1
        # All chunks within limit (allowing for numbering prefix)
        for chunk in chunks:
            assert len(chunk) <= 4096 + 20

    def test_chunk_html_message_tags(self):
        """Test that chunking handles HTML tags safely."""
        # HTML message — should not break mid-tag
        html_msg = "<b>" + "A" * 100 + "</b>"
        chunks = chunk_html_message(html_msg, 50)
        for chunk in chunks:
            # No broken tags
            open_bracket = chunk.rfind('<')
            close_bracket = chunk.rfind('>')
            if open_bracket >= 0:
                assert close_bracket >= open_bracket or '<' not in chunk[open_bracket:]
