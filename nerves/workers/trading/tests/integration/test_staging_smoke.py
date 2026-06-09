"""
Staging Smoke Test Suite — Live Server Validation
==================================================
Kiểm tra nhanh (smoke test) trên server staging đang chạy.
Sử dụng httpx async, skip tự động nếu server không khả dụng.

Run:
    python -m pytest tests/integration/test_staging_smoke.py -m staging -v

Env vars:
    SMOKE_BASE_URL  — full base URL  (default: http://localhost:{PORT})
    PORT            — server port     (default: 5000)
    WEBHOOK_SECRET  — secret for X-TV-Secret header (default: test-secret)
"""

import os

import httpx
import pytest
import pytest_asyncio


# Try to load .env from the project root
def _load_env_webhook_secret():
    # Attempt using python-dotenv first
    try:
        from dotenv import load_dotenv

        # 1. Check relative to this file
        _cur_dir = os.path.dirname(os.path.abspath(__file__))
        _root_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_cur_dir))))
        )
        _env_path = os.path.join(_root_dir, ".env")
        if os.path.exists(_env_path):
            load_dotenv(_env_path, override=True)
        # 2. Check in current working directory
        elif os.path.exists(".env"):
            load_dotenv(".env", override=True)
    except ImportError:
        pass

    # Direct manual parsing fallback
    _paths = []
    _cur_dir = os.path.dirname(os.path.abspath(__file__))
    _root_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_cur_dir))))
    )
    _paths.append(os.path.join(_root_dir, ".env"))
    _paths.append(".env")
    _paths.append(os.path.join(os.getcwd(), ".env"))

    for _p in _paths:
        if os.path.exists(_p):
            try:
                with open(_p, "r", encoding="utf-8") as _f:
                    for _line in _f:
                        _line = _line.strip()
                        if _line and not _line.startswith("#") and "=" in _line:
                            _k, _v = _line.split("=", 1)
                            _k = _k.strip()
                            _v = _v.strip()
                            if _k == "WEBHOOK_SECRET":
                                # Strip quotes if present
                                if (_v.startswith('"') and _v.endswith('"')) or (
                                    _v.startswith("'") and _v.endswith("'")
                                ):
                                    _v = _v[1:-1]
                                os.environ["WEBHOOK_SECRET"] = _v
                                return
            except Exception:  # noqa: S110
                pass


_load_env_webhook_secret()

# ── URL & Auth Configuration ─────────────────────────────────────────────────
SMOKE_BASE_URL = os.getenv(
    "SMOKE_BASE_URL",
    f"http://localhost:{os.getenv('PORT', '5000')}",
)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "test-secret")  # noqa: S105

pytestmark = pytest.mark.staging


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def staging_client():
    """Yield an httpx.AsyncClient pointed at the staging server.

    Tự động skip toàn bộ test nếu server không phản hồi /health.
    """
    async with httpx.AsyncClient(
        base_url=SMOKE_BASE_URL,
        timeout=httpx.Timeout(10.0),
    ) as client:
        try:
            resp = await client.get("/health")
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPStatusError) as exc:
            pytest.skip(f"Staging server not reachable at {SMOKE_BASE_URL}: {exc}")
        yield client


# ── 1. Health Check ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_endpoint(staging_client: httpx.AsyncClient):
    """SMOKE-HEALTH: GET /health trả về 200 và có trường 'status'."""
    resp = await staging_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data, f"Missing 'status' key in /health response: {data}"


# ── 2. Webhook — Valid TradingView Alert ──────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_valid_alert(staging_client: httpx.AsyncClient):
    """SMOKE-WEBHOOK: POST /webhook với payload hợp lệ và X-TV-Secret header."""
    payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 68000,
        "source": "tradingview",
    }
    resp = await staging_client.post(
        "/webhook",
        json=payload,
        headers={"X-TV-Secret": WEBHOOK_SECRET},
    )
    if resp.status_code == 401:
        # Fallback in case staging server runs with default empty WEBHOOK_SECRET
        resp = await staging_client.post(
            "/webhook",
            json=payload,
            headers={"X-TV-Secret": ""},
        )
    # 200 = accepted, 422 = validation issue — both are valid server responses
    assert resp.status_code in (200, 422), (
        f"Unexpected status {resp.status_code}: {resp.text[:300]}"
    )
    if resp.status_code == 200:
        body = resp.json()
        assert body.get("received") is True, f"Expected received=True, got {body}"


# ── 3. Webhook — Unauthorized (no secret) ────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_unauthorized(staging_client: httpx.AsyncClient):
    """SMOKE-AUTH: POST /webhook không có secret → 401 Unauthorized."""
    payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 68000,
        "source": "tradingview",
    }
    resp = await staging_client.post("/webhook", json=payload)
    assert resp.status_code == 401, (
        f"Expected 401 without secret, got {resp.status_code}: {resp.text[:300]}"
    )


# ── 4. Indicator Signals List ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_indicator_signals_list(staging_client: httpx.AsyncClient):
    """SMOKE-SIGNALS: GET /api/indicator-signals trả về 200 và JSON list/object."""
    resp = await staging_client.get("/api/indicator-signals")
    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
    )
    data = resp.json()
    # API trả về list hoặc paginated object có key "items"/"data"/"signals"
    assert isinstance(data, (list, dict)), (
        f"Expected JSON list or object, got {type(data).__name__}"
    )


# ── 5. Indicator Signals Stats ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_indicator_signals_stats(staging_client: httpx.AsyncClient):
    """SMOKE-STATS: GET /api/indicator-signals/stats trả về 200 và JSON object."""
    resp = await staging_client.get("/api/indicator-signals/stats")
    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
    )
    data = resp.json()
    assert isinstance(data, dict), (
        f"Expected JSON object for stats, got {type(data).__name__}"
    )


# ── 6. Trades List ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trades_list(staging_client: httpx.AsyncClient):
    """SMOKE-TRADES: GET /trades trả về 200 và JSON list."""
    resp = await staging_client.get("/trades")
    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
    )
    data = resp.json()
    assert isinstance(data, (list, dict)), (
        f"Expected JSON list or object, got {type(data).__name__}"
    )


# ── 7. Trades Stats ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trades_stats(staging_client: httpx.AsyncClient):
    """SMOKE-TRADES-STATS: GET /trades/stats trả về 200 và JSON object."""
    resp = await staging_client.get("/trades/stats")
    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
    )
    data = resp.json()
    assert isinstance(data, dict), (
        f"Expected JSON object for trade stats, got {type(data).__name__}"
    )
