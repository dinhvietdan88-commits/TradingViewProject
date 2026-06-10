import pathlib
import sys

import pytest
import pytest_asyncio

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
import config
import database
from core.consensus import ConsensusEngine
from core.events import ConsensusEvaluated
from core.event_bus import EventBus


@pytest_asyncio.fixture(autouse=True)
async def isolated_db(tmp_path):
    db_file = str(tmp_path / "test.db")
    config.DB_PATH = db_file
    await database.init_db()
    yield


@pytest.mark.asyncio
async def test_consensus_standard_operation_majority_passes():
    test_bus = EventBus()
    engine = ConsensusEngine(event_bus=test_bus)

    # 3 GO/WARN, 1 BLOCK -> Passes
    votes = {"sa": "GO", "sre": "WARN", "meta": "GO", "ac": "BLOCK"}
    events = []

    @test_bus.on(ConsensusEvaluated)
    async def on_evaluated(event):
        events.append(event)

    verdict = await engine.evaluate(
        operation="run_scanner",
        votes=votes,
        rationale="Standard operation test",
        details={"foo": "bar"},
    )

    assert verdict == "GO"
    assert len(events) == 1
    assert events[0].final_verdict == "GO"
    assert events[0].operation == "run_scanner"

    # Check DB entry
    logs = await database.get_consensus_audit_logs(limit=10)
    assert len(logs) == 1
    assert logs[0]["operation"] == "run_scanner"
    assert logs[0]["final_verdict"] == "GO"
    assert logs[0]["sa_verdict"] == "GO"
    assert logs[0]["ac_verdict"] == "BLOCK"


@pytest.mark.asyncio
async def test_consensus_standard_operation_no_majority_fails():
    test_bus = EventBus()
    engine = ConsensusEngine(event_bus=test_bus)

    # 2 GO/WARN, 2 BLOCK -> Fails
    votes = {"sa": "GO", "sre": "BLOCK", "meta": "WARN", "ac": "BLOCK"}
    verdict = await engine.evaluate(operation="run_scanner", votes=votes)

    assert verdict == "BLOCK"


@pytest.mark.asyncio
async def test_consensus_critical_operation_fails_on_any_block():
    test_bus = EventBus()
    engine = ConsensusEngine(event_bus=test_bus)

    # 3 GO/WARN, 1 BLOCK -> Critical fails
    votes = {"sa": "GO", "sre": "WARN", "meta": "GO", "ac": "BLOCK"}
    verdict = await engine.evaluate(operation="disable_circuit_breaker", votes=votes)

    assert verdict == "BLOCK"


@pytest.mark.asyncio
async def test_consensus_critical_operation_passes_all_go_or_warn():
    test_bus = EventBus()
    engine = ConsensusEngine(event_bus=test_bus)

    votes = {"sa": "GO", "sre": "WARN", "meta": "GO", "ac": "WARN"}
    verdict = await engine.evaluate(operation="disable_circuit_breaker", votes=votes)

    assert verdict == "GO"


@pytest.mark.asyncio
async def test_consensus_override_tokens():
    test_bus = EventBus()
    engine = ConsensusEngine(event_bus=test_bus)

    # All BLOCKs but with creative_violation override token -> Passes
    votes = {"sa": "BLOCK", "sre": "BLOCK", "meta": "BLOCK", "ac": "BLOCK"}
    verdict = await engine.evaluate(
        operation="disable_circuit_breaker",
        votes=votes,
        override_token="[creative_violation]",
        rationale="Overriding blocks",
    )

    assert verdict == "GO"

    # All BLOCKs but with documentation_only override token -> Passes
    verdict2 = await engine.evaluate(
        operation="disable_circuit_breaker",
        votes=votes,
        override_token="[documentation_only]",
    )

    assert verdict2 == "GO"

    # All BLOCKs with random override token -> Fails
    verdict3 = await engine.evaluate(
        operation="disable_circuit_breaker",
        votes=votes,
        override_token="[invalid_token]",
    )

    assert verdict3 == "BLOCK"
