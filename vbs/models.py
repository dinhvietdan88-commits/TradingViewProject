from typing import Optional, Dict, Any, List
from pydantic import BaseModel


class IngestResponse(BaseModel):
    queued: bool
    queue_id: Optional[int] = None
    expires_at: Optional[str] = None
    status: str
    duplicate_of: Optional[int] = None


class QueueSignal(BaseModel):
    queue_id: int
    symbol: str
    action: str
    price: Optional[float] = None
    quote_qty: Optional[float] = None
    interval: Optional[str] = None
    exchange: str = "binance"
    sl: Optional[str] = None
    tp: Optional[str] = None
    received_at: str
    expires_at: str
    age_minutes: float
    payload: Dict[str, Any]


class ConsumeResponse(BaseModel):
    signals: List[QueueSignal]
    count: int
    has_more: bool


class AckItem(BaseModel):
    queue_id: int
    status: str  # "executed", "skipped_stale", "failed"
    error_msg: Optional[str] = None


class AckRequest(BaseModel):
    acks: List[AckItem]


class AckResultItem(BaseModel):
    queue_id: int
    status: str


class AckResponse(BaseModel):
    acked: int
    results: List[AckResultItem]


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
    oldest_pending_age_minutes: Optional[float] = None


class QueueStatusResponse(BaseModel):
    summary: QueueSummary
    pending_signals: List[PendingSummaryItem]
