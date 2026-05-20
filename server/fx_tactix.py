"""
fx_tactix.py — FX Tactix Claude subsystem

Endpoint: POST /api/fx-tactix/generate
Sinh Pine Script v5 từ mô tả tự nhiên qua Claude (subscription CLI / Anthropic SDK / Gemini).
Đây là phương án bổ sung — chạy song song với Minervini engine, không thay thế.

Xem docs/fx_tactix/README.md và .claude/skills/fx-tactix/SKILL.md.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Header, status
from pydantic import BaseModel, Field

import config

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fx-tactix", tags=["fx-tactix"])

GENERATED_DIR = Path(__file__).resolve().parent.parent / "pine" / "v2" / "generated"

Style = Literal["brief", "strategy", "indicator", "backtest_review", "mtf", "alert"]


# ── Prompt templates (mirror docs/fx_tactix/prompts/*.md) ───────────────────
_STRATEGY_PROMPT = """Bạn là Pine Script v5 expert. Sinh code đầy đủ, compile được trên TradingView.

## MÔ TẢ
{description}

## RÀNG BUỘC
- //@version=5 ở dòng đầu
- Loại: {kind} (strategy = có entry/exit; indicator = chỉ plot)
- Risk mặc định nếu strategy: SL {sl_pct:.0%}, TP {tp_pct:.0%}, risk per trade {risk_pct:.0%}
- Mọi magic number → input.* với tooltip tiếng Việt
- Có ≥ 1 alertcondition() với message JSON match webhook schema:
  {{"symbol":"{{{{ticker}}}}","action":"buy|sell","price":"{{{{close}}}}","alert_type":"fx_tactix_v1","timeframe":"{{{{interval}}}}","secret":"INSERT_WEBHOOK_SECRET"}}
- KHÔNG dùng request.security(..., lookahead=barmerge.lookahead_on)
- Tên: snake_case prefix "fx_"

## OUTPUT
Trả về DUY NHẤT 1 block ```pinescript ... ``` — KHÔNG kèm giải thích bên ngoài.
"""

_BRIEF_PROMPT = """Bạn là analyst FX Tactix. Mô tả: {description}
Trả về morning brief ≤ 200 từ tiếng Việt: symbol/tf, price action 24h, SMC (OB/FVG/sweep),
indicator confluence (RSI/MACD/EMA), bias Long/Short/Neutral, kế hoạch entry/SL/TP."""

_BACKTEST_PROMPT = """Bạn là FX Tactix analyst. Review backtest sau:
{description}
Trả về ≤ 250 từ tiếng Việt: đánh giá tổng quan, 3 điểm yếu, 3 chỉnh sửa cụ thể (chỉ rõ biến/dòng),
cảnh báo overfitting nếu có."""

_MTF_PROMPT = """Phân tích đa khung thời gian cho {description}.
Trả về 4 phần: TF cao (bias), TF trung (setup), TF thấp (trigger), KẾT LUẬN (entry/SL/TP).
≤ 300 từ tiếng Việt."""

_ALERT_PROMPT = """Cho Pine code/strategy sau:
{description}
Bổ sung alertcondition() message JSON cho webhook FastAPI (schema: symbol/action/price/alert_type/timeframe/secret).
Trả về Pine v5 code đã chỉnh, kèm hướng dẫn 3 dòng cách paste alert message vào TradingView."""


# ── Request/Response models ──────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    description: str = Field(..., min_length=10, max_length=4000)
    style: Style = "strategy"
    kind: Literal["strategy", "indicator"] = "strategy"
    save: bool = True
    name_hint: Optional[str] = Field(None, max_length=60)


class GenerateResponse(BaseModel):
    status: str
    style: Style
    output: str
    pine_code: Optional[str] = None
    file_path: Optional[str] = None
    provider: str


# ── Helpers ──────────────────────────────────────────────────────────────────
_PINE_FENCE_RE = re.compile(r"```(?:pinescript|pine)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_len: int = 40) -> str:
    s = _SLUG_RE.sub("_", text.lower()).strip("_")
    return (s[:max_len] or "fx_strategy").rstrip("_")


def _extract_pine(text: str) -> Optional[str]:
    m = _PINE_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    if text.lstrip().startswith("//@version="):
        return text.strip()
    return None


def _build_prompt(req: GenerateRequest) -> str:
    if req.style in ("strategy", "indicator"):
        return _STRATEGY_PROMPT.format(
            description=req.description,
            kind=req.kind,
            sl_pct=getattr(config, "STOP_LOSS_PCT", 0.08),
            tp_pct=getattr(config, "TAKE_PROFIT_PCT", 0.20),
            risk_pct=getattr(config, "RISK_PER_TRADE", 0.02),
        )
    if req.style == "brief":
        return _BRIEF_PROMPT.format(description=req.description)
    if req.style == "backtest_review":
        return _BACKTEST_PROMPT.format(description=req.description)
    if req.style == "mtf":
        return _MTF_PROMPT.format(description=req.description)
    if req.style == "alert":
        return _ALERT_PROMPT.format(description=req.description)
    raise HTTPException(status_code=400, detail=f"Unsupported style: {req.style}")


async def _call_provider(prompt: str) -> tuple[str, str]:
    """Return (text, provider_name). Routes through config.AI_PROVIDER."""
    provider = getattr(config, "AI_PROVIDER", "anthropic").lower()

    if provider == "claude_cli":
        try:
            from rag import _call_claude_cli  # reuse subscription path
            text = await _call_claude_cli(prompt)
            return text, "claude_cli"
        except Exception as e:
            log.warning(f"fx-tactix: claude_cli failed ({e}); falling back to anthropic SDK")
            provider = "anthropic"

    if provider == "anthropic":
        import importlib.util
        if importlib.util.find_spec("anthropic") is None or not getattr(config, "ANTHROPIC_API_KEY", None):
            raise HTTPException(status_code=503, detail="Anthropic SDK/API key chưa cấu hình")
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=getattr(config, "ANTHROPIC_MODEL", "claude-sonnet-4-5"),
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text, "anthropic"

    if provider == "gemini":
        import importlib.util
        if importlib.util.find_spec("google.genai") is None or not getattr(config, "GEMINI_API_KEY", None):
            raise HTTPException(status_code=503, detail="Gemini SDK/API key chưa cấu hình")
        from google import genai
        gclient = genai.Client(api_key=config.GEMINI_API_KEY)
        resp = gclient.models.generate_content(
            model=getattr(config, "GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt,
        )
        return resp.text, "gemini"

    raise HTTPException(status_code=500, detail=f"Provider không hỗ trợ: {provider}")


def _save_pine(pine_code: str, name_hint: Optional[str], description: str) -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slugify(name_hint or description)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = GENERATED_DIR / f"fx_{slug}_{ts}.pine"
    path.write_text(pine_code, encoding="utf-8")
    return path


def _check_auth(auth_header: Optional[str]) -> None:
    expected = getattr(config, "WEBHOOK_SECRET", "")
    if not expected or expected == "change_me_in_dotenv":
        return  # auth disabled
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth_header.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid token")


# ── Routes ───────────────────────────────────────────────────────────────────
@router.get("/health")
async def health():
    return {
        "status": "ok",
        "provider": getattr(config, "AI_PROVIDER", "anthropic"),
        "generated_dir": str(GENERATED_DIR),
        "styles": list(Style.__args__),
    }


@router.post("/generate", response_model=GenerateResponse, status_code=status.HTTP_200_OK)
async def generate(req: GenerateRequest, authorization: Optional[str] = Header(None)) -> GenerateResponse:
    """Generate Pine Script / brief / review từ mô tả tiếng Việt."""
    _check_auth(authorization)
    prompt = _build_prompt(req)
    text, provider = await _call_provider(prompt)

    pine_code: Optional[str] = None
    file_path: Optional[str] = None

    if req.style in ("strategy", "indicator", "alert"):
        pine_code = _extract_pine(text)
        if req.save and pine_code:
            saved = _save_pine(pine_code, req.name_hint, req.description)
            file_path = str(saved.relative_to(Path(__file__).resolve().parent.parent))
            log.info(f"fx-tactix: saved {file_path} ({len(pine_code)} chars, provider={provider})")
        elif not pine_code:
            log.warning(f"fx-tactix: provider returned no Pine block for style={req.style}")

    return GenerateResponse(
        status="ok",
        style=req.style,
        output=text,
        pine_code=pine_code,
        file_path=file_path,
        provider=provider,
    )
