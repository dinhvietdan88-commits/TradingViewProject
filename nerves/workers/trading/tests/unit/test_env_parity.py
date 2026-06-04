"""
test_env_parity.py — Kiểm tra sự đồng bộ giữa .env.example và config.py.

Đảm bảo mọi biến môi trường trong .env.example đều có giá trị default
trong config.py, và không có os.getenv() nào thiếu fallback nguy hiểm.
"""

import os
import re
import pytest
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────

SERVER_DIR = Path(__file__).resolve().parent.parent.parent  # server/
PROJECT_ROOT = SERVER_DIR.parent  # TradingViewProject/

CONFIG_PY = SERVER_DIR / "config.py"

# Possible locations for .env.example
ENV_EXAMPLE_CANDIDATES = [
    SERVER_DIR / ".env.example",
    PROJECT_ROOT / ".env.example",
]

# Known exceptions: vars intentionally used by subsystems, not config.py
# These vars are read directly in their respective modules/agents
ALLOWED_NOT_IN_CONFIG = {
    "OPENAI_API_KEY",          # Optional, no default needed
    "FORCE_LIVE_TRADING",      # Safety override, intentionally no default
    "ANGATI_AGENTS_ROOT",      # Used by angati satellite, not server config
    "ANGATI_BUS_BIND",         # Used by angati satellite, not server config
    "LOG_LEVEL",               # Used by logging_config.py directly
    "LOG_MAX_SIZE_MB",         # Used by logging_config.py directly
    "LOG_BACKUP_COUNT",        # Used by logging_config.py directly
    "LOG_JSON_FORMAT",         # Used by logging_config.py directly
    "SERVER_A_HEALTH_URL",     # Used by monitor.py directly
    "SERVER_B_HEALTH_URL",     # Used by monitor.py directly
    "NTP_DRIFT_THRESHOLD_MS",  # Used by monitor.py directly
    "DISK_WARNING_THRESHOLD_PCT",   # Used by monitor.py directly
    "DISK_CRITICAL_THRESHOLD_PCT",  # Used by monitor.py directly
    "LIVENESS_ALERT_AFTER_FAILURES", # Used by monitor.py directly
    "LONG_POLL_TIMEOUT_SEC",   # Used by vbs worker directly
}

# ALLOWED_NO_DEFAULT: secrets that must NOT have defaults in source code
ALLOWED_NO_DEFAULT = {
    "OPENAI_API_KEY",
    "FORCE_LIVE_TRADING",
}


def _find_env_example() -> Path | None:
    """Tìm file .env.example ở server/ hoặc project root."""
    for candidate in ENV_EXAMPLE_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _parse_env_example(path: Path) -> dict[str, str]:
    """Parse .env.example thành dict KEY -> VALUE.

    Bỏ qua comment (#) và dòng trống. Split trên dấu = đầu tiên.
    """
    env_vars = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            env_vars[key] = value.strip()
    return env_vars


def _read_config_source() -> str:
    """Đọc source code config.py dưới dạng text."""
    return CONFIG_PY.read_text(encoding="utf-8", errors="replace")


# ── Test 1: .env.example tồn tại ──────────────────────────────────────


def test_env_example_exists():
    """Kiểm tra file .env.example tồn tại ở server/ hoặc project root.

    Nếu không tồn tại, test skip với thông báo rõ ràng — không phải lỗi
    nếu project chưa tạo file này.
    """
    env_path = _find_env_example()
    if env_path is None:
        pytest.skip(
            f".env.example not found at any of: "
            f"{[str(p) for p in ENV_EXAMPLE_CANDIDATES]}. "
            f"This is acceptable if the project uses a different env management approach."
        )
    assert env_path.is_file(), f".env.example exists but is not a regular file: {env_path}"


# ── Test 2: Tất cả env keys đều có default trong config.py ────────────


def test_all_env_keys_have_config_defaults():
    """Parse .env.example, kiểm tra mỗi KEY được sử dụng ở đâu đó trong server/.

    Mỗi biến phải được đọc bởi os.getenv() trong ít nhất một Python file,
    để đảm bảo không có var nào bị khai báo trong .env.example mà không dùng.
    """
    env_path = _find_env_example()
    if env_path is None:
        pytest.skip(
            ".env.example not found — cannot verify key-to-default parity. "
            "Skipping gracefully."
        )

    env_vars = _parse_env_example(env_path)
    if not env_vars:
        pytest.skip(".env.example is empty — nothing to verify.")

    # Scan specific source dirs only (skip tests/, __pycache__, venv, node_modules)
    server_dir = Path(__file__).resolve().parent.parent.parent
    EXCLUDE_DIRS = {"tests", "__pycache__", ".venv", "venv", "node_modules", ".git", "site-packages"}

    all_python_src = ""
    for py_file in server_dir.rglob("*.py"):
        # Skip excluded directories
        if any(part in EXCLUDE_DIRS for part in py_file.parts):
            continue
        try:
            all_python_src += py_file.read_text(encoding="utf-8", errors="replace") + "\n"
        except Exception:
            pass

    # Pattern: os.getenv("KEY") or os.getenv("KEY", ...) or os.getenv(_var)
    # Also handle indirect: _var = "KEY" then os.getenv(_var, ...)
    getenv_any = re.compile(r'os\.getenv\(\s*["\']([^"\']+)["\']')
    keys_in_codebase = set(getenv_any.findall(all_python_src))

    # Also detect indirect pattern: _xxx_var = "KEY" (used by BINANCE_DRY_RUN)
    indirect_pattern = re.compile(r'=\s*["\']([A-Z_][A-Z_0-9]+)["\']\s*\n[^\n]*os\.getenv\(')
    for match in indirect_pattern.finditer(all_python_src):
        keys_in_codebase.add(match.group(1))

    not_used = []
    for key in env_vars:
        if key in ALLOWED_NOT_IN_CONFIG:
            continue
        if key not in keys_in_codebase:
            not_used.append(key)

    assert not not_used, (
        f"Keys in .env.example not found via os.getenv() anywhere in server/:\n"
        f"{not_used}\n"
        f"Either add os.getenv('{not_used[0] if not_used else '?'}', 'default') in config.py "
        f"or add to ALLOWED_NOT_IN_CONFIG if intentional."
    )


# ── Test 3: Không có bare os.getenv() thiếu default ───────────────────


def test_no_bare_getenv_without_default():
    """Scan config.py tìm os.getenv("...") KHÔNG có tham số default.

    Đây là nguy hiểm trên staging nơi .env có thể không đầy đủ,
    dẫn đến config = None → runtime error khó debug.
    """
    config_src = _read_config_source()

    # Match os.getenv("KEY") — specifically where the closing paren comes
    # right after the string, with no comma for a second argument.
    # Pattern: os.getenv("KEY") but NOT os.getenv("KEY", ...)
    bare_getenv = re.compile(
        r'os\.getenv\(\s*["\']([^"\']+)["\']\s*\)'
    )

    all_bare = bare_getenv.findall(config_src)

    # Filter out known exceptions
    dangerous = [k for k in all_bare if k not in ALLOWED_NO_DEFAULT]

    assert not dangerous, (
        f"Found os.getenv() calls WITHOUT default in config.py — dangerous on staging!\n"
        f"Variables: {dangerous}\n"
        f"Fix: add a fallback value, e.g. os.getenv('VAR', '') or os.getenv('VAR', 'default')\n"
        f"If intentionally no default, add to ALLOWED_NO_DEFAULT set in this test."
    )
