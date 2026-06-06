"""
Pattern Overlay — Pure Python pattern detection for chart rendering.

Detects 3 Minervini/O'Neil patterns from OHLCV data:
  1. VCP (Volatility Contraction Pattern) — multi-contraction waves
  2. Cup & Handle — U-shape base + shallow pullback
  3. Double Bottom — 2 troughs within 3% of each other

No external dependencies (no scipy). Uses simple N-bar pivot detection.
Output: dataclasses consumed by chart_generator_mpl for overlay rendering.
"""

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════


@dataclass
class VCPContraction:
    """Single contraction wave in a VCP pattern."""

    pivot_high_idx: int
    pivot_high_price: float
    trough_idx: int
    trough_price: float
    depth_pct: float  # (high - low) / high * 100
    duration_bars: int  # candles in this contraction


@dataclass
class VCPOverlay:
    """Complete VCP pattern with multiple contractions."""

    detected: bool
    contractions: list[VCPContraction] = field(default_factory=list)
    pivot_line_price: float = 0.0  # Breakout level (highest pivot)
    quality_score: float = 0.0  # 0-100


@dataclass
class CupHandleOverlay:
    """Cup & Handle pattern."""

    detected: bool
    cup_start_idx: int = 0
    cup_bottom_idx: int = 0
    cup_end_idx: int = 0
    handle_end_idx: int = 0
    cup_depth_pct: float = 0.0
    handle_depth_pct: float = 0.0
    neckline_price: float = 0.0


@dataclass
class DoubleBottomOverlay:
    """Double Bottom pattern."""

    detected: bool
    first_bottom_idx: int = 0
    first_bottom_price: float = 0.0
    second_bottom_idx: int = 0
    second_bottom_price: float = 0.0
    neckline_price: float = 0.0  # High between the two bottoms
    neckline_idx: int = 0


# ═══════════════════════════════════════════════════════════════
# PIVOT DETECTION — Pure Python (no scipy)
# ═══════════════════════════════════════════════════════════════


def find_pivot_highs(prices: list[float], window: int = 5) -> list[tuple[int, float]]:
    """Find local pivot highs using N-bar window comparison.

    A pivot high at index i means prices[i] >= all prices in
    [i-window, i+window] range.

    Returns list of (index, price) tuples, sorted by index.
    """
    pivots = []
    n = len(prices)
    for i in range(window, n - window):
        is_pivot = True
        for j in range(i - window, i + window + 1):
            if j != i and prices[j] > prices[i]:
                is_pivot = False
                break
        if is_pivot:
            pivots.append((i, prices[i]))
    return pivots


def find_pivot_lows(prices: list[float], window: int = 5) -> list[tuple[int, float]]:
    """Find local pivot lows using N-bar window comparison."""
    pivots = []
    n = len(prices)
    for i in range(window, n - window):
        is_pivot = True
        for j in range(i - window, i + window + 1):
            if j != i and prices[j] < prices[i]:
                is_pivot = False
                break
        if is_pivot:
            pivots.append((i, prices[i]))
    return pivots


def _extract_closes(ohlcv: list) -> list[float]:
    """Extract close prices from OHLCV data (list-of-lists or list-of-dicts)."""
    if not ohlcv:
        return []
    if isinstance(ohlcv[0], dict):
        return [float(c.get("close", c.get("Close", 0))) for c in ohlcv]
    return [float(c[4]) for c in ohlcv]


def _extract_highs(ohlcv: list) -> list[float]:
    """Extract high prices from OHLCV data."""
    if not ohlcv:
        return []
    if isinstance(ohlcv[0], dict):
        return [float(c.get("high", c.get("High", 0))) for c in ohlcv]
    return [float(c[2]) for c in ohlcv]


def _extract_lows(ohlcv: list) -> list[float]:
    """Extract low prices from OHLCV data."""
    if not ohlcv:
        return []
    if isinstance(ohlcv[0], dict):
        return [float(c.get("low", c.get("Low", 0))) for c in ohlcv]
    return [float(c[3]) for c in ohlcv]


def _extract_volumes(ohlcv: list) -> list[float]:
    """Extract volumes from OHLCV data."""
    if not ohlcv:
        return []
    if isinstance(ohlcv[0], dict):
        return [float(c.get("volume", c.get("Volume", 0))) for c in ohlcv]
    return [float(c[5]) if len(c) > 5 else 0.0 for c in ohlcv]


# ═══════════════════════════════════════════════════════════════
# VCP DETECTION — Multi-Contraction Waves
# ═══════════════════════════════════════════════════════════════


def detect_vcp_contractions(
    ohlcv: list,
    pivot_window: int = 5,
    min_contractions: int = 2,
    max_depth_first_pct: float = 30.0,
    min_depth_decrease_ratio: float = 0.3,
) -> VCPOverlay:
    """Detect VCP pattern with decreasing pivot highs and contracting depth.

    Algorithm:
    1. Find pivot highs in close prices
    2. Between consecutive pivot highs, find the trough (lowest low)
    3. Calculate depth_pct for each contraction
    4. Validate: depths must decrease by at least min_depth_decrease_ratio
    5. Volume should decrease across contractions (bonus quality)

    Parameters:
        ohlcv: OHLCV candle data
        pivot_window: N-bar window for pivot detection (default 5)
        min_contractions: Minimum contractions to qualify (default 2 = T1+T2)
        max_depth_first_pct: Max depth for T1 (reject if >30% = too volatile)
        min_depth_decrease_ratio: Each subsequent depth must be < previous * (1 - ratio)

    Returns:
        VCPOverlay with detected flag and contraction details
    """
    closes = _extract_closes(ohlcv)
    lows = _extract_lows(ohlcv)
    volumes = _extract_volumes(ohlcv)

    if len(closes) < 30:
        return VCPOverlay(detected=False)

    # Step 1: Find pivot highs
    pivot_highs = find_pivot_highs(closes, window=pivot_window)
    if len(pivot_highs) < min_contractions:
        return VCPOverlay(detected=False)

    # Step 2: Build contraction waves between consecutive pivot highs
    contractions: list[VCPContraction] = []
    for i in range(len(pivot_highs) - 1):
        ph_idx, ph_price = pivot_highs[i]
        next_ph_idx, _ = pivot_highs[i + 1]

        # Find trough (lowest low) between these two pivot highs
        if ph_idx >= next_ph_idx:
            continue
        segment_lows = lows[ph_idx : next_ph_idx + 1]
        if not segment_lows:
            continue

        trough_offset = segment_lows.index(min(segment_lows))
        trough_idx = ph_idx + trough_offset
        trough_price = segment_lows[trough_offset]

        if ph_price <= 0:
            continue

        depth_pct = ((ph_price - trough_price) / ph_price) * 100
        duration = next_ph_idx - ph_idx

        contractions.append(
            VCPContraction(
                pivot_high_idx=ph_idx,
                pivot_high_price=ph_price,
                trough_idx=trough_idx,
                trough_price=trough_price,
                depth_pct=round(depth_pct, 1),
                duration_bars=duration,
            )
        )

    if len(contractions) < min_contractions:
        return VCPOverlay(detected=False)

    # Step 3: Validate decreasing depth
    # Only consider the last N contractions (most recent pattern)
    recent = contractions[-min(len(contractions), 4) :]

    # First contraction shouldn't be too deep
    if recent[0].depth_pct > max_depth_first_pct:
        return VCPOverlay(detected=False)

    depths_decreasing = True
    for i in range(1, len(recent)):
        if recent[i].depth_pct >= recent[i - 1].depth_pct * (
            1 - min_depth_decrease_ratio
        ):
            depths_decreasing = False
            break

    if not depths_decreasing:
        return VCPOverlay(detected=False)

    # Step 4: Quality scoring
    # Depth decrease score (40%)
    depth_ratios = [
        recent[i].depth_pct / recent[i - 1].depth_pct
        for i in range(1, len(recent))
        if recent[i - 1].depth_pct > 0
    ]
    avg_depth_ratio = sum(depth_ratios) / len(depth_ratios) if depth_ratios else 1.0
    depth_score = max(0, min(100, (1 - avg_depth_ratio) * 100))

    # Volume decrease score (40%)
    vol_score = 50.0  # default neutral
    if volumes:
        vol_avgs = []
        for c in recent:
            seg_vols = volumes[c.pivot_high_idx : c.trough_idx + 1]
            if seg_vols:
                vol_avgs.append(sum(seg_vols) / len(seg_vols))
        if len(vol_avgs) >= 2:
            vol_decreasing = all(
                vol_avgs[i] < vol_avgs[i - 1] for i in range(1, len(vol_avgs))
            )
            vol_score = 80.0 if vol_decreasing else 30.0

    # Near 52w high score (20%)
    max_price = max(closes) if closes else 0
    current_price = closes[-1] if closes else 0
    near_high_score = (
        min(100, (current_price / max_price * 100)) if max_price > 0 else 0
    )

    quality = depth_score * 0.4 + vol_score * 0.4 + near_high_score * 0.2

    # Breakout pivot = highest pivot high in the recent set
    pivot_line = max(c.pivot_high_price for c in recent)

    return VCPOverlay(
        detected=True,
        contractions=recent,
        pivot_line_price=pivot_line,
        quality_score=round(quality, 1),
    )


# ═══════════════════════════════════════════════════════════════
# CUP & HANDLE DETECTION
# ═══════════════════════════════════════════════════════════════


def detect_cup_handle(
    ohlcv: list,
    min_cup_bars: int = 30,
    max_cup_bars: int = 150,
    max_cup_depth_pct: float = 35.0,
    max_handle_depth_pct: float = 15.0,
    pivot_window: int = 5,
) -> CupHandleOverlay:
    """Detect Cup & Handle pattern.

    Algorithm:
    1. Find significant pivot lows
    2. Look for U-shape: price drops, forms rounded bottom, recovers near prior high
    3. Handle: shallow pullback after cup right rim recovery
    """
    closes = _extract_closes(ohlcv)
    _extract_highs(ohlcv)
    _extract_lows(ohlcv)

    if len(closes) < min_cup_bars + 10:
        return CupHandleOverlay(detected=False)

    # Search in the most recent portion of data
    search_end = len(closes)
    search_start = max(0, search_end - max_cup_bars - 30)
    segment = closes[search_start:search_end]

    if len(segment) < min_cup_bars:
        return CupHandleOverlay(detected=False)

    # Find the highest point in the first third (cup left rim)
    first_third = len(segment) // 3
    if first_third < 5:
        return CupHandleOverlay(detected=False)

    left_rim_idx = max(range(first_third), key=lambda i: segment[i])
    left_rim_price = segment[left_rim_idx]

    # Find the lowest point in the middle (cup bottom)
    mid_start = first_third
    mid_end = 2 * len(segment) // 3
    if mid_end <= mid_start:
        return CupHandleOverlay(detected=False)

    cup_bottom_idx = mid_start + min(
        range(mid_end - mid_start), key=lambda i: segment[mid_start + i]
    )
    cup_bottom_price = segment[cup_bottom_idx]

    # Calculate cup depth
    if left_rim_price <= 0:
        return CupHandleOverlay(detected=False)
    cup_depth = ((left_rim_price - cup_bottom_price) / left_rim_price) * 100

    if cup_depth > max_cup_depth_pct or cup_depth < 5:
        return CupHandleOverlay(detected=False)

    # Find right rim recovery (price returns near left rim level)
    right_segment = segment[cup_bottom_idx:]
    right_rim_idx = None
    for i, p in enumerate(right_segment):
        if p >= left_rim_price * 0.95:  # Within 5% of left rim
            right_rim_idx = cup_bottom_idx + i
            break

    if right_rim_idx is None:
        return CupHandleOverlay(detected=False)

    # Handle detection: shallow pullback after right rim
    handle_segment = segment[right_rim_idx:]
    if len(handle_segment) < 3:
        return CupHandleOverlay(detected=False)

    handle_high = max(handle_segment)
    handle_low = min(handle_segment)
    handle_depth = (
        ((handle_high - handle_low) / handle_high * 100) if handle_high > 0 else 0
    )

    if handle_depth > max_handle_depth_pct:
        return CupHandleOverlay(detected=False)

    neckline = max(left_rim_price, segment[right_rim_idx])

    return CupHandleOverlay(
        detected=True,
        cup_start_idx=search_start + left_rim_idx,
        cup_bottom_idx=search_start + cup_bottom_idx,
        cup_end_idx=search_start + right_rim_idx,
        handle_end_idx=search_start + len(segment) - 1,
        cup_depth_pct=round(cup_depth, 1),
        handle_depth_pct=round(handle_depth, 1),
        neckline_price=neckline,
    )


# ═══════════════════════════════════════════════════════════════
# DOUBLE BOTTOM DETECTION
# ═══════════════════════════════════════════════════════════════


def detect_double_bottom(
    ohlcv: list,
    tolerance_pct: float = 3.0,
    min_bars_between: int = 10,
    max_bars_between: int = 80,
    pivot_window: int = 5,
) -> DoubleBottomOverlay:
    """Detect Double Bottom (W-pattern).

    Algorithm:
    1. Find pivot lows in the recent data
    2. Look for 2 lows within tolerance_pct of each other
    3. Minimum distance between bottoms (avoid noise)
    4. Neckline = highest point between the two bottoms
    """
    closes = _extract_closes(ohlcv)
    lows_data = _extract_lows(ohlcv)

    if len(closes) < 30:
        return DoubleBottomOverlay(detected=False)

    pivot_lows = find_pivot_lows(lows_data, window=pivot_window)
    if len(pivot_lows) < 2:
        return DoubleBottomOverlay(detected=False)

    # Search from most recent backwards for 2 matching lows
    for i in range(len(pivot_lows) - 1, 0, -1):
        second_idx, second_price = pivot_lows[i]
        for j in range(i - 1, -1, -1):
            first_idx, first_price = pivot_lows[j]

            bars_between = second_idx - first_idx
            if bars_between < min_bars_between or bars_between > max_bars_between:
                continue

            # Check if prices are within tolerance
            if first_price <= 0:
                continue
            diff_pct = abs(second_price - first_price) / first_price * 100
            if diff_pct > tolerance_pct:
                continue

            # Found matching pair — calculate neckline
            between_highs = closes[first_idx : second_idx + 1]
            if not between_highs:
                continue

            neckline_offset = between_highs.index(max(between_highs))
            neckline_idx = first_idx + neckline_offset
            neckline_price = between_highs[neckline_offset]

            return DoubleBottomOverlay(
                detected=True,
                first_bottom_idx=first_idx,
                first_bottom_price=first_price,
                second_bottom_idx=second_idx,
                second_bottom_price=second_price,
                neckline_price=neckline_price,
                neckline_idx=neckline_idx,
            )

    return DoubleBottomOverlay(detected=False)


# ═══════════════════════════════════════════════════════════════
# UNIFIED ENTRY POINT
# ═══════════════════════════════════════════════════════════════


@dataclass
class PatternOverlayResult:
    """Combined result of all pattern detection."""

    vcp: VCPOverlay
    cup_handle: CupHandleOverlay
    double_bottom: DoubleBottomOverlay

    @property
    def any_detected(self) -> bool:
        return (
            self.vcp.detected or self.cup_handle.detected or self.double_bottom.detected
        )

    @property
    def summary(self) -> str:
        parts = []
        if self.vcp.detected:
            n = len(self.vcp.contractions)
            parts.append(f"VCP ({n}T, Q={self.vcp.quality_score:.0f})")
        if self.cup_handle.detected:
            parts.append(f"Cup&Handle (depth={self.cup_handle.cup_depth_pct:.0f}%)")
        if self.double_bottom.detected:
            parts.append("Double Bottom")
        return " | ".join(parts) if parts else "No pattern"


def detect_all_patterns(ohlcv: list, pivot_window: int = 5) -> PatternOverlayResult:
    """Run all pattern detectors on OHLCV data.

    Returns a PatternOverlayResult with all detections.
    """
    vcp = detect_vcp_contractions(ohlcv, pivot_window=pivot_window)
    cup = detect_cup_handle(ohlcv, pivot_window=pivot_window)
    db = detect_double_bottom(ohlcv, pivot_window=pivot_window)

    if vcp.detected or cup.detected or db.detected:
        log.info(f"Pattern detection: {PatternOverlayResult(vcp, cup, db).summary}")

    return PatternOverlayResult(vcp=vcp, cup_handle=cup, double_bottom=db)
