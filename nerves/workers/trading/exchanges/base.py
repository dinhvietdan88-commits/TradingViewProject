from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


class ExchangeErrorCategory(Enum):
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    INVALID_SYMBOL = "INVALID_SYMBOL"
    RATE_LIMITED = "RATE_LIMITED"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    ORDER_REJECTED = "ORDER_REJECTED"
    UNKNOWN = "UNKNOWN"


class ExchangeError(Exception):
    """Unified exchange error with category and original details."""

    def __init__(
        self,
        category: ExchangeErrorCategory,
        message: str,
        original_code: str | None = None,
        exchange: str = "",
    ):
        super().__init__(message)
        self.category = category
        self.original_code = original_code
        self.exchange = exchange


class ExchangeNotFoundError(Exception):
    pass


class ExchangeUnavailableError(Exception):
    pass


class SymbolMappingError(Exception):
    pass


@dataclass
class RiskParams:
    """Computed SL/TP levels and position sizing."""

    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    stop_loss_pct: float
    take_profit_pct: float
    risk_reward_ratio: float
    quantity: float  # base asset qty
    cost: float  # quote asset cost
    risk_amount: float  # $ at risk
    account_balance: float
    position_pct: float  # % of account

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_price": round(self.entry_price, 8),
            "stop_loss_price": round(self.stop_loss_price, 8),
            "take_profit_price": round(self.take_profit_price, 8),
            "stop_loss_pct": round(self.stop_loss_pct * 100, 2),
            "take_profit_pct": round(self.take_profit_pct * 100, 2),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "quantity": round(self.quantity, 8),
            "cost": round(self.cost, 2),
            "risk_amount": round(self.risk_amount, 2),
            "account_balance": round(self.account_balance, 2),
            "position_pct": round(self.position_pct * 100, 2),
        }


@dataclass
class OrderResult:
    """Unified result for order execution across all exchanges."""

    success: bool
    dry_run: bool
    side: str
    symbol: str
    exchange: str = ""  # exchange identifier
    entry_order: dict[str, Any] = field(default_factory=dict)
    oco_order: dict[str, Any] | None = None
    risk: RiskParams | None = None
    error: str | None = None
    error_category: ExchangeErrorCategory | None = None
    fallback_used: bool = False
    original_exchange: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "success": self.success,
            "dry_run": self.dry_run,
            "side": self.side,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "entry_order": self.entry_order,
            "oco_order": self.oco_order,
            "risk": self.risk.to_dict() if self.risk else None,
            "error": self.error,
            "error_category": self.error_category.value
            if self.error_category
            else None,
            "fallback_used": self.fallback_used,
            "original_exchange": self.original_exchange,
        }
        return d


@runtime_checkable
class ExchangeAdapter(Protocol):
    """Unified interface for all exchange adapters."""

    @property
    def exchange_name(self) -> str:
        """Unique identifier: 'binance', 'bybit', etc."""
        ...

    @property
    def is_testnet(self) -> bool: ...

    @property
    def is_dry_run(self) -> bool: ...

    @property
    def supported_order_types(self) -> list[str]:
        """e.g. ['MARKET', 'LIMIT', 'OCO', 'CONDITIONAL']"""
        ...

    async def get_account_balance(self, asset: str = "USDT") -> float: ...

    async def get_symbol_info(self, symbol: str) -> dict[str, Any]: ...

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quote_qty: float | None = None,
        base_qty: float | None = None,
    ) -> dict[str, Any]: ...

    async def place_oco_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        take_profit_price: float,
        stop_price: float,
        stop_limit_price: float,
    ) -> dict[str, Any]: ...

    async def get_ticker_price(self, symbol: str) -> float: ...

    async def place_limit_order(
        self, symbol: str, side: str, price: float, quantity: float
    ) -> dict[str, Any]: ...

    async def get_order(self, symbol: str, order_id: str) -> dict[str, Any]: ...

    async def cancel_order(self, symbol: str, order_id: str) -> dict[str, Any]: ...

    async def cancel_oco_order(
        self, symbol: str, order_list_id: str
    ) -> dict[str, Any]: ...

    async def execute_smart_order(
        self,
        symbol: str,
        side: str,
        entry_price: float | None = None,
        quote_qty: float | None = None,
        sl_pct: float | None = None,
        tp_pct: float | None = None,
        risk_pct: float | None = None,
        sl_price: float | None = None,
        tp_price: float | None = None,
        asset: str = "USDT",
        order_type: str = "MARKET",
    ) -> OrderResult: ...

    async def health_check(self) -> dict[str, Any]:
        """Returns {'healthy': bool, 'latency_ms': float, 'error': Optional[str]}"""
        ...
