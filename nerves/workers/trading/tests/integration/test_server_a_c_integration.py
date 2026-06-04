import sys
import os
import asyncio
import pytest
import httpx
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import ASGITransport

# ── Dynamic import wrapper for VBS (to prevent module collisions) ──
_VBS_MODULE_NAMES = ['config', 'database', 'main', 'router', 'models', 'notifier', 'scheduler', 'telegram_bot']
_originals = {name: sys.modules.pop(name, None) for name in _VBS_MODULE_NAMES}

# Locate VBS dir (assumed to be 5 parents up and under /vbs)
vbs_path = str(Path(__file__).resolve().parents[5] / "vbs")
if vbs_path not in sys.path:
    sys.path.insert(0, vbs_path)

import config as vbs_config
import database as vbs_db
import notifier as vbs_notifier
import scheduler as vbs_scheduler
from main import app as vbs_app

# Cleanup sys.path & restore original server modules to sys.modules
if vbs_path in sys.path:
    sys.path.remove(vbs_path)
for name in _VBS_MODULE_NAMES:
    if _originals[name] is not None:
        sys.modules[name] = _originals[name]
    else:
        sys.modules.pop(name, None)


# Mock VBS scheduler to prevent background tasks in tests
vbs_scheduler.start_scheduler = MagicMock()
vbs_scheduler.stop_scheduler = MagicMock()
vbs_notifier.send_telegram_alert = AsyncMock(return_value=[])


# Helper to fetch DB state directly from VBS database
async def get_signal_db_status(queue_id: int):
    import aiosqlite
    async with aiosqlite.connect(vbs_config.DB_PATH) as db:
        async with db.execute("SELECT status, ack_status FROM signal_queue WHERE id = ?", (queue_id,)) as cur:
            row = await cur.fetchone()
            return (row[0], row[1]) if row else (None, None)


# ── Mocking aiohttp client sessions to target the VBS App ──
class FakeResponse:
    def __init__(self, status, json_data=None, text_data=""):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockResponseContext:
    def __init__(self, app, method, path, params=None, json_data=None, headers=None):
        self.app = app
        self.method = method
        self.path = path
        self.params = params
        self.json_data = json_data
        self.headers = headers
        self.client = httpx.AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")

    async def __aenter__(self):
        if self.method == "GET":
            response = await self.client.get(self.path, params=self.params, headers=self.headers)
        elif self.method == "POST":
            response = await self.client.post(self.path, json=self.json_data, headers=self.headers)
        else:
            raise ValueError(f"Unsupported method {self.method}")
            
        json_val = {}
        if response.status_code == 200:
            try:
                json_val = response.json()
            except Exception:
                pass
        return FakeResponse(
            status=response.status_code,
            json_data=json_val,
            text_data=response.text
        )

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()


class MockAiohttpSession:
    def __init__(self, vbs_app):
        self.vbs_app = vbs_app
        self.closed = False
        self.post_calls = []
        self.post_responses = {}

    async def close(self):
        self.closed = True

    def get(self, url, params=None, headers=None, timeout=None):
        from urllib.parse import urlparse
        path = urlparse(url).path
        return MockResponseContext(self.vbs_app, "GET", path, params=params, headers=headers)

    def post(self, url, json=None, headers=None, timeout=None):
        self.post_calls.append((url, json))
        
        # Check if we have pre-programmed responses or errors
        for key in self.post_responses:
            if key in url:
                resp_list = self.post_responses[key]
                if resp_list:
                    item = resp_list.pop(0)
                    if isinstance(item, Exception):
                        raise item
                    return item

        # Default trade execution response
        if "execute-trade" in url:
            return FakeResponse(status=200, json_data={"success": True, "status": 200, "data": {"order_id": "MOCK-123"}})
            
        from urllib.parse import urlparse
        path = urlparse(url).path
        return MockResponseContext(self.vbs_app, "POST", path, json_data=json, headers=headers)


# ── Pytest Fixtures ──
@pytest.fixture
async def test_db(tmp_path):
    """Isolate DB per test."""
    original_db = vbs_config.DB_PATH
    test_db_path = str(tmp_path / "test_vbs.db")
    vbs_config.DB_PATH = test_db_path
    vbs_config.BUFFER_SECRET = "test-secret"
    
    await vbs_db.init_db()
    yield test_db_path
    
    vbs_config.DB_PATH = original_db


@pytest.fixture
async def worker(test_db):
    """Instantiate VpsAnalyzerWorker configured to connect to the test VBS app."""
    from workers.vps_analyzer import VpsAnalyzerWorker
    import config as server_config
    
    # Configure Server C config keys to align with the mock VBS settings
    server_config.VPS_BUFFER_URL = "http://vbs-mock"
    server_config.VPS_BUFFER_SECRET = "test-secret"
    server_config.LOCAL_EXECUTE_URL = "http://server-b-mock"
    server_config.SERVER_B_EXECUTE_URL = "http://server-b-real-mock"
    
    # Ensure RAG is disabled during test initialization
    server_config.RAG_ENABLED = False
    
    worker = VpsAnalyzerWorker()
    worker._session = MockAiohttpSession(vbs_app)
    
    yield worker
    await worker.close()


@pytest.fixture(autouse=True)
def mock_rag_init():
    with patch("rag.init_vector_db", new_callable=AsyncMock, return_value=True):
        yield


@pytest.fixture(autouse=True)
def mock_uvicorn_serve():
    with patch("uvicorn.Server.serve", new_callable=AsyncMock) as mock_serve:
        yield mock_serve


@pytest.fixture(autouse=True)
def mock_scheduler_start_stop():
    with patch("scheduler.start_scheduler") as mock_start, \
         patch("scheduler.stop_scheduler") as mock_stop:
        yield mock_start, mock_stop


# ── Integration Tests ──

@pytest.mark.asyncio
async def test_server_a_c_integration_flow(test_db, worker):
    """
    R1: Cross-Server Integration Test (Server A -> Consumer C -> RAG Analyze -> Server B -> ACK).
    - Ingest a signal via VBS app /ingest.
    - Run the VpsAnalyzerWorker loop.
    - Worker long-polls /consume-long, analyzes the signal, forwards to Server B (mocked), and ACKs.
    - Verify signal state transitions in VBS SQLite database.
    """
    # 1. Ingest signal in parallel using VBS app client
    payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": "60000.0",
        "secret": "test-secret",
        "source": "strategy"
    }
    
    async with httpx.AsyncClient(transport=ASGITransport(app=vbs_app), base_url="http://test") as client:
        resp = await client.post("/ingest", json=payload)
        assert resp.status_code == 200
        ingest_data = resp.json()
        assert ingest_data["queued"] is True
        queue_id = ingest_data["queue_id"]

    # 2. Run the worker run method in a background task
    # We will lower LONG_POLL_TIMEOUT to speed up exit (minimum accepted by VBS Query validation is 5)
    worker.LONG_POLL_TIMEOUT = 5
    
    # Mock RAG/AI analysis to approve the signal and extract confidence
    # (since we are in AI mode, is_available=True)
    with patch("rag.init_vector_db", return_value=True), \
         patch("rag.build_rag_query", return_value="query"), \
         patch("rag.query_knowledge", return_value=[]), \
         patch("rag.generate_trading_advice", new_callable=AsyncMock, return_value="Strong BUY signal. approved"), \
         patch("workers.ai_circuit_breaker.llm_breaker.is_available", return_value=True), \
         patch("notifier.send_telegram_alert", new_callable=AsyncMock), \
         patch("capture_client.get_capture_client") as mock_get_capture:
         
        mock_capture = AsyncMock()
        mock_capture.fetch_ohlcv.return_value = None  # Force error/skip pattern detection
        mock_get_capture.return_value = mock_capture
        
        run_task = asyncio.create_task(worker.run())
        
        # Give it a short moment to process the signal
        await asyncio.sleep(0.5)
        
        # Trigger shutdown
        worker._shutdown_event.set()
        await run_task

    # 3. Verify the signal state transitions in VBS SQLite database
    status, ack_status = await get_signal_db_status(queue_id)
    assert status == "ACKED"
    assert ack_status == "executed"


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence, mode, expected_approval, expected_hold", [
    # AI Mode (Circuit Closed)
    (49, "ai", True, False),
    (50, "ai", True, True),
    (51, "ai", True, True),
    # Algorithmic Mode (Circuit Open)
    (49, "algorithmic", False, False),
    (50, "algorithmic", False, False),
    (51, "algorithmic", True, True),
])
async def test_confidence_edge_cases(test_db, worker, confidence, mode, expected_approval, expected_hold):
    """
    R2: Confidence Edge Case Test.
    - Test confidence scores 49, 50, and 51.
    - In AI Mode (circuit closed):
        - Confidence 49: approved, no hold.
        - Confidence 50: approved, hold.
        - Confidence 51: approved, hold.
    - In Algorithmic fallback Mode (circuit open):
        - Confidence 49: auto-rejected (rounded to score 2 < 3).
        - Confidence 50: auto-rejected (banker's rounding: 2.5 -> 2.0 < 3).
        - Confidence 51: approved and hold (score is 3 >= 3).
    """
    # Seed database with pending signal
    q_id, _ = await vbs_db.insert_signal({
        "symbol": "ETHUSDT",
        "action": "buy",
        "price": 3000.0,
        "source": "strategy",
        "payload": {
            "volume": 2000000,
            "volume_avg": 1000000,
            "rsi": 60,
            "alert_type": "vcp",
            "sl": 2900,
        }
    })

    if mode == "ai":
        patch_available = patch("workers.ai_circuit_breaker.llm_breaker.is_available", return_value=True)
        patch_rag = patch("rag.generate_trading_advice", new_callable=AsyncMock, return_value="Strong BUY signal. approved")
        patch_conf = patch.object(worker, "_extract_confidence", return_value=confidence)
        patch_algo = patch.object(worker, "_algorithmic_analysis", return_value=("Algo advice", confidence))
    else:
        patch_available = patch("workers.ai_circuit_breaker.llm_breaker.is_available", return_value=False)
        patch_rag = patch("rag.generate_trading_advice", new_callable=AsyncMock, return_value="Strong BUY signal. approved")
        patch_conf = patch.object(worker, "_extract_confidence", return_value=confidence)
        patch_algo = patch.object(worker, "_algorithmic_analysis", return_value=("Algo advice", confidence))

    with patch_available, patch_rag, patch_conf, patch_algo, \
         patch("rag.init_vector_db", return_value=True), \
         patch("rag.build_rag_query", return_value="query"), \
         patch("rag.query_knowledge", return_value=[]), \
         patch("notifier.send_telegram_alert", new_callable=AsyncMock), \
         patch("capture_client.get_capture_client") as mock_get_capture:
         
        mock_capture = AsyncMock()
        mock_capture.fetch_ohlcv.return_value = None
        mock_get_capture.return_value = mock_capture
        
        results = await worker.poll_and_analyze()

    assert len(results) == 1
    assert results[0]["approved"] is expected_approval
    if expected_approval:
        assert results[0]["trade_payload"]["hold_for_approval"] is expected_hold


@pytest.mark.asyncio
async def test_fallback_routing_and_recovery(test_db):
    """
    R3: Fallback Routing & Recovery Test.
    - If Primary (Local) succeeds -> execute on Local.
    - If Primary fails/offline -> Fallback to Server B.
    - If both fail -> return success=False.
    - If Primary recovers (in subsequent calls) -> execute on Local and do not fallback.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker
    import config as server_config
    
    # Configure mock execution URLs
    server_config.LOCAL_EXECUTE_URL = "http://local-execute"
    server_config.SERVER_B_EXECUTE_URL = "http://server-b-execute"
    server_config.LOCAL_EXECUTE_SECRET = "local-sec"
    server_config.SERVER_B_SECRET = "b-sec"
    
    worker = VpsAnalyzerWorker()
    session = MockAiohttpSession(vbs_app)
    worker._session = session
    
    trade_payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 60000.0,
        "qty": 1.0,
    }
    
    # ── Case 1: Primary (Local) succeeds ──
    session.post_calls = []
    session.post_responses = {
        "http://local-execute": [
            FakeResponse(status=200, json_data={"success": True, "order_id": "LOCAL-1"})
        ]
    }
    
    res = await worker.forward_to_server_b(trade_payload)
    assert res["success"] is True
    assert res["executed_on"] == "local"
    assert len(session.post_calls) == 1
    assert "local-execute" in session.post_calls[0][0]
    
    # ── Case 2: Primary fails/offline -> Fallback to Server B ──
    session.post_calls = []
    session.post_responses = {
        "http://local-execute": [
            Exception("Connection refused")
        ],
        "http://server-b-execute": [
            FakeResponse(status=200, json_data={"success": True, "order_id": "B-1"})
        ]
    }
    
    with patch("notifier.send_telegram_alert", new_callable=AsyncMock) as mock_alert:
        res = await worker.forward_to_server_b(trade_payload)
        assert res["success"] is True
        assert res["executed_on"] == "server_b"
        assert len(session.post_calls) == 2
        assert "local-execute" in session.post_calls[0][0]
        assert "server-b-execute" in session.post_calls[1][0]
        mock_alert.assert_called_once()
        assert "Local Windows Offline" in mock_alert.call_args[0][0]
    
    # ── Case 3: Both fail ──
    session.post_calls = []
    session.post_responses = {
        "http://local-execute": [
            Exception("Connection refused")
        ],
        "http://server-b-execute": [
            FakeResponse(status=500, json_data={"detail": "Server B down"})
        ]
    }
    
    with patch("notifier.send_telegram_alert", new_callable=AsyncMock):
        res = await worker.forward_to_server_b(trade_payload)
        assert res["success"] is False
        assert len(session.post_calls) == 2
        assert "local-execute" in session.post_calls[0][0]
        assert "server-b-execute" in session.post_calls[1][0]
    
    # ── Case 4: Primary recovers (in subsequent calls) ──
    session.post_calls = []
    session.post_responses = {
        "http://local-execute": [
            FakeResponse(status=200, json_data={"success": True, "order_id": "LOCAL-RECOVERED"})
        ]
    }
    
    res = await worker.forward_to_server_b(trade_payload)
    assert res["success"] is True
    assert res["executed_on"] == "local"
    assert len(session.post_calls) == 1
    assert "local-execute" in session.post_calls[0][0]

    await worker.close()


@pytest.mark.asyncio
async def test_end_to_end_duplicate_signals(test_db):
    """
    R4: End-to-End Duplicate Signals Test.
    - Ingest a signal via VBS app /ingest.
    - Ingest it again within config.DEDUP_WINDOW_SECONDS seconds.
    - The second signal must be rejected as duplicate (status == "DUPLICATE").
    """
    vbs_config.DEDUP_WINDOW_SECONDS = 5
    
    payload = {
        "symbol": "SOLUSDT",
        "action": "buy",
        "price": "150.0",
        "secret": "test-secret",
        "source": "strategy"
    }
    
    async with httpx.AsyncClient(transport=ASGITransport(app=vbs_app), base_url="http://test") as client:
        # Ingest first signal
        resp1 = await client.post("/ingest", json=payload)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["queued"] is True
        assert data1["status"] == "PENDING"
        
        # Ingest second signal (duplicate) immediately
        resp2 = await client.post("/ingest", json=payload)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["queued"] is False
        assert data2["status"] == "DUPLICATE"
        assert data2["duplicate_of"] == data1["queue_id"]
