import json
import os

import pytest

from utils import telegram_templates


@pytest.fixture(autouse=True)
def clean_templates_env(monkeypatch, tmp_path):
    """Monkeypatch the TEMPLATE_FILE path to a temporary path to isolate test runs."""
    temp_file = tmp_path / "telegram_templates.json"
    monkeypatch.setattr(telegram_templates, "TEMPLATE_FILE", str(temp_file))
    # Clear the internal cache
    telegram_templates._templates_cache = {}
    yield


def test_load_templates_default():
    """Verify that loading templates defaults back to hardcoded configurations if file doesn't exist."""
    templates = telegram_templates.load_templates()
    assert "A" in templates
    assert "B" in templates
    assert "C" in templates
    assert "D" in templates
    assert "PENDING APPROVAL" in templates["A"]
    # Verify file is initialized
    assert os.path.exists(telegram_templates.TEMPLATE_FILE)


def test_load_templates_custom(tmp_path):
    """Verify that templates load custom values from JSON if present."""
    custom_data = {
        "A": "Custom A {symbol}",
        "B": "Custom B {scan_time}",
        "C": "Custom C {server_name}",
        "D": "Custom D {exchange}",
    }
    with open(telegram_templates.TEMPLATE_FILE, "w", encoding="utf-8") as f:
        json.dump(custom_data, f)

    templates = telegram_templates.load_templates()
    assert templates["A"] == "Custom A {symbol}"
    assert templates["B"] == "Custom B {scan_time}"


def test_validate_template_syntax_ok():
    """Verify that correct placeholders pass validation."""
    # Mẫu A dynamic keys are valid
    telegram_templates.validate_template_syntax(
        "A", "Signal: {symbol} price {price} action {action}"
    )


def test_validate_template_syntax_fail():
    """Verify that unbalanced braces or unsupported keys fail validation."""
    # Unbalanced braces
    with pytest.raises(ValueError, match="syntax error"):
        telegram_templates.validate_template_syntax("A", "Unbalanced {symbol")

    # Unsupported placeholder key
    with pytest.raises(ValueError, match="unsupported placeholder key"):
        telegram_templates.validate_template_syntax(
            "A", "Unsupported {invalid_key_name}"
        )

    # Empty placeholder
    with pytest.raises(ValueError, match="empty placeholders"):
        telegram_templates.validate_template_syntax("A", "Empty placeholder {}")


def test_save_templates_success():
    """Verify that valid templates are successfully saved and loaded."""
    valid_templates = {
        "A": "Symbol is {symbol} action {action} price {price} timeframe {timeframe} tt_score {tt_score} stage {stage} vcp_status {vcp_status} volume_ratio {volume_ratio} ai_provider {ai_provider} ai_advice {ai_advice} stop_loss {stop_loss} sl_pct {sl_pct} take_profit {take_profit} tp_pct {tp_pct}",
        "B": "Time is {scan_time} results {scan_results_list}",
        "C": "Outage on {server_name} code {error_code} service {service_name} traceback {error_traceback} diagnosis {diagnostic_recommendation}",
        "D": "Warning for {symbol} on {exchange} details {warning_detail} block {details_block} fallback {fallback_action_desc}",
    }
    telegram_templates.save_templates(valid_templates)

    # Reload and check
    reloaded = telegram_templates.load_templates()
    assert reloaded["A"] == valid_templates["A"]
    assert reloaded["B"] == valid_templates["B"]


def test_save_templates_missing_id():
    """Verify that saving fails if template IDs are missing."""
    invalid = {"A": "test"}
    with pytest.raises(ValueError, match="Missing required template ID"):
        telegram_templates.save_templates(invalid)


def test_render_template_ok():
    """Verify standard rendering works and populates variables."""
    custom_a = "Signal for {symbol} is {action} at {price}"
    telegram_templates.save_templates({"A": custom_a, "B": "B", "C": "C", "D": "D"})

    rendered = telegram_templates.render_template(
        "A", symbol="ETHUSDT", action="BUY", price=3200
    )
    assert rendered == "Signal for ETHUSDT is BUY at 3200"


def test_render_template_missing_keys_fallback():
    """Verify that rendering doesn't crash on missing keys and fallbacks to N/A."""
    custom_a = "Signal for {symbol} is {action} at {price}"
    telegram_templates.save_templates({"A": custom_a, "B": "B", "C": "C", "D": "D"})

    # price and action are missing
    rendered = telegram_templates.render_template("A", symbol="BTCUSDT")
    assert rendered == "Signal for BTCUSDT is N/A at N/A"
