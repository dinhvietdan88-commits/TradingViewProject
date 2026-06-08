import asyncio
import pytest
from unittest.mock import AsyncMock
from workers.ai_circuit_breaker import LLMCircuitBreaker, CircuitState


@pytest.mark.asyncio
async def test_circuit_breaker_initial_state():
    breaker = LLMCircuitBreaker(
        failure_threshold=3, recovery_timeout_sec=2.0, call_timeout_sec=1.0
    )
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0
    assert breaker.is_available() is True

    status = breaker.status_dict
    assert status["circuit_state"] == "closed"
    assert status["failure_count"] == 0
    assert status["failure_threshold"] == 3


@pytest.mark.asyncio
async def test_circuit_breaker_record_failure_trip():
    breaker = LLMCircuitBreaker(
        failure_threshold=3, recovery_timeout_sec=2.0, call_timeout_sec=1.0
    )

    # 1st failure
    breaker.record_failure("error 1")
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 1
    assert breaker.is_available() is True

    # 2nd failure
    breaker.record_failure("error 2")
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 2
    assert breaker.is_available() is True

    # 3rd failure (trips to OPEN)
    breaker.record_failure("error 3")
    assert breaker.state == CircuitState.OPEN
    assert breaker.failure_count == 3
    assert breaker.is_available() is False
    assert breaker.total_fallbacks == 1


@pytest.mark.asyncio
async def test_circuit_breaker_recovery_path():
    breaker = LLMCircuitBreaker(
        failure_threshold=2, recovery_timeout_sec=0.1, call_timeout_sec=1.0
    )

    # Trip the breaker
    breaker.record_failure("err 1")
    breaker.record_failure("err 2")
    assert breaker.state == CircuitState.OPEN
    assert breaker.is_available() is False

    # Wait for recovery timeout
    await asyncio.sleep(0.15)

    # is_available transitions to HALF_OPEN
    assert breaker.is_available() is True
    assert breaker.state == CircuitState.HALF_OPEN

    # Record success -> CLOSED
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0
    assert breaker.total_successes == 1


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_failure_re_opens():
    breaker = LLMCircuitBreaker(
        failure_threshold=2, recovery_timeout_sec=0.1, call_timeout_sec=1.0
    )

    # Trip
    breaker.record_failure("err 1")
    breaker.record_failure("err 2")

    # Wait for recovery
    await asyncio.sleep(0.15)
    assert breaker.is_available() is True
    assert breaker.state == CircuitState.HALF_OPEN

    # Failure in HALF_OPEN -> immediately goes back to OPEN
    breaker.record_failure("probe err")
    assert breaker.state == CircuitState.OPEN
    assert breaker.is_available() is False


@pytest.mark.asyncio
async def test_circuit_breaker_alert_hooks():
    breaker = LLMCircuitBreaker(
        failure_threshold=2, recovery_timeout_sec=10.0, call_timeout_sec=1.0
    )

    mock_hook = AsyncMock()
    breaker.alert_hook = mock_hook

    # Trip
    breaker.record_failure("trip error")
    breaker.record_failure("trip error 2")
    assert breaker.state == CircuitState.OPEN

    # Let event loop process tasks if run in loop
    await asyncio.sleep(0.05)
    mock_hook.assert_called_once()
    assert "LLM CIRCUIT BREAKER — OPEN" in mock_hook.call_args[0][0]

    # Success alert
    mock_hook.reset_mock()
    breaker.state = CircuitState.HALF_OPEN
    breaker.record_success()
    await asyncio.sleep(0.05)
    mock_hook.assert_called_once()
    assert "LLM CIRCUIT BREAKER — RECOVERED" in mock_hook.call_args[0][0]
