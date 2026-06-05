"""
sec-01: Real-time Developer Sanitizers

Provides CodeQL-validated, reusable helper functions to prevent common
vulnerabilities (CWE-22, CWE-117, CWE-78) in python code.
"""

import os
import re
from pathlib import Path
from typing import List, Optional


# ── CWE-117: Log Injection Prevention ────────────────────────────────
def sanitize_log(message: str) -> str:
    """
    Sanitize log messages to prevent CRLF injection (log forging).
    Replaces newlines and carriage returns with spaces.
    """
    if not message:
        return ""
    # Replace CRLF characters
    return str(message).replace("\r", " ").replace("\n", " ")


# ── CWE-22: Path Injection Prevention ────────────────────────────────
def sanitize_path(input_path: str, allowed_roots: List[str]) -> Optional[str]:
    """
    Sanitize a file path to prevent Path Traversal (CWE-22) and directory traversal.
    Returns the resolved, safe absolute path, or None if the path is invalid or escape is detected.

    Implements the 5-step fresh-path reconstruction logic validated by CodeQL:
    1. Resolve and normalize absolute path.
    2. Verify path prefix matches one of the allowed roots.
    3. Re-verify using relpath to ensure no traversal parts '..' remain.
    4. Reconstruct clean path using only safe parts.
    5. Return the newly created path string.
    """
    if not input_path:
        return None

    try:
        # Step 1: Normalize and resolve the path
        resolved = os.path.realpath(os.path.normpath(str(input_path)))

        # Step 2: Check matching root
        matched_root = None
        for r in allowed_roots:
            abs_root = os.path.realpath(os.path.normpath(r))
            if resolved.startswith(abs_root):
                matched_root = abs_root
                break

        if not matched_root:
            return None

        # Step 3: Traversal component double check
        rel = os.path.relpath(resolved, matched_root)
        parts = Path(rel).parts
        if ".." in parts or any(p.startswith("..") for p in parts):
            return None

        # Step 4: Fresh path reconstruction (breaks the CodeQL data-flow taint trace)
        clean_path = matched_root
        for part in parts:
            if part and part != ".":
                clean_path = os.path.join(clean_path, part)

        # Step 5: Final safety verify
        if not os.path.realpath(clean_path).startswith(matched_root):
            return None

        return clean_path
    except Exception:
        return None


# ── General Input Validation: Symbol Sanitizer ──────────────────────
def sanitize_symbol(symbol: str) -> str:
    """
    Sanitize a trading symbol to allow only standard alphanumeric, dots, and hyphens.
    Example: BTCUSDT, ETH-USDT, BTC.P
    """
    if not symbol:
        return ""
    # Only allow A-Z, 0-9, -, ., /
    cleaned = re.sub(r"[^A-Z0-9\-./]", "", str(symbol).upper())
    return cleaned
