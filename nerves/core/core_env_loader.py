#!/usr/bin/env python3
"""
env_loader.py -- Centralized Secret Management (Phase 5: Security Hardening)

Single source of truth for ALL API keys across the .agents/ ecosystem.
Priority: System ENV > .env file > qdrant_config.json (legacy fallback)

Usage: import core_env_loader as env_loader; env_loader.load()
"""

import os
from pathlib import Path

# Known .env locations to search (NO recursive glob - fast direct lookup)
ENV_SEARCH_PATHS = [
    # Local workspace
    Path(__file__).resolve().parent.parent.parent / ".env",
    Path(__file__).resolve().parent.parent.parent / "memory" / ".env",
]


def _parse_env_file(path: Path) -> dict:
    """Parse a .env file. Handles BOM, comments, quoted values."""
    if not path.exists():
        return {}
    try:
        env = {}
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
        return env
    except Exception:
        return {}


def load(verbose: bool = False) -> dict:
    """
    Load secrets into os.environ. Returns dict of what was loaded.
    Priority: System ENV > .env file > qdrant_config.json fallback.
    """
    loaded = {}

    # 1. Try each known .env path (fast, no scanning)
    env_data = {}
    for path in ENV_SEARCH_PATHS:
        data = _parse_env_file(path)
        if data:
            env_data = data
            if verbose:
                print(f"[env_loader] Loaded from: {path}")
            break

    # 2. Map known keys into os.environ (only if not already set)
    KEY_MAP = {
        "GEMINI_API_KEY": [
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENCLAW_AUTH_GOOGLE_GEMINI_CLI_TOKEN",
            "MR_PESI_OPENCLAW_GOOGLE_MAIN_TOKEN",
            "OPENCLAW_GOOGLE_MAIN_TOKEN",
            "OPENCLAW_GOOGLE_FARM_PESI",
        ],
        "OPENAI_API_KEY": ["OPENAI_API_KEY", "OPENCLAW_OPENAI_API_KEY"],
        "OPENROUTER_API_KEY": ["OPENROUTER_API_KEY"],
        "ANGATI_EDGE_ID": ["ANGATI_EDGE_ID", "EDGE_NODE_ID"],
    }

    for target_key, source_candidates in KEY_MAP.items():
        if os.environ.get(target_key):
            loaded[target_key] = "already_set"
            continue
        for candidate in source_candidates:
            val = env_data.get(candidate, "")
            if val and len(val) > 10:
                os.environ[target_key] = val
                loaded[target_key] = f"from:{candidate}"
                break

    # 3. Legacy fallback: qdrant_config.json
    import json

    cfg_path = (
        Path(__file__).resolve().parent.parent.parent / "memory" / "qdrant_config.json"
    )
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            for k in ["gemini_api_key", "openai_api_key", "openrouter_api_key"]:
                env_k = k.upper()
                if not os.environ.get(env_k) and cfg.get(k) and len(cfg[k]) > 10:
                    os.environ[env_k] = cfg[k]
                    loaded[env_k] = "from:qdrant_config_legacy"
        except ValueError as e:
            import logging

            logging.getLogger(__name__).warning("Ignored: %s", e)

    # 4. Phase 12 (Hard Right): Force Colab A100 Tunnel logic
    # If the orchestrator has a running Colab vLLM, redirect all `openai/` tools there.
    tunnel_path = (
        Path(__file__).resolve().parent.parent.parent / "memory" / "cf_tunnel.url"
    )
    if tunnel_path.exists():
        try:
            cf_url = tunnel_path.read_text(encoding="utf-8").strip()
            if cf_url:
                os.environ["OPENAI_API_BASE"] = f"{cf_url}/v1"
                os.environ["OPENAI_API_KEY"] = (
                    "dummy_for_vllm"  # pragma: allowlist secret
                )
                loaded["OPENAI_API_BASE"] = "from:cf_tunnel.url"
                loaded["OPENAI_API_KEY"] = (
                    "from:cf_tunnel.url (dummy)"  # pragma: allowlist secret
                )
        except OSError:
            # Tunnel URL file unreadable — skip silently, not a critical path
            pass

    return loaded


if __name__ == "__main__":
    result = load(verbose=True)
    import json

    # Show what was loaded (key names only, NOT values)
    print(json.dumps({k: v for k, v in result.items()}, indent=2))
