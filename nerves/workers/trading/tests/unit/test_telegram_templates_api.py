import pytest
from fastapi.testclient import TestClient
from main import app
from utils import telegram_templates


@pytest.fixture
def client():
    # Make sure cache is clean
    telegram_templates._templates_cache = {}
    return TestClient(app)


def test_api_get_templates(client, monkeypatch, tmp_path):
    # Mock templates path to isolate
    monkeypatch.setattr(
        telegram_templates, "TEMPLATE_FILE", str(tmp_path / "templates_get.json")
    )

    response = client.get("/api/telegram/templates")
    assert response.status_code == 200
    data = response.json()
    assert "A" in data
    assert "B" in data


def test_api_post_templates_success(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        telegram_templates, "TEMPLATE_FILE", str(tmp_path / "templates_post.json")
    )

    valid_payload = {
        "A": "Symbol is {symbol} action {action} price {price} timeframe {timeframe} tt_score {tt_score} stage {stage} vcp_status {vcp_status} volume_ratio {volume_ratio} ai_provider {ai_provider} ai_advice {ai_advice} stop_loss {stop_loss} sl_pct {sl_pct} take_profit {take_profit} tp_pct {tp_pct}",
        "B": "Time is {scan_time} results {scan_results_list}",
        "C": "Outage on {server_name} code {error_code} service {service_name} traceback {error_traceback} diagnosis {diagnostic_recommendation}",
        "D": "Warning for {symbol} on {exchange} details {warning_detail} block {details_block} fallback {fallback_action_desc}",
    }

    response = client.post("/api/telegram/templates", json=valid_payload)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify loaded
    reload_resp = client.get("/api/telegram/templates")
    assert reload_resp.json()["A"] == valid_payload["A"]


def test_api_post_templates_invalid_syntax(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        telegram_templates, "TEMPLATE_FILE", str(tmp_path / "templates_post_err.json")
    )

    invalid_payload = {
        "A": "Invalid braces {symbol",  # unbalanced brace
        "B": "B",
        "C": "C",
        "D": "D",
    }

    response = client.post("/api/telegram/templates", json=invalid_payload)
    assert response.status_code == 400
    assert "syntax error" in response.json()["detail"]


def test_api_post_templates_unsupported_key(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        telegram_templates, "TEMPLATE_FILE", str(tmp_path / "templates_post_key.json")
    )

    invalid_payload = {
        "A": "Unsupported key {my_made_up_key}",
        "B": "B",
        "C": "C",
        "D": "D",
    }

    response = client.post("/api/telegram/templates", json=invalid_payload)
    assert response.status_code == 400
    assert "unsupported placeholder key" in response.json()["detail"]
