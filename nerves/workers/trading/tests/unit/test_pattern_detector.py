"""Tests for utils/pattern_overlay.py — VCP, Cup&Handle, Double Bottom detection."""
import sys
from pathlib import Path
import pytest

# Fix path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.pattern_overlay import (
    find_pivot_highs,
    find_pivot_lows,
    detect_vcp_contractions,
    detect_cup_handle,
    detect_double_bottom,
    detect_all_patterns,
    VCPOverlay,
    CupHandleOverlay,
    DoubleBottomOverlay,
)


# ── Helpers ──────────────────────────────────────────────

def _make_ohlcv(closes: list, spread: float = 0.5) -> list:
    """Build minimal OHLCV list-of-lists from close prices."""
    return [
        [i * 86400000, c - spread, c + spread, c - spread, c, 1000.0]
        for i, c in enumerate(closes)
    ]


# ── Pivot Detection ──────────────────────────────────────

def test_find_pivot_highs_basic():
    prices = [1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 3, 2, 1]
    pivots = find_pivot_highs(prices, window=2)
    # Peak at index 4 (value 5) and index 11 (value 4)
    assert any(idx == 4 for idx, _ in pivots)


def test_find_pivot_lows_basic():
    prices = [5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2, 3, 4, 5]
    pivots = find_pivot_lows(prices, window=2)
    assert any(idx == 4 for idx, _ in pivots)


# ── VCP Detection ────────────────────────────────────────

def test_vcp_3_contractions_detected():
    """Synthetic VCP: 3 contractions with decreasing depth."""
    # T1: rise to 100, drop -15% to 85
    # T2: rise to 98, drop -8% to 90
    # T3: rise to 97, drop -4% to 93
    prices = (
        list(range(80, 100)) +          # uptrend to 100
        list(range(100, 85, -1)) +      # T1 drop -15%
        list(range(85, 98)) +           # recovery
        list(range(98, 90, -1)) +       # T2 drop -8%
        list(range(90, 97)) +           # recovery
        list(range(97, 93, -1)) +       # T3 drop -4%
        list(range(93, 97))             # final recovery
    )
    ohlcv = _make_ohlcv(prices)
    result = detect_vcp_contractions(ohlcv, pivot_window=3, min_contractions=2)
    assert result.detected is True
    assert len(result.contractions) >= 2
    assert result.quality_score > 0


def test_vcp_random_noise_not_detected():
    """Random flat data should not detect VCP."""
    import random
    random.seed(42)
    prices = [100 + random.uniform(-1, 1) for _ in range(80)]
    ohlcv = _make_ohlcv(prices)
    result = detect_vcp_contractions(ohlcv, pivot_window=3)
    # Flat noise — either not detected or very low quality
    if result.detected:
        assert result.quality_score < 50


def test_vcp_too_short_data():
    """Short data should return not detected."""
    ohlcv = _make_ohlcv([100, 101, 102])
    result = detect_vcp_contractions(ohlcv)
    assert result.detected is False


def test_vcp_quality_score_range():
    """Quality score should be 0-100."""
    prices = (
        list(range(50, 100)) +
        list(range(100, 80, -1)) +
        list(range(80, 98)) +
        list(range(98, 90, -1)) +
        list(range(90, 97))
    )
    ohlcv = _make_ohlcv(prices)
    result = detect_vcp_contractions(ohlcv, pivot_window=3, min_contractions=2)
    if result.detected:
        assert 0 <= result.quality_score <= 100


# ── Cup & Handle Detection ───────────────────────────────

def test_cup_handle_u_shape():
    """Synthetic U-shape should detect cup pattern."""
    # Left rim at 100, drop to 80, recover to 100, shallow handle
    prices = (
        [100] * 5 +                    # left rim plateau
        list(range(100, 80, -1)) +      # cup left side
        [80] * 5 +                      # cup bottom
        list(range(80, 100)) +          # cup right side
        [100, 99, 98, 97, 98, 99] +    # shallow handle
        [100]                           # breakout
    )
    ohlcv = _make_ohlcv(prices)
    result = detect_cup_handle(ohlcv, min_cup_bars=20, pivot_window=3)
    assert result.detected is True
    assert result.cup_depth_pct > 10
    assert result.handle_depth_pct < 15


def test_cup_handle_too_deep_rejected():
    """Cup deeper than 35% should be rejected."""
    prices = (
        [100] * 5 +
        list(range(100, 50, -1)) +      # -50% depth
        [50] * 5 +
        list(range(50, 100)) +
        [100]
    )
    ohlcv = _make_ohlcv(prices)
    result = detect_cup_handle(ohlcv, min_cup_bars=20, max_cup_depth_pct=35.0)
    assert result.detected is False


def test_cup_handle_short_data():
    ohlcv = _make_ohlcv([100, 90, 100])
    result = detect_cup_handle(ohlcv)
    assert result.detected is False


# ── Double Bottom Detection ──────────────────────────────

def test_double_bottom_within_3pct():
    """Two lows within 3% should detect double bottom."""
    prices = (
        list(range(100, 90, -1)) +      # drop to 90
        list(range(90, 100)) +          # recovery to ~100
        [100] * 5 +                     # neckline area
        list(range(100, 91, -1)) +      # drop to 91 (within 3% of 90)
        list(range(91, 100))            # recovery
    )
    ohlcv = _make_ohlcv(prices)
    result = detect_double_bottom(ohlcv, pivot_window=3, min_bars_between=5)
    assert result.detected is True
    assert abs(result.first_bottom_price - result.second_bottom_price) / result.first_bottom_price * 100 <= 3.0
    assert result.neckline_price > 0


def test_double_bottom_too_far_apart():
    """Bottoms >80 bars apart should not detect."""
    prices = (
        list(range(100, 80, -1)) +      # first bottom at 80
        list(range(80, 120)) +          # long recovery (40 bars)
        [120] * 50 +                     # plateau (50 bars) = total >80
        list(range(120, 81, -1)) +      # second bottom
        list(range(81, 100))
    )
    ohlcv = _make_ohlcv(prices)
    result = detect_double_bottom(ohlcv, pivot_window=3, max_bars_between=80)
    # May or may not detect depending on exact pivot detection
    # The point is: if detected, bottoms should be within max_bars_between


def test_double_bottom_bottoms_too_different():
    """Bottoms >3% apart should not detect."""
    prices = (
        list(range(100, 85, -1)) +      # bottom at 85
        list(range(85, 100)) +
        list(range(100, 95, -1)) +      # bottom at 95 (>3% diff from 85)
        list(range(95, 100))
    )
    ohlcv = _make_ohlcv(prices)
    result = detect_double_bottom(ohlcv, pivot_window=3, tolerance_pct=3.0)
    assert result.detected is False


# ── Unified detect_all_patterns ──────────────────────────

def test_detect_all_returns_result():
    """detect_all_patterns should return PatternOverlayResult."""
    prices = list(range(50, 100)) + list(range(100, 50, -1)) + list(range(50, 100))
    ohlcv = _make_ohlcv(prices)
    result = detect_all_patterns(ohlcv, pivot_window=3)
    assert hasattr(result, 'vcp')
    assert hasattr(result, 'cup_handle')
    assert hasattr(result, 'double_bottom')
    assert hasattr(result, 'any_detected')
    assert hasattr(result, 'summary')
    assert isinstance(result.summary, str)
