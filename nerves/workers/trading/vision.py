"""
P7 Sprint 7.5 — AI Vision Analysis
Gửi chart screenshot cho Claude Vision để nhận diện pattern trực quan.

Capabilities:
    - VCP (Volatility Contraction Pattern) visual detection
    - Cup-with-Handle, Ascending Base, Flat Base identification
    - Volume analysis from chart visual
    - Support/Resistance zone detection
    - Combined score: algorithmic (TT/VCP) + visual (Claude Vision)
"""

import logging
import base64
import asyncio
from pathlib import Path
from typing import Optional, List, Tuple

log = logging.getLogger(__name__)

# Lazy import checks (we will import them directly in the function if needed)
ANTHROPIC_AVAILABLE = True
VERTEXAI_AVAILABLE = True
GENAI_AVAILABLE = True

import config


# ── Vision Analysis Prompt ────────────────────────────────────────────────

VISION_SYSTEM_PROMPT = """Bạn là chuyên gia phân tích kỹ thuật theo phương pháp SEPA của Mark Minervini.
Bạn đang nhìn vào biểu đồ TradingView của một cổ phiếu/crypto.

Nhiệm vụ: Phân tích biểu đồ này dựa trên Minervini methodology và trả về kết quả có cấu trúc."""

VISION_USER_PROMPT = """Phân tích biểu đồ TradingView này cho {symbol}:

## DỮ LIỆU ĐỊNH LƯỢNG (từ scanner)
{algo_context}

## YÊU CẦU PHÂN TÍCH SÂU (BEHAVIORAL & TECHNICAL)
Nhìn vào biểu đồ và đánh giá theo chuẩn SEPA:

1. **Pattern Recognition** — Nhận dạng cấu trúc:
   - Có VCP, Cup-with-Handle, Ascending Base không?
   - Vùng giá đi ngang (accumulation) hay xả hàng (distribution)?

2. **Trend Assessment** — Xu hướng và Động lượng:
   - Đang ở Stage mấy? (1, 2, 3, hay 4)
   - Price action có hẹp lại (contraction) đúng chuẩn không?

3. **Behavioral Analysis (Phân tích Hành vi User)** — Bắt bệnh Tâm lý:
   - Lệnh này là kỷ luật (SEPA compliant) hay là FOMO / Đu đỉnh / Bắt đáy hoảng loạn?
   - Cấu trúc giá có an toàn để cược tiền không?

4. **Trading Plan (Kế hoạch Giao dịch)**:
   - Cung cấp điểm vào, cắt lỗ, và chốt lời cụ thể dựa trên Kháng cự/Hỗ trợ của biểu đồ.
   - Entry Price: ...
   - Stop Loss: ...
   - Take Profit: ...
   - R:R Ratio: ...

5. **Visual Confidence Score**:
   - 1-10: Điểm số setup (Chỉ >7 mới nên giao dịch).
   - Lý do cốt lõi.

## FORMAT TRẢ LỜI
Trả lời NGẮN GỌN (dưới 250 từ), format Telegram-friendly.
Bắt đầu bằng: 👁️ VISUAL ANALYSIS — {symbol}"""


# ── Multi-Timeframe Vision Prompt ─────────────────────────────────────────

VISION_MTF_SYSTEM_PROMPT = """Bạn là chuyên gia phân tích kỹ thuật theo phương pháp SEPA của Mark Minervini.
Bạn đang nhìn vào 3 biểu đồ (Khung 1D, 4H, và 1H) của một cặp giao dịch crypto/cổ phiếu.

Nhiệm vụ: Phân tích đa khung thời gian để tìm điểm đồng thuận xu hướng (Multi-Timeframe Alignment) và đề xuất lệnh mua/bán (Long/Short) cụ thể."""

VISION_MTF_USER_PROMPT = """Phân tích đa khung thời gian cho {symbol}:
- Ảnh 1: Khung ngày (1D)
- Ảnh 2: Khung 4 giờ (4H)
- Ảnh 3: Khung 1 giờ (1H)

## DỮ LIỆU ĐỊNH LƯỢNG (từ scanner)
{mtf_context}

## YÊU CẦU PHÂN TÍCH
Hãy phân tích sự liên kết xu hướng đa khung thời gian:
1. **Xu hướng lớn (1D)**: Xu hướng chính đang ở Stage mấy? Cấu trúc kháng cự/hỗ trợ lớn.
2. **Cấu trúc trung hạn (4H)**: Có mẫu hình VCP, Cup-with-Handle, hay tích lũy Base đi ngang không?
3. **Điểm kích hoạt (1H)**: Điểm Pivot hay vùng nén giá chặt chẽ đã sẵn sàng breakout/breakdown chưa?
4. **Quyết định lệnh (Trading Decision)**:
   - **Tín hiệu**: LONG (Mua), SHORT (Bán khống) hoặc AVOID (Đứng ngoài).
   - **Entry Price** (Giá vào): ...
   - **Stop Loss** (Cắt lỗ): ...
   - **Take Profit** (Chốt lời): ...
   - **R:R Ratio** (Tỷ lệ R:R): ...
5. **Visual Confidence Score** (1-10): Điểm tin cậy trực quan.

## FORMAT TRẢ LỜI
Trả lời bằng Tiếng Việt ngắn gọn, format Telegram-friendly (sử dụng tag HTML bold/code).
Bắt đầu bằng: 👁️ MULTI-TIMEFRAME ANALYSIS — {symbol}"""



def _validate_and_read_image(image_path: Path) -> Optional[bytes]:
    """Validate that image_path is within allowed dirs, then read bytes.

    Security Architecture (CodeQL CWE-22 safe):
      1. Resolve and normalize the caller-supplied path.
      2. Verify the resolved path falls under an allowed root directory.
      3. Extract relative path components and reject any '..' traversal.
      4. Construct a FRESH path from the allowed root + validated
         components — this new string has **no data-flow link** to
         the original parameter, breaking the CodeQL taint chain.
      5. Open ONLY the freshly-constructed path for reading.
    """
    import os
    import tempfile

    # Step 1 — Resolve and normalize
    resolved = os.path.realpath(os.path.normpath(str(image_path)))

    # Allowed root directories (constant, trusted strings)
    allowed_roots = [
        os.path.realpath(tempfile.gettempdir()),
        os.path.realpath(os.path.expanduser("~")),
        os.path.realpath(
            os.path.join(
                os.path.dirname(__file__), os.pardir, os.pardir
            )
        ),
    ]

    # Step 2 — Validate: resolved path MUST be under an allowed root
    matched_root: Optional[str] = None
    for root in allowed_roots:
        root_prefix = root if root.endswith(os.sep) else root + os.sep
        if resolved == root or resolved.startswith(root_prefix):
            matched_root = root
            break

    if matched_root is None:
        sanitized = resolved.replace("\r", "").replace("\n", "")
        log.error(
            "Security Rejection: Path is outside allowed "
            f"directories: {sanitized}"
        )
        return None

    # Step 3 — Extract and validate relative path components
    relative = os.path.relpath(resolved, matched_root)
    parts = relative.replace("\\", "/").split("/")
    if ".." in parts:
        sanitized = resolved.replace("\r", "").replace("\n", "")
        log.error(
            "Security Rejection: Path traversal "
            f"detected: {sanitized}"
        )
        return None

    # Step 4 — Construct a FRESH path from trusted root + clean parts.
    # Each part is a plain directory/filename string validated above.
    # This creates a new str object with NO data-flow from `image_path`.
    clean_path = matched_root
    for part in parts:
        clean_path = os.path.join(clean_path, part)

    # Step 5 — Read file using the freshly-constructed path
    try:
        with open(clean_path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        safe_log = clean_path.replace("\r", "").replace("\n", "")
        log.error(f"Failed to read image file {safe_log}: {exc}")
        return None


def _encode_image(
    image_path: Path, max_width: int = 1024
) -> Tuple[Optional[str], str]:
    """Encode image to base64, compressing/resizing to WebP if PIL is available."""
    mime_type = _get_media_type(image_path)

    # ── SECURE FILE READ (CodeQL CWE-22 safe) ──
    raw_bytes = _validate_and_read_image(image_path)
    if raw_bytes is None:
        return None, mime_type

    try:
        from PIL import Image
        import io

        with Image.open(io.BytesIO(raw_bytes)) as img:
            # Resize if too large
            if img.width > max_width:
                height = int((max_width / img.width) * img.height)
                img = img.resize(
                    (max_width, height), Image.Resampling.LANCZOS
                )

            # Save to bytes in WebP format
            output = io.BytesIO()
            img.save(output, format="WEBP", quality=80)
            base64_str = base64.b64encode(
                output.getvalue()
            ).decode("utf-8")
            return base64_str, "image/webp"
    except Exception as e:
        log.warning(f"PIL compression failed, falling back to raw: {e}")
        base64_str = base64.b64encode(raw_bytes).decode("utf-8")
        return base64_str, mime_type


def _get_media_type(image_path: Path) -> str:
    """Detect media type from file extension."""
    ext = image_path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/png")


def _build_algo_context(scan_result: dict = None) -> str:
    """Build algorithmic context string from scan result."""
    if not scan_result:
        return "Không có dữ liệu scanner."

    lines = []
    if "price" in scan_result:
        lines.append(f"- Price: {scan_result['price']:,.2f}")
    if "trend_template_score" in scan_result:
        lines.append(f"- Trend Template: {scan_result['trend_template_score']}/8")
    if "trend_template_stage" in scan_result:
        lines.append(f"- Stage: {scan_result['trend_template_stage']}")
    if "vcp_detected" in scan_result:
        vcp = "✅ Detected" if scan_result["vcp_detected"] else "❌ Not detected"
        lines.append(f"- VCP (algorithmic): {vcp}")
    if "volume_ratio" in scan_result and scan_result["volume_ratio"]:
        lines.append(f"- Volume ratio: {scan_result['volume_ratio']*100:.0f}% of avg")
    if "pivot_level" in scan_result and scan_result["pivot_level"]:
        lines.append(f"- Pivot estimate: {scan_result['pivot_level']:,.2f}")

    return "\n".join(lines) if lines else "Không có dữ liệu scanner."


async def _analyze_chart_sdk_fallback(symbol: str, scan_result: dict = None) -> dict:
    """
    Tầng 3 Fallback: Gửi prompt chứa trạng thái kỹ thuật và RAG rules tới LiteLLM server local (port 9101).
    """
    import httpx
    # Build algo context
    algo_context = _build_algo_context(scan_result)
    
    # Retrieve RAG rules
    rag_rules = ""
    try:
        import rag
        if rag._collection is not None:
            query = f"Minervini trading rules guidelines SEPA setup for {symbol}"
            chunks = rag.query_knowledge(query, n_results=3)
            if chunks:
                rag_rules = "\n\n".join([f"- Chunk {c['metadata'].get('chapter', 'N/A')}: {c['content']}" for c in chunks])
    except Exception as re_err:
        log.warning(f"SDK Fallback: Failed to query RAG knowledge: {re_err}")
    
    # Construct enriched prompt
    fallback_prompt = f"""Bạn là expert AI Assistant tích hợp trong hệ thống giao dịch TradingViewProject.
Do các kết nối API Vision chính bị quá tải hoặc gặp lỗi (Rate Limit/Quota), bạn được kích hoạt làm Tầng 3 Fallback (Text-Based Specialist).

Nhiệm vụ: Dựa trên dữ liệu định lượng của scanner và các nguyên tắc giao dịch SEPA/Minervini dưới đây, hãy đưa ra nhận định phân tích kỹ thuật và quyết định giao dịch cho mã {symbol}.

## DỮ LIỆU ĐỊNH LƯỢNG (Scanner Telemetry):
{algo_context}

## NGUYÊN TẮC SEPA/MINERVINI RÚT TRÍCH TỪ RAG:
{rag_rules if rag_rules else "Không có dữ liệu RAG bổ sung."}

## HƯỚNG DẪN ĐÁNH GIÁ:
1. Nhận định xu hướng (Stage 1, 2, 3, hay 4).
2. Kiểm tra các điều kiện nén giá (VCP) và khối lượng.
3. Đánh giá tính kỷ luật và mức độ Compliant với phương pháp Minervini.
4. Đưa ra Kế hoạch giao dịch cụ thể (Entry, Stop Loss, Take Profit, R:R).
5. Cho điểm Confidence Score trực quan từ 1 đến 10.

## FORMAT TRẢ LỜI BẮT BUỘC:
Trả lời ngắn gọn (dưới 250 từ), phù hợp gửi qua Telegram.
Bắt đầu bằng: 👁️ VISUAL ANALYSIS (SDK FALLBACK) — {symbol}
Có chứa dòng điểm số dạng: Confidence: X/10 hoặc Score: X/10 ở cuối bài.
"""
    
    # Request parameters
    url = "http://127.0.0.1:9101/v1/chat/completions"
    payload = {
        "model": "gpt-4o-mini", # LiteLLM will route this automatically
        "messages": [
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {"role": "user", "content": fallback_prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 800
    }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                analysis_text = data["choices"][0]["message"]["content"]
                return {
                    "symbol": symbol,
                    "analysis": analysis_text,
                    "confidence": _parse_confidence(analysis_text),
                    "patterns": _parse_patterns(analysis_text),
                    "combined_score": "N/A",
                    "error": None
                }
            else:
                return {
                    "symbol": symbol,
                    "analysis": "",
                    "confidence": 0,
                    "patterns": [],
                    "combined_score": "N/A",
                    "error": f"LiteLLM error: HTTP {response.status_code} - {response.text}"
                }
    except Exception as exc:
        return {
            "symbol": symbol,
            "analysis": "",
            "confidence": 0,
            "patterns": [],
            "combined_score": "N/A",
            "error": f"LiteLLM connection failed: {exc}"
        }


async def _analyze_chart_mtf_sdk_fallback(symbol: str, mtf_scan_result: dict = None) -> dict:
    """
    Tầng 3 Fallback cho MTF: Gửi prompt chứa trạng thái kỹ thuật đa khung và RAG rules tới LiteLLM server local (port 9101).
    """
    import httpx
    # Build mtf context
    mtf_context_lines = []
    if mtf_scan_result and "timeframes" in mtf_scan_result:
        for tf, scan in mtf_scan_result["timeframes"].items():
            if scan and not getattr(scan, 'error', None):
                mtf_context_lines.append(
                    f"Khung {tf.upper()}:\n"
                    f"  - Price: {scan.price:,.2f}\n"
                    f"  - Trend Template: {scan.trend_template.score}/8 ({scan.trend_template.stage})\n"
                    f"  - VCP: {'Detected' if scan.vcp.detected else 'Not detected'} ({scan.vcp.note})"
                )
            elif scan:
                mtf_context_lines.append(f"Khung {tf.upper()}: Lỗi scan ({scan.error})")
    
    mtf_context = "\n".join(mtf_context_lines) if mtf_context_lines else "Không có dữ liệu scanner."
    
    # Retrieve RAG rules
    rag_rules = ""
    try:
        import rag
        if rag._collection is not None:
            query = f"Minervini trading rules guidelines SEPA setup multi timeframe for {symbol}"
            chunks = rag.query_knowledge(query, n_results=3)
            if chunks:
                rag_rules = "\n\n".join([f"- Chunk {c['metadata'].get('chapter', 'N/A')}: {c['content']}" for c in chunks])
    except Exception as re_err:
        log.warning(f"SDK MTF Fallback: Failed to query RAG knowledge: {re_err}")
        
    fallback_prompt = f"""Bạn là expert AI Assistant tích hợp trong hệ thống giao dịch TradingViewProject.
Do các kết nối API Vision chính bị quá tải hoặc gặp lỗi (Rate Limit/Quota), bạn được kích hoạt làm Tầng 3 Fallback (Text-Based Specialist) cho phân tích Đa Khung Thời Gian (MTF).

Nhiệm vụ: Dựa trên dữ liệu định lượng của scanner đa khung và các nguyên tắc giao dịch SEPA/Minervini dưới đây, hãy đưa ra nhận định phân tích kỹ thuật và quyết định giao dịch cho mã {symbol}.

## DỮ LIỆU ĐỊNH LƯỢNG (Scanner Telemetry):
{mtf_context}

## NGUYÊN TẮC SEPA/MINERVINI RÚT TRÍCH TỪ RAG:
{rag_rules if rag_rules else "Không có dữ liệu RAG bổ sung."}

## HƯỚNG DẪN ĐÁNH GIÁ:
1. Nhận định xu hướng đa khung thời gian (1D, 4H, 1H).
2. Kiểm tra các điều kiện nén giá (VCP) và khối lượng ở khung nhỏ.
3. Đưa ra Quyết định lệnh (LONG/SHORT/AVOID) kèm Entry, Stop Loss, Take Profit, R:R.
4. Cho điểm Confidence Score trực quan từ 1 đến 10.

## FORMAT TRẢ LỜI BẮT BUỘC:
Trả lời ngắn gọn (dưới 250 từ) bằng Tiếng Việt, phù hợp gửi qua Telegram.
Bắt đầu bằng: 👁️ MULTI-TIMEFRAME ANALYSIS (SDK FALLBACK) — {symbol}
Có chứa dòng điểm số dạng: Confidence: X/10 hoặc Score: X/10 ở cuối bài.
"""
    
    url = "http://127.0.0.1:9101/v1/chat/completions"
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": VISION_MTF_SYSTEM_PROMPT},
            {"role": "user", "content": fallback_prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 1000
    }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                analysis_text = data["choices"][0]["message"]["content"]
                return {
                    "symbol": symbol,
                    "analysis": analysis_text,
                    "confidence": _parse_confidence(analysis_text),
                    "patterns": _parse_patterns(analysis_text),
                    "combined_score": "N/A",
                    "error": None
                }
            else:
                return {
                    "symbol": symbol,
                    "analysis": "",
                    "confidence": 0,
                    "patterns": [],
                    "combined_score": "N/A",
                    "error": f"LiteLLM error: HTTP {response.status_code} - {response.text}"
                }
    except Exception as exc:
        return {
            "symbol": symbol,
            "analysis": "",
            "confidence": 0,
            "patterns": [],
            "combined_score": "N/A",
            "error": f"LiteLLM connection failed: {exc}"
        }


async def analyze_chart_vision(
    image_path: Path,
    symbol: str,
    scan_result: dict = None,
    model: str = "claude-sonnet-4-5",
) -> dict:
    """
    Gửi chart screenshot cho Claude Vision để phân tích pattern.

    Args:
        image_path: Path tới screenshot PNG
        symbol: Mã symbol (VD: "BTCUSDT")
        scan_result: Dict scan result từ analysis.py (optional — for combined scoring)
        model: Claude model (default: claude-sonnet-4-5 — supports vision)

    Returns:
        dict {
            "symbol": str,
            "analysis": str,      # Claude's visual analysis text
            "confidence": int,    # 1-10 visual confidence (parsed)
            "patterns": list,     # Detected patterns
            "combined_score": str, # Algo + Visual combined
            "error": str or None,
        }
    """
    result = {
        "symbol": symbol,
        "analysis": "",
        "confidence": 0,
        "patterns": [],
        "combined_score": "N/A",
        "error": None,
    }

    provider = getattr(config, "AI_PROVIDER", "anthropic").lower()

    # Validate
    has_vertex = VERTEXAI_AVAILABLE and getattr(config, "GCP_PROJECT_ID", None)
    has_genai = GENAI_AVAILABLE and getattr(config, "GEMINI_API_KEY", None)
    has_gemini = bool(has_vertex or has_genai)

    if provider == "gemini":
        if not has_gemini:
            result["error"] = "Gemini API not available or configured (need GCP_PROJECT_ID or GEMINI_API_KEY)"
            return result
    elif provider == "claude_cli":
        pass  # CLI verify khi gọi, không cần API key
    else:
        if not ANTHROPIC_AVAILABLE or not getattr(config, "ANTHROPIC_API_KEY", None) or getattr(config, "ANTHROPIC_API_KEY", "").startswith("sk-ant-xxx"):
            if has_gemini:
                log.info("Anthropic API key is not configured. Falling back to Gemini...")
                provider = "gemini"
            else:
                result["error"] = "Anthropic API not available or configured"
                return result

    image_path = Path(image_path)
    if not image_path.exists():
        log.warning(f"Image not found at {image_path}. Triggering Tier 3 SDK Fallback directly...")
        fallback_res = await _analyze_chart_sdk_fallback(symbol, scan_result)
        if not fallback_res.get("error"):
            result.update(fallback_res)
            if scan_result:
                tt_score = scan_result.get("trend_template_score", 0)
                vcp_algo = scan_result.get("vcp_detected", False)
                visual_conf = result["confidence"]
                algo_score = (tt_score / 8) * 10
                if visual_conf >= 9:
                    combined = algo_score * 0.4 + visual_conf * 0.6
                else:
                    combined = algo_score * 0.5 + visual_conf * 0.5
                result["combined_score"] = f"{combined:.1f}/10"
                
                visual_vcp = any("vcp" in p.lower() or "volatility contraction" in p.lower() for p in result["patterns"])
                is_downtrend = any("stage 4" in p.lower() or "stage 3" in p.lower() for p in result["patterns"])
                if is_downtrend:
                    result["verdict"] = "🔴 AVOID — Stage 3/4 Downtrend Detected"
                elif combined >= 8 and (vcp_algo or visual_vcp):
                    result["verdict"] = "🟢 STRONG BUY SETUP"
                elif combined >= 6:
                    result["verdict"] = "🟡 WATCHLIST — Monitor for breakout"
                elif combined >= 4:
                    result["verdict"] = "🟠 NEUTRAL — Base building"
                else:
                    result["verdict"] = "🔴 AVOID — Weak setup"
            else:
                result["combined_score"] = f"{result['confidence']}/10 (visual only)"
        else:
            result["error"] = f"Image not found: {image_path}. Fallback error: {fallback_res['error']}"
        return result

    # Build prompt
    algo_context = _build_algo_context(scan_result)
    user_prompt = VISION_USER_PROMPT.format(
        symbol=symbol,
        algo_context=algo_context,
    )

    try:
        analysis_text = ""
        
        # 1. Try Anthropic first if it's the provider
        if provider == "anthropic":
            try:
                # Encode image for Anthropic
                image_data, mime_type = _encode_image(image_path)
                if not image_data:
                    raise ValueError("Failed to encode image")

                import anthropic
                client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
                message = client.messages.create(
                    model=model,
                    max_tokens=800,
                    system=VISION_SYSTEM_PROMPT,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": mime_type,
                                        "data": image_data,
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": user_prompt,
                                },
                            ],
                        }
                    ],
                )
                analysis_text = message.content[0].text
            except Exception as e:
                if has_gemini:
                    log.warning(f"Anthropic SDK vision call failed: {e}. Falling back to Gemini...")
                    provider = "gemini"
                else:
                    raise e

        # 2. Try Claude CLI if provider is claude_cli
        if provider == "claude_cli":
            try:
                import rag as _rag
                cli_prompt = (
                    f"{VISION_SYSTEM_PROMPT}\n\n"
                    f"Đọc và phân tích biểu đồ tại đường dẫn sau:\n"
                    f"{image_path.resolve()}\n\n"
                    f"{user_prompt}"
                )
                analysis_text = await _rag._call_claude_cli(
                    cli_prompt, image_path=str(image_path.resolve())
                )
            except Exception as cli_err:
                if (
                    getattr(config, "CLAUDE_CLI_FALLBACK_SDK", True)
                    and ANTHROPIC_AVAILABLE
                    and getattr(config, "ANTHROPIC_API_KEY", None)
                    and not getattr(config, "ANTHROPIC_API_KEY", "").startswith("sk-ant-xxx")
                ):
                    log.warning(f"Vision: Claude CLI fail ({cli_err}). Fallback SDK.")
                    provider = "anthropic"  # try Anthropic SDK
                    # try Anthropic SDK logic
                    image_data, mime_type = _encode_image(image_path)
                    if not image_data:
                        raise ValueError("Failed to encode image")
                    import anthropic
                    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
                    message = client.messages.create(
                        model=model,
                        max_tokens=800,
                        system=VISION_SYSTEM_PROMPT,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": mime_type,
                                            "data": image_data,
                                        },
                                    },
                                    {
                                        "type": "text",
                                        "text": user_prompt,
                                    },
                                ],
                            }
                        ],
                    )
                    analysis_text = message.content[0].text
                elif has_gemini:
                    log.warning(f"Vision: Claude CLI fail ({cli_err}). Falling back to Gemini...")
                    provider = "gemini"
                else:
                    result["error"] = f"Claude CLI error: {cli_err}"
                    return result

        # 3. Try Gemini (either by design or as a fallback)
        if provider == "gemini":
            # Hybrid Strategy: Pro for high precision, Flash for fast scan
            model_name = "gemini-2.5-pro" if model == "claude-sonnet-4-5" else "gemini-2.5-flash"
            max_retries = 3
            
            for attempt in range(max_retries):
                try:
                    # Determine best available auth method
                    has_vertex = getattr(config, "GCP_PROJECT_ID", None) and VERTEXAI_AVAILABLE
                    has_genai  = getattr(config, "GEMINI_API_KEY", None) and GENAI_AVAILABLE

                    # Check if ADC (Application Default Credentials) is available before using Vertex AI
                    _use_vertex = False
                    if has_vertex:
                        try:
                            import google.auth
                            google.auth.default()  # raises if no ADC
                            _use_vertex = True
                        except Exception:
                            log.warning("Vertex AI ADC not found — falling back to GEMINI_API_KEY")

                    if _use_vertex:
                        import vertexai
                        from vertexai.generative_models import GenerativeModel as VertexGenerativeModel, Part as VertexPart
                        vertexai.init(project=config.GCP_PROJECT_ID, location=getattr(config, "GCP_LOCATION", "us-central1"))
                        g_model = VertexGenerativeModel(model_name, system_instruction=VISION_SYSTEM_PROMPT)
                        image_data = image_path.read_bytes()
                        mime_type = _get_media_type(image_path)
                        image_part = VertexPart.from_data(data=image_data, mime_type=mime_type)
                        response = g_model.generate_content([user_prompt, image_part])
                        analysis_text = response.text
                        break
                    elif has_genai:
                        from google import genai
                        from google.genai import types as genai_types
                        client = genai.Client(api_key=config.GEMINI_API_KEY)
                        image_bytes = image_path.read_bytes()
                        mime_type = _get_media_type(image_path)
                        response = client.models.generate_content(
                            model=model_name,
                            contents=[
                                user_prompt,
                                genai_types.Part.from_bytes(
                                    data=image_bytes,
                                    mime_type=mime_type,
                                ),
                            ],
                            config=genai_types.GenerateContentConfig(
                                system_instruction=VISION_SYSTEM_PROMPT,
                            ),
                        )
                        analysis_text = response.text
                        break
                    else:
                        raise RuntimeError("No Gemini credentials available")
                except Exception as e:
                    error_str = str(e).lower()
                    if "429" in error_str or "quota" in error_str or "exhausted" in error_str or "rate limit" in error_str:
                        if attempt < max_retries - 1:
                            wait_time = 2 ** attempt
                            log.warning(f"Rate limit hit for {model_name} on {symbol}. Retrying in {wait_time}s...")
                            await asyncio.sleep(wait_time)
                            continue
                    raise  # Reraise nếu không phải lỗi rate limit hoặc đã thử tối đa

        result["analysis"] = analysis_text

        # Parse confidence score from response
        result["confidence"] = _parse_confidence(analysis_text)

        # Parse detected patterns
        result["patterns"] = _parse_patterns(analysis_text)

        # Combined score with algorithmic data
        if scan_result:
            tt_score = scan_result.get("trend_template_score", 0)
            vcp_algo = scan_result.get("vcp_detected", False)
            visual_conf = result["confidence"]

            # Combined: algorithmic weight 50% + visual 50%
            algo_score = (tt_score / 8) * 10  # normalize to 0-10
            
            # Dynamic weighting: If AI is extremely confident (>= 9), trust visual more.
            if visual_conf >= 9:
                combined = algo_score * 0.4 + visual_conf * 0.6
            else:
                combined = algo_score * 0.5 + visual_conf * 0.5

            result["combined_score"] = f"{combined:.1f}/10"

            # Check for Visual Veto and Stage Penalty
            visual_vcp = any("vcp" in p.lower() or "volatility contraction" in p.lower() for p in result["patterns"])
            is_downtrend = any("stage 4" in p.lower() or "stage 3" in p.lower() for p in result["patterns"])

            # Enhanced verdict
            if is_downtrend:
                result["verdict"] = "🔴 AVOID — Stage 3/4 Downtrend Detected"
            elif combined >= 8 and (vcp_algo or visual_vcp):
                result["verdict"] = "🟢 STRONG BUY SETUP"
            elif combined >= 6:
                result["verdict"] = "🟡 WATCHLIST — Monitor for breakout"
            elif combined >= 4:
                result["verdict"] = "🟠 NEUTRAL — Base building"
            else:
                result["verdict"] = "🔴 AVOID — Weak setup"
        else:
            result["combined_score"] = f"{result['confidence']}/10 (visual only)"
            result["verdict"] = ""

        log.info(f"Vision: {symbol} analyzed — confidence {result['confidence']}/10, "
                 f"patterns: {result['patterns']}")

    except Exception as e:
        log.warning(f"Vision API error for {symbol}: {e}. Triggering Tier 3 SDK Fallback...")
        fallback_res = await _analyze_chart_sdk_fallback(symbol, scan_result)
        if not fallback_res.get("error"):
            result.update(fallback_res)
            if scan_result:
                tt_score = scan_result.get("trend_template_score", 0)
                vcp_algo = scan_result.get("vcp_detected", False)
                visual_conf = result["confidence"]
                algo_score = (tt_score / 8) * 10
                if visual_conf >= 9:
                    combined = algo_score * 0.4 + visual_conf * 0.6
                else:
                    combined = algo_score * 0.5 + visual_conf * 0.5
                result["combined_score"] = f"{combined:.1f}/10"
                
                visual_vcp = any("vcp" in p.lower() or "volatility contraction" in p.lower() for p in result["patterns"])
                is_downtrend = any("stage 4" in p.lower() or "stage 3" in p.lower() for p in result["patterns"])
                if is_downtrend:
                    result["verdict"] = "🔴 AVOID — Stage 3/4 Downtrend Detected"
                elif combined >= 8 and (vcp_algo or visual_vcp):
                    result["verdict"] = "🟢 STRONG BUY SETUP"
                elif combined >= 6:
                    result["verdict"] = "🟡 WATCHLIST — Monitor for breakout"
                elif combined >= 4:
                    result["verdict"] = "🟠 NEUTRAL — Base building"
                else:
                    result["verdict"] = "🔴 AVOID — Weak setup"
            else:
                result["combined_score"] = f"{result['confidence']}/10 (visual only)"
        else:
            result["error"] = f"Original error: {e}. Fallback error: {fallback_res['error']}"

    return result


async def analyze_chart_vision_mtf(
    image_paths: List[Path],
    symbol: str,
    mtf_scan_result: dict = None,
    model: str = "claude-sonnet-4-5",
) -> dict:
    """
    Gửi 3 chart screenshots (1D, 4H, 1H) cho Claude/Gemini Vision để phân tích đa khung thời gian.
    """
    result = {
        "symbol": symbol,
        "analysis": "",
        "confidence": 0,
        "patterns": [],
        "combined_score": "N/A",
        "error": None,
        "verdict": "",
    }

    provider = getattr(config, "AI_PROVIDER", "anthropic").lower()

    # Validate
    has_vertex = VERTEXAI_AVAILABLE and getattr(config, "GCP_PROJECT_ID", None)
    has_genai = GENAI_AVAILABLE and getattr(config, "GEMINI_API_KEY", None)
    has_gemini = bool(has_vertex or has_genai)

    has_anthropic = (
        ANTHROPIC_AVAILABLE
        and bool(getattr(config, "ANTHROPIC_API_KEY", None))
        and not getattr(config, "ANTHROPIC_API_KEY", "").startswith("sk-ant-xxx")
    )

    if provider == "gemini":
        if not has_gemini:
            result["error"] = "Gemini API not available or configured"
            return result
    elif provider == "claude_cli":
        pass
    else:
        if not has_anthropic:
            if has_gemini:
                log.info("Vision MTF: Anthropic mock or missing. Switching to Gemini fallback.")
                provider = "gemini"
            else:
                result["error"] = "Anthropic API not available or configured"
                return result

    # Check images exist
    valid_paths = [Path(p) for p in image_paths if Path(p).exists()]
    if not valid_paths:
        log.warning(f"No valid images found from paths: {image_paths}. Triggering Tier 3 SDK Fallback directly...")
        fallback_res = await _analyze_chart_mtf_sdk_fallback(symbol, mtf_scan_result)
        if not fallback_res.get("error"):
            result.update(fallback_res)
            if mtf_scan_result and "timeframes" in mtf_scan_result:
                scan_1d = mtf_scan_result["timeframes"].get("1d")
                tt_score = scan_1d.trend_template.score if scan_1d and not getattr(scan_1d, 'error', None) else 0
                # vcp_algo reserved for future VCP-weighted scoring
                # vcp_algo = scan_1d.vcp.detected if scan_1d and not getattr(scan_1d, 'error', None) else False
                visual_conf = result["confidence"]
                algo_score = (tt_score / 8) * 10
                combined = algo_score * 0.4 + visual_conf * 0.6 if visual_conf >= 9 else algo_score * 0.5 + visual_conf * 0.5
                result["combined_score"] = f"{combined:.1f}/10"

                is_long = "long" in result["analysis"].lower() or "mua" in result["analysis"].lower()
                is_short = "short" in result["analysis"].lower() or "bán" in result["analysis"].lower()
                is_avoid = "avoid" in result["analysis"].lower() or "đứng ngoài" in result["analysis"].lower() or "bỏ qua" in result["analysis"].lower()

                if is_avoid:
                    result["verdict"] = "🔴 AVOID — MTF Structure Neutral/Weak"
                elif is_long and combined >= 6:
                    result["verdict"] = "🟢 STRONG LONG SETUP"
                elif is_short and combined >= 6:
                    result["verdict"] = "🟣 STRONG SHORT SETUP"
                else:
                    result["verdict"] = "🟡 WATCHLIST — Uncertain structure"
            else:
                result["combined_score"] = f"{result['confidence']}/10 (visual only)"
        else:
            result["error"] = f"No valid images found: {image_paths}. Fallback error: {fallback_res['error']}"
        return result

    # Build prompt context
    mtf_context_lines = []
    if mtf_scan_result and "timeframes" in mtf_scan_result:
        for tf, scan in mtf_scan_result["timeframes"].items():
            if scan and not getattr(scan, 'error', None):
                mtf_context_lines.append(
                    f"Khung {tf.upper()}:\n"
                    f"  - Price: {scan.price:,.2f}\n"
                    f"  - Trend Template: {scan.trend_template.score}/8 ({scan.trend_template.stage})\n"
                    f"  - VCP: {'Detected' if scan.vcp.detected else 'Not detected'} ({scan.vcp.note})"
                )
            elif scan:
                mtf_context_lines.append(f"Khung {tf.upper()}: Lỗi scan ({scan.error})")
    
    mtf_context = "\n".join(mtf_context_lines) if mtf_context_lines else "Không có dữ liệu scanner."
    user_prompt = VISION_MTF_USER_PROMPT.format(
        symbol=symbol,
        mtf_context=mtf_context,
    )

    try:
        # 1. Try Claude CLI if provider is claude_cli
        if provider == "claude_cli":
            try:
                import rag as _rag
                cli_prompt = f"{VISION_MTF_SYSTEM_PROMPT}\n\n{user_prompt}"
                # call with the first image, since CLI only takes one primary image
                analysis_text = await _rag._call_claude_cli(
                    cli_prompt, image_path=str(valid_paths[0].resolve())
                )
            except Exception as cli_err:
                if (
                    getattr(config, "CLAUDE_CLI_FALLBACK_SDK", True)
                    and ANTHROPIC_AVAILABLE
                    and getattr(config, "ANTHROPIC_API_KEY", None)
                    and not getattr(config, "ANTHROPIC_API_KEY", "").startswith("sk-ant-xxx")
                ):
                    log.warning(f"Vision MTF: Claude CLI fail ({cli_err}). Fallback SDK.")
                    provider = "anthropic"
                elif has_gemini:
                    log.warning(f"Vision MTF: Claude CLI fail ({cli_err}). Falling back to Gemini...")
                    provider = "gemini"
                else:
                    result["error"] = f"Claude CLI error: {cli_err}"
                    return result

        # 2. Try Anthropic SDK if provider is anthropic
        if provider != "claude_cli" and provider != "gemini":
            try:
                content_blocks = []
                for path in valid_paths:
                    image_data, mime_type = _encode_image(path)
                    if image_data:
                        content_blocks.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": image_data,
                            },
                        })
                content_blocks.append({
                    "type": "text",
                    "text": user_prompt,
                })

                import anthropic
                client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
                message = client.messages.create(
                    model=model,
                    max_tokens=1000,
                    system=VISION_MTF_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": content_blocks}],
                )
                analysis_text = message.content[0].text
            except Exception as e:
                if has_gemini:
                    log.warning(f"Anthropic SDK MTF vision call failed: {e}. Falling back to Gemini...")
                    provider = "gemini"
                else:
                    raise e

        # 3. Try Gemini (either initially or as a fallback)
        if provider == "gemini":
            model_name = "gemini-2.5-pro" if model == "claude-sonnet-4-5" else "gemini-2.5-flash"
            max_retries = 3
            analysis_text = ""
            
            for attempt in range(max_retries):
                try:
                    has_vertex = getattr(config, "GCP_PROJECT_ID", None) and VERTEXAI_AVAILABLE
                    has_genai  = getattr(config, "GEMINI_API_KEY", None) and GENAI_AVAILABLE

                    _use_vertex = False
                    if has_vertex:
                        try:
                            import google.auth
                            google.auth.default()
                            _use_vertex = True
                        except Exception:
                            pass

                    if _use_vertex:
                        import vertexai
                        from vertexai.generative_models import GenerativeModel as VertexGenerativeModel, Part as VertexPart
                        vertexai.init(project=config.GCP_PROJECT_ID, location=getattr(config, "GCP_LOCATION", "us-central1"))
                        g_model = VertexGenerativeModel(model_name, system_instruction=VISION_MTF_SYSTEM_PROMPT)
                        contents = [user_prompt]
                        for path in valid_paths:
                            contents.append(VertexPart.from_data(data=path.read_bytes(), mime_type=_get_media_type(path)))
                        response = g_model.generate_content(contents)
                        analysis_text = response.text
                        break
                    elif has_genai:
                        from google import genai
                        from google.genai import types as genai_types
                        client = genai.Client(api_key=config.GEMINI_API_KEY)
                        contents = [user_prompt]
                        for path in valid_paths:
                            contents.append(
                                genai_types.Part.from_bytes(
                                    data=path.read_bytes(),
                                    mime_type=_get_media_type(path),
                                )
                            )
                        response = client.models.generate_content(
                            model=model_name,
                            contents=contents,
                            config=genai_types.GenerateContentConfig(
                                system_instruction=VISION_MTF_SYSTEM_PROMPT,
                            ),
                        )
                        analysis_text = response.text
                        break
                    else:
                        raise RuntimeError("No Gemini credentials available")
                except Exception as e:
                    error_str = str(e).lower()
                    if "429" in error_str or "quota" in error_str or "exhausted" in error_str or "rate limit" in error_str:
                        if attempt < max_retries - 1:
                            wait_time = 2 ** attempt
                            await asyncio.sleep(wait_time)
                            continue
                    raise

        result["analysis"] = analysis_text
        result["confidence"] = _parse_confidence(analysis_text)
        result["patterns"] = _parse_patterns(analysis_text)

        # Combined scoring logic for MTF
        if mtf_scan_result and "timeframes" in mtf_scan_result:
            scan_1d = mtf_scan_result["timeframes"].get("1d")
            tt_score = scan_1d.trend_template.score if scan_1d and not getattr(scan_1d, 'error', None) else 0
            # vcp_algo reserved for future VCP-weighted scoring
            # vcp_algo = scan_1d.vcp.detected if scan_1d and not getattr(scan_1d, 'error', None) else False
            visual_conf = result["confidence"]

            algo_score = (tt_score / 8) * 10
            combined = algo_score * 0.4 + visual_conf * 0.6 if visual_conf >= 9 else algo_score * 0.5 + visual_conf * 0.5
            result["combined_score"] = f"{combined:.1f}/10"

            is_long = "long" in analysis_text.lower() or "mua" in analysis_text.lower()
            is_short = "short" in analysis_text.lower() or "bán" in analysis_text.lower()
            is_avoid = "avoid" in analysis_text.lower() or "đứng ngoài" in analysis_text.lower() or "bỏ qua" in analysis_text.lower()

            if is_avoid:
                result["verdict"] = "🔴 AVOID — MTF Structure Neutral/Weak"
            elif is_long and combined >= 6:
                result["verdict"] = "🟢 STRONG LONG SETUP"
            elif is_short and combined >= 6:
                result["verdict"] = "🟣 STRONG SHORT SETUP"
            else:
                result["verdict"] = "🟡 WATCHLIST — Uncertain structure"
        else:
            result["combined_score"] = f"{result['confidence']}/10 (visual only)"
            result["verdict"] = ""

        log.info(f"Vision MTF: {symbol} analyzed — confidence {result['confidence']}/10")

    except Exception as e:
        log.warning(f"Vision MTF API error for {symbol}: {e}. Triggering Tier 3 SDK Fallback...")
        fallback_res = await _analyze_chart_mtf_sdk_fallback(symbol, mtf_scan_result)
        if not fallback_res.get("error"):
            result.update(fallback_res)
            if mtf_scan_result and "timeframes" in mtf_scan_result:
                scan_1d = mtf_scan_result["timeframes"].get("1d")
                tt_score = scan_1d.trend_template.score if scan_1d and not getattr(scan_1d, 'error', None) else 0
                # vcp_algo extraction reserved for future VCP-weighted scoring
                # vcp_algo = scan_1d.vcp.detected if scan_1d and not getattr(scan_1d, 'error', None) else False
                visual_conf = result["confidence"]
                algo_score = (tt_score / 8) * 10
                combined = algo_score * 0.4 + visual_conf * 0.6 if visual_conf >= 9 else algo_score * 0.5 + visual_conf * 0.5
                result["combined_score"] = f"{combined:.1f}/10"

                is_long = "long" in result["analysis"].lower() or "mua" in result["analysis"].lower()
                is_short = "short" in result["analysis"].lower() or "bán" in result["analysis"].lower()
                is_avoid = "avoid" in result["analysis"].lower() or "đứng ngoài" in result["analysis"].lower() or "bỏ qua" in result["analysis"].lower()

                if is_avoid:
                    result["verdict"] = "🔴 AVOID — MTF Structure Neutral/Weak"
                elif is_long and combined >= 6:
                    result["verdict"] = "🟢 STRONG LONG SETUP"
                elif is_short and combined >= 6:
                    result["verdict"] = "🟣 STRONG SHORT SETUP"
                else:
                    result["verdict"] = "🟡 WATCHLIST — Uncertain structure"
            else:
                result["combined_score"] = f"{result['confidence']}/10 (visual only)"
        else:
            result["error"] = f"Original error: {e}. Fallback error: {fallback_res['error']}"

    return result


def _parse_confidence(text: str) -> int:
    """Extract visual confidence score (1-10) from Claude/Gemini's response."""
    import re
    # Look for patterns like "7/10", "Score: 8", "confidence: 9/10"
    patterns = [
        r"(?:confidence|score|tin cậy)[:\s]*(\d+)\s*/\s*10",
        r"(\d+)\s*/\s*10",
        r"(?:confidence|score|tin cậy)[:\s]*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            score = int(match.group(1))
            if 1 <= score <= 10:
                return score
    return 5  # default middle confidence


def _parse_patterns(text: str) -> list[str]:
    """Extract detected pattern names from the response."""
    known_patterns = [
        "VCP", "Volatility Contraction",
        "Cup-with-Handle", "Cup with Handle", "Cup and Handle",
        "Ascending Base", "Flat Base",
        "High Tight Flag", "HTF",
        "Double Bottom", "Triple Bottom",
        "Bull Flag", "Pennant",
        "Breakout", "Pivot",
        "Accumulation", "Tích lũy",
        "Stage 2", "Stage 1",
    ]
    found = []
    text_lower = text.lower()
    for p in known_patterns:
        if p.lower() in text_lower and p not in found:
            found.append(p)
    return found


def format_vision_telegram(vision_result: dict) -> str:
    """Format vision analysis for Telegram message."""
    if vision_result.get("error"):
        return f"👁️ Vision Error: {vision_result['error']}"

    lines = [
        vision_result.get("analysis", "No analysis"),
        "",
        f"📊 Combined Score: *{vision_result.get('combined_score', 'N/A')}*",
    ]

    if vision_result.get("verdict"):
        lines.append(f"📋 Verdict: *{vision_result['verdict']}*")

    if vision_result.get("patterns"):
        lines.append(f"🔍 Patterns: {', '.join(vision_result['patterns'])}")

    return "\n".join(lines)
