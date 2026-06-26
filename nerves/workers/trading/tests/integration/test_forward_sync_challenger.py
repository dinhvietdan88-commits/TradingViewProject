"""
Adversarial verification and stress tests for forward sync features.
"""

import pytest
import aiosqlite
import config
import json
from unittest.mock import MagicMock
from main import app


@pytest.mark.asyncio
async def test_auth_bypass_forward_api(client):
    """
    Verify that requests starting with "/api/forward/" bypass redirect and token checks,
    even when authentication is enabled (DASHBOARD_TOKEN is set and auth_service is active).
    Verify that normal protected paths are blocked.
    """
    # 1. Enable authentication
    original_token = getattr(config, "DASHBOARD_TOKEN", "")
    config.DASHBOARD_TOKEN = "super-secret-token"  # noqa: S105

    # Mock an AuthService so the middleware thinks authentication is required
    mock_auth_svc = MagicMock()
    mock_auth_svc.verify_bearer_token.return_value = False
    mock_auth_svc.verify_session_token.side_effect = Exception("Invalid session")

    original_auth_service = getattr(app.state, "auth_service", None)
    app.state.auth_service = mock_auth_svc

    try:
        # 2. Test protected path (e.g. /trades) with API headers (expect 401)
        headers_api = {"accept": "application/json"}
        response = await client.get("/trades", headers=headers_api)
        assert response.status_code == 401
        assert response.json() == {"detail": "Authentication required"}

        # Test protected path with browser headers (expect 302 Redirect)
        headers_browser = {"accept": "text/html"}
        response = await client.get("/trades", headers=headers_browser)
        assert response.status_code == 302
        assert response.headers["location"] == "/auth/login?next=/trades"

        # 3. Test that GET /api/forward/sync-settings passes through (returns 200)
        # Even without credentials/headers
        response = await client.get("/api/forward/sync-settings")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Test GET /api/forward/production-signals passes through
        response = await client.get("/api/forward/production-signals")
        assert response.status_code == 200
        assert response.json()["success"] is True

        # Test POST /api/forward/sync-now passes through
        response = await client.post("/api/forward/sync-now")
        assert response.status_code == 200
        assert response.json()["success"] is True

    finally:
        config.DASHBOARD_TOKEN = original_token
        app.state.auth_service = original_auth_service


@pytest.mark.asyncio
async def test_production_signals_query_filters(client):
    """
    Verify GET /api/forward/production-signals filters correctly by symbol, source, start_id, end_id.
    """
    # Seed signals in trades.db (config.DB_PATH)
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM signals")
        # 1. Matching symbol, matching source
        await db.execute(
            """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                101,
                "BTCUSDT",
                "buy",
                68000.0,
                1.0,
                json.dumps({"source": "webhook"}),
                "LIVE",
            ),
        )
        # 2. Matching symbol, different source
        await db.execute(
            """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                102,
                "BTCUSDT",
                "sell",
                69000.0,
                1.0,
                json.dumps({"source": "indicator"}),
                "LIVE",
            ),
        )
        # 3. Different symbol, matching source
        await db.execute(
            """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                103,
                "ETHUSDT",
                "buy",
                3500.0,
                2.0,
                json.dumps({"source": "webhook"}),
                "LIVE",
            ),
        )
        # 4. Different symbol, different source
        await db.execute(
            """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                104,
                "SOLUSDT",
                "buy",
                150.0,
                5.0,
                json.dumps({"source": "manual"}),
                "LIVE",
            ),
        )
        await db.commit()

    # Query with no filters -> returns all 4 signals
    response = await client.get("/api/forward/production-signals")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["signals"]) == 4

    # Query by symbol (case insensitive)
    response = await client.get("/api/forward/production-signals?symbol=btcusdt")
    data = response.json()
    assert len(data["signals"]) == 2
    assert {s["id"] for s in data["signals"]} == {101, 102}

    # Query by source (case insensitive)
    response = await client.get("/api/forward/production-signals?source=WEBHOOK")
    data = response.json()
    assert len(data["signals"]) == 2
    assert {s["id"] for s in data["signals"]} == {101, 103}

    # Query by start_id
    response = await client.get("/api/forward/production-signals?start_id=103")
    data = response.json()
    assert len(data["signals"]) == 2
    assert {s["id"] for s in data["signals"]} == {103, 104}

    # Query by end_id
    response = await client.get("/api/forward/production-signals?end_id=102")
    data = response.json()
    assert len(data["signals"]) == 2
    assert {s["id"] for s in data["signals"]} == {101, 102}

    # Query by range start_id and end_id
    response = await client.get(
        "/api/forward/production-signals?start_id=102&end_id=103"
    )
    data = response.json()
    assert len(data["signals"]) == 2
    assert {s["id"] for s in data["signals"]} == {102, 103}

    # Non-existent symbol
    response = await client.get("/api/forward/production-signals?symbol=XYZ")
    data = response.json()
    assert data["success"] is True
    assert data["signals"] == []

    # Non-existent source
    response = await client.get("/api/forward/production-signals?source=xyz")
    data = response.json()
    assert data["success"] is True
    assert data["signals"] == []

    # Out-of-bounds start_id
    response = await client.get("/api/forward/production-signals?start_id=999")
    data = response.json()
    assert len(data["signals"]) == 0

    # Inverted range (start_id > end_id)
    response = await client.get(
        "/api/forward/production-signals?start_id=103&end_id=102"
    )
    data = response.json()
    assert len(data["signals"]) == 0


@pytest.mark.asyncio
async def test_production_signals_query_validations(client):
    """
    Verify boundary conditions for query parameters: types, limit constraints.
    """
    # 1. Invalid type parameters (e.g. non-int start_id/end_id) -> expect 422
    response = await client.get("/api/forward/production-signals?start_id=abc")
    assert response.status_code == 422

    response = await client.get("/api/forward/production-signals?end_id=xyz")
    assert response.status_code == 422

    response = await client.get("/api/forward/production-signals?limit=not-an-int")
    assert response.status_code == 422

    # 2. Limit constraints (limit ge=1, le=1000)
    response = await client.get("/api/forward/production-signals?limit=0")
    assert response.status_code == 422

    response = await client.get("/api/forward/production-signals?limit=-5")
    assert response.status_code == 422

    response = await client.get("/api/forward/production-signals?limit=1001")
    assert response.status_code == 422

    response = await client.get("/api/forward/production-signals?offset=-1")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_sync_now_ids_boundary_conditions(client):
    """
    Verify POST /api/forward/sync-now behavior with various formats in the 'ids' body parameter.
    """
    # Seed signals in trades.db
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM signals")
        for i in range(201, 206):
            await db.execute(
                """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    i,
                    "BTCUSDT",
                    "buy",
                    68000.0,
                    1.0,
                    json.dumps({"source": "webhook"}),
                    "LIVE",
                ),
            )
        await db.commit()

    # Reset forward DB
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as f_db:
        await f_db.execute("DELETE FROM signals")
        await f_db.commit()

    # 1. Empty ID list -> syncs nothing, returns synced_count = 0
    response = await client.post("/api/forward/sync-now", json={"ids": []})
    assert response.status_code == 200
    assert response.json() == {"success": True, "synced_count": 0}

    # 2. Non-existent IDs -> syncs nothing, returns synced_count = 0
    response = await client.post("/api/forward/sync-now", json={"ids": [999, 1000]})
    assert response.status_code == 200
    assert response.json() == {"success": True, "synced_count": 0}

    # 3. Invalid types inside list -> "abc" (ignored), None (ignored), float/string numbers should be handled safely.
    # Duplicates in the list should only sync once.
    # IDs 201 and 202 are valid, "201" should be cast to 201 (already synced so ignored), 202 is synced.
    response = await client.post(
        "/api/forward/sync-now", json={"ids": ["abc", None, 201, 202, 202, "203"]}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    # Should sync 201, 202, and 203 (total 3)
    assert data["synced_count"] == 3

    # Verify which IDs are actually in the forward DB
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as f_db:
        async with f_db.execute("SELECT id FROM signals ORDER BY id ASC") as cursor:
            rows = await cursor.fetchall()
            synced_ids = {r[0] for r in rows}
            assert synced_ids == {201, 202, 203}

    # 4. Attempt to sync again with already existing IDs -> should be ignored (synced_count = 0)
    response = await client.post("/api/forward/sync-now", json={"ids": [201, 202]})
    assert response.status_code == 200
    assert response.json() == {"success": True, "synced_count": 0}

    # 5. Missing "ids" key in request body -> should fall back to settings-based sync.
    # Set sync settings
    settings = {
        "symbols": "BTCUSDT",
        "sources": "webhook",
        "start_id": 204,
        "end_id": 205,
        "sync_enabled": True,
    }
    await client.post("/api/forward/sync-settings", json=settings)

    response = await client.post("/api/forward/sync-now", json={"other": "value"})
    assert response.status_code == 200
    # Should sync 204 and 205
    assert response.json() == {"success": True, "synced_count": 2}

    async with aiosqlite.connect(config.FORWARD_DB_PATH) as f_db:
        async with f_db.execute("SELECT id FROM signals ORDER BY id ASC") as cursor:
            rows = await cursor.fetchall()
            synced_ids = {r[0] for r in rows}
            assert synced_ids == {201, 202, 203, 204, 205}


@pytest.mark.asyncio
async def test_sync_now_error_handling_empty_db_paths(client):
    """
    Verify POST /api/forward/sync-now handles database path errors gracefully.
    """
    original_db = config.FORWARD_DB_PATH
    try:
        # Set to an invalid path that triggers SQLite failure
        config.FORWARD_DB_PATH = "/invalid_dir_does_not_exist/test_forward.db"
        response = await client.post("/api/forward/sync-now", json={"ids": [1, 2]})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data
    finally:
        config.FORWARD_DB_PATH = original_db
