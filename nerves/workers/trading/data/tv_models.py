"""
TradingView Alert Data Models.

Defines Pydantic schemas for incoming TradingView webhook payloads.
"""

from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict


class TradingViewAlertPayload(BaseModel):
    """
    Schema for TradingView indicator and strategy alerts.
    Designed with flexible Optional fields to support various alert formats while
    ensuring type safety and backward compatibility.
    """

    secret: Optional[str] = Field(
        default=None, description="Webhook secret for authentication"
    )

    # Core trading fields
    action: Optional[str] = Field(
        default=None, alias="side", description="Buy or Sell action"
    )
    symbol: Optional[str] = Field(
        default=None, description="Trading pair symbol (e.g., BTCUSDT)"
    )
    price: Optional[Any] = Field(default=None, description="Price at the time of alert")

    # Volume and position sizing
    volume: Optional[Any] = Field(
        default=None, description="Volume at the time of alert"
    )
    quoteQty: Optional[Any] = Field(
        default=10.0, alias="size", description="Quote quantity to trade"
    )

    # Time and context
    time: Optional[str] = Field(default=None, description="Timestamp of the alert")
    interval: Optional[str] = Field(
        default=None, description="Chart interval/timeframe"
    )

    # Risk management
    sl: Optional[str] = Field(default=None, description="Stop Loss price or percentage")
    tp: Optional[str] = Field(
        default=None, description="Take Profit price or percentage"
    )

    # Exchange routing
    exchange: Optional[str] = Field(default=None, description="Target exchange")

    # Extra/Custom fields
    indicator: Optional[str] = Field(
        default=None, description="Name of the indicator triggering the alert"
    )
    strategy: Optional[str] = Field(default=None, description="Name of the strategy")
    message: Optional[str] = Field(default=None, description="Custom text message")

    # Strategy execution mode (from OPTIMIZED_PARAMETERS_MATRIX)
    mode: Optional[str] = Field(
        default=None,
        description="Strategy mode: 'MTT' (Daily Trend Follower) or 'MIS' (1H Momentum/Mean Reversion)",
    )

    model_config = ConfigDict(populate_by_name=True, extra="allow")
