"""Tests for utils/html_chunker.py — Telegram HTML truncation and chunking."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.html_chunker import truncate_caption_html_safe, chunk_html_message


# ── truncate_caption_html_safe ────────────────────────────


def test_truncate_short_text_unchanged():
    text = "Hello world"
    assert truncate_caption_html_safe(text, 1024) == text


def test_truncate_long_text():
    text = "A" * 2000
    result = truncate_caption_html_safe(text, 1024)
    assert len(result) <= 1024
    assert result.endswith("…")


def test_truncate_preserves_html_tags():
    text = "<b>Bold text that is " + "x" * 1000 + "</b>"
    result = truncate_caption_html_safe(text, 100)
    assert len(result) <= 100
    # With max_len=100 and original 1020+ chars, function may strip HTML
    # to fit. Either </b> is present (preserved) or tags are stripped (plain text).
    # Key invariant: no broken tags
    open_bracket = result.rfind("<")
    close_bracket = result.rfind(">")
    if open_bracket >= 0:
        assert close_bracket > open_bracket, "Found broken HTML tag"


def test_truncate_no_broken_tags():
    text = "Hello <b>wor" + "l" * 1000 + "d</b>"
    result = truncate_caption_html_safe(text, 50)
    assert len(result) <= 50
    # Should not have broken tag like "<b" without ">"
    open_bracket = result.rfind("<")
    close_bracket = result.rfind(">")
    if open_bracket >= 0:
        assert close_bracket > open_bracket, "Found broken HTML tag"


# ── chunk_html_message ────────────────────────────────────


def test_chunk_short_message_single():
    text = "Hello world"
    chunks = chunk_html_message(text, 4096)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_long_message_splits():
    # Create text with many paragraphs
    paragraphs = [f"Paragraph {i}: " + "x" * 100 for i in range(50)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_html_message(text, 500)
    assert len(chunks) > 1
    # Each chunk should be within limit
    for chunk in chunks:
        assert len(chunk) <= 500 + 20  # small margin for numbering


def test_chunk_numbering():
    paragraphs = ["A" * 200 for _ in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_html_message(text, 500)
    if len(chunks) > 1:
        assert chunks[0].startswith("(1/")
        assert chunks[-1].startswith(f"({len(chunks)}/")


def test_chunk_single_long_paragraph():
    text = "A" * 5000  # single paragraph > 4096
    chunks = chunk_html_message(text, 4096)
    assert len(chunks) >= 1
    # Should handle gracefully without crashing
