"""
Unit tests: test_rag.py
Tests for RAG (Retrieval-Augmented Generation) knowledge base functionality.
"""
import unittest
import sys

class TestRAGSystem(unittest.TestCase):
    def test_rag_context_retrieval_empty(self):
        """Should gracefully handle queries with no matches in the vector database."""
        from unittest.mock import MagicMock, patch
        import rag

        # 1. Test when _collection is None
        with patch("rag._collection", None):
            results = rag.query_knowledge("test query")
            self.assertEqual(results, [])

        # 2. Test when _collection count is 0
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        with patch("rag._collection", mock_collection):
            results = rag.query_knowledge("test query")
            self.assertEqual(results, [])
            mock_collection.count.assert_called_once()
            mock_collection.query.assert_not_called()

    def test_rag_context_retrieval_success(self):
        """Should retrieve relevant documents based on semantic similarity."""
        from unittest.mock import MagicMock, patch
        import rag

        mock_collection = MagicMock()
        mock_collection.count.return_value = 2
        mock_collection.query.return_value = {
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{"source": "book"}, {"source": "article"}]],
            "distances": [[0.1, 0.2]]
        }

        with patch("rag._collection", mock_collection):
            results = rag.query_knowledge("test query", n_results=3)
            
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["content"], "doc1")
            self.assertEqual(results[0]["metadata"]["source"], "book")
            self.assertEqual(results[0]["relevance_score"], 0.9)
            
            self.assertEqual(results[1]["content"], "doc2")
            self.assertEqual(results[1]["metadata"]["source"], "article")
            self.assertEqual(results[1]["relevance_score"], 0.8)
            
            mock_collection.query.assert_called_once_with(
                query_texts=["test query"],
                n_results=2
            )

    def test_generate_trading_advice_antigravity_success(self):
        """Should call Antigravity SDK to generate advice when AI_PROVIDER is 'antigravity'."""
        from unittest.mock import MagicMock, patch
        import asyncio

        # 1. Define Mock classes for google.antigravity
        class MockLocalAgentConfig:
            def __init__(self, system_instructions, model):
                self.system_instructions = system_instructions
                self.model = model

        class MockResponse:
            async def text(self):
                return "Mocked Antigravity SEPA Advice: Buy breakout pattern."

        class MockAgent:
            def __init__(self, config):
                self.config = config
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
            async def chat(self, prompt):
                return MockResponse()

        mock_module = MagicMock()
        mock_module.Agent = MockAgent
        mock_module.LocalAgentConfig = MockLocalAgentConfig

        # Patch sys.modules to simulate presence of google.antigravity
        with patch.dict("sys.modules", {"google.antigravity": mock_module}), \
             patch("rag.ANTIGRAVITY_AVAILABLE", True), \
             patch("rag.config") as mock_config:
            
            mock_config.AI_PROVIDER = "antigravity"
            mock_config.CLAUDE_CLI_MODEL = "gemini-2.5-flash"
            
            import rag
            
            advice = asyncio.run(rag.generate_trading_advice(
                symbol="BTCUSDT",
                action="buy",
                price="68000",
                payload={"alert_type": "buy", "volume": 100, "volume_avg": 50},
                rag_chunks=[{"metadata": {"topic": "SEPA", "chapter": "001"}, "content": "SEPA buy rules", "relevance_score": 0.9}]
            ))
            
            self.assertEqual(advice, "Mocked Antigravity SEPA Advice: Buy breakout pattern.")

    def test_generate_trading_advice_antigravity_missing_sdk(self):
        """Should return error message when AI_PROVIDER is 'antigravity' but SDK is not available."""
        from unittest.mock import patch
        import asyncio

        with patch("rag.ANTIGRAVITY_AVAILABLE", False), \
             patch("rag.config") as mock_config:
            
            mock_config.AI_PROVIDER = "antigravity"
            
            import rag
            
            advice = asyncio.run(rag.generate_trading_advice(
                symbol="BTCUSDT",
                action="buy",
                price="68000",
                payload={"alert_type": "buy", "volume": 100, "volume_avg": 50},
                rag_chunks=[{"metadata": {"topic": "SEPA", "chapter": "001"}, "content": "SEPA buy rules", "relevance_score": 0.9}]
            ))
            
            self.assertIn("thiếu google-antigravity SDK", advice)

    @unittest.skipIf(sys.platform != "win32", "Requires Windows to run angati.exe")
    def test_weex_l1_ingestion_trigger(self):
        """Trigger Weex L1 SQLite-Vec Memory ingestion via genuine MCP tool and verify presence."""
        try:
            from . import ingest_and_verify_mcp
        except ImportError:
            from nerves.workers.trading.tests.unit import ingest_and_verify_mcp
        success = ingest_and_verify_mcp.run_mcp_ingestion()
        self.assertTrue(success, "Weex memory ingestion via genuine MCP tool failed or verification failed")