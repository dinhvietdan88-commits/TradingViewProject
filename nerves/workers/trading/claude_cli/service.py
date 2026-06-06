"""
service.py — ClaudeService (AnalysisOrchestrator) + ContextManager.

Responsibilities:
- ContextManager: Single owner of per-symbol conversation context, depth/token pruning,
  and SEPA system prompt. All mutable context state lives here.
- ClaudeService: Stateless orchestrator — assembles prompts from system context,
  RAG chunks, and conversation history; delegates SDK calls to SdkClient;
  parses responses. Named ClaudeService for backward API compatibility.

Design invariants:
- ClaudeService holds no state between requests — all state in SdkClient or ContextManager.
- Context state is ONLY mutated through ContextManager; interface layers are read-only consumers.
- Single response type: all paths produce AnalysisResponse (no CliResult).
"""

from __future__ import annotations

import importlib.util
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import config

if TYPE_CHECKING:
    from .sdk_client import SdkClient

log = logging.getLogger(__name__)

ANTHROPIC_AVAILABLE = importlib.util.find_spec("anthropic") is not None

# ─── Public dataclasses ────────────────────────────────────────────────────────


@dataclass
class AnalysisRequest:
    """Input to ClaudeService for any analysis."""

    query: str
    symbol: str = ""
    action: str = ""
    price: float | None = None
    trading_context: dict | None = None  # positions, signals, watchlist
    include_rag_context: bool = True
    image_path: str | None = None  # reserved for future vision integration


@dataclass
class AnalysisResponse:
    """Output from ClaudeService (single response type for all paths)."""

    text: str
    confidence: int = 5  # 1-10 scale
    source: str = "anthropic_api"  # "anthropic_api" | "none"
    duration_seconds: float = 0.0
    context_tokens_used: int = 0
    error: str = ""
    rate_limited: bool = False
    timed_out: bool = False


@dataclass
class ContextEntry:
    """Single conversation turn in per-symbol history."""

    role: str  # "user" | "assistant"
    content: str
    timestamp: float
    estimated_tokens: int


# ─── SEPA System Prompt ────────────────────────────────────────────────────────

_SEPA_SYSTEM_PROMPT_TEMPLATE = """Bạn là chuyên gia giao dịch theo phương pháp SEPA (Specific Entry Point Analysis) \
của Mark Minervini. Nhiệm vụ của bạn là phân tích các tín hiệu giao dịch và đưa ra khuyến nghị \
dựa trên nguyên tắc SEPA chính xác, ngắn gọn, và có thể hành động ngay.

Nguyên tắc cốt lõi:
- Trend Template: 8 tiêu chí xác nhận Stage 2 uptrend
- VCP (Volatility Contraction Pattern): tìm điểm breakout từ base có volume cạn
- Risk Management: SL tối đa 7-8%, R:R tối thiểu 2.5:1
- Volume xác nhận: breakout cần volume ≥ 150% trung bình 50 phiên
- Không mua khi thị trường chung Stage 3/4 (distribution)

Trả lời NGẮN GỌN (dưới 200 từ), dùng emoji để dễ đọc trên Telegram.
Luôn kết thúc bằng mức confidence 1-10 theo format: [Confidence: X/10]
"""


# ─── ContextManager ───────────────────────────────────────────────────────────


class ContextManager:
    """Per-symbol conversation context with FIFO pruning.

    Owns all mutable context state. The orchestrator reads/writes
    through this interface but never holds context references directly.

    Property guarantees:
        Property 3: context depth ≤ CLAUDE_CONTEXT_DEPTH per symbol
        Property 4: context token total ≤ CLAUDE_MAX_CONTEXT_TOKENS per symbol
        Property 10: reset() clears exactly what is requested
    """

    def __init__(
        self,
        context_depth: int = 0,
        max_context_tokens: int = 0,
    ):
        self._contexts: dict[str, list[ContextEntry]] = {}
        self._context_depth: int = context_depth or getattr(
            config, "CLAUDE_CONTEXT_DEPTH", 5
        )
        self._max_context_tokens: int = max_context_tokens or getattr(
            config, "CLAUDE_MAX_CONTEXT_TOKENS", 50_000
        )
        self._system_prompt: str = _SEPA_SYSTEM_PROMPT_TEMPLATE

    async def load_system_prompt(self) -> None:
        """Enrich system prompt with top RAG chunks. Called at startup."""
        try:
            import rag

            chunks = rag.query_knowledge(
                "SEPA Trend Template VCP pivot breakout", n_results=2
            )
            if chunks:
                extra = "\n\n---\n".join(c["content"][:600] for c in chunks)
                self._system_prompt = (
                    _SEPA_SYSTEM_PROMPT_TEMPLATE
                    + "\n\n## Tham khảo từ Minervini Knowledge Base:\n"
                    + extra
                )
                log.info(
                    f"ContextManager: system prompt enriched with {len(chunks)} RAG chunks"
                )
        except Exception as exc:
            log.warning(f"ContextManager: RAG enrichment skipped: {exc}")

    @property
    def system_prompt(self) -> str:
        """The current SEPA system prompt (possibly RAG-enriched)."""
        return self._system_prompt

    def get_history(self, symbol: str, max_turns: int = 0) -> list[ContextEntry]:
        """Return conversation history for a symbol (most recent N turns)."""
        key = symbol or "__global__"
        entries = self._contexts.get(key, [])
        if max_turns and max_turns > 0:
            return entries[-max_turns:]
        return list(entries)

    def update(self, symbol: str, query: str, response: str) -> None:
        """Append user+assistant turn and prune."""
        key = symbol or "__global__"
        if key not in self._contexts:
            self._contexts[key] = []

        self._contexts[key].append(
            ContextEntry(
                role="user",
                content=query,
                timestamp=time.monotonic(),
                estimated_tokens=self._estimate_tokens(query),
            )
        )
        self._contexts[key].append(
            ContextEntry(
                role="assistant",
                content=response,
                timestamp=time.monotonic(),
                estimated_tokens=self._estimate_tokens(response),
            )
        )
        self._prune(key)

    def reset(self, symbol: str = "") -> None:
        """Clear context for a symbol, or all if symbol is empty.

        Property 10 guarantee.
        """
        if symbol:
            cleared = len(self._contexts.pop(symbol, []))
            log.info(f"ContextManager: context cleared for {symbol} ({cleared} turns)")
        else:
            total = sum(len(v) for v in self._contexts.values())
            self._contexts.clear()
            log.info(f"ContextManager: ALL context cleared ({total} total turns)")

    def get_stats(self) -> dict:
        """Return context usage stats per symbol."""
        stats: dict = {"symbols": {}}
        for sym, entries in self._contexts.items():
            total_tokens = sum(e.estimated_tokens for e in entries)
            stats["symbols"][sym] = {
                "turns": len(entries),
                "estimated_tokens": total_tokens,
            }
        stats["total_symbols"] = len(self._contexts)
        stats["total_turns"] = sum(len(v) for v in self._contexts.values())
        stats["total_estimated_tokens"] = sum(
            e.estimated_tokens for entries in self._contexts.values() for e in entries
        )
        return stats

    def total_tokens(self, symbol: str) -> int:
        """Current estimated token count for a symbol."""
        key = symbol or "__global__"
        return sum(e.estimated_tokens for e in self._contexts.get(key, []))

    def _prune(self, symbol: str) -> None:
        """Remove oldest entries until both:
          - len(entries) ≤ 2 × context_depth (turns = user+assistant pairs)
          - total estimated tokens ≤ max_context_tokens

        Property 3 & 4 guarantees.
        """
        entries = self._contexts.get(symbol, [])
        max_turns = self._context_depth * 2

        # Depth pruning
        while len(entries) > max_turns:
            entries.pop(0)

        # Token budget pruning
        while (
            entries
            and sum(e.estimated_tokens for e in entries) > self._max_context_tokens
        ):
            entries.pop(0)

        self._contexts[symbol] = entries

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate: chars / 4 (conservative, skewed for mixed EN/VI)."""
        return max(1, len(text) // 4)


# ─── ClaudeService (AnalysisOrchestrator) ──────────────────────────────────────


class ClaudeService:
    """Stateless orchestrator for Claude SDK analysis.

    Lifecycle:
        svc = ClaudeService(sdk)
        await svc.initialize()   # called at app startup
        response = await svc.analyze(request)
        response = await svc.query("explain VCP", symbol="BTCUSDT")

    Named ClaudeService for backward API compatibility.
    Functionally acts as the AnalysisOrchestrator defined in design.md.

    Property guarantees:
        Property 5: error responses have source="none" and confidence=0
        Property 6: AnalysisComplete structural equivalence (via EventBusInterface)
    """

    def __init__(self, sdk: SdkClient, ctx: ContextManager | None = None):
        self._sdk = sdk
        self._ctx = ctx or ContextManager()
        self._initialized: bool = False

    # ── Lifecycle ───────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Load system prompt via ContextManager.
        Called once during app startup via lifespan hook.
        """
        if self._initialized:
            return
        await self._ctx.load_system_prompt()
        self._initialized = True
        log.info("ClaudeService initialized (SDK-Headless mode).")

    # ── Public API ──────────────────────────────────────────────────────────────

    async def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        """Main entry point for all structured trading analysis requests.

        Steps:
            1. Assemble prompt (system + RAG + context + query)
            2. Call SdkClient.invoke()
            3. Parse confidence from response text
            4. Update per-symbol context via ContextManager
            5. Return AnalysisResponse
        """
        t_start = time.monotonic()
        prompt = await self._assemble_prompt(request)

        # ── SDK call ─────────────────────────────────────────────────────
        response = await self._sdk.invoke(
            prompt=prompt,
            system_prompt=self._ctx.system_prompt,
        )

        if response.source != "none":
            # Success — parse confidence and update context
            response.confidence = self._parse_confidence(response.text)
            response.context_tokens_used = self._ctx.total_tokens(request.symbol)
            self._ctx.update(request.symbol, request.query, response.text)
        else:
            # SDK error — ensure total duration is recorded
            response.duration_seconds = time.monotonic() - t_start

        return response

    async def query(self, query: str, symbol: str = "") -> AnalysisResponse:
        """Simplified entry for ad-hoc queries without full trading context."""
        return await self.analyze(
            AnalysisRequest(
                query=query,
                symbol=symbol,
                include_rag_context=False,
            )
        )

    def reset_context(self, symbol: str = "") -> None:
        """Delegate to ContextManager.reset(). Property 10 guarantee."""
        self._ctx.reset(symbol)

    def get_context_stats(self) -> dict:
        """Delegate to ContextManager.get_stats()."""
        return self._ctx.get_stats()

    # ── Private helpers ─────────────────────────────────────────────────────────

    async def _assemble_prompt(self, request: AnalysisRequest) -> str:
        """Build the full prompt: optional RAG context + conversation history + query."""
        parts: list[str] = []

        # RAG context (Minervini chunks)
        if request.include_rag_context:
            try:
                import rag

                query_hint = f"{request.action} {request.symbol} {request.query}"
                chunks = rag.query_knowledge(query_hint.strip(), n_results=2)
                if chunks:
                    rag_text = "\n\n---\n".join(
                        f"[{c['metadata'].get('topic', 'chunk')} | score={c['relevance_score']:.2%}]\n"
                        + c["content"][:600]
                        for c in chunks
                    )
                    parts.append(f"## Kiến thức Minervini liên quan:\n{rag_text}")
            except Exception as exc:
                log.debug(f"ClaudeService: RAG retrieval skipped in prompt: {exc}")

        # Trading context (positions, signals)
        if request.trading_context:
            ctx_lines = []
            for k, v in request.trading_context.items():
                ctx_lines.append(f"- {k}: {v}")
            if ctx_lines:
                parts.append("## Bối cảnh giao dịch:\n" + "\n".join(ctx_lines))

        # Symbol + action metadata
        if request.symbol:
            meta = [f"Symbol: {request.symbol}"]
            if request.action:
                meta.append(f"Action: {request.action.upper()}")
            if request.price is not None:
                meta.append(f"Price: {request.price}")
            parts.append("## Tín hiệu:\n" + " | ".join(meta))

        # Conversation history for this symbol
        depth = getattr(self._ctx, "_context_depth", 5)
        history = self._ctx.get_history(
            request.symbol or "__global__", max_turns=depth * 2
        )
        if history:
            hist_lines = []
            for entry in history:
                tag = "User" if entry.role == "user" else "Claude"
                hist_lines.append(f"[{tag}]: {entry.content[:400]}")
            parts.append("## Lịch sử hội thoại:\n" + "\n".join(hist_lines))

        # The actual query
        parts.append(f"## Câu hỏi / Yêu cầu:\n{request.query}")

        return "\n\n".join(parts)

    @staticmethod
    def _parse_confidence(text: str) -> int:
        """Extract confidence from text matching patterns like:
            [Confidence: 7/10]  or  Confidence: 8/10  or  độ tin cậy: 6
        Returns integer 1–10, defaults to 5 if not found.
        """
        patterns = [
            r"\[Confidence:\s*(\d+)/10\]",
            r"Confidence:\s*(\d+)/10",
            r"độ\s*tin\s*cậy:\s*(\d+)",
            r"\b(\d+)/10\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = int(m.group(1))
                return max(1, min(10, val))
        return 5
