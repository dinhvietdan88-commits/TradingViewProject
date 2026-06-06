"""
rag.py — RAG (Retrieval-Augmented Generation) Module
Tích hợp ChromaDB + Sentence Transformers + Claude (Anthropic) vào FastAPI backend.

Flow:
    1. init_vector_db()  → Đọc 36 chunk Minervini, embed và lưu vào ChromaDB
    2. query_knowledge() → Truy vấn theo semantic similarity
    3. generate_trading_advice() → Gọi Claude API để phân tích tín hiệu
"""

import asyncio
import importlib.util
import logging
import re
from pathlib import Path
from typing import Optional

import config

log = logging.getLogger(__name__)

CHROMADB_AVAILABLE = importlib.util.find_spec("chromadb") is not None
ANTHROPIC_AVAILABLE = importlib.util.find_spec("anthropic") is not None
GENAI_AVAILABLE = importlib.util.find_spec("google.genai") is not None
VERTEXAI_AVAILABLE = importlib.util.find_spec("vertexai") is not None
ANTIGRAVITY_AVAILABLE = importlib.util.find_spec("google.antigravity") is not None

if not CHROMADB_AVAILABLE:
    log.warning(
        "chromadb not installed. Run: pip install chromadb sentence-transformers"
    )
if not ANTHROPIC_AVAILABLE:
    log.warning("anthropic not installed. Run: pip install anthropic")
if not GENAI_AVAILABLE:
    log.warning("google-genai not installed. Run: pip install google-genai")
if not VERTEXAI_AVAILABLE:
    log.warning("vertexai not installed. Run: pip install google-cloud-aiplatform")
if not ANTIGRAVITY_AVAILABLE:
    log.warning("google-antigravity not installed. Run: pip install google-antigravity")

# ── Globals ────────────────────────────────────────────────────────────────
_chroma_client: Optional[object] = None
_collection: Optional[object] = None


def _get_embedding_function():
    """Dùng sentence-transformers local (không cần API key, miễn phí)."""
    if not CHROMADB_AVAILABLE:
        return None
    from chromadb.utils import embedding_functions

    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="paraphrase-multilingual-MiniLM-L12-v2"  # hỗ trợ tiếng Việt
    )


def _parse_chunk_metadata(content: str, filename: str) -> dict:
    """Extract metadata từ header của mỗi file chunk Markdown."""
    meta = {"filename": filename, "topic": "general", "chapter": ""}
    # Lấy dòng đầu tiên làm title
    lines = content.strip().splitlines()
    for line in lines:
        if line.startswith("# "):
            meta["topic"] = line.lstrip("# ").strip()
            break
    # Extract chapter info từ tên file (chunk_001.md → 001)
    match = re.search(r"chunk_(\d+)", filename)
    if match:
        meta["chapter"] = match.group(1)
    return meta


_cli_semaphore: Optional[object] = None


def _get_cli_semaphore():
    """Lazy-init Semaphore (cần event loop để khởi tạo)."""
    global _cli_semaphore
    if _cli_semaphore is None:
        n = getattr(config, "CLAUDE_CLI_MAX_PARALLEL", 2)
        _cli_semaphore = asyncio.Semaphore(max(1, n))
    return _cli_semaphore


class ClaudeCLIError(Exception):
    """Raised khi CLI fail — cho phép caller fallback sang SDK."""


async def _call_claude_cli(prompt: str, image_path: Optional[str] = None) -> str:
    """Gọi `claude -p` headless qua subscription OAuth (không cần API key).

    Args:
        prompt: Nội dung prompt. Nếu có image_path, prompt nên reference image đó.
        image_path: Đường dẫn tuyệt đối tới ảnh (PNG/JPG). Khi set, CLI được cấp
            quyền Read + --add-dir tới thư mục chứa ảnh.

    Raises:
        ClaudeCLIError: khi binary không tồn tại, timeout, hoặc returncode != 0.
            Caller có thể bắt để fallback sang SDK.
    """

    claude_path = getattr(config, "CLAUDE_CLI_PATH", "claude")
    timeout = getattr(config, "CLAUDE_CLI_TIMEOUT", 60)
    model = getattr(config, "CLAUDE_CLI_MODEL", "")

    args = [claude_path, "-p", "--output-format", "text"]
    if model:
        args += ["--model", model]

    if image_path:
        from security.runtime_guard import safe_screenshot_path

        img = safe_screenshot_path(image_path)
        args += [
            "--add-dir",
            str(img.parent),
            "--allowedTools",
            "Read",
            "--dangerously-skip-permissions",
        ]

    sem = _get_cli_semaphore()
    async with sem:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as err:
            raise ClaudeCLIError(
                f"Không tìm thấy Claude CLI tại '{claude_path}'"
            ) from err

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")), timeout=timeout
            )
        except asyncio.TimeoutError as err:
            proc.kill()
            raise ClaudeCLIError(f"Claude CLI timeout sau {timeout}s") from err

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")[:300]
        raise ClaudeCLIError(f"Claude CLI rc={proc.returncode}: {err}") from err

    return stdout.decode("utf-8", errors="replace").strip()


async def init_vector_db() -> bool:
    """
    Khởi tạo ChromaDB và embed tất cả Markdown chunks vào Vector DB.
    Được gọi trong FastAPI lifespan startup.

    Returns:
        True nếu thành công, False nếu không có packages cần thiết.
    """
    global _chroma_client, _collection

    if not CHROMADB_AVAILABLE:
        log.error("RAG unavailable: chromadb not installed.")
        return False

    # ── Remote / Local DB client setup ───────────────────────────────────
    if getattr(config, "CHROMA_REMOTE", False):
        import chromadb

        _chroma_client = chromadb.HttpClient(
            host=config.CHROMA_SERVER_HOST,
            port=config.CHROMA_SERVER_PORT,
        )
        ef = _get_embedding_function()
        _collection = _chroma_client.get_or_create_collection(
            name="minervini_knowledge",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        log.info(
            f"RAG: Connected to remote ChromaDB at "
            f"{config.CHROMA_SERVER_HOST}:{config.CHROMA_SERVER_PORT}"
        )
    else:
        # Khởi tạo ChromaDB local (lưu persistent vào disk)
        chroma_db_path = Path(config.CHROMA_DB_PATH)
        chroma_db_path.mkdir(parents=True, exist_ok=True)

        import chromadb

        _chroma_client = chromadb.PersistentClient(path=str(chroma_db_path))
        ef = _get_embedding_function()
        _collection = _chroma_client.get_or_create_collection(
            name="minervini_knowledge",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

    knowledge_dir = Path(config.KNOWLEDGE_DIR)
    # Fallback: check common Docker mount paths if primary not found
    fallback_dirs = [
        Path("/app/knowledge/trading_wizard/chunks"),
        Path("/app/docs/knowledge/trading_wizard/chunks"),
        Path(config.KNOWLEDGE_DIR),
    ]
    if not knowledge_dir.exists():
        for fb in fallback_dirs:
            if fb.exists() and list(fb.glob("chunk_*.md")):
                log.info(f"RAG: Using fallback knowledge dir: {fb}")
                knowledge_dir = fb
                break

    if not knowledge_dir.exists():
        if getattr(config, "CHROMA_REMOTE", False) and _collection.count() > 0:
            log.info(
                f"RAG: Knowledge dir not found, but remote ChromaDB has {_collection.count()} vectors. Using existing data."
            )
            return True
        elif getattr(config, "CHROMA_REMOTE", False):
            log.warning(
                f"RAG: Knowledge dir not found ({knowledge_dir}) AND remote ChromaDB is EMPTY. RAG will be non-functional!"
            )
            return True  # Don't crash, but RAG won't work
        log.error(f"RAG: Knowledge dir not found: {knowledge_dir}")
        return False

    chunk_files = sorted(knowledge_dir.glob("chunk_*.md"))
    if not chunk_files:
        log.warning(f"RAG: No chunk files found in {knowledge_dir}")
        return False

    # Kiểm tra xem đã embed chưa (tránh re-embed mỗi lần restart)
    existing_count = _collection.count()
    if existing_count >= len(chunk_files):
        log.info(f"RAG: Vector DB đã có {existing_count} vectors. Bỏ qua re-embedding.")
        return True

    log.info(f"RAG: Bắt đầu embed {len(chunk_files)} Minervini chunks → ChromaDB...")

    documents, metadatas, ids = [], [], []

    for chunk_file in chunk_files:
        try:
            content = chunk_file.read_text(encoding="utf-8")
            if not content.strip():
                continue
            meta = _parse_chunk_metadata(content, chunk_file.name)
            doc_id = f"minervini_{chunk_file.stem}"

            documents.append(content)
            metadatas.append(meta)
            ids.append(doc_id)
        except Exception as e:
            log.warning(f"RAG: Lỗi đọc {chunk_file.name}: {e}")

    if documents:
        # Upsert theo batch (tránh timeout với nhiều docs)
        batch_size = 10
        for i in range(0, len(documents), batch_size):
            _collection.upsert(
                documents=documents[i : i + batch_size],
                metadatas=metadatas[i : i + batch_size],
                ids=ids[i : i + batch_size],
            )
        log.info(f"RAG: ✅ Đã embed và lưu {len(documents)} chunks vào ChromaDB.")

    return True


def query_knowledge(query: str, n_results: int = 3) -> list[dict]:
    """
    Truy vấn Vector DB để tìm các đoạn Minervini liên quan nhất.

    Args:
        query: Câu truy vấn ngữ nghĩa (vd: "Quy tắc mua khi VCP breakout")
        n_results: Số lượng kết quả trả về (mặc định 3)

    Returns:
        List of dicts với keys: 'content', 'metadata', 'distance'
    """
    if _collection is None:
        log.warning("RAG: Collection chưa được khởi tạo.")
        return []

    try:
        if _collection.count() == 0:
            log.warning("RAG: Collection is empty.")
            return []

        results = _collection.query(
            query_texts=[query],
            n_results=min(n_results, _collection.count()),
        )

        output = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc, meta, dist in zip(docs, metas, distances, strict=False):
            output.append(
                {
                    "content": doc,
                    "metadata": meta,
                    "relevance_score": round(1 - dist, 4),  # cosine similarity
                }
            )

        log.info(f"RAG: Query '{query[:50]}...' → {len(output)} chunks retrieved.")
        return output

    except Exception as e:
        log.error(f"RAG query error: {e}")
        return []


def _call_gemini(prompt: str, has_vertex: bool, has_genai: bool) -> str | None:
    """Shared Gemini call logic (DRY — used by both primary and fallback paths).

    Returns advice text on success, None on auth failure.
    Raises on API error (caller handles).
    """
    model_name = "gemini-2.5-flash"

    _use_vertex = False
    if has_vertex:
        try:
            import google.auth

            google.auth.default()
            _use_vertex = True
        except Exception:
            log.warning("Vertex AI ADC not found — falling back to GEMINI_API_KEY")

    if _use_vertex:
        import vertexai
        from vertexai.generative_models import GenerativeModel as VertexGenerativeModel

        vertexai.init(
            project=config.GCP_PROJECT_ID,
            location=getattr(config, "GCP_LOCATION", "us-central1"),
        )
        g_model = VertexGenerativeModel(model_name)
        response = g_model.generate_content(prompt)
        return response.text
    elif has_genai:
        from google import genai

        client = genai.Client(api_key=config.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        return response.text
    else:
        return None


async def generate_trading_advice(
    symbol: str,
    action: str,
    price: str,
    payload: dict,
    rag_chunks: list[dict],
) -> str:
    """
    Gọi Claude (Anthropic) để phân tích tín hiệu giao dịch dựa trên kiến thức Minervini.

    Args:
        symbol: Mã cổ phiếu/crypto (vd: "BTCUSDT")
        action: "buy" | "sell" | "alert"
        price: Giá hiện tại
        payload: Full webhook payload từ TradingView
        rag_chunks: Các đoạn kiến thức Minervini được retrieve

    Returns:
        Chuỗi phân tích từ Claude, hoặc thông báo lỗi.
    """
    provider = getattr(config, "AI_PROVIDER", "anthropic").lower()

    # Determine if Gemini is available
    has_vertex = VERTEXAI_AVAILABLE and getattr(config, "GCP_PROJECT_ID", None)
    has_genai = GENAI_AVAILABLE and getattr(config, "GEMINI_API_KEY", None)
    has_gemini = bool(has_vertex or has_genai)

    # Determine if Anthropic is available via SDK (non-mock, non-placeholder key)
    has_anthropic_sdk = (
        ANTHROPIC_AVAILABLE
        and bool(getattr(config, "ANTHROPIC_API_KEY", None))
        and not getattr(config, "ANTHROPIC_API_KEY", "").startswith("sk-ant-xxx")
    )

    if provider == "antigravity":
        if not ANTIGRAVITY_AVAILABLE:
            return "⚠️ RAG Analysis không khả dụng (thiếu google-antigravity SDK)."
    elif provider == "claude_cli":
        pass  # không cần check key, sẽ verify binary khi gọi
    elif provider == "gemini":
        if not has_gemini:
            return "⚠️ RAG Analysis không khả dụng (thiếu GEMINI_API_KEY hoặc GCP_PROJECT_ID)."
    elif provider == "agy":
        pass  # validated at execution time via AgyHarness
    elif provider == "anthropic":
        # Priority: Claude CLI (OAuth) → SDK (API key) → Gemini fallback
        # User dùng Claude login session — không cần ANTHROPIC_API_KEY
        pass  # will try CLI first, then SDK, then Gemini in execution block
    else:
        if ANTIGRAVITY_AVAILABLE:
            provider = "antigravity"
        elif not has_anthropic_sdk:
            if has_gemini:
                log.info(
                    "RAG: Anthropic not configured/mock. Switching to Gemini fallback."
                )
                provider = "gemini"
            else:
                return "⚠️ RAG Analysis không khả dụng (thiếu ANTHROPIC_API_KEY)."

    if not rag_chunks:
        return "⚠️ Không tìm thấy kiến thức phù hợp trong Knowledge Base."

    # ── Xây dựng context từ các chunks retrieved ─────────────────────────
    context_parts = []
    for i, chunk in enumerate(rag_chunks, 1):
        meta = chunk.get("metadata", {})
        score = chunk.get("relevance_score", 0)
        topic = meta.get("topic", "N/A")
        content_preview = chunk["content"][:400]  # giới hạn context (compressed)
        context_parts.append(
            f"[Tài liệu {i} | Chủ đề: {topic} | Độ liên quan: {score:.2%}]\n{content_preview}"
        )

    knowledge_context = "\n\n---\n\n".join(context_parts)

    # ── Extra market data từ payload ──────────────────────────────────────
    volume = payload.get("volume", "N/A")
    volume_avg = payload.get("volume_avg", "N/A")
    rsi = payload.get("rsi", "N/A")
    alert_type = payload.get("alert_type", action)
    timeframe = payload.get("timeframe", "N/A")

    # ── VCP & Trend Template stats ─────────────────────────────────────────
    vcp_stats = payload.get("vcp_stats", {})
    trend_stats = payload.get("trend_stats", {})

    stats_context = ""
    if trend_stats:
        if "error" in trend_stats:
            stats_context += (
                f"- Trend Template Checklist: ERROR ({trend_stats['error']})\n"
            )
        else:
            stats_context += (
                f"- Macro Regime: {trend_stats.get('macro_regime', 'Unknown')}\n"
            )
            stats_context += f"- Trend Template Score: {trend_stats.get('score', 0)}/8 ({trend_stats.get('stage', 'Unknown')})\n"
            stats_context += f"  Detail: {trend_stats.get('summary', '')}\n"
            criteria_list = []
            for k, v in trend_stats.get("criteria", {}).items():
                status = "✅" if v is True else ("❌" if v is False else "❓")
                criteria_list.append(f"{k}: {status}")
            stats_context += f"  Checklist: {', '.join(criteria_list)}\n"

    if vcp_stats:
        if vcp_stats.get("detected"):
            stats_context += f"- VCP Pattern: DETECTED (Quality: {vcp_stats.get('quality_score', 0)}%)\n"
            stats_context += (
                f"  Pivot Breakout Level: {vcp_stats.get('pivot_line', 0.0)}\n"
            )
            stats_context += (
                f"  Contractions ({vcp_stats.get('contractions_count', 0)} waves):\n"
            )
            for idx, c in enumerate(vcp_stats.get("contractions", []), 1):
                stats_context += f"    * Wave {idx}: High={c['high']}, Low={c['low']}, Depth={c['depth_pct']}%, Duration={c['duration_bars']} bars\n"
        else:
            stats_context += (
                "- VCP Pattern: NOT DETECTED or invalid contraction sequence\n"
            )

    pattern_detection = payload.get("pattern_detection", "")
    if pattern_detection:
        stats_context += f"- Pattern Result (AI Analyzer): {pattern_detection}\n"

    prompt = f"""Chuyên gia SEPA Minervini. Phân tích tín hiệu TradingView.

## TÍN HIỆU: {symbol} {action.upper()} @ {price}
- Loại: {alert_type} | TF: {timeframe}
- Vol: {volume} (avg: {volume_avg}) | RSI: {rsi}

## CHỈ BÁO KỸ THUẬT THỰC TẾ (HỆ THỐNG TỰ TÍNH TOÁN)
{stats_context}

## KIẾN THỨC MINERVINI
{knowledge_context}

## YÊU CẦU (dưới 150 từ, emoji cho Telegram)
1. Bắt đầu bằng chữ 'APPROVED', 'REJECTED' hoặc 'WAIT' dựa trên việc kiểm duyệt quy tắc.
2. Chất lượng tín hiệu (Mạnh/Trung bình/Yếu) + lý do.
3. Phải đối chiếu chéo các chỉ báo thực tế trên (Trend Template, VCP, Volume) với tài liệu kiến thức Minervini. Nếu Trend Template < 5/8 hoặc Stop Loss thực tế > 8% (hoặc mẫu hình VCP bị hỏng), bắt buộc phải từ chối (bắt đầu bằng REJECTED hoặc WAIT).
4. Khuyến nghị + SL/TP gợi ý cụ thể.
5. Cảnh báo rủi ro."""

    try:
        # ── agy: bridge sidecar (host :9100, google-genai SDK, ~12s) ──
        # NOTE: google.antigravity Agent SDK wraps localharness (Go binary)
        # which launches a full agent session → always >20s → not suitable
        # for single-shot analysis. Bridge uses google-genai SDK directly.
        if provider == "agy":
            agy_model = getattr(config, "AGY_MODEL", "gemini-2.5-flash")

            from agy_harness import AgyHarness

            harness = AgyHarness(
                bridge_url=getattr(
                    config, "AGY_BRIDGE_URL", "http://host.docker.internal:9100"
                ),
                timeout_sec=getattr(config, "AGY_TIMEOUT_SEC", 25),
                model=agy_model,
            )
            try:
                result = await harness.analyze(prompt)
                if result.success:
                    log.info(
                        f"RAG: agy bridge generated advice for {symbol} ({action}) "
                        f"[{result.latency_ms:.0f}ms]"
                    )
                    return f"{result.advice}\n\n[Provider: {result.provider or 'agy-bridge'}]"
                else:
                    log.warning(
                        f"RAG: agy bridge failed ({result.error}). "
                        f"Falling back to gemini..."
                    )
                    provider = "gemini"
            except Exception as e:
                log.warning(f"RAG: agy bridge error ({e}). Falling back to gemini...")
                provider = "gemini"
            finally:
                await harness.close()

        if provider == "antigravity":
            from google.antigravity import Agent, LocalAgentConfig

            model_name = getattr(config, "CLAUDE_CLI_MODEL", "") or "gemini-2.5-flash"
            agent_cfg = LocalAgentConfig(
                system_instructions="Bạn là chuyên gia giao dịch theo phương pháp SEPA của Mark Minervini. Phân tích tín hiệu giao dịch và đưa ra khuyến nghị hành động chi tiết.",
                model=model_name,
            )
            async with Agent(agent_cfg) as agent:
                response = await agent.chat(prompt)
                advice = await response.text()
            log.info(
                f"RAG: Antigravity SDK Agent 2.0 generated advice for {symbol} ({action})"
            )
            return f"{advice}\n\n[Provider: antigravity-sdk]"

        if provider == "claude_cli":
            try:
                advice = await _call_claude_cli(prompt)
                log.info(f"RAG: Claude CLI generated advice for {symbol} ({action})")
                return f"{advice}\n\n[Provider: claude-cli]"
            except ClaudeCLIError as e:
                log.warning(f"RAG: Claude CLI fail ({e}). Fallback?")
                if (
                    getattr(config, "CLAUDE_CLI_FALLBACK_SDK", True)
                    and ANTHROPIC_AVAILABLE
                    and getattr(config, "ANTHROPIC_API_KEY", None)
                ):
                    log.info("RAG: Fallback sang Anthropic SDK.")
                    # Rơi xuống nhánh else dưới
                else:
                    return f"⚠️ Claude CLI lỗi: {e}"
                provider = "anthropic"  # ép xuống nhánh SDK
        if provider == "gemini":
            advice = _call_gemini(prompt, has_vertex, has_genai)
            if advice is None:
                return "⚠️ RAG Analysis không khả dụng (thiếu Gemini auth)."
            log.info(f"RAG: Gemini generated advice for {symbol} ({action})")
            return f"{advice}\n\n[Provider: gemini-direct]"

        elif provider in ("anthropic", "claude_cli"):
            # Priority chain: Claude CLI (OAuth session) → SDK (API key) → Gemini fallback
            # Step 1: Try Claude CLI (uses user's Claude login — no API key needed)
            try:
                advice = await _call_claude_cli(prompt)
                log.info(
                    f"RAG: Claude CLI (auth session) generated advice for {symbol} ({action})"
                )
                return f"{advice}\n\n[Provider: claude-cli]"
            except ClaudeCLIError as cli_err:
                log.warning(f"RAG: Claude CLI fail ({cli_err}). Trying SDK fallback...")

            # Step 2: Try Anthropic SDK (if real API key is configured)
            if has_anthropic_sdk:
                try:
                    import anthropic

                    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
                    message = client.messages.create(
                        model="claude-sonnet-4-5",
                        max_tokens=512,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    advice = message.content[0].text
                    log.info(
                        f"RAG: Claude SDK generated advice for {symbol} ({action})"
                    )
                    return f"{advice}\n\n[Provider: claude-sdk]"
                except Exception as sdk_err:
                    log.warning(
                        f"RAG: Anthropic SDK fail ({sdk_err}). Trying Gemini fallback..."
                    )

            # Step 3: Gemini fallback
            if has_gemini:
                log.info("RAG: Falling back to Gemini...")
                provider = "gemini"  # will be caught by fallback block below
            else:
                return "⚠️ Claude không khả dụng (CLI + SDK failed). Cài đặt GEMINI_API_KEY để fallback."

        else:
            # Unknown provider — try anthropic SDK directly
            try:
                import anthropic

                client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
                message = client.messages.create(
                    model="claude-sonnet-4-5",
                    max_tokens=512,
                    messages=[{"role": "user", "content": prompt}],
                )
                advice = message.content[0].text
                log.info(f"RAG: Claude generated advice for {symbol} ({action})")
                return f"{advice}\n\n[Provider: claude-sdk]"
            except Exception as sdk_err:
                if has_gemini:
                    log.warning(
                        f"RAG: Anthropic call failed ({sdk_err}). Falling back to Gemini..."
                    )
                    provider = "gemini"
                else:
                    raise sdk_err

        # Run Gemini if fallback activated it
        if provider == "gemini":
            advice = _call_gemini(prompt, has_vertex, has_genai)
            if advice is None:
                return "⚠️ RAG Analysis không khả dụng (thiếu Gemini auth)."
            log.info(f"RAG: Gemini fallback generated advice for {symbol} ({action})")
            return f"{advice}\n\n[Provider: gemini-fallback]"

    except Exception as e:
        log.error(f"RAG API error: {e}")
        return f"⚠️ Lỗi kết nối AI API: {str(e)[:100]}"


def build_rag_query(symbol: str, action: str, payload: dict) -> str:
    """
    Tạo câu truy vấn ngữ nghĩa tối ưu từ webhook payload.
    """
    alert_type = payload.get("alert_type", "")
    volume = payload.get("volume", 0)
    volume_avg = payload.get("volume_avg", 0)

    base = f"Quy tắc giao dịch Minervini khi {action}"

    if "vcp" in alert_type.lower() or "volatility contraction" in alert_type.lower():
        return f"VCP Volatility Contraction Pattern breakout điểm mua pivot {base}"
    if "trend template" in alert_type.lower():
        return f"Trend Template 8 tiêu chí Stage 2 xác nhận {base}"
    if volume and volume_avg:
        try:
            if float(volume) > float(volume_avg) * 1.5:
                return f"Volume nổ gấp đôi tăng bất thường xác nhận breakout {base}"
        except (TypeError, ValueError):
            pass
    if action == "buy":
        return f"Điểm mua tối ưu SEPA pivot breakout Stage 2 {symbol} {base}"
    if action == "sell":
        return f"Tín hiệu bán stop loss trailing stop quản lý vị thế {base}"

    return f"Quy tắc phân tích tín hiệu kỹ thuật SEPA Minervini {symbol} {base}"
