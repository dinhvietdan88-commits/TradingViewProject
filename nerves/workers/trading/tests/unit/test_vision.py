"""
Unit tests: test_vision.py
Tests for AI prompt formatting, algorithmic context building, and response parsing.
"""

from vision import (
    _build_algo_context,
    _parse_confidence,
    _parse_patterns,
    format_vision_telegram,
)


def test_build_algo_context_empty():
    """Should return fallback string when no scanner data is provided."""
    assert _build_algo_context(None) == "Không có dữ liệu scanner."
    assert _build_algo_context({}) == "Không có dữ liệu scanner."


def test_build_algo_context_with_data():
    """Should correctly format quantitative scan results into the prompt context."""
    scan_result = {
        "price": 68000.5,
        "trend_template_score": 7,
        "trend_template_stage": "Stage 2",
        "vcp_detected": True,
        "volume_ratio": 1.5,
        "pivot_level": 68500.0,
    }
    context = _build_algo_context(scan_result)
    assert "- Price: 68,000.50" in context
    assert "- Trend Template: 7/8" in context
    assert "- Stage: Stage 2" in context
    assert "- VCP (algorithmic): ✅ Detected" in context
    assert "- Volume ratio: 150% of avg" in context
    assert "- Pivot estimate: 68,500.00" in context


def test_parse_confidence():
    """Should parse the confidence score effectively from free-form AI text."""
    assert _parse_confidence("Score: 8/10") == 8
    assert _parse_confidence("Confidence: 9/10") == 9
    assert _parse_confidence("Tin cậy: 7") == 7
    assert _parse_confidence("7/10") == 7
    assert _parse_confidence("I give it a 6/10 because it looks okay.") == 6
    assert _parse_confidence("No score mentioned here.") == 5  # Default fallback


def test_parse_patterns():
    """Should detect specific known trading patterns inside AI generated text."""
    text = "I see a Cup with Handle and some Volatility Contraction here in Stage 2."
    patterns = _parse_patterns(text)
    assert "Cup with Handle" in patterns
    assert "Volatility Contraction" in patterns
    assert "Stage 2" in patterns


def test_format_vision_telegram_success():
    """Should correctly format the final Telegram alert message."""
    vision_result = {
        "analysis": "This is a great chart.",
        "combined_score": "8.5/10",
        "verdict": "🟢 STRONG BUY SETUP",
        "patterns": ["VCP", "Stage 2"],
    }
    msg = format_vision_telegram(vision_result)
    assert "This is a great chart." in msg
    assert "Combined Score: *8.5/10*" in msg
    assert "Verdict: *🟢 STRONG BUY SETUP*" in msg
    assert "Patterns: VCP, Stage 2" in msg


def test_format_vision_telegram_error():
    """Should format the error message properly when API calls fail."""
    vision_result = {"error": "Failed to connect to API"}
    msg = format_vision_telegram(vision_result)
    assert "👁️ Vision Error: Failed to connect to API" in msg


def test_encode_image_compression(tmp_path):
    """Should compress and resize image using PIL and return base64 and mime type."""
    import base64
    import io

    from PIL import Image

    from vision import _encode_image

    # Create a dummy large image (e.g. 2000x2000 px)
    img_path = tmp_path / "large_chart.png"
    img = Image.new("RGB", (2000, 2000), color="blue")
    img.save(img_path)

    base64_str, mime_type = _encode_image(img_path, max_width=1024)

    # Assertions
    assert base64_str is not None
    assert mime_type == "image/webp"

    # Decode image to verify size
    decoded_img = Image.open(io.BytesIO(base64.b64decode(base64_str)))
    assert decoded_img.width == 1024
    assert decoded_img.height == 1024
    assert decoded_img.format == "WEBP"
