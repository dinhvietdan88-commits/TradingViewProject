import os
import sys
import logging

logging.basicConfig(level=logging.DEBUG)

os.environ["TELEGRAM_BOT_ENABLED"] = "false"
os.environ["BRIEF_ENABLED"] = "false"
os.environ["RAG_ENABLED"] = "false"
os.environ["MCP_ENABLED"] = "false"
os.environ["DASHBOARD_TOKEN"] = ""

try:
    print("Running Weex L1 Ingestion from test_startup...")
    sys.path.insert(
        0, r"c:\Users\pesil\working\mj_trading\TradingViewProject\.agents\worker_weex_3"
    )
    import ingest_l1

    ingest_l1.main()
    print("Weex L1 Ingestion complete!")
except Exception as e:
    print(f"Weex L1 Ingestion failed: {e}")


from main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

print("Starting TestClient...")
try:
    client = TestClient(app)
    print("TestClient started successfully!")
except Exception as e:
    print(f"Exception during TestClient: {e}")
