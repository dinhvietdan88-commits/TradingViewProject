#!/usr/bin/env python3
"""
A2A Agent Card — Satellite Discovery Endpoint

Serves the Agent Card at `GET /.well-known/agent-card.json` per the
Agent-to-Agent (A2A) Protocol specification. This makes the Angati
Trading Satellite discoverable by any ADK-built agent or A2A-compliant
orchestrator.

Architecture Note:
    This module only defines the card data and handler logic.
    It is mounted into the main gateway server (a2a_handler.py).

References:
    - A2A Spec: https://google.github.io/a2a-spec/
    - KI: google-adk-deep-research (16-point isomorphism)
    - Satellite Protocol v1.4 (platform.go → discover.go parallel)
"""

import json
import os
from datetime import datetime, UTC

# ---------------------------------------------------------------------------
# Agent Card Schema (A2A v1.0 compliant)
# ---------------------------------------------------------------------------


def build_agent_card(*, host: str = "localhost", port: int = 9108) -> dict:
    """
    Build the A2A Agent Card for this satellite node.

    The card structure follows the A2A specification:
    - Identity: name, description, version
    - Connectivity: url, protocols
    - Capabilities: streaming, push notifications
    - Skills: advertised agent capabilities
    - Authentication: supported auth schemes

    Returns:
        dict: A2A-compliant Agent Card
    """
    return {
        "name": "angati-trading-satellite",
        "description": (
            "Sovereign TradingView signal processing & trade execution satellite. "
            "Receives indicator webhooks, validates signals against scar memory, "
            "and executes trades via exchange APIs. Part of the Angati V10 ecosystem."
        ),
        "version": "10.0.0",
        "url": f"http://{host}:{port}",
        "provider": {
            "organization": "Angati Sovereign Brain",
            "url": "https://github.com/UTP-TRINNETWORK",
        },
        "protocols": ["a2a/1.0", "jsonrpc/2.0", "mcp/1.0"],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "skills": [
            {
                "id": "webhook-signal-processor",
                "name": "Webhook Signal Processor",
                "description": (
                    "Receives TradingView indicator signals via webhook, "
                    "validates symbol and indicator_name fields, and stores "
                    "validated signals to the indicator_signals table in trades.db."
                ),
                "tags": ["tradingview", "webhook", "signals", "indicator"],
                "examples": [
                    "Process incoming BTCUSDT signal from TradingView",
                    "Validate and store RSI alert for ETHUSDT",
                ],
            },
            {
                "id": "trade-executor",
                "name": "Trade Executor",
                "description": (
                    "Executes trades based on validated signals via exchange APIs. "
                    "Supports stealth alert flows with exchange propagation through "
                    "AlertTriggered → SignalValidated → AnalysisComplete pipeline."
                ),
                "tags": ["trading", "execution", "exchange", "binance"],
                "examples": [
                    "Execute a BUY order for BTCUSDT based on SMA crossover",
                    "Process stealth alert with exchange routing",
                ],
            },
            {
                "id": "scar-memory-query",
                "name": "Scar Memory Query",
                "description": (
                    "Queries local ChromaDB for historical scars, trading lessons, "
                    "and pattern-based circuit breaker checks. Isolated per workspace "
                    "sovereignty (does NOT access global EAIS Qdrant)."
                ),
                "tags": ["memory", "scar", "chromadb", "lessons"],
                "examples": [
                    "Check if this error pattern has occurred before",
                    "Retrieve trading lessons for MACD divergence signals",
                ],
            },
            {
                "id": "indicator-dashboard",
                "name": "Indicator Signal Dashboard",
                "description": (
                    "Provides real-time access to the Signals tab via "
                    "/api/indicator-signals endpoint. Reads from the "
                    "indicator_signals table with filtering and pagination."
                ),
                "tags": ["dashboard", "signals", "monitoring"],
                "examples": [
                    "Get latest 50 indicator signals",
                    "Filter signals by symbol BTCUSDT",
                ],
            },
        ],
        "authentication": {
            "schemes": ["bearer"],
            "credentials": "Use WEBHOOK_SECRET as Bearer token",
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "metadata": {
            "angati_epoch": "V10.0",
            "brain_architecture": "7-Zone Modular (V9)",
            "sovereignty": "ISOLATED (TradingViewProject satellite)",
            "generated_at": datetime.now(UTC).isoformat(),
        },
    }


def get_agent_card_json(*, host: str = "localhost", port: int = 9108) -> str:
    """Return the Agent Card as a formatted JSON string."""
    card = build_agent_card(host=host, port=port)
    return json.dumps(card, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# HTTP Handler mixin (for embedding in a BaseHTTPRequestHandler)
# ---------------------------------------------------------------------------


class AgentCardMixin:
    """
    Mixin that adds Agent Card serving to any BaseHTTPRequestHandler.

    Usage:
        class MyHandler(AgentCardMixin, BaseHTTPRequestHandler):
            def do_GET(self):
                if not self.try_serve_agent_card():
                    # handle other routes
                    ...
    """

    _agent_card_path = "/.well-known/agent-card.json"

    def try_serve_agent_card(self) -> bool:
        """
        If the request path matches the Agent Card endpoint,
        serve the card and return True. Otherwise return False.
        """
        if self.path == self._agent_card_path:
            host = os.environ.get("A2A_HOST", "localhost")
            port = int(os.environ.get("A2A_PORT", "9108"))
            body = get_agent_card_json(host=host, port=port).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(body)
            return True
        return False
