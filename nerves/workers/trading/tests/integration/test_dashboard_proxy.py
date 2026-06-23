from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
import httpx
import sys
from pathlib import Path

# Ensure server/ is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from live_dashboard_server import app  # noqa: E402

client = TestClient(app)


def test_serve_dashboard_live():
    """Verify that dashboard_live.html serves the static dashboard template."""
    response = client.get("/dashboard_live.html")
    assert response.status_code == 200
    assert "Minervini SEPA" in response.text or "dashboard" in response.text


@patch("live_dashboard_server.client.request", new_callable=AsyncMock)
def test_proxy_api_request(mock_request):
    """Verify that API requests are proxied to port 5000 and mode=FORWARD is injected."""
    mock_response = httpx.Response(
        status_code=200,
        content=b'{"success": true}',
        headers={"content-type": "application/json"},
    )
    mock_request.return_value = mock_response

    # Send a request to proxy
    response = client.get("/trades/stats?symbol=BTCUSDT")

    assert response.status_code == 200
    assert response.json() == {"success": True}

    # Assert outgoing request to port 5000 had mode=FORWARD forced
    mock_request.assert_called_once()
    kwargs = mock_request.call_args[1]
    assert kwargs["url"] == "/trades/stats"
    assert kwargs["params"] == {"symbol": "BTCUSDT", "mode": "FORWARD"}


@patch("live_dashboard_server.client.request", new_callable=AsyncMock)
def test_proxy_static_request_no_mode(mock_request):
    """Verify that static/asset requests are proxied without injecting mode=FORWARD."""
    mock_response = httpx.Response(
        status_code=200,
        content=b"body { color: white; }",
        headers={"content-type": "text/css"},
    )
    mock_request.return_value = mock_response

    response = client.get("/static/css/dashboard.css")

    assert response.status_code == 200
    assert response.text == "body { color: white; }"

    # Assert outgoing request did NOT get mode=FORWARD injected
    mock_request.assert_called_once()
    kwargs = mock_request.call_args[1]
    assert kwargs["url"] == "/static/css/dashboard.css"
    assert "mode" not in kwargs["params"]
