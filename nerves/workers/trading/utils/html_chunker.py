"""
HTML Chunking Utilities for Telegram Messages.

Handles Telegram API limits:
  - Photo caption: 1024 characters max
  - Text message: 4096 characters max

Ensures HTML tags are never broken mid-tag when truncating/chunking.
"""

import logging
import re

log = logging.getLogger(__name__)

# HTML tags we need to track for safe truncation
_OPEN_TAG_RE = re.compile(
    r"<(b|i|u|s|code|pre|a|em|strong)(?:\s[^>]*)?>", re.IGNORECASE
)
_CLOSE_TAG_RE = re.compile(r"</(b|i|u|s|code|pre|a|em|strong)>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def truncate_caption_html_safe(text: str, max_len: int = 1024) -> str:
    """Truncate HTML text for Telegram photo captions (1024 char limit).

    Strategy:
    1. If len <= max_len: return as-is
    2. Strip text of HTML tags, truncate, add "…"
    3. If budget allows, preserve HTML structure
    """
    if len(text) <= max_len:
        return text

    # Step 1: Find all open/close tag pairs in the text
    open_tags: list[str] = []
    for match in _OPEN_TAG_RE.finditer(text):
        open_tags.append(match.group(1).lower())
    for match in _CLOSE_TAG_RE.finditer(text):
        tag_name = match.group(1).lower()
        if open_tags and open_tags[-1] == tag_name:
            open_tags.pop()

    # Estimate space needed for closing tags
    closing_space = sum(len(f"</{t}>") for t in open_tags)
    available = max_len - closing_space - 1  # -1 for "…"

    if available < 10:
        # Not enough space — strip all HTML and truncate plain text
        plain = _TAG_RE.sub("", text)
        return plain[: max_len - 1] + "…"

    # Step 2: Truncate at available length
    truncated = text[:available]

    # Step 3: Don't cut inside an HTML tag — walk backward
    last_open = truncated.rfind("<")
    last_close = truncated.rfind(">")
    if last_open > last_close:
        truncated = truncated[:last_open]

    # Step 4: Recount unclosed tags in the truncated portion
    open_in_truncated: list[str] = []
    for match in _OPEN_TAG_RE.finditer(truncated):
        open_in_truncated.append(match.group(1).lower())
    for match in _CLOSE_TAG_RE.finditer(truncated):
        tag_name = match.group(1).lower()
        if open_in_truncated and open_in_truncated[-1] == tag_name:
            open_in_truncated.pop()

    # Close remaining open tags in reverse order
    closing = "".join(f"</{tag}>" for tag in reversed(open_in_truncated))
    result = truncated + "…" + closing

    # Final safety
    if len(result) > max_len:
        plain = _TAG_RE.sub("", text)
        return plain[: max_len - 1] + "…"

    return result


def chunk_html_message(text: str, chunk_size: int = 4096) -> list[str]:
    """Split long HTML message into Telegram-safe chunks.

    Rules:
    - Split at paragraph boundaries (\\n\\n) first
    - If a single paragraph > chunk_size, split at line boundaries (\\n)
    - Never break inside HTML tags
    - Add "(1/N)" prefix to each chunk if multiple chunks

    Returns:
        List of strings, each within chunk_size limit.
    """
    if len(text) <= chunk_size:
        return [text]

    # Split by double newline (paragraph boundaries)
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        candidate = current + ("\n\n" if current else "") + para

        if len(candidate) <= chunk_size:
            current = candidate
        else:
            # Current chunk is full — save it
            if current:
                chunks.append(current.strip())

            # Check if this paragraph itself is too long
            if len(para) > chunk_size:
                # Split by single newlines
                lines = para.split("\n")
                current = ""
                for line in lines:
                    line_candidate = current + ("\n" if current else "") + line
                    if len(line_candidate) <= chunk_size:
                        current = line_candidate
                    else:
                        if current:
                            chunks.append(current.strip())
                        # If a single line is too long, hard truncate
                        if len(line) > chunk_size:
                            chunks.append(truncate_caption_html_safe(line, chunk_size))
                            current = ""
                        else:
                            current = line
            else:
                current = para

    if current.strip():
        chunks.append(current.strip())

    # Add chunk numbering if multiple chunks
    if len(chunks) > 1:
        total = len(chunks)
        chunks = [f"({i + 1}/{total})\n{chunk}" for i, chunk in enumerate(chunks)]

    return chunks if chunks else [text[:chunk_size]]
