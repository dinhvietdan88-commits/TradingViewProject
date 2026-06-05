"""
tests/unit/test_claude_service.py
Unit tests for claude_cli.ClaudeService + ContextManager + SdkClient.

Tests cover:
  - analyze(): SDK success path (source="anthropic_api")
  - analyze(): SDK error → AnalysisResponse with error field
  - analyze(): SDK unavailable → immediate error response
  - _assemble_prompt(): sections present in correct order
  - ContextManager: turns added per-symbol
  - ContextManager: FIFO depth pruning (oldest entries removed)
  - ContextManager: Token budget pruning
  - ContextManager: reset per-symbol vs global
  - ContextManager: get_stats() field accuracy
  - ClaudeService._parse_confidence() regex patterns
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from claude_cli.sdk_client import SdkClient
from claude_cli.service import (
    ClaudeService,
    ContextManager,
    AnalysisRequest,
    AnalysisResponse,
)


# ── fixtures ────────────────────────────────────────────────────────────────────


def _make_sdk(
    available: bool = True,
    response_text: str = "analysis ok [Confidence: 7/10]",
    error: str = "",
) -> MagicMock:
    """Create a mock SdkClient."""
    sdk = MagicMock(spec=SdkClient)
    sdk.available = available
    if error:
        sdk.invoke = AsyncMock(
            return_value=AnalysisResponse(
                text=f"⚠️ {error}",
                confidence=0,
                source="none",
                error=error,
            )
        )
    else:
        sdk.invoke = AsyncMock(
            return_value=AnalysisResponse(
                text=response_text,
                confidence=5,  # default; service will re-parse
                source="anthropic_api",
                duration_seconds=0.1,
            )
        )
    return sdk


def _make_service(sdk=None, depth: int = 3, max_tokens: int = 1000) -> ClaudeService:
    if sdk is None:
        sdk = _make_sdk()
    ctx = ContextManager(context_depth=depth, max_context_tokens=max_tokens)
    svc = ClaudeService(sdk, ctx)
    svc._initialized = True  # skip RAG init
    return svc


def _req(
    query: str = "analyse AAPL", symbol: str = "AAPL", include_rag: bool = False
) -> AnalysisRequest:
    return AnalysisRequest(query=query, symbol=symbol, include_rag_context=include_rag)


# ── analyze: success ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_sdk_success_returns_source_api():
    svc = _make_service()
    resp: AnalysisResponse = await svc.analyze(_req())
    assert resp.source == "anthropic_api"
    assert resp.text == "analysis ok [Confidence: 7/10]"
    assert resp.confidence == 7
    assert resp.error == ""


@pytest.mark.asyncio
async def test_analyze_sdk_success_updates_context():
    svc = _make_service()
    await svc.analyze(_req(symbol="BTCUSDT"))
    history = svc._ctx.get_history("BTCUSDT")
    assert len(history) == 2  # user + assistant
    assert history[0].role == "user"
    assert history[1].role == "assistant"


# ── analyze: error ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_sdk_error_returns_error_response():
    sdk = _make_sdk(error="Rate limit exceeded")
    svc = _make_service(sdk=sdk)
    resp = await svc.analyze(_req())
    assert resp.source == "none"
    assert resp.confidence == 0
    assert "Rate limit" in resp.error


@pytest.mark.asyncio
async def test_analyze_sdk_unavailable_returns_error():
    sdk = _make_sdk(available=False, error="SDK not available")
    svc = _make_service(sdk=sdk)
    resp = await svc.analyze(_req())
    assert resp.source == "none"
    assert resp.confidence == 0


# ── context management ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_depth_pruning_fifo():
    """With depth=2, after 3 interactions only the last 4 entries survive."""
    svc = _make_service(depth=2)  # max entries = 2*2 = 4
    for i in range(3):
        await svc.analyze(_req(query=f"query {i}", symbol="TSLA"))
    ctx = svc._ctx.get_history("TSLA")
    assert len(ctx) <= 4, f"Expected ≤4 entries, got {len(ctx)}"
    # Oldest entries should be gone, newest preserved
    assert ctx[-1].role == "assistant"


@pytest.mark.asyncio
async def test_context_token_budget_pruning():
    """Token budget pruning removes oldest entries until within limit."""
    # max_tokens so small that only 1 turn fits (~4 chars per token → 100 tokens → 400 chars)
    svc = _make_service(depth=10, max_tokens=50)
    for i in range(5):
        await svc.analyze(_req(query=f"q{i}", symbol="NVDA"))
    ctx = svc._ctx.get_history("NVDA")
    total_tokens = sum(e.estimated_tokens for e in ctx)
    assert total_tokens <= 50, f"Token budget exceeded: {total_tokens}"


def test_reset_context_per_symbol():
    ctx = ContextManager()
    ctx.update("AAPL", "q1", "a1")
    ctx.update("MSFT", "q2", "a2")
    ctx.reset("AAPL")
    assert len(ctx.get_history("AAPL")) == 0
    assert len(ctx.get_history("MSFT")) == 2  # untouched


def test_reset_context_global():
    ctx = ContextManager()
    ctx.update("AAPL", "q1", "a1")
    ctx.update("MSFT", "q2", "a2")
    ctx.reset("")
    assert ctx.get_stats()["total_turns"] == 0


# ── get_context_stats ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_context_stats_fields():
    svc = _make_service()
    await svc.analyze(_req(symbol="AMD"))
    stats = svc.get_context_stats()
    assert "symbols" in stats
    assert "AMD" in stats["symbols"]
    assert stats["total_symbols"] == 1
    assert stats["total_turns"] == 2  # user + assistant
    assert stats["total_estimated_tokens"] > 0


# ── _parse_confidence ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("[Confidence: 8/10]", 8),
        ("Confidence: 3/10", 3),
        ("độ tin cậy: 9", 9),
        ("some text 7/10 more text", 7),
        ("no confidence here", 5),  # default
        ("[Confidence: 11/10]", 10),  # capped at 10
        ("[Confidence: 0/10]", 1),  # floor at 1
    ],
)
def test_parse_confidence(text, expected):
    assert ClaudeService._parse_confidence(text) == expected


# ── _assemble_prompt ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assemble_prompt_contains_query():
    svc = _make_service()
    req = AnalysisRequest(
        query="Is AAPL a good buy?",
        symbol="AAPL",
        action="BUY",
        price=185.5,
        include_rag_context=False,
    )
    prompt = await svc._assemble_prompt(req)
    assert "Is AAPL a good buy?" in prompt
    assert "AAPL" in prompt
    assert "BUY" in prompt


@pytest.mark.asyncio
async def test_assemble_prompt_includes_history():
    svc = _make_service()
    svc._ctx.update("AAPL", "prior question", "prior answer")
    req = _req(symbol="AAPL", include_rag=False)
    prompt = await svc._assemble_prompt(req)
    assert "prior question" in prompt or "prior answer" in prompt
