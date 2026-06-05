"""
Sprint 7.2 — Binance Client Unit Tests
Tests position sizing, SL/TP calculation, and dry-run order flow.
No API keys required — all tests use dry-run mode.
"""

import os
import sys
import pytest

# Ensure server/ is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Set env before imports
os.environ.setdefault("BINANCE_API_KEY", "")
os.environ.setdefault("BINANCE_API_SECRET", "")
os.environ.setdefault("BINANCE_TESTNET", "true")
os.environ.setdefault("BINANCE_DRY_RUN", "true")


from binance_client import BinanceClient, OrderResult
from unittest.mock import AsyncMock


# ═══════════════════════════════════════════════════════════════
# POSITION SIZING TESTS
# ═══════════════════════════════════════════════════════════════


class TestPositionSizing:
    def test_calculate_position_size_basic(self):
        """Risk 2% on $10,000 with 8% SL → correct qty."""
        balance = 10000
        entry = 67500.0
        sl = 67500 * 0.92  # 8% below
        risk_pct = 0.02

        qty = BinanceClient.calculate_position_size(balance, entry, sl, risk_pct)
        risk_amount = balance * risk_pct  # $200

        # qty × distance = risk_amount
        distance = abs(entry - sl)
        assert abs(qty * distance - risk_amount) < 0.01

    def test_calculate_position_size_zero_distance(self):
        """Zero distance → zero qty (no division by zero)."""
        qty = BinanceClient.calculate_position_size(10000, 100, 100, 0.02)
        assert qty == 0.0

    def test_calculate_position_size_small_account(self):
        """Small account still calculates correctly."""
        qty = BinanceClient.calculate_position_size(100, 50000, 46000, 0.02)
        assert qty > 0
        risk = qty * abs(50000 - 46000)
        assert abs(risk - 2.0) < 0.01  # $2 risk on $100 account

    def test_position_size_respects_risk_pct(self):
        """Different risk percentages produce proportional sizes."""
        entry = 50000
        sl = 46000  # $4000 distance

        qty_2pct = BinanceClient.calculate_position_size(10000, entry, sl, 0.02)
        qty_5pct = BinanceClient.calculate_position_size(10000, entry, sl, 0.05)

        assert abs(qty_5pct / qty_2pct - 2.5) < 0.01


# ═══════════════════════════════════════════════════════════════
# SL/TP CALCULATION TESTS
# ═══════════════════════════════════════════════════════════════


class TestSLTP:
    def test_sl_tp_buy(self):
        """BUY: SL below entry, TP above entry."""
        levels = BinanceClient.calculate_sl_tp(100.0, "BUY", sl_pct=0.08, tp_pct=0.20)
        assert levels["stop_loss"] == 92.0  # 100 * 0.92
        assert levels["take_profit"] == 120.0  # 100 * 1.20
        assert levels["risk_reward"] == 2.5

    def test_sl_tp_sell(self):
        """SELL: SL above entry, TP below entry."""
        levels = BinanceClient.calculate_sl_tp(100.0, "SELL", sl_pct=0.08, tp_pct=0.20)
        assert levels["stop_loss"] == 108.0  # 100 * 1.08
        assert levels["take_profit"] == 80.0  # 100 * 0.80
        assert levels["risk_reward"] == 2.5

    def test_sl_tp_crypto_price(self):
        """Works with real crypto prices."""
        levels = BinanceClient.calculate_sl_tp(67500.0, "BUY", sl_pct=0.08, tp_pct=0.20)
        assert abs(levels["stop_loss"] - 62100.0) < 0.01
        assert abs(levels["take_profit"] - 81000.0) < 0.01

    def test_sl_tp_rr_ratio_varies(self):
        """Custom SL/TP percentages change R:R ratio."""
        levels = BinanceClient.calculate_sl_tp(100.0, "BUY", sl_pct=0.05, tp_pct=0.15)
        assert levels["risk_reward"] == 3.0

    def test_sl_tp_zero_sl(self):
        """Zero SL → zero R:R (edge case)."""
        levels = BinanceClient.calculate_sl_tp(100.0, "BUY", sl_pct=0.0, tp_pct=0.20)
        assert levels["risk_reward"] == 0


# ═══════════════════════════════════════════════════════════════
# DRY-RUN ORDER TESTS
# ═══════════════════════════════════════════════════════════════


class TestDryRunOrders:
    @pytest.fixture
    def client(self):
        return BinanceClient(
            api_key="test-key",
            api_secret="test-secret",
            testnet=True,
            dry_run=True,
        )

    @pytest.mark.asyncio
    async def test_dry_run_market_order(self, client):
        """Dry-run market order returns mock result."""
        result = await client.place_market_order("BTCUSDT", "BUY", quote_qty=1000)
        assert result["status"] == "FILLED"
        assert result["side"] == "BUY"
        assert result["symbol"] == "BTCUSDT"
        assert result["_dry_run"] is True
        assert "DRY-" in result["orderId"]

    @pytest.mark.asyncio
    async def test_dry_run_market_order_sell(self, client):
        """Dry-run SELL market order."""
        result = await client.place_market_order("ETHUSDT", "SELL", base_qty=0.5)
        assert result["side"] == "SELL"
        assert result["_dry_run"] is True

    @pytest.mark.asyncio
    async def test_dry_run_oco_order(self, client):
        """Dry-run OCO order returns mock with TP and SL."""
        result = await client.place_oco_order(
            symbol="BTCUSDT",
            side="SELL",
            quantity=0.015,
            take_profit_price=81000,
            stop_price=62100,
            stop_limit_price=61800,
        )
        assert result["_dry_run"] is True
        assert "DRY-OCO-" in result["orderListId"]
        assert len(result["orders"]) == 2
        assert result["take_profit_price"] == 81000
        assert result["stop_loss_price"] == 62100

    @pytest.mark.asyncio
    async def test_dry_run_balance(self, client):
        """Dry-run balance returns $10,000."""
        balance = await client.get_account_balance("USDT")
        assert balance == 10000.0

    @pytest.mark.asyncio
    async def test_market_order_requires_qty(self, client):
        """Must provide either quote_qty or base_qty."""
        with pytest.raises(ValueError):
            await client.place_market_order("BTCUSDT", "BUY")


# ═══════════════════════════════════════════════════════════════
# SMART ORDER FLOW TEST
# ═══════════════════════════════════════════════════════════════


class TestSmartOrder:
    @pytest.fixture
    def client(self):
        return BinanceClient(
            api_key="test-key",
            api_secret="test-secret",
            testnet=True,
            dry_run=True,
        )

    @pytest.mark.asyncio
    async def test_smart_order_buy_dry_run(self, client):
        """Full BUY smart order flow in dry-run."""
        result = await client.execute_smart_order(
            symbol="BTCUSDT",
            side="BUY",
            entry_price=67500,
            sl_pct=0.08,
            tp_pct=0.20,
        )

        assert isinstance(result, OrderResult)
        assert result.success is True
        assert result.dry_run is True
        assert result.side == "BUY"
        assert result.entry_order is not None
        assert result.oco_order is not None
        assert result.risk is not None
        assert result.risk.stop_loss_price < result.risk.entry_price
        assert result.risk.take_profit_price > result.risk.entry_price
        assert result.risk.risk_reward_ratio == 2.5

    @pytest.mark.asyncio
    async def test_smart_order_sell_dry_run(self, client):
        """Full SELL smart order flow in dry-run."""
        result = await client.execute_smart_order(
            symbol="BTCUSDT",
            side="SELL",
            entry_price=67500,
        )

        assert result.success is True
        assert result.side == "SELL"
        assert result.risk.stop_loss_price > result.risk.entry_price
        assert result.risk.take_profit_price < result.risk.entry_price

    @pytest.mark.asyncio
    async def test_smart_order_position_capped(self, client):
        """Position size capped at 95% of balance."""
        result = await client.execute_smart_order(
            symbol="BTCUSDT",
            side="BUY",
            entry_price=100,  # Very low price → large position
            sl_pct=0.001,  # Very tight SL → huge size
        )

        assert result.success is True
        # Cost should not exceed 95% of $10,000
        assert result.risk.cost <= 10000 * 0.95 + 0.01

    @pytest.mark.asyncio
    async def test_smart_order_dynamic_atr_prices(self, client):
        """Verify smart order execution with dynamic ATR-based SL/TP prices."""
        # Explicitly pass dynamic sl_price and tp_price (e.g. from ATR calculation)
        result = await client.execute_smart_order(
            symbol="BTCUSDT",
            side="BUY",
            entry_price=67500.0,
            sl_price=67400.0,
            tp_price=67750.0,
        )

        assert result.success is True
        assert result.risk.stop_loss_price == 67400.0
        assert result.risk.take_profit_price == 67750.0
        # R:R = (67750 - 67500) / (67500 - 67400) = 250 / 100 = 2.5
        assert result.risk.risk_reward_ratio == 2.5

    @pytest.mark.asyncio
    async def test_smart_order_slippage_adjustment(self, client, mocker):
        """Verify Stop-Loss and Take-Profit values are shifted by slippage."""
        # Mock place_market_order to return a different fill price
        # If entry_price was 100.0, but fill price was 102.0 (slippage = +2.0)
        # SL and TP must shift up by +2.0 to keep the risk distance constant.
        mocker.patch.object(
            client,
            "place_market_order",
            new_callable=AsyncMock,
            return_value={
                "orderId": "DRY-MOCK-ENTRY",
                "executedQty": "2.0",
                "cummulativeQuoteQty": "204.0",  # fill price = 204 / 2 = 102.0
                "status": "FILLED",
                "_dry_run": True,
            },
        )

        result = await client.execute_smart_order(
            symbol="BTCUSDT",
            side="BUY",
            entry_price=100.0,
            sl_price=90.0,
            tp_price=125.0,
            order_type="MARKET",
        )

        assert result.success is True
        # Actual fill price is 102.0
        assert result.risk.entry_price == 102.0
        # SL must be shifted: 90.0 + 2.0 = 92.0
        assert result.risk.stop_loss_price == 92.0
        # TP must be shifted: 125.0 + 2.0 = 127.0
        assert result.risk.take_profit_price == 127.0


# ═══════════════════════════════════════════════════════════════
# SIGNING TEST
# ═══════════════════════════════════════════════════════════════


class TestSigning:
    def test_sign_params(self):
        """HMAC signature is added correctly."""
        client = BinanceClient(
            api_key="test-key",
            api_secret="test-secret",
            testnet=True,
            dry_run=True,
        )
        params = {"symbol": "BTCUSDT", "side": "BUY"}
        signed = client._sign_params(params)

        assert "signature" in signed
        assert "timestamp" in signed
        assert len(signed["signature"]) == 64  # SHA256 hex digest
