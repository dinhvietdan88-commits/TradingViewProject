from typing import Any

from pydantic import BaseModel


class IngestResponse(BaseModel):
    queued: bool
    queue_id: int | None = None
    expires_at: str | None = None
    status: str
    duplicate_of: int | None = None


class QueueSignal(BaseModel):
    queue_id: int
    symbol: str
    action: str
    price: float | None = None
    quote_qty: float | None = None
    interval: str | None = None
    exchange: str = "binance"
    sl: str | None = None
    tp: str | None = None
    received_at: str
    expires_at: str
    age_minutes: float
    payload: dict[str, Any]


class ConsumeResponse(BaseModel):
    signals: list[QueueSignal]
    count: int
    has_more: bool


class AckItem(BaseModel):
    queue_id: int
    status: str  # "executed", "skipped_stale", "failed"
    error_msg: str | None = None


class AckRequest(BaseModel):
    acks: list[AckItem]


class AckResultItem(BaseModel):
    queue_id: int
    status: str


class AckResponse(BaseModel):
    acked: int
    results: list[AckResultItem]


class PendingSummaryItem(BaseModel):
    queue_id: int
    symbol: str
    action: str
    received_at: str
    ttl_remaining_minutes: float


class QueueSummary(BaseModel):
    pending: int
    dispatched: int
    acked_today: int
    stale_today: int
    oldest_pending_age_minutes: float | None = None


class QueueStatusResponse(BaseModel):
    summary: QueueSummary
    pending_signals: list[PendingSummaryItem]
