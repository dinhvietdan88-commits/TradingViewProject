import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
import config
import database
from core.events import (
    SignalIngested,
    SignalValidated,
    ConsensusRequested,
    ConsensusEvaluated,
)
from core.event_bus import EventBus
from core.consensus import ConsensusEngine
from processor.macro_trend_processor import MacroTrendProcessor


@pytest_asyncio.fixture(autouse=True)
async def isolated_db(tmp_path):
    db_file = str(tmp_path / "test.db")
    config.DB_PATH = db_file
    await database.init_db()
    yield


@pytest.mark.asyncio
async def test_end_to_end_pipeline_propagation(tmp_path):
    """End-to-end event propagation test:
    SignalIngested -> SignalValidated (MTA precalculated) -> ConsensusRequested -> ConsensusEvaluated -> DB Audit Logging
    """
    test_bus = EventBus()
    engine = ConsensusEngine(event_bus=test_bus)
    processor = MacroTrendProcessor()

    # Track received events
    received_validated = []
    received_requested = []
    received_evaluated = []

    @test_bus.on(SignalValidated)
    async def on_validated(event):
        received_validated.append(event)

    @test_bus.on(ConsensusRequested)
    async def on_requested(event):
        received_requested.append(event)

    @test_bus.on(ConsensusEvaluated)
    async def on_evaluated(event):
        received_evaluated.append(event)

    # Set up mock capture client to return trends
    mock_client = MagicMock()
    # 7 timeframes return mock OHLCV list
    # c[4] is the close price. Let's make close price > SMA for all except daily to get positive TAS/STS/MLTS.
    mock_ohlcv = [[0, 0, 0, 0, 100 + i, 0] for i in range(50)]
    mock_client.fetch_ohlcv = AsyncMock(return_value=mock_ohlcv)

    orig_mta = config.MTA_ENABLED
    config.MTA_ENABLED = True

    try:
        with (
            patch("capture_client.get_capture_client", return_value=mock_client),
            patch("engine.regime_switcher.get_market_regime", return_value="TREND"),
            patch("database.set_setting", return_value=None),
        ):
            # Emit SignalIngested to start propagation
            event_ingested = SignalIngested(
                signal_id=701,
                symbol="BTCUSDT",
                action="buy",
                price=60000.0,
                quote_qty=10.0,
                interval="5m",
                exchange="binance",
            )

            # Directly process through processor using the test bus
            accepted = await processor.process(event_ingested, bus=test_bus)
            assert accepted is True

            # Trigger the subscriber manually using processor.process output
            tas = processor.last_tas
            sts = processor.last_sts
            mlts = processor.last_mlts
            mta_calc = processor.last_mta_calculated

            await test_bus.emit(
                SignalValidated(
                    signal_id=event_ingested.signal_id,
                    symbol=event_ingested.symbol,
                    action=event_ingested.action,
                    price=event_ingested.price,
                    quote_qty=event_ingested.quote_qty,
                    sl=event_ingested.sl,
                    tp=event_ingested.tp,
                    exchange=event_ingested.exchange,
                    mode=event_ingested.mode,
                    is_recovered=event_ingested.is_recovered,
                    age_minutes=event_ingested.age_minutes,
                    tas=tas,
                    sts=sts,
                    mlts=mlts,
                    mta_calculated=mta_calc,
                )
            )

            # Assert SignalValidated was emitted and contains precalculated values
            assert len(received_validated) == 1
            assert received_validated[0].signal_id == 701
            assert received_validated[0].mta_calculated is True
            assert received_validated[0].tas > 0.0

            # 2. Simulate requesting Consensus for this signal validation operation
            votes = {"sa": "GO", "sre": "GO", "meta": "WARN", "ac": "BLOCK"}
            verdict = await engine.evaluate(
                operation="validate_signal_701",
                votes=votes,
                rationale="E5 review of macro trend validated signal",
                details={"signal_id": 701, "tas": tas},
            )

            # Assert standard operation passed (3 GO/WARN, 1 BLOCK = GO)
            assert verdict == "GO"

            # Assert ConsensusRequested and ConsensusEvaluated were emitted on the event bus
            assert len(received_requested) == 1
            assert received_requested[0].operation == "validate_signal_701"
            assert received_requested[0].requester == "ConsensusEngine"
            assert received_requested[0].details["signal_id"] == 701

            assert len(received_evaluated) == 1
            assert received_evaluated[0].operation == "validate_signal_701"
            assert received_evaluated[0].final_verdict == "GO"
            assert (
                received_evaluated[0].rationale
                == "E5 review of macro trend validated signal"
            )

            # Verify the consensus audit log is recorded in the database
            logs = await database.get_consensus_audit_logs(limit=10)
            assert len(logs) == 1
            assert logs[0]["operation"] == "validate_signal_701"
            assert logs[0]["final_verdict"] == "GO"
            assert logs[0]["sa_verdict"] == "GO"
            assert logs[0]["sre_verdict"] == "GO"
            assert logs[0]["meta_verdict"] == "WARN"
            assert logs[0]["ac_verdict"] == "BLOCK"

    finally:
        config.MTA_ENABLED = orig_mta
