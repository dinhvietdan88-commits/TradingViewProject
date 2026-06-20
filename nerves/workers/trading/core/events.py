"""
Event Definitions — Immutable data classes for inter-component communication.

Design Invariant:
- Once emitted, event payloads are read-only.
- Each event carries a unique event_id for tracing.
- Events do NOT carry references to mutable state.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# ═══════════════════════════════════════════════════════════════
# BASE EVENT
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Event:
    """Base class for all domain events. Frozen = immutable after creation."""

    event_id: str = field(default_factory=_uid)
    timestamp: str = field(default_factory=_now)


# ═══════════════════════════════════════════════════════════════
# SIGNAL EVENTS (WebhookGateway → SignalProcessor)
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class SignalReceived(Event):
    """Emitted by WebhookGateway when a webhook payload is parsed and authenticated."""

    signal_id: int = 0
    symbol: str = ""
    action: str = ""
    price: float | None = None
    quote_qty: float = 10.0
    interval: str = ""
    sl: str = ""
    tp: str = ""
    source_ip: str = ""
    payload: dict[str, Any] | None = None
    exchange: str = "binance"
    rag_advice: str = ""
    mode: str = ""  # "MTT" | "MIS" | "" (empty = not specified)
    is_recovered: bool = False
    age_minutes: float = 0.0


@dataclass(frozen=True)
class SignalIngested(Event):
    """Emitted by Ingestion/Gatekeeper Layer (SignalProcessor) after passing dedup and timeframe checks."""

    signal_id: int = 0
    symbol: str = ""
    action: str = ""
    price: float | None = None
    quote_qty: float = 10.0
    interval: str = ""
    sl: str = ""
    tp: str = ""
    exchange: str = "binance"
    mode: str = ""  # "MTT" | "MIS" | ""
    is_recovered: bool = False
    age_minutes: float = 0.0


@dataclass(frozen=True)
class IndicatorSignalReceived(Event):
    """Emitted by WebhookGateway when an indicator payload is parsed and authenticated."""

    signal_id: int = 0
    symbol: str = ""
    indicator_name: str = ""
    signal_type: str = "info"  # "entry" | "exit" | "info"
    interval: str = ""
    price: float | None = None
    conditions_met: tuple = ()  # Immutable tuple of condition strings
    confidence_score: int = 0  # 0-100
    metadata: dict[str, Any] | None = None
    source_ip: str = ""
    exchange: str = "binance"
    is_recovered: bool = False
    age_minutes: float = 0.0


@dataclass(frozen=True)
class IndicatorSignalValidated(Event):
    """Emitted by SignalProcessor after indicator signal passes validation."""

    signal_id: int = 0
    symbol: str = ""
    indicator_name: str = ""
    signal_type: str = "info"
    price: float | None = None
    conditions_met: tuple = ()
    confidence_score: int = 0
    metadata: dict[str, Any] | None = None
    exchange: str = "binance"


@dataclass(frozen=True)
class IndicatorSignalRejected(Event):
    """Emitted by SignalProcessor when an indicator signal fails validation."""

    signal_id: int = 0
    symbol: str = ""
    indicator_name: str = ""
    signal_type: str = ""
    reason: str = ""
    exchange: str = "binance"
    is_recovered: bool = False
    age_minutes: float = 0.0


@dataclass(frozen=True)
class SignalValidated(Event):
    """Emitted by SignalProcessor after dedup + timeframe validation passes."""

    signal_id: int = 0
    symbol: str = ""
    action: str = ""
    price: float | None = None
    quote_qty: float = 10.0
    sl: str = ""
    tp: str = ""
    exchange: str = "binance"
    mode: str = ""  # "MTT" | "MIS" | "" — forwarded from SignalReceived
    is_recovered: bool = False
    age_minutes: float = 0.0
    tas: float = 0.0
    sts: float = 0.0
    mlts: float = 0.0
    mta_calculated: bool = False


@dataclass(frozen=True)
class MacroValidated(Event):
    """Emitted by Layer 2 MacroTrendProcessor after trend template & regime validation passes."""

    signal_id: int = 0
    symbol: str = ""
    action: str = ""
    price: float | None = None
    quote_qty: float = 10.0
    interval: str = ""
    sl: str = ""
    tp: str = ""
    exchange: str = "binance"
    mode: str = ""  # "MTT" | "MIS" | ""
    is_recovered: bool = False
    age_minutes: float = 0.0
    mta_trend_score: float = 0.0
    market_regime: str = ""


@dataclass(frozen=True)
class SignalRejected(Event):
    """Emitted by SignalProcessor when a signal fails validation."""

    signal_id: int = 0
    symbol: str = ""
    action: str = ""
    reason: str = ""
    interval: str = ""
    exchange: str = "binance"
    analysis_text: str = ""


# ═══════════════════════════════════════════════════════════════
# TRADE EVENTS (TradeEngine → PersistenceStore, NotificationHub)
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TradeApproved(Event):
    """Emitted by AIAnalyzer (auto) or Telegram Bot (human) when a trade is approved to execute."""

    signal_id: int = 0
    symbol: str = ""
    action: str = ""
    price: float | None = None
    quote_qty: float = 10.0
    sl: str = ""
    tp: str = ""
    exchange: str = "binance"
    approved_by: str = "AI"  # "AI" or "Human"
    analysis_text: str = ""
    mode: str = ""  # "MTT" | "MIS" | "" — forwarded from SignalValidated
    is_recovered: bool = False
    age_minutes: float = 0.0
    combined_score: str | None = None


@dataclass(frozen=True)
class TradeExecuted(Event):
    """Emitted by TradeEngine on successful order execution."""

    signal_id: int = 0
    trade_id: int = 0
    symbol: str = ""
    side: str = ""
    order_id: str = ""
    status: str = "FILLED"
    executed_qty: float = 0.0
    executed_price: float | None = None
    quote_qty: float = 0.0
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    oco_order_id: str | None = None
    order_type: str = "MARKET"
    exchange: str = "binance"
    combined_score: str | None = None
    rag_advice: str = ""
    telegram_message: str = ""


@dataclass(frozen=True)
class TradeFailed(Event):
    """Emitted by TradeEngine on order execution failure."""

    signal_id: int = 0
    symbol: str = ""
    side: str = ""
    error: str = ""
    quote_qty: float = 0.0
    exchange: str = "binance"
    combined_score: str | None = None


@dataclass(frozen=True)
class CircuitBreakerTripped(Event):
    """Emitted by TradeEngine when a circuit breaker trips to OPEN."""

    exchange: str = ""
    symbol: str = ""
    prev_state: str = ""
    new_state: str = "OPEN"
    reason: str = ""
    metrics: dict[str, Any] | None = None


@dataclass(frozen=True)
class TradeApprovalTimeout(Event):
    """Emitted by NotificationHub or ApprovalTimeoutManager when an interactive request expires."""

    signal_id: int = 0
    symbol: str = ""
    reason: str = "Timeout exceeded (5 mins)"


@dataclass(frozen=True)
class PositionClosed(Event):
    """Emitted by PositionMonitor when SL/TP fill is detected on an exchange.

    REQ2: P&L Notification on SL/TP Hit.
    exit_reason: 'STOP_LOSS' | 'TAKE_PROFIT' | 'MANUAL'
    """

    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    exchange: str = "binance"


# ═══════════════════════════════════════════════════════════════
# AI EVENTS (AIAnalyzer → TradeEngine, NotificationHub)
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class AlertTriggered(Event):
    """Emitted by SignalProcessor when action='alert' (stealth capture path)."""

    signal_id: int = 0
    symbol: str = ""
    price: str = ""
    quote_qty: float = 10.0
    rag_advice: str = ""
    exchange: str = "binance"
    is_recovered: bool = False
    age_minutes: float = 0.0


@dataclass(frozen=True)
class AnalysisComplete(Event):
    """Emitted by AIAnalyzer after Vision AI + RAG completes."""

    signal_id: int = 0
    symbol: str = ""
    action: str = ""
    price: float | None = None
    quote_qty: float = 10.0
    sl: str = ""
    tp: str = ""
    exchange: str = "binance"
    confidence: int = 0
    analysis_text: str = ""
    screenshot_path: str = ""
    combined_score: str | None = None
    vision_result: dict[str, Any] | None = None
    should_trade: bool = False  # confidence >= 8
    interactive_required: bool = False  # True if Human approval is needed
    is_recovered: bool = False
    age_minutes: float = 0.0
    mode: str = ""


# ═══════════════════════════════════════════════════════════════
# BRIEF / SCHEDULER EVENTS
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class BriefTriggered(Event):
    """Emitted by SchedulerDaemon or manual trigger to start Morning Brief."""

    source: str = "scheduler"  # "scheduler" | "manual" | "bot"


@dataclass(frozen=True)
class BriefCompleted(Event):
    """Emitted after Morning Brief generation completes."""

    brief_id: int = 0
    symbols_scanned: int = 0
    success: bool = True
    screenshot_path: str = ""


# ═══════════════════════════════════════════════════════════════
# CAPTURE EVENTS (HookDispatcher → PythonCaptureClient)
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CaptureTriggered(Event):
    """Emitted by HookDispatcher when a capture is triggered."""

    symbol: str = ""
    trigger: str = ""  # "signal" | "schedule" | "command"
    source_event_id: str = ""


# ═══════════════════════════════════════════════════════════════
# CONSENSUS EVENTS
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ConsensusRequested(Event):
    """Fired when an E5 operation or state transition requires council evaluation."""

    operation: str = ""
    requester: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConsensusEvaluated(Event):
    """Fired when the Council has completed voting."""

    operation: str = ""
    sa_verdict: str = ""
    sre_verdict: str = ""
    meta_verdict: str = ""
    ac_verdict: str = ""
    final_verdict: str = ""
    override_token: str | None = None
    rationale: str = ""
