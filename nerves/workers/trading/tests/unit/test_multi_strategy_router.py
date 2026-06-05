"""
test_multi_strategy_router.py — Tests for V3 Multi-Strategy Router in VpsAnalyzer.

Tests:
  - _detect_strategy_group: Correctly identifies A.007, SuperTrend, Indicator, Minervini
  - _route_algorithmic_analysis: Routes to correct algo method
  - _algo_a007: A.007 payload sanity check (action + price + interval + position_size)
  - _algo_supertrend: SuperTrend payload check (action + price + SL + confidence)
  - _algo_indicator_passthrough: Indicator passthrough with source confidence
  - _algorithmic_analysis: Minervini SEPA (original, unchanged)
  - Integration: Smoke test payload gets >= 60% confidence via A.007 route
"""

import pytest
import sys
from pathlib import Path

# Ensure server root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from workers.vps_analyzer import VpsAnalyzerWorker


@pytest.fixture
def worker():
    """Create a VpsAnalyzerWorker instance for testing."""
    return VpsAnalyzerWorker()


# ═══════════════════════════════════════════════════════════════
# _detect_strategy_group
# ═══════════════════════════════════════════════════════════════


class TestDetectStrategyGroup:
    """Verify signal routing classification."""

    def test_a007_signal_name(self, worker):
        signal = {"signal": "V1_A007MIS_AUTO", "payload": {}}
        assert worker._detect_strategy_group(signal) == "A.007 (MA Crossover + ADX)"

    def test_a007_fwd_signal(self, worker):
        signal = {"signal": "FWD_ADX25_TRAIL", "payload": {}}
        assert worker._detect_strategy_group(signal) == "A.007 (MA Crossover + ADX)"

    def test_a007_mis_auto_signal(self, worker):
        signal = {"signal": "A007+MIS_AUTO_LONG", "payload": {}}
        assert worker._detect_strategy_group(signal) == "A.007 (MA Crossover + ADX)"

    def test_a007_from_payload(self, worker):
        signal = {"payload": {"signal": "A007+MIS_LONG"}}
        assert worker._detect_strategy_group(signal) == "A.007 (MA Crossover + ADX)"

    def test_supertrend_signal(self, worker):
        signal = {"signal": "ST_FLIP_BULL", "payload": {}}
        assert worker._detect_strategy_group(signal) == "SuperTrend"

    def test_supertrend_from_indicator_name(self, worker):
        signal = {"payload": {"indicator_name": "SuperTrend Flip Webhook"}}
        assert worker._detect_strategy_group(signal) == "SuperTrend"

    def test_indicator_source(self, worker):
        signal = {
            "payload": {"source": "indicator", "indicator_name": "MIS(A7-01B.V3)"}
        }
        assert worker._detect_strategy_group(signal).startswith("Indicator")

    def test_indicator_source_with_name(self, worker):
        signal = {
            "payload": {"source": "indicator", "indicator_name": "MIS(A7-01B.V3)"}
        }
        result = worker._detect_strategy_group(signal)
        assert "MIS(A7-01B.V3)" in result

    def test_unknown_defaults_to_minervini(self, worker):
        signal = {"signal": "SOME_RANDOM_SIGNAL", "payload": {}}
        assert worker._detect_strategy_group(signal) == "Minervini SEPA"

    def test_empty_signal(self, worker):
        signal = {}
        assert worker._detect_strategy_group(signal) == "Minervini SEPA"

    def test_string_payload_handled(self, worker):
        """Payload might arrive as JSON string — should be parsed."""
        import json

        signal = {"payload": json.dumps({"signal": "A007+MIS_LONG"})}
        assert worker._detect_strategy_group(signal) == "A.007 (MA Crossover + ADX)"


# ═══════════════════════════════════════════════════════════════
# _route_algorithmic_analysis
# ═══════════════════════════════════════════════════════════════


class TestRouteAlgorithmicAnalysis:
    """Verify routing dispatches to correct algo method."""

    def test_routes_a007(self, worker):
        signal = {
            "signal": "V1_A007MIS_AUTO",
            "action": "buy",
            "price": "62647",
            "payload": {"interval": "5"},
        }
        advice, conf = worker._route_algorithmic_analysis(signal)
        assert "A.007" in advice
        assert conf >= 75  # 3/4 or 4/4 checks pass

    def test_routes_supertrend(self, worker):
        signal = {
            "signal": "ST_FLIP_BULL",
            "action": "buy",
            "price": "62647",
            "payload": {},
        }
        advice, conf = worker._route_algorithmic_analysis(signal)
        assert "SUPERTREND" in advice

    def test_routes_indicator(self, worker):
        signal = {
            "payload": {
                "source": "indicator",
                "indicator_name": "MIS V3",
                "confidence_score": 85,
            }
        }
        advice, conf = worker._route_algorithmic_analysis(signal)
        assert "INDICATOR PASSTHROUGH" in advice
        assert conf == 85

    def test_routes_minervini_default(self, worker):
        signal = {"signal": "RANDOM", "action": "buy", "price": "100", "payload": {}}
        advice, conf = worker._route_algorithmic_analysis(signal)
        assert "ALGORITHMIC MODE" in advice  # Original method


# ═══════════════════════════════════════════════════════════════
# _algo_a007
# ═══════════════════════════════════════════════════════════════


class TestAlgoA007:
    """A.007 sanity check — verifies payload integrity, not trading criteria."""

    def test_full_payload_100pct(self, worker):
        """Complete A.007 payload should score 4/4 = 100%."""
        signal = {
            "action": "buy",
            "price": "62647.91",
            "payload": {
                "interval": "5",
                "position_size": "0.01",
            },
        }
        advice, conf = worker._algo_a007(signal)
        assert conf == 100
        assert "PASS" in advice

    def test_minimal_payload_75pct(self, worker):
        """Payload with action + price + interval (no position_size) = 4/4 (position_size defaults)."""
        signal = {"action": "buy", "price": "62647", "payload": {"interval": "5"}}
        advice, conf = worker._algo_a007(signal)
        assert conf >= 75
        assert "PASS" in advice

    def test_smoke_test_payload(self, worker):
        """The smoke test payload that was previously rejected at 0%."""
        signal = {
            "action": "buy",
            "price": "62647",
            "symbol": "BTCUSDT",
            "signal": "SMOKE_TEST_V2",
            "payload": {
                "interval": "5",
                "signal": "SMOKE_TEST_V2",
            },
        }
        advice, conf = worker._algo_a007(signal)
        # action=buy ✅, price=62647 ✅, interval=5 ✅, no position_size → default ✅
        assert conf == 100
        assert "PASS" in advice

    def test_invalid_action_rejected(self, worker):
        signal = {"action": "hold", "price": "100", "payload": {"interval": "5"}}
        advice, conf = worker._algo_a007(signal)
        assert conf < 100
        assert "không hợp lệ" in advice

    def test_zero_price_rejected(self, worker):
        signal = {"action": "buy", "price": "0", "payload": {"interval": "5"}}
        advice, conf = worker._algo_a007(signal)
        assert conf < 100


# ═══════════════════════════════════════════════════════════════
# _algo_supertrend
# ═══════════════════════════════════════════════════════════════


class TestAlgoSupertrend:
    """SuperTrend sanity check."""

    def test_full_vbs_payload(self, worker):
        """Complete ST Flip payload from VBS_Webhook_Lib."""
        signal = {
            "action": "buy",
            "price": "62647",
            "payload": {
                "confidence_score": 85,
                "metadata": {"sl": "62000", "tp": "63500"},
            },
        }
        advice, conf = worker._algo_supertrend(signal)
        assert conf == 100
        assert "PASS" in advice

    def test_no_metadata_still_passes(self, worker):
        """ST signal without metadata should still score ≥ 75%."""
        signal = {"action": "buy", "price": "62647", "payload": {}}
        advice, conf = worker._algo_supertrend(signal)
        # action ✅, price ✅, SL default ✅, confidence default ✅
        assert conf >= 75


# ═══════════════════════════════════════════════════════════════
# _algo_indicator_passthrough
# ═══════════════════════════════════════════════════════════════


class TestAlgoIndicatorPassthrough:
    """Indicator passthrough — uses source confidence, no trade criteria."""

    def test_passes_source_confidence(self, worker):
        signal = {
            "payload": {
                "source": "indicator",
                "indicator_name": "MIS(A7-01B.V3)",
                "confidence_score": 85,
            },
            "symbol": "BTCUSDT",
            "action": "buy",
        }
        advice, conf = worker._algo_indicator_passthrough(signal)
        assert conf == 85
        assert "MIS(A7-01B.V3)" in advice
        assert "INDICATOR PASSTHROUGH" in advice

    def test_default_confidence_when_missing(self, worker):
        signal = {"payload": {"source": "indicator"}}
        advice, conf = worker._algo_indicator_passthrough(signal)
        assert conf == 60  # Default

    def test_clamps_confidence(self, worker):
        signal = {"payload": {"confidence_score": 150}}
        _, conf = worker._algo_indicator_passthrough(signal)
        assert conf == 100

    def test_handles_string_payload(self, worker):
        import json

        signal = {
            "payload": json.dumps({"indicator_name": "Test", "confidence_score": 70})
        }
        advice, conf = worker._algo_indicator_passthrough(signal)
        assert conf == 70
        assert "Test" in advice


# ═══════════════════════════════════════════════════════════════
# Integration: End-to-end algorithmic analysis
# ═══════════════════════════════════════════════════════════════


class TestIntegrationAlgorithmic:
    """End-to-end: signal → route → analyze → verdict."""

    def test_a007_smoke_test_not_rejected_by_minervini(self, worker):
        """Previously this payload scored 1/5 = 20% = REJECT.
        With multi-strategy router, it should score 4/4 = 100% = PASS."""
        signal = {
            "action": "buy",
            "price": "62647",
            "signal": "V2_A007MIS_COMBINED",
            "payload": {"interval": "5", "signal": "V2_A007MIS_COMBINED"},
        }
        advice, conf = worker._route_algorithmic_analysis(signal)
        assert conf >= 75
        assert "Minervini" not in advice
        assert "A.007" in advice

    def test_minervini_signal_still_uses_old_logic(self, worker):
        """Generic signals without A.007/ST/Indicator markers should
        still use the original 5-criteria Minervini check."""
        signal = {
            "action": "buy",
            "price": "100",
            "signal": "GENERIC_ALERT",
            "payload": {
                "rsi": 65,
                "volume": 1000,
                "volume_avg": 500,
                "alert_type": "breakout",
                "sl": "95",
            },
        }
        advice, conf = worker._route_algorithmic_analysis(signal)
        assert "ALGORITHMIC MODE" in advice  # Original format
        # Should score well: rsi ✅, volume ✅, breakout ✅, sl ✅, action ✅
        assert conf >= 80


# ═══════════════════════════════════════════════════════════════
# Production-realistic payloads (VBS consume_signals format)
# ═══════════════════════════════════════════════════════════════


class TestProductionPayloads:
    """Test with exact VBS consume_signals() response dicts.

    These replicate the signal dicts Server C receives from Server A
    when consuming via /consume-long endpoint.
    """

    def test_production_a007_mis_v2_long(self, worker):
        """Exact payload from Alert 1: A007+MIS V2 → buy signal."""
        signal = {
            "queue_id": 371,
            "symbol": "BTCUSDT",
            "action": "buy",
            "price": 63266.38,
            "quote_qty": 12.5,
            "interval": "5",
            "exchange": "BINANCE",
            "sl": "",
            "tp": "",
            "received_at": "2026-06-04 02:00:00",
            "expires_at": "2026-06-04 14:00:00",
            "age_minutes": 0.3,
            "payload": {
                "secret": "7086c59c89104",
                "action": "buy",
                "symbol": "BTCUSDT",
                "price": 63266.38,
                "quoteQty": 12.5,
                "interval": "5",
                "signal": "A007+MIS_LONG",
                "exchange": "binance",
            },
        }
        # Must route to A.007 and PASS
        group = worker._detect_strategy_group(signal)
        assert group == "A.007 (MA Crossover + ADX)"

        advice, conf = worker._route_algorithmic_analysis(signal)
        assert "A.007" in advice
        assert conf == 100  # action ✅, price ✅, interval ✅, position_size default ✅

    def test_production_supertrend_flip_bull(self, worker):
        """Exact payload from Alert 2: SuperTrend Flip → bull flip."""
        signal = {
            "queue_id": 372,
            "symbol": "BTCUSDT",
            "action": "buy",
            "price": 63100.0,
            "quote_qty": 10.0,
            "interval": "5",
            "exchange": "BINANCE",
            "sl": "",
            "tp": "",
            "received_at": "2026-06-04 02:05:00",
            "expires_at": "2026-06-04 14:05:00",
            "age_minutes": 0.1,
            "payload": {
                "action": "buy",
                "symbol": "BTCUSDT",
                "price": 63100.0,
                "interval": "5",
                "signal": "ST_FLIP_BULL",
                "source": "indicator",
                "indicator_name": "SuperTrend Flip Webhook",
                "confidence_score": 78,
                "metadata": {
                    "sl": "62500.00",
                    "tp": "64200.00",
                    "atr": "350.5",
                },
                "exchange": "binance",
            },
        }
        group = worker._detect_strategy_group(signal)
        assert group == "SuperTrend"

        advice, conf = worker._route_algorithmic_analysis(signal)
        assert "SUPERTREND" in advice
        assert conf == 100  # action ✅, price ✅, SL ✅, confidence ✅

    def test_production_mis_v3_indicator(self, worker):
        """Exact payload from Test04: MIS(A7-01B.V3) indicator signal."""
        signal = {
            "queue_id": 373,
            "symbol": "BTCUSDT",
            "action": "info",
            "price": 63200.0,
            "quote_qty": 10.0,
            "interval": "5",
            "exchange": "BINANCE",
            "sl": "",
            "tp": "",
            "received_at": "2026-06-04 02:10:00",
            "expires_at": "2026-06-04 14:10:00",
            "age_minutes": 0.5,
            "payload": {
                "action": "info",
                "symbol": "BTCUSDT",
                "price": 63200.0,
                "interval": "5",
                "source": "indicator",
                "indicator_name": "MIS(A7-01B.V3)",
                "signal_type": "momentum",
                "confidence_score": 85,
                "conditions_met": [
                    "EMA20>50>200",
                    "RSI>50",
                    "MACD_CROSS_UP",
                    "VOL>AVG",
                ],
                "metadata": {
                    "rsi": 62.5,
                    "macd": 45.2,
                    "ema20": 63100.0,
                },
                "exchange": "binance",
            },
        }
        group = worker._detect_strategy_group(signal)
        assert group == "Indicator (MIS(A7-01B.V3))"

        advice, conf = worker._route_algorithmic_analysis(signal)
        assert "INDICATOR PASSTHROUGH" in advice
        assert conf == 85  # From source confidence_score

    def test_production_a007_short(self, worker):
        """A007+MIS V2 short signal — checks SHORT routing works."""
        signal = {
            "queue_id": 374,
            "symbol": "BTCUSDT",
            "action": "sell",
            "price": 62500.0,
            "quote_qty": 12.5,
            "interval": "5",
            "exchange": "BINANCE",
            "payload": {
                "action": "sell",
                "symbol": "BTCUSDT",
                "price": 62500.0,
                "quoteQty": 12.5,
                "interval": "5",
                "signal": "A007+MIS_SHORT",
                "exchange": "binance",
            },
        }
        group = worker._detect_strategy_group(signal)
        assert group == "A.007 (MA Crossover + ADX)"

        advice, conf = worker._route_algorithmic_analysis(signal)
        assert conf == 100
        assert "SELL" in advice

    def test_no_signal_field_but_has_a007_in_payload(self, worker):
        """Edge case: top-level 'signal' key missing, but payload has it."""
        signal = {
            "queue_id": 999,
            "symbol": "ETHUSDT",
            "action": "buy",
            "price": 3500.0,
            "payload": {
                "signal": "A007+MIS_LONG",
                "interval": "15",
            },
        }
        group = worker._detect_strategy_group(signal)
        assert group == "A.007 (MA Crossover + ADX)"
