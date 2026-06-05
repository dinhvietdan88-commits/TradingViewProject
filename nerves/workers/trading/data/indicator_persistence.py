"""
IndicatorPersistence — Independent EventBus listener for indicator signal storage.

Design Invariant DI-1:
    This module listens to IndicatorSignalReceived independently from SignalProcessor.
    Persistence MUST NOT block validation — errors are logged but the pipeline continues.

Listens To: IndicatorSignalReceived
Emits: nothing (side-effect: DB row inserted)
"""

import json
import logging

from core.event_bus import bus as _default_bus
from core.events import IndicatorSignalReceived
from data.persistence_store import insert_indicator_signal

log = logging.getLogger(__name__)


@_default_bus.on(IndicatorSignalReceived)
async def persist_indicator_signal(event: IndicatorSignalReceived) -> None:
    """
    Insert indicator signal to DB before validation occurs.
    Errors are logged but do NOT block the SignalProcessor pipeline (DI-1).
    """
    try:
        await insert_indicator_signal(
            signal_id=event.signal_id,
            symbol=event.symbol,
            indicator_name=event.indicator_name,
            signal_type=event.signal_type,
            interval=event.interval,
            price=event.price,
            confidence_score=event.confidence_score,
            conditions_met=json.dumps(list(event.conditions_met))
            if event.conditions_met
            else "[]",
            metadata=json.dumps(event.metadata) if event.metadata else "{}",
            source_ip=event.source_ip,
            exchange=event.exchange,
        )
    except Exception as e:
        log.error(
            f"IndicatorPersistence: Failed to persist signal #{event.signal_id} "
            f"({event.indicator_name} / {event.symbol}): {e}"
        )
        # Do NOT re-raise — pipeline must continue (DI-1)
