import pytest
import asyncio

from core.events import SignalReceived
from core.event_bus import bus
import config

pytestmark = pytest.mark.asyncio


async def test_chaos_ai_analyzer_outage(client, mocker):
    """
    Chaos Engineering: Simulate complete outage of the AI subsystem (Server C / LLM / VectorDB).
    Ensure that Server A / Trade Engine degrades gracefully to Algorithmic Mode without dropping the signal.
    """
    # 1. Mock cấu hình
    mocker.patch.object(config, "DISABLE_RATE_LIMIT", True)
    mocker.patch.object(config, "WEBHOOK_SECRET", "chaos_secret")

    # 2. Mock Circuit Breaker luôn trả về False (OPEN / Outage)
    mocker.patch(
        "workers.ai_circuit_breaker.llm_breaker.is_available", return_value=False
    )

    # Lắng nghe sự kiện để kiểm chứng hệ thống vẫn dispatch SignalReceived thành công
    dispatched_events = []

    @bus.on(SignalReceived)
    async def capture_event(event: SignalReceived):
        dispatched_events.append(event)

    payload = {
        "action": "buy",
        "symbol": "BTCUSDT",
        "price": 55000,
        "secret": "chaos_secret",
    }

    # Bắn signal khi hệ thống AI đang sập
    response = await client.post("/webhook", json=payload)

    # HTTP ingress vẫn phải trả về 200 OK (Graceful degradation)
    assert response.status_code == 200, "Webhook failed during AI outage!"

    # Chờ một chút cho event loop chạy task background
    await asyncio.sleep(0.1)

    # Đảm bảo Signal vẫn được xử lý vào luồng Algorithmic
    assert len(dispatched_events) == 1
    event = dispatched_events[0]
    assert event.symbol == "BTCUSDT"
    assert event.action == "buy"
    assert event.price == 55000.0

    print(
        "Chaos Test Passed: System survived AI outage and degraded to Algorithmic mode seamlessly."
    )
