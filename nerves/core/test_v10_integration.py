#!/usr/bin/env python3
"""
Brain V10 Integration Tests

Tests all 4 phases of the ADK Convergence:
    P1: A2A Agent Card + Task Handler
    P2: Guardrail Registry + Callback Bridge
    P3: ADK Eval Metrics
    P4: Memory Bridge

Run: python -m pytest nerves/core/test_v10_integration.py -v
"""

import json
import os
import sys
import unittest
from pathlib import Path

# Setup path
AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(AGENTS_ROOT / "nerves" / "core"))
sys.path.insert(0, str(AGENTS_ROOT / "spine" / "gateway"))


# ===================================================================
# Phase 1: A2A Agent Card Tests
# ===================================================================


class TestAgentCard(unittest.TestCase):
    """Tests for A2A Agent Card endpoint."""

    def test_agent_card_structure(self):
        """Agent Card must contain all A2A-required fields."""
        from agent_card import build_agent_card

        card = build_agent_card()

        self.assertIn("name", card)
        self.assertIn("description", card)
        self.assertIn("version", card)
        self.assertIn("url", card)
        self.assertIn("protocols", card)
        self.assertIn("capabilities", card)
        self.assertIn("skills", card)
        self.assertIn("authentication", card)

    def test_agent_card_name(self):
        """Agent Card name must be the satellite identifier."""
        from agent_card import build_agent_card

        card = build_agent_card()
        self.assertEqual(card["name"], "angati-trading-satellite")

    def test_agent_card_protocols(self):
        """Agent Card must advertise A2A and JSON-RPC 2.0 protocols."""
        from agent_card import build_agent_card

        card = build_agent_card()
        self.assertIn("a2a/1.0", card["protocols"])
        self.assertIn("jsonrpc/2.0", card["protocols"])

    def test_agent_card_skills_not_empty(self):
        """Agent Card must advertise at least one skill."""
        from agent_card import build_agent_card

        card = build_agent_card()
        self.assertGreater(len(card["skills"]), 0)

    def test_agent_card_skill_ids(self):
        """Each skill must have an id, name, and description."""
        from agent_card import build_agent_card

        card = build_agent_card()
        for skill in card["skills"]:
            self.assertIn("id", skill)
            self.assertIn("name", skill)
            self.assertIn("description", skill)

    def test_agent_card_json_serializable(self):
        """Agent Card must be JSON-serializable."""
        from agent_card import get_agent_card_json

        json_str = get_agent_card_json()
        parsed = json.loads(json_str)
        self.assertIsInstance(parsed, dict)

    def test_agent_card_custom_host_port(self):
        """Agent Card URL must reflect custom host/port."""
        from agent_card import build_agent_card

        card = build_agent_card(host="192.168.1.100", port=9999)
        self.assertEqual(card["url"], "http://192.168.1.100:9999")

    def test_agent_card_v10_metadata(self):
        """Agent Card metadata must indicate V10 epoch."""
        from agent_card import build_agent_card

        card = build_agent_card()
        self.assertEqual(card["metadata"]["angati_epoch"], "V10.0")


# ===================================================================
# Phase 1: A2A Task Handler Tests
# ===================================================================


class TestA2AHandler(unittest.TestCase):
    """Tests for A2A JSON-RPC 2.0 task handler."""

    def setUp(self):
        from a2a_handler import A2AHandler

        self.handler = A2AHandler()

    def test_tasks_send_valid(self):
        """tasks/send with valid skill_id should create and complete a task."""
        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tasks/send",
                "params": {
                    "skill_id": "webhook-signal-processor",
                    "payload": {"symbol": "BTCUSDT", "indicator_name": "RSI14"},
                },
            }
        ).encode()

        response = self.handler.handle_request(request)
        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 1)
        self.assertIn("result", response)
        self.assertEqual(response["result"]["status"]["state"], "completed")

    def test_tasks_send_missing_symbol(self):
        """tasks/send with missing symbol should fail the task."""
        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tasks/send",
                "params": {
                    "skill_id": "webhook-signal-processor",
                    "payload": {"indicator_name": "RSI14"},
                },
            }
        ).encode()

        response = self.handler.handle_request(request)
        self.assertEqual(response["result"]["status"]["state"], "failed")

    def test_tasks_send_unknown_skill(self):
        """tasks/send with unknown skill_id should return error."""
        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tasks/send",
                "params": {"skill_id": "nonexistent-skill", "payload": {}},
            }
        ).encode()

        response = self.handler.handle_request(request)
        self.assertIn("error", response)

    def test_tasks_get_existing(self):
        """tasks/get should return task status for existing task."""
        # First create a task
        send_req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tasks/send",
                "params": {
                    "skill_id": "webhook-signal-processor",
                    "payload": {"symbol": "ETHUSDT", "indicator_name": "MACD"},
                },
            }
        ).encode()
        send_resp = self.handler.handle_request(send_req)
        task_id = send_resp["result"]["id"]

        # Then get it
        get_req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tasks/get",
                "params": {"task_id": task_id},
            }
        ).encode()
        get_resp = self.handler.handle_request(get_req)
        self.assertEqual(get_resp["result"]["id"], task_id)

    def test_tasks_cancel(self):
        """tasks/cancel should cancel a submitted task."""
        # Create a task
        send_req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tasks/send",
                "params": {
                    "skill_id": "trade-executor",
                    "payload": {"symbol": "BTCUSDT"},
                },
            }
        ).encode()
        send_resp = self.handler.handle_request(send_req)
        task_id = send_resp["result"]["id"]

        # Cancel it
        cancel_req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 21,
                "method": "tasks/cancel",
                "params": {"task_id": task_id},
            }
        ).encode()
        cancel_resp = self.handler.handle_request(cancel_req)
        self.assertEqual(cancel_resp["result"]["status"]["state"], "canceled")

    def test_invalid_jsonrpc(self):
        """Request without jsonrpc=2.0 should return Invalid Request error."""
        request = json.dumps({"id": 1, "method": "tasks/send"}).encode()
        response = self.handler.handle_request(request)
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32600)

    def test_unknown_method(self):
        """Unknown method should return Method not found error."""
        request = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "unknown/method"}
        ).encode()
        response = self.handler.handle_request(request)
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32601)

    def test_malformed_json(self):
        """Malformed JSON should return Parse error."""
        response = self.handler.handle_request(b"not json at all")
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32700)


# ===================================================================
# Phase 2: Guardrail Registry Tests
# ===================================================================


class TestGuardrailRegistry(unittest.TestCase):
    """Tests for the declarative guardrail registry."""

    def test_registry_loaded(self):
        """GUARDRAILS registry must contain all expected policies."""
        from guardrail_registry import GUARDRAILS

        self.assertIn("kg_guard", GUARDRAILS)
        self.assertIn("circuit_breaker", GUARDRAILS)
        self.assertIn("scar_consult", GUARDRAILS)
        self.assertIn("reflex", GUARDRAILS)
        self.assertIn("gitnexus_post_commit", GUARDRAILS)

    def test_guardrail_structure(self):
        """Each guardrail must have required fields."""
        from guardrail_registry import GUARDRAILS

        for name, g in GUARDRAILS.items():
            self.assertIn("type", g, f"Missing 'type' in guardrail {name}")
            self.assertIn("tools", g, f"Missing 'tools' in guardrail {name}")
            self.assertIn("handler", g, f"Missing 'handler' in guardrail {name}")
            self.assertIn(
                "short_circuit", g, f"Missing 'short_circuit' in guardrail {name}"
            )
            self.assertIn(
                "description", g, f"Missing 'description' in guardrail {name}"
            )
            self.assertTrue(callable(g["handler"]), f"Handler not callable in {name}")

    def test_evaluate_guardrails_allow(self):
        """evaluate_guardrails should return allow for benign requests."""
        from guardrail_registry import evaluate_guardrails

        result = evaluate_guardrails(
            "before_tool",
            "view_file",
            {"AbsolutePath": "/tmp/test"},  # noqa: S108
        )
        self.assertEqual(result["decision"], "allow")

    def test_evaluate_guardrails_filters_by_type(self):
        """Only guardrails matching lifecycle type should be evaluated."""
        from guardrail_registry import evaluate_guardrails

        result = evaluate_guardrails("after_tool", "view_file", {})
        # after_tool guardrails only apply to run_command
        self.assertEqual(result["decision"], "allow")


# ===================================================================
# Phase 2: ADK Callback Bridge Tests
# ===================================================================


class TestADKCallbackBridge(unittest.TestCase):
    """Tests for the ADK Callback Bridge."""

    def test_context_from_hook_data(self):
        """AngatiCallbackContext should parse hook data correctly."""
        from adk_callback_bridge import AngatiCallbackContext

        ctx = AngatiCallbackContext.from_hook_data(
            {
                "tool_name": "write_to_file",
                "tool_input": {"TargetFile": "/test.py", "CodeContent": "print('hi')"},
            }
        )
        self.assertEqual(ctx.tool_name, "write_to_file")
        self.assertEqual(ctx.tool_input["TargetFile"], "/test.py")

    def test_to_function_call_event(self):
        """Function call event should have correct structure."""
        from adk_callback_bridge import AngatiCallbackContext

        ctx = AngatiCallbackContext(
            tool_name="grep_search", tool_input={"Query": "test"}
        )
        event = ctx.to_function_call_event()
        self.assertEqual(event.author, "angati-hook-service")
        self.assertTrue(event.is_function_call())
        self.assertFalse(event.is_function_response())

    def test_to_function_response_event(self):
        """Function response event should have correct structure."""
        from adk_callback_bridge import AngatiCallbackContext

        ctx = AngatiCallbackContext(tool_name="grep_search", tool_input={})
        event = ctx.to_function_response_event({"matches": 5})
        self.assertTrue(event.is_function_response())
        self.assertFalse(event.is_function_call())

    def test_event_serializable(self):
        """ADKEvent should be JSON-serializable."""
        from adk_callback_bridge import ADKEvent

        event = ADKEvent(author="test", content_parts=[{"text": "hello"}])
        d = event.to_dict()
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["author"], "test")

    def test_telemetry_exporter(self):
        """ADKTelemetryExporter should record and return events."""
        from adk_callback_bridge import ADKEvent, ADKTelemetryExporter

        exporter = ADKTelemetryExporter()
        event = ADKEvent(author="test", content_parts=[{"text": "test event"}])
        exporter.record(event)
        self.assertEqual(len(exporter.get_events()), 1)
        exporter.flush()
        self.assertEqual(len(exporter.get_events()), 0)


# ===================================================================
# Phase 3: ADK Eval Metrics Tests
# ===================================================================


class TestToolTrajectoryScore(unittest.TestCase):
    """Tests for tool_trajectory_score metric."""

    def test_exact_match(self):
        from eval_metrics import tool_trajectory_score

        score = tool_trajectory_score(["a", "b", "c"], ["a", "b", "c"], "EXACT")
        self.assertEqual(score, 1.0)

    def test_exact_mismatch(self):
        from eval_metrics import tool_trajectory_score

        score = tool_trajectory_score(["a", "b"], ["b", "a"], "EXACT")
        self.assertEqual(score, 0.0)

    def test_in_order_with_extras(self):
        from eval_metrics import tool_trajectory_score

        score = tool_trajectory_score(
            ["search", "write"], ["search", "read", "write"], "IN_ORDER"
        )
        self.assertEqual(score, 1.0)

    def test_in_order_partial(self):
        from eval_metrics import tool_trajectory_score

        # IN_ORDER is a strict subsequence: "search" matches, but "write"
        # can't match "analyze" so expected_idx stays at 1. Score = 1/3.
        score = tool_trajectory_score(
            ["search", "analyze", "write"], ["search", "write"], "IN_ORDER"
        )
        self.assertAlmostEqual(score, 1 / 3, places=2)

    def test_any_order_match(self):
        from eval_metrics import tool_trajectory_score

        score = tool_trajectory_score(
            ["write", "search"], ["search", "write"], "ANY_ORDER"
        )
        self.assertEqual(score, 1.0)

    def test_empty_expected(self):
        from eval_metrics import tool_trajectory_score

        score = tool_trajectory_score([], ["a", "b"], "EXACT")
        self.assertEqual(score, 0.0)

    def test_empty_both(self):
        from eval_metrics import tool_trajectory_score

        score = tool_trajectory_score([], [], "EXACT")
        self.assertEqual(score, 1.0)


class TestResponseQualityScore(unittest.TestCase):
    """Tests for response_quality_score (ROUGE-1) metric."""

    def test_identical(self):
        from eval_metrics import response_quality_score

        score = response_quality_score(
            "the cat sat on the mat", "the cat sat on the mat"
        )
        self.assertEqual(score, 1.0)

    def test_partial_overlap(self):
        from eval_metrics import response_quality_score

        score = response_quality_score("hello world", "goodbye world")
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_no_overlap(self):
        from eval_metrics import response_quality_score

        score = response_quality_score("alpha beta", "gamma delta")
        self.assertEqual(score, 0.0)

    def test_empty_both(self):
        from eval_metrics import response_quality_score

        score = response_quality_score("", "")
        self.assertEqual(score, 1.0)

    def test_empty_reference(self):
        from eval_metrics import response_quality_score

        score = response_quality_score("", "some text")
        self.assertEqual(score, 0.0)


class TestScarRegressionCheck(unittest.TestCase):
    """Tests for scar_regression_check metric."""

    def test_no_regression(self):
        from eval_metrics import scar_regression_check

        result = scar_regression_check(
            [
                {
                    "id": "SCAR-001",
                    "pattern": "CommandNotFoundException",
                    "description": "test",
                }
            ],
            "All tests passed successfully",
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(len(result["regressions"]), 0)

    def test_regression_detected(self):
        from eval_metrics import scar_regression_check

        result = scar_regression_check(
            [
                {
                    "id": "SCAR-001",
                    "pattern": "CommandNotFoundException",
                    "description": "test",
                }
            ],
            "Error: CommandNotFoundException: gitnexus_query is not recognized",
        )
        self.assertFalse(result["passed"])
        self.assertIn("SCAR-001", result["regressions"])

    def test_empty_patterns(self):
        from eval_metrics import scar_regression_check

        result = scar_regression_check([], "some output")
        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 1.0)

    def test_multiple_scars(self):
        from eval_metrics import scar_regression_check

        result = scar_regression_check(
            [
                {
                    "id": "SCAR-001",
                    "pattern": "CommandNotFoundException",
                    "description": "test1",
                },
                {"id": "SCAR-002", "pattern": "UTF-16LE", "description": "test2"},
                {"id": "SCAR-003", "pattern": "&&", "description": "test3"},
            ],
            "Found UTF-16LE encoding in file",
        )
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["regressions"]), 1)
        self.assertIn("SCAR-002", result["regressions"])
        self.assertAlmostEqual(result["score"], 2 / 3, places=2)


class TestCompositeEvaluation(unittest.TestCase):
    """Tests for evaluate_agent_run composite metric."""

    def test_all_pass(self):
        from eval_metrics import evaluate_agent_run

        result = evaluate_agent_run(
            expected_trajectory=["search", "write"],
            actual_trajectory=["search", "write"],
            reference_response="success",
            actual_response="success",
            scar_patterns=[{"id": "S1", "pattern": "FAIL", "description": "test"}],
            test_output="All passed",
        )
        self.assertTrue(result["overall_passed"])

    def test_trajectory_fail(self):
        from eval_metrics import evaluate_agent_run

        result = evaluate_agent_run(
            expected_trajectory=["a", "b", "c"],
            actual_trajectory=["x"],
            thresholds={"tool_trajectory_avg_score": 0.8},
        )
        self.assertFalse(result["overall_passed"])


# ===================================================================
# Phase 4: Memory Bridge Tests
# ===================================================================


class TestMemoryBridge(unittest.TestCase):
    """Tests for the Memory Bridge."""

    def test_health_check(self):
        """Health check should return structured status."""
        from memory_bridge import AngatiMemoryBridge

        bridge = AngatiMemoryBridge(
            db_path="/nonexistent/path.db", chroma_path="/nonexistent/chroma"
        )
        health = bridge.health()
        self.assertIn("status", health)
        self.assertIn("backends", health)
        self.assertEqual(health["epoch"], "V10")

    def test_search_empty_db(self):
        """Search on nonexistent DB should return empty list."""
        from memory_bridge import AngatiMemoryBridge

        bridge = AngatiMemoryBridge(
            db_path="/nonexistent/path.db", chroma_path="/nonexistent/chroma"
        )
        results = bridge.search_memories("test query")
        self.assertIsInstance(results, list)

    def test_add_memory_fallback(self):
        """add_memory should return a valid UUID even in fallback mode."""
        import tempfile

        from memory_bridge import AngatiMemoryBridge

        # Use ignore_cleanup_errors=True to handle Windows file locks from ChromaDB
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            # Point chroma to a nonexistent nested path to force fallback to JSONL
            bridge = AngatiMemoryBridge(
                db_path=os.path.join(tmpdir, "test.db"),
                chroma_path=os.path.join(tmpdir, "nonexistent_chroma_dir_skip"),
            )
            # Explicitly disable chroma to ensure JSONL fallback
            bridge._chroma_client = None
            bridge._ensure_chroma = lambda: False

            # Patch AGENTS_ROOT for ledger fallback
            import memory_bridge

            original_root = memory_bridge.AGENTS_ROOT
            memory_bridge.AGENTS_ROOT = Path(tmpdir)

            try:
                memory_id = bridge.add_memory("test lesson learned", {"type": "scar"})
                self.assertIsInstance(memory_id, str)
                self.assertGreater(len(memory_id), 0)

                # Verify ledger file was created
                ledger = Path(tmpdir) / "cortex" / "state" / "memory_ledger.jsonl"
                self.assertTrue(ledger.exists(), "JSONL ledger should be created")
                with open(ledger) as f:
                    line = f.readline()
                    entry = json.loads(line)
                    self.assertEqual(entry["content"], "test lesson learned")
            finally:
                memory_bridge.AGENTS_ROOT = original_root

    def test_session_history_empty(self):
        """Session history on nonexistent DB should return empty list."""
        from memory_bridge import AngatiMemoryBridge

        bridge = AngatiMemoryBridge(db_path="/nonexistent/path.db")
        history = bridge.get_session_history()
        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 0)


# ===================================================================
# Run
# ===================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
