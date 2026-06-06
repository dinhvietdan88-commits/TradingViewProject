import json
import logging
import os
import string
from typing import Dict

log = logging.getLogger(__name__)

TEMPLATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "telegram_templates.json",
)

DEFAULT_TEMPLATES = {
    "A": (
        "🔔 <b>TÍN HIỆU GIAO DỊCH CẦN DUYỆT (PENDING APPROVAL)</b>\n"
        "──────────────────────────────\n"
        "🪙 <b>Mã giao dịch:</b> #{symbol}\n"
        "🚀 <b>Hành động:</b> <code>{action}</code> | <b>Giá hiện tại:</b> <code>{price}</code>\n"
        "📊 <b>Khung thời gian:</b> <code>{timeframe}</code>\n\n"
        "⚙️ <b>ĐÁNH GIÁ TIÊU CHÍ MINERVINI SEPA:</b>\n"
        "• Trend Template: <b>{tt_score}/8 ({stage})</b>\n"
        "• Volatility Contraction (VCP): <b>{vcp_status}</b>\n"
        "• Khối lượng (Volume): <code>{volume_ratio}x avg</code>\n\n"
        "🧠 <b>KHUYẾN NGHỊ AI ({ai_provider}):</b>\n"
        "{ai_advice}\n\n"
        "🛑 <b>Quản lý rủi ro (Risk Limits):</b>\n"
        "• Stop-Loss: <code>{stop_loss} ({sl_pct}%)</code>\n"
        "• Take-Profit: <code>{take_profit} ({tp_pct}%)</code>\n"
        "──────────────────────────────"
    ),
    "B": (
        "📊 <b>BÁO CÁO QUÉT THỊ TRƯỜNG (MARKET WATCHLIST SCAN)</b>\n"
        "──────────────────────────────\n"
        "⏱️ <b>Thời gian quét:</b> <code>{scan_time}</code>\n"
        "🎯 <b>Trạng thái xu hướng các mã đang theo dõi:</b>\n\n"
        "{scan_results_list}\n"
        "──────────────────────────────"
    ),
    "C": (
        "🔴 <b>CẢNH BÁO: SỰ CỐ HỆ THỐNG PHÂN PHỐI (CRITICAL OUTAGE)</b>\n"
        "──────────────────────────────\n"
        "💻 <b>Máy chủ:</b> <code>{server_name}</code>\n"
        "🏷️ <b>Mã sự cố:</b> #{error_code}\n"
        "📌 <b>Dịch vụ gặp lỗi:</b> <code>{service_name}</code>\n\n"
        "🔍 <b>Triệu chứng lỗi (Traceback Preview):</b>\n"
        "<pre>{error_traceback}</pre>\n\n"
        "🩺 <b>Tự động chẩn đoán & Khắc phục:</b>\n"
        "⚠️ {diagnostic_recommendation}\n\n"
        "🛠️ <b>Hành động nhanh (Quick Actions):</b>\n"
        "──────────────────────────────"
    ),
    "D": (
        "🟡 <b>CẢNH BÁO: LỖI THỰC THI GIAO DỊCH (EXECUTION WARNING)</b>\n"
        "──────────────────────────────\n"
        "🪙 <b>Mã giao dịch:</b> #{symbol}\n"
        "📢 <b>Sàn giao dịch:</b> <code>{exchange}</code>\n"
        "🚨 <b>Vấn đề:</b> <code>{warning_detail}</code>\n\n"
        "📋 <b>Thông tin chi tiết:</b>\n"
        "<pre>{details_block}</pre>\n"
        "🩺 <b>Hướng giải quyết:</b>\n"
        "{fallback_action_desc}\n"
        "──────────────────────────────"
    ),
}

MOCK_KEYS = {
    "symbol": "BTC",
    "action": "BUY",
    "price": "67250.50",
    "timeframe": "1D",
    "tt_score": "8",
    "stage": "Stage 2",
    "vcp_status": "Confirmed",
    "volume_ratio": "1.8",
    "ai_provider": "Claude-3.5-Sonnet RAG",
    "ai_advice": "Strong bullish continuation pattern.",
    "stop_loss": "62540.00",
    "sl_pct": "-7.0",
    "take_profit": "80700.00",
    "tp_pct": "+20.0",
    "id": "1",
    "scan_time": "12:00:00",
    "scan_results_list": "1. BTC - Score 8/8",
    "server_name": "Local",
    "error_code": "ERR-CDP-2620",
    "service_name": "TradingView",
    "error_traceback": "Traceback info",
    "diagnostic_recommendation": "Check CDP port",
    "exchange": "Binance",
    "warning_detail": "API rate limit",
    "details_block": "Rate limit info",
    "fallback_action_desc": "Retry in 60s",
}

_templates_cache: Dict[str, str] = {}


def get_templates_file_path() -> str:
    return TEMPLATE_FILE


def load_templates() -> Dict[str, str]:
    """Load templates from json file, falling back to defaults if not exists or corrupted."""
    global _templates_cache
    if _templates_cache:
        return _templates_cache

    templates = DEFAULT_TEMPLATES.copy()
    if os.path.exists(TEMPLATE_FILE):
        try:
            with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k in ["A", "B", "C", "D"]:
                    if k in data and isinstance(data[k], str):
                        templates[k] = data[k]
            log.info("Loaded custom Telegram templates from file.")
        except Exception as e:
            log.error(
                f"Error loading Telegram templates json: {e}, falling back to defaults"
            )
    else:
        # Write default templates to file initially
        try:
            with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
                json.dump(templates, f, indent=4, ensure_ascii=False)
            log.info("Initialized default Telegram templates file.")
        except Exception as e:
            log.error(f"Could not initialize Telegram templates file: {e}")

    _templates_cache = templates
    return _templates_cache


def validate_template_syntax(template_id: str, content: str) -> None:
    """Validate that the template compiles with python format() using mock keys.
    Raises ValueError on mismatch/invalid format.
    """
    # 1. Parse fields using standard string Formatter to check for unbalanced braces
    try:
        fields = [
            field_name
            for _, field_name, _, _ in string.Formatter().parse(content)
            if field_name is not None
        ]
    except ValueError as err:
        raise ValueError(
            f"Template {template_id} contains syntax error: {str(err)}"
        ) from err

    # 2. Try dry-run rendering with mock keys to check for missing/unsupported tags
    # We build a dictionary containing only the fields specified in the string.
    # If the user put a field NOT in MOCK_KEYS, we'll raise an error.
    mock_payload = {}
    for f in fields:
        # Handle index-based or nested formatting if present (we only support standard keys)
        if not f:
            raise ValueError(
                f"Template {template_id} contains empty placeholders '{{}}' which is not supported."
            )
        if f not in MOCK_KEYS:
            raise ValueError(
                f"Template {template_id} contains unsupported placeholder key: '{{{f}}}'"
            )
        mock_payload[f] = MOCK_KEYS[f]

    try:
        content.format(**mock_payload)
    except Exception as err:
        raise ValueError(
            f"Template {template_id} failed dry-run format validation: {str(err)}"
        ) from err


def save_templates(templates: Dict[str, str]) -> None:
    """Validate and write templates to config file, updating the runtime cache."""
    global _templates_cache

    # 1. Validation check
    for k in ["A", "B", "C", "D"]:
        if k not in templates:
            raise ValueError(f"Missing required template ID: '{k}'")
        validate_template_syntax(k, templates[k])

    # 2. Write to file
    try:
        with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
            json.dump(templates, f, indent=4, ensure_ascii=False)
        log.info(f"Saved custom Telegram templates to {TEMPLATE_FILE}")
    except Exception as err:
        log.error(f"Failed to save Telegram templates to file: {err}")
        raise ValueError(f"Could not write templates to file: {str(err)}") from err

    # 3. Update cache
    _templates_cache = templates.copy()


def render_template(template_id: str, **kwargs) -> str:
    """Retrieve template_id and render with kwargs.
    Safely handles missing keys by leaving them empty or returning N/A to prevent crashes.
    """
    templates = load_templates()
    template_str = templates.get(template_id, DEFAULT_TEMPLATES.get(template_id, ""))

    # Pre-populate missing keys with 'N/A' to avoid KeyError
    fields = [
        field_name
        for _, field_name, _, _ in string.Formatter().parse(template_str)
        if field_name is not None
    ]

    render_args = {}
    for f in fields:
        if f in kwargs:
            render_args[f] = kwargs[f]
        else:
            render_args[f] = "N/A"

    try:
        return template_str.format(**render_args)
    except Exception as e:
        log.error(f"Error rendering template {template_id}: {e}")
        # Return fallback default template render on absolute crash
        default_str = DEFAULT_TEMPLATES.get(template_id, "")
        default_args = {
            f: kwargs.get(f, "N/A")
            for _, f, _, _ in string.Formatter().parse(default_str)
            if f is not None
        }
        return default_str.format(**default_args)
