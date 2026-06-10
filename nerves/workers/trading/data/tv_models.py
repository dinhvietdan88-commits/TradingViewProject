"""
TradingView Alert Data Models.

Defines Pydantic schemas for incoming TradingView webhook payloads.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TradingViewAlertPayload(BaseModel):
    """
    Schema for TradingView indicator and strategy alerts.
    Designed with flexible Optional fields to support various alert formats while
    ensuring type safety and backward compatibility.
    """

    secret: str | None = Field(
        default=None, description="Webhook secret for authentication"
    )

    # Core trading fields
    action: str | None = Field(
        default=None, alias="side", description="Buy or Sell action"
    )
    symbol: str | None = Field(
        default=None, description="Trading pair symbol (e.g., BTCUSDT)"
    )
    price: Any | None = Field(default=None, description="Price at the time of alert")

    # Volume and position sizing
    volume: Any | None = Field(default=None, description="Volume at the time of alert")
    quoteQty: Any | None = Field(
        default=10.0, alias="size", description="Quote quantity to trade"
    )

    # Time and context
    time: str | None = Field(default=None, description="Timestamp of the alert")
    interval: str | None = Field(default=None, description="Chart interval/timeframe")

    # Risk management
    sl: str | float | None = Field(
        default=None, description="Stop Loss price or percentage"
    )
    tp: str | float | None = Field(
        default=None, description="Take Profit price or percentage"
    )

    # Exchange routing
    exchange: str | None = Field(default=None, description="Target exchange")

    # Extra/Custom fields
    indicator: str | None = Field(
        default=None, description="Name of the indicator triggering the alert"
    )
    strategy: str | None = Field(default=None, description="Name of the strategy")
    message: str | None = Field(default=None, description="Custom text message")

    # Strategy execution mode (from OPTIMIZED_PARAMETERS_MATRIX)
    mode: str | None = Field(
        default=None,
        description="Strategy mode: 'MTT' (Daily Trend Follower) or 'MIS' (1H Momentum/Mean Reversion)",
    )

    model_config = ConfigDict(populate_by_name=True, extra="allow")
