#!/usr/bin/env python3
"""
ADK Callback Bridge — Angati ↔ ADK Interoperability Layer

Provides adapters that translate between Angati hook service data
and Google ADK's CallbackContext/Event interfaces. This enables
Angati's hook system to produce ADK-compatible telemetry and
to consume ADK-formatted callback configurations.

Isomorphism:
    ADK CallbackContext  ↔  Angati SRAHookHandler input_data
    ADK Event            ↔  Angati hook response
    ADK EventActions     ↔  Angati guardrail verdicts

References:
    - KI: google-adk-deep-research §4 (Event-Driven Architecture)
    - KI: google-adk-deep-research §8 (Callback & Guardrail System)
"""

import json
import time
import uuid
from typing import Optional


# ---------------------------------------------------------------------------
# ADK Event Representation (Simplified for interop)
# ---------------------------------------------------------------------------


class ADKEvent:
    """
    Represents an ADK Event for interoperability.

    Maps the core ADK Event structure (author, content, actions, metadata)
    to a Python dataclass-like object that can be serialized to JSON.

    This is NOT a full ADK Event implementation — it's a bridge type
    that enables Angati hook data to be expressed in ADK's vocabulary.
    """

    def __init__(
        self,
        author: str,
        content_parts: list = None,
        state_delta: dict = None,
        event_id: str = None,
        invocation_id: str = None,
        partial: bool = False,
    ):
        self.author = author
        self.content_parts = content_parts or []
        self.state_delta = state_delta or {}
        self.id = event_id or str(uuid.uuid4())
        self.invocation_id = invocation_id or str(uuid.uuid4())
        self.partial = partial
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        """Serialize to ADK Event JSON format."""
        return {
            "id": self.id,
            "invocation_id": self.invocation_id,
            "author": self.author,
            "content": {"parts": self.content_parts},
            "actions": {"state_delta": self.state_delta},
            "partial": self.partial,
            "timestamp": self.timestamp,
        }

    def is_function_call(self) -> bool:
        """Check if this event contains a function_call part."""
        return any(
            isinstance(p, dict) and "function_call" in p for p in self.content_parts
        )

    def is_function_response(self) -> bool:
        """Check if this event contains a function_response part."""
        return any(
            isinstance(p, dict) and "function_response" in p for p in self.content_parts
        )

    def is_final_response(self) -> bool:
        """Check if this is the final response in a turn (non-partial, non-tool)."""
        return (
            not self.partial
            and not self.is_function_call()
            and not self.is_function_response()
        )


# ---------------------------------------------------------------------------
# Callback Context Adapter
# ---------------------------------------------------------------------------


class AngatiCallbackContext:
    """
    Adapts Angati hook data to ADK CallbackContext interface.

    This bridge allows Angati's existing hook system to express its
    pre-tool/post-tool/on-error lifecycle in ADK's vocabulary, enabling:
    1. ADK-compatible telemetry export
    2. Standardized guardrail result formatting
    3. Future integration with ADK AgentEvaluator

    Usage:
        # In hook_service.py's handle_pre_tool:
        ctx = AngatiCallbackContext.from_hook_data(input_data)
        event = ctx.to_function_call_event()
    """

    def __init__(
        self,
        tool_name: str,
        tool_input: dict,
        lifecycle: str = "before_tool",
        session_id: str = None,
    ):
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.lifecycle = lifecycle
        self.session_id = session_id or str(uuid.uuid4())
        self.state = {}
        self.invocation_id = str(uuid.uuid4())

    @classmethod
    def from_hook_data(
        cls, input_data: dict, lifecycle: str = "before_tool"
    ) -> "AngatiCallbackContext":
        """Create a CallbackContext from Angati hook service input data."""
        return cls(
            tool_name=input_data.get("tool_name", ""),
            tool_input=input_data.get("tool_input", {}),
            lifecycle=lifecycle,
            session_id=input_data.get("session_id"),
        )

    def to_function_call_event(self) -> ADKEvent:
        """
        Convert to an ADK Event representing a function_call.

        This is emitted BEFORE tool execution (maps to before_tool_callback).
        """
        return ADKEvent(
            author="angati-hook-service",
            content_parts=[
                {"function_call": {"name": self.tool_name, "args": self.tool_input}}
            ],
            state_delta=self.state,
            invocation_id=self.invocation_id,
        )

    def to_function_response_event(self, result: dict) -> ADKEvent:
        """
        Convert to an ADK Event representing a function_response.

        This is emitted AFTER tool execution (maps to after_tool_callback).
        """
        return ADKEvent(
            author="angati-hook-service",
            content_parts=[
                {"function_response": {"name": self.tool_name, "response": result}}
            ],
            state_delta=self.state,
            invocation_id=self.invocation_id,
        )

    def to_guardrail_event(self, guardrail_result: dict) -> ADKEvent:
        """
        Convert guardrail evaluation result to an ADK Event.

        This captures the guardrail's decision (ALLOW/BLOCK/WARN) as
        an ADK event for telemetry and observability.
        """
        return ADKEvent(
            author="angati-guardrail-engine",
            content_parts=[
                {
                    "text": json.dumps(
                        {
                            "tool": self.tool_name,
                            "lifecycle": self.lifecycle,
                            "guardrail_result": guardrail_result,
                        }
                    )
                }
            ],
            state_delta={
                "last_guardrail_decision": guardrail_result.get("decision", "allow"),
                "last_guardrail_verdicts": len(guardrail_result.get("verdicts", [])),
            },
            invocation_id=self.invocation_id,
        )


# ---------------------------------------------------------------------------
# Telemetry Export
# ---------------------------------------------------------------------------


class ADKTelemetryExporter:
    """
    Exports Angati hook events in ADK-compatible format for observability.

    This can be connected to OpenTelemetry exporters or written to
    a local JSONL file for offline analysis.
    """

    def __init__(self, output_path: Optional[str] = None):
        self.output_path = output_path
        self._events: list[dict] = []

    def record(self, event: ADKEvent):
        """Record an ADK event."""
        event_dict = event.to_dict()
        self._events.append(event_dict)

        if self.output_path:
            try:
                with open(self.output_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event_dict, ensure_ascii=False) + "\n")
            except Exception:
                pass  # Offline-first: never crash on telemetry failure

    def get_events(self) -> list[dict]:
        """Return all recorded events."""
        return list(self._events)

    def flush(self):
        """Clear the in-memory event buffer."""
        self._events.clear()
