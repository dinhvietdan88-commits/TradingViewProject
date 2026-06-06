import os
import unittest


class TestWeexIngestion(unittest.TestCase):
    def test_run_weex_ingestion_and_verify(self):
        import sys

        workspace_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        if workspace_root not in sys.path:
            sys.path.insert(0, workspace_root)
        from nerves.workers.trading.tests.unit import ingest_and_verify_mcp

        success = ingest_and_verify_mcp.run_mcp_ingestion()
        self.assertTrue(
            success,
            "Weex memory ingestion via genuine MCP tool failed or verification failed",
        )


if __name__ == "__main__":
    unittest.main()
