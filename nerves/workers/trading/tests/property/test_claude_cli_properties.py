"""
tests/property/test_claude_cli_properties.py
Property-based tests for claude_cli invariants (hypothesis, 100 examples each).

Properties tested:
  P2: Rate limiting correctness (sliding window) — SdkClient
  P3: Context depth enforcement (FIFO, depth*2 entries max) — ContextManager
  P4: Context token limit enforcement (FIFO, token budget) — ContextManager
  P7: Telegram response length ≤ 4096
  P10: Context reset completeness (per-symbol & global)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from claude_cli.sdk_client import SdkClient
from claude_cli.service import (
    ClaudeService,
    ContextManager,
    AnalysisRequest,
    AnalysisResponse,
)
from claude_cli.telegram_commands import _format_response


# ── helpers ─────────────────────────────────────────────────────────────────────


def _run(coro):
    return asyncio.run(coro)


def _make_sdk(text: str = "ok [Confidence: 7/10]") -> MagicMock:
    sdk = MagicMock(spec=SdkClient)
    sdk.available = True
    sdk.invoke = AsyncMock(
        return_value=AnalysisResponse(
            text=text, confidence=5, source="anthropic_api", duration_seconds=0.01
        )
    )
    return sdk


def _make_svc(depth: int = 5, max_tokens: int = 50_000) -> ClaudeService:
    ctx = ContextManager(context_depth=depth, max_context_tokens=max_tokens)
    svc = ClaudeService(_make_sdk(), ctx)
    svc._initialized = True
    return svc


# ── P2: Rate Limiting (SdkClient internal) ──────────────────────────────────────


@given(
    limit=st.integers(min_value=1, max_value=10),
    extra=st.integers(min_value=1, max_value=5),
)
@settings(max_examples=100, deadline=None)
def test_p2_rate_limit_exactly_n_pass(limit, extra):
    """Exactly `limit` requests pass; the rest are rate-limited."""
    sdk = SdkClient(
        api_key="test-key",
        rate_limit=limit,
        max_parallel=limit + extra + 1,
        timeout=5,
    )
    # Manually simulate: fill timestamps up to `limit`
    import time

    now = time.monotonic()
    sdk._request_timestamps = [now for _ in range(limit)]
    sdk._available = True

    # After limit timestamps, next check should fail
    assert sdk._check_rate_limit() is False

    # Clear and verify fresh state passes
    sdk._request_timestamps = []
    for _i in range(limit):
        assert sdk._check_rate_limit() is True
        sdk._request_timestamps.append(time.monotonic())

    # One more should be rejected
    assert sdk._check_rate_limit() is False


# ── P3: Context Depth Enforcement ───────────────────────────────────────────────


@given(
    depth=st.integers(min_value=1, max_value=5),
    interactions=st.integers(min_value=1, max_value=20),
)
@settings(max_examples=100, deadline=None)
def test_p3_context_depth_never_exceeded(depth, interactions):
    """Context per symbol never exceeds depth*2 entries."""
    svc = _make_svc(depth=depth, max_tokens=10_000_000)

    async def run():
        for i in range(interactions):
            await svc.analyze(
                AnalysisRequest(query=f"q{i}", symbol="SYM", include_rag_context=False)
            )

    _run(run())
    ctx = svc._ctx.get_history("SYM")
    assert len(ctx) <= depth * 2, (
        f"depth={depth}, interactions={interactions}, got {len(ctx)}"
    )


# ── P4: Context Token Budget Enforcement ────────────────────────────────────────


@given(
    max_tokens=st.integers(min_value=10, max_value=500),
    interactions=st.integers(min_value=1, max_value=15),
)
@settings(max_examples=100, deadline=None)
def test_p4_token_budget_never_exceeded(max_tokens, interactions):
    """Total estimated tokens per symbol never exceeds max_tokens after pruning."""
    svc = _make_svc(
        depth=100, max_tokens=max_tokens
    )  # depth huge → token is the binding constraint

    async def run():
        for i in range(interactions):
            await svc.analyze(
                AnalysisRequest(
                    query=f"query number {i} with some text",
                    symbol="TOK",
                    include_rag_context=False,
                )
            )

    _run(run())
    ctx = svc._ctx.get_history("TOK")
    total = sum(e.estimated_tokens for e in ctx)
    assert total <= max_tokens, f"max_tokens={max_tokens}, got {total}"


# ── P7: Telegram Response Length ─────────────────────────────────────────────────


@given(
    text=st.text(min_size=0, max_size=10_000),
    source=st.sampled_from(["anthropic_api", "none"]),
    confidence=st.integers(min_value=0, max_value=10),
    duration=st.floats(min_value=0.0, max_value=120.0, allow_nan=False),
)
@settings(max_examples=100, deadline=None)
def test_p7_telegram_response_never_exceeds_4096(text, source, confidence, duration):
    """Formatted Telegram message is always ≤ 4096 characters."""
    formatted = _format_response(
        text=text, source=source, confidence=confidence, duration=duration
    )
    assert len(formatted) <= 4096, f"Message exceeded 4096: len={len(formatted)}"


# ── P10: Context Reset Completeness ─────────────────────────────────────────────


@given(
    symbols=st.lists(
        st.text(min_size=1, max_size=10, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        min_size=1,
        max_size=5,
        unique=True,
    ),
    target_idx=st.integers(min_value=0, max_value=4),
)
@settings(max_examples=100, deadline=None)
def test_p10_per_symbol_reset_clears_only_target(symbols, target_idx):
    """reset() clears exactly that symbol, others unchanged."""
    assume(len(symbols) > 0)
    target_idx = target_idx % len(symbols)
    target = symbols[target_idx]

    ctx = ContextManager()
    for sym in symbols:
        ctx.update(sym, "question", "answer")

    ctx.reset(target)

    assert len(ctx.get_history(target)) == 0, f"Symbol {target} not cleared"
    for sym in symbols:
        if sym != target:
            assert len(ctx.get_history(sym)) > 0, (
                f"Symbol {sym} was incorrectly cleared"
            )


@given(
    symbols=st.lists(
        st.text(min_size=1, max_size=10, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        min_size=1,
        max_size=6,
        unique=True,
    )
)
@settings(max_examples=100, deadline=None)
def test_p10_global_reset_clears_all(symbols):
    """reset('') clears ALL symbol contexts."""
    ctx = ContextManager()
    for sym in symbols:
        ctx.update(sym, "question", "answer")

    ctx.reset("")
    assert ctx.get_stats()["total_turns"] == 0, f"Global reset left: {ctx.get_stats()}"
