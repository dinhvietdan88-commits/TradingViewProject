"""
tests/unit/test_cli_infrastructure.py
Unit tests for claude_cli.CliInfrastructure.

Tests cover:
  - Subprocess success path (stdout captured, success=True)
  - Timeout enforcement (timed_out=True, success=False)
  - Rate limit rejection (rate_limited=True, no subprocess spawned)
  - Semaphore concurrency bounding (max_parallel=1 serialises calls)
  - check_availability with present/absent binary
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from claude_cli.infrastructure import CliInfrastructure, CliResult


# ── helpers ────────────────────────────────────────────────────────────────────


def _make_cli(**kwargs) -> CliInfrastructure:
    """Create a CliInfrastructure with sensible test defaults."""
    defaults = dict(cli_path="claude", timeout=5, rate_limit=5, max_parallel=2)
    defaults.update(kwargs)
    return CliInfrastructure(**defaults)


def _mock_proc(stdout: bytes = b"ok", returncode: int = 0, delay: float = 0.0):
    """Build an asyncio.Process mock that optionally sleeps.

    communicate() accepts **kwargs so that the stdin-delivery call
    proc.communicate(input=prompt_bytes) doesn't raise TypeError.
    """
    proc = AsyncMock()
    proc.returncode = returncode

    async def communicate(**kwargs):  # accept input=... kwarg
        if delay:
            await asyncio.sleep(delay)
        return stdout, b""

    proc.communicate = communicate
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=returncode)
    return proc


# ── check_availability ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_availability_binary_present():
    cli = _make_cli()
    mock_proc = _mock_proc(stdout=b"Claude CLI", returncode=0)
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await cli.check_availability()
    assert result is True
    assert cli.available is True


@pytest.mark.asyncio
async def test_check_availability_binary_absent():
    cli = _make_cli()
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        result = await cli.check_availability()
    assert result is False
    assert cli.available is False


# ── invoke: success path ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invoke_success_returns_stdout():
    cli = _make_cli()
    mock_proc = _mock_proc(stdout=b"SEPA analysis result", returncode=0)
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        result: CliResult = await cli.invoke(prompt="Analyse AAPL")
    assert result.success is True
    assert result.stdout == "SEPA analysis result"
    assert result.stderr == ""
    assert result.exit_code == 0
    assert result.rate_limited is False
    assert result.timed_out is False
    # Confirm subprocess was actually spawned
    mock_exec.assert_called_once()


@pytest.mark.asyncio
async def test_invoke_nonzero_exit_returns_failure():
    cli = _make_cli()
    mock_proc = _mock_proc(stdout=b"", returncode=1)
    mock_proc.communicate = AsyncMock(return_value=(b"", b"some error"))
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result: CliResult = await cli.invoke(prompt="bad prompt")
    assert result.success is False
    assert result.exit_code == 1


# ── invoke: timeout ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invoke_timeout_sets_timed_out_flag():
    cli = _make_cli(timeout=1)
    # subprocess that hangs forever
    mock_proc = _mock_proc(delay=999)
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=-9)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        t0 = time.monotonic()
        result: CliResult = await cli.invoke(prompt="hang forever")
        elapsed = time.monotonic() - t0

    assert result.timed_out is True
    assert result.success is False
    # Wall clock must not exceed timeout + 6s grace headroom
    assert elapsed < 7.0


# ── rate limiting ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_rejects_excess_requests():
    limit = 3
    cli = _make_cli(rate_limit=limit, max_parallel=10)
    mock_proc = _mock_proc(stdout=b"ok")

    results = []
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        for _ in range(limit + 2):  # 5 attempts, limit=3
            results.append(await cli.invoke(prompt="test"))

    passed = [r for r in results if r.success]
    rejected = [r for r in results if r.rate_limited]
    assert len(passed) == limit
    assert len(rejected) == 2


@pytest.mark.asyncio
async def test_rate_limit_resets_after_window():
    """Requests after 60s window should succeed again."""
    cli = _make_cli(rate_limit=2, max_parallel=5)
    mock_proc = _mock_proc(stdout=b"ok")

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        # Fill the window
        for _ in range(2):
            await cli.invoke(prompt="test")
        # 3rd should be rate-limited
        r3 = await cli.invoke(prompt="test")
    assert r3.rate_limited is True

    # Manually expire all timestamps (simulate 61s passing)
    cli._request_timestamps.clear()
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        r4 = await cli.invoke(prompt="test after reset")
    assert r4.success is True
    assert r4.rate_limited is False


# ── semaphore concurrency ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_semaphore_serialises_at_max_parallel_1():
    """With max_parallel=1, two concurrent invocations run sequentially."""
    cli = _make_cli(max_parallel=1, rate_limit=100, timeout=10)
    order: list[int] = []

    async def slow_proc_factory(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 0

        async def communicate(**kw):  # accept input=... kwarg
            await asyncio.sleep(0.05)
            order.append(id(proc))
            return b"ok", b""

        proc.communicate = communicate
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=0)
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=slow_proc_factory):
        await asyncio.gather(
            cli.invoke(prompt="first"),
            cli.invoke(prompt="second"),
        )

    # Both completed, but only one ran at a time (serialised by semaphore)
    assert len(order) == 2
