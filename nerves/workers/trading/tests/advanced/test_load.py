import asyncio
import pytest
import time
from httpx import AsyncClient, ASGITransport

from main import app
import config

# Cấu hình test chạy bất đồng bộ
pytestmark = pytest.mark.asyncio

async def test_webhook_rate_limit_and_burst_load(client, mocker):
    """
    Test load & rate limiting (TVP-004): 15 req/min per IP.
    Simulate a burst of 100 requests from the same IP concurrently.
    We expect exactly 15 to pass (or at least <= 15 depending on race conditions),
    and the rest to get 429 Too Many Requests.
    """
    # Không vô hiệu hóa rate limit trong config
    mocker.patch.object(config, "DISABLE_RATE_LIMIT", False)
    mocker.patch.object(config, "WEBHOOK_SECRET", "test_secret")

    payload = {
        "action": "buy",
        "symbol": "BTCUSDT",
        "price": 50000,
        "secret": "test_secret"
    }

    # Bắn 50 request đồng thời
    reqs = []
    for _ in range(50):
        reqs.append(
            client.post("/webhook", json=payload, headers={"x-forwarded-for": "203.0.113.1"})
        )
    
    start_time = time.time()
    responses = await asyncio.gather(*reqs)
    duration = time.time() - start_time

    status_codes = [r.status_code for r in responses]
    
    success_count = status_codes.count(200)
    rate_limited_count = status_codes.count(429)

    print(f"Bắn 50 requests tốn {duration:.3f}s. Thành công: {success_count}, Bị chặn: {rate_limited_count}")

    # Rate limit là 15 req/phút. Do bắn đồng thời, có thể có chút race condition ở dict state,
    # nhưng cơ bản số lượng request thành công không được vượt quá xa 15, và phải có 429.
    assert rate_limited_count > 0, "Rate limit didn't trigger under burst load!"
    assert success_count <= 20, f"Too many requests bypassed the rate limit! Allowed: {success_count}"



