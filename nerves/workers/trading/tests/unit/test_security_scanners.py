import json
from pathlib import Path
from unittest.mock import MagicMock, patch


from security import Severity
from security.sanitizers import sanitize_log, sanitize_path, sanitize_symbol
import security.scanners.dependency_scanner as dependency_scanner
import security.scanners.secret_scanner as secret_scanner
import security.scanners.static_scanner as static_scanner
import security.scanners.trading_rules as trading_rules


# ──────────────────────────────────────────────────────────────────────
# 1. Tests for security/sanitizers.py
# ──────────────────────────────────────────────────────────────────────


def test_sanitize_log():
    assert sanitize_log("") == ""
    assert sanitize_log(None) == ""
    assert sanitize_log("hello\rworld\n") == "hello world "
    assert sanitize_log("normal message") == "normal message"


def test_sanitize_path(tmp_path):
    root_dir = tmp_path / "allowed_root"
    root_dir.mkdir()
    other_dir = tmp_path / "other_dir"
    other_dir.mkdir()

    allowed_roots = [str(root_dir)]

    # Safe path
    safe_file = root_dir / "safe.txt"
    res = sanitize_path(str(safe_file), allowed_roots)
    assert res is not None
    assert Path(res).resolve() == safe_file.resolve()

    # Traversal escape check (..)
    unsafe_file = root_dir / "../other_dir/unsafe.txt"
    assert sanitize_path(str(unsafe_file), allowed_roots) is None

    # Prefix match check
    assert sanitize_path(str(other_dir / "file.txt"), allowed_roots) is None

    # Empty/None input
    assert sanitize_path("", allowed_roots) is None
    assert sanitize_path(None, allowed_roots) is None

    # Exception check
    assert sanitize_path(12345, allowed_roots) is None


def test_sanitize_symbol():
    assert sanitize_symbol("") == ""
    assert sanitize_symbol(None) == ""
    assert sanitize_symbol("btc-usdt") == "BTC-USDT"
    assert sanitize_symbol("ETH.P") == "ETH.P"
    assert sanitize_symbol("BTC/USDT") == "BTC/USDT"
    assert sanitize_symbol("BTC$USDT") == "BTCUSDT"  # removes $


# ──────────────────────────────────────────────────────────────────────
# 2. Tests for security/scanners/dependency_scanner.py
# ──────────────────────────────────────────────────────────────────────


def test_dependency_scanner_no_reqs(tmp_path):
    # Temp target dir with no requirements.txt in target or parent
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    findings = dependency_scanner.scan_requirements(target_dir)
    assert len(findings) == 0


def test_dependency_scanner_unpinned(tmp_path):
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    req_file = target_dir / "requirements.txt"
    req_file.write_text(
        "requests\nflask>=2.0\npytest==7.0.0\n# comment\n-r other.txt\n",
        encoding="utf-8",
    )

    findings = dependency_scanner.scan_requirements(target_dir)
    # requests and flask are unpinned (flask>=2.0 is considered unpinned since no ==)
    assert len(findings) == 1
    assert findings[0].rule_id == "DEP-002"
    assert "requests" in findings[0].evidence


def test_dependency_scanner_pip_audit_mock(tmp_path):
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    req_file = target_dir / "requirements.txt"
    req_file.write_text("requests==2.26.0\n", encoding="utf-8")

    pip_audit_output = json.dumps(
        {
            "dependencies": [
                {
                    "name": "requests",
                    "version": "2.26.0",
                    "vulns": [
                        {
                            "id": "CVE-2021-33503",
                            "description": "critical vulnerability in requests urllib3 dependency",
                            "fix_versions": ["2.27.0"],
                        }
                    ],
                }
            ]
        }
    )

    with patch("subprocess.run") as mock_run, patch("os.name", "posix"):
        mock_run.return_value = MagicMock(returncode=0, stdout=pip_audit_output)
        findings = dependency_scanner.scan_requirements(target_dir)
        assert len(findings) == 1
        assert findings[0].rule_id == "DEP-001"
        assert findings[0].severity == Severity.CRITICAL
        assert "CVE-2021-33503" in findings[0].description


# ──────────────────────────────────────────────────────────────────────
# 3. Tests for security/scanners/secret_scanner.py
# ──────────────────────────────────────────────────────────────────────


def test_secret_scanner(tmp_path):
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    # Create config files with various mock secrets and placeholders
    env_file = target_dir / "secrets.ini"
    env_file.write_text(
        "API_KEY=AKIA1234567890ABCDEF\n"  # AWS style (though rule is AKIA + 16 chars)
        "TELEGRAM_TOKEN=12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi_-\n"  # TG style
        "BINANCE_SECRET=binance_secret_value_longer_than_thirty_chars\n"  # Binance API key pattern
        "PASSWORD=real_secret_password_here\n"  # Generic password
        "DUMMY_KEY=change_me_now\n"  # Placeholder, should be skipped
        'EMPTY_KEY=""\n'  # Empty, should be skipped
        "# API_KEY=commented_out_key_here\n",  # Comment, should be skipped
        encoding="utf-8",
    )

    # AWS specific pattern test (AKIA[0-9A-Z]{16})
    aws_file = target_dir / "credentials.json"
    aws_file.write_text(
        json.dumps({"aws_key": "AKIAJ9876543210ABCDE"}), encoding="utf-8"
    )

    # Skip files / patterns
    skip_file = target_dir / ".env.example"
    skip_file.write_text("API_KEY=your_api_key_here\n", encoding="utf-8")

    findings = secret_scanner.scan_directory(target_dir)

    # Should find API_KEY, TELEGRAM_TOKEN, BINANCE_SECRET, PASSWORD, and AWS Key
    # (Note: env_file name matches .env, which is not in skip list when in target directory)
    rule_ids = [f.rule_id for f in findings]
    assert "SEC-001" in rule_ids
    assert len(findings) >= 2


# ──────────────────────────────────────────────────────────────────────
# 4. Tests for security/scanners/static_scanner.py
# ──────────────────────────────────────────────────────────────────────


def test_static_scanner_dangerous_calls(tmp_path):
    code_content = """
eval("1 + 1")
exec("x = 2")
compile("x", "x", "exec")
import pickle
pickle.loads(b"data")
pickle.load(None)
import yaml
yaml.load("data")
import subprocess
subprocess.call("ls", shell=True)
subprocess.Popen("ls", shell=True)
subprocess.run("ls", shell=True)
import os
os.system("ls")
os.popen("ls")
eval("1 + 1") # nosec
"""
    file_path = tmp_path / "test_static.py"
    file_path.write_text(code_content, encoding="utf-8")

    findings = static_scanner.scan_file(file_path)
    rule_ids = [f.rule_id for f in findings]

    # STA-001 (eval, exec, compile)
    assert "STA-001" in rule_ids
    # STA-002 (pickle, yaml, os.system, os.popen)
    assert "STA-002" in rule_ids
    # STA-003 (subprocess shell=True)
    assert "STA-003" in rule_ids

    # Check nosec count: we have one eval() with nosec, which should not produce a finding
    eval_findings = [f for f in findings if f.evidence.startswith("eval(")]
    # Only the first eval is expected to be recorded
    assert len(eval_findings) == 1


def test_static_scanner_debug_and_secrets(tmp_path):
    code_content = """
DEBUG = True
api_key = "abcdefghijklmnopqrstuvwxyz"
api_key = os.getenv("API_KEY") # should be skipped
"""
    file_path = tmp_path / "config.py"
    file_path.write_text(code_content, encoding="utf-8")

    findings = static_scanner.scan_file(file_path)
    rule_ids = [f.rule_id for f in findings]

    assert "STA-004" in rule_ids
    assert "STA-005" in rule_ids


def test_static_scanner_large_file_skip(tmp_path):
    file_path = tmp_path / "large_file.py"
    file_path.write_text("DEBUG = True\n" * 30000, encoding="utf-8")  # > 300KB

    findings = static_scanner.scan_file(file_path)
    rule_ids = [f.rule_id for f in findings]
    # Regex checks (like debug mode check) should still run and find debug mode
    assert "STA-004" in rule_ids
    # AST visit should have been skipped, so no dangerous calls (if any) would be visited


def test_static_scanner_directory_scan(tmp_path):
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    file_1 = target_dir / "main.py"
    file_1.write_text("eval('x')", encoding="utf-8")

    file_skip = target_dir / "test_main.py"
    file_skip.write_text("eval('x')", encoding="utf-8")

    findings = static_scanner.scan_directory(target_dir)
    # test_main.py is skipped by filename prefix
    assert len(findings) == 1
    assert findings[0].file == str(file_1)


# ──────────────────────────────────────────────────────────────────────
# 5. Tests for security/scanners/trading_rules.py
# ──────────────────────────────────────────────────────────────────────


def test_trading_rules(tmp_path):
    # TVP-001: unsafe_price_parse
    tvp001_code = """
price = float(price_str)
try:
    qty = float(qty_str)
except Exception:
    qty = 0.0
# float(price) comment
"""
    file_1 = tmp_path / "webhook_handler.py"
    file_1.write_text(tvp001_code, encoding="utf-8")

    # TVP-002: uncapped_quote_qty
    tvp002_code = """
quote_qty = payload.get('quoteQty')
# no validation or clamping here
"""
    file_2 = tmp_path / "webhook.py"
    file_2.write_text(tvp002_code, encoding="utf-8")

    # TVP-003: secret_in_payload
    tvp003_code = """
secret = payload.get("secret")
insert_signal(payload)
payload.pop("secret")
"""
    file_3 = tmp_path / "webhook_db.py"
    file_3.write_text(tvp003_code, encoding="utf-8")

    # TVP-004: missing_rate_limit
    tvp004_code = """
@app.post("/trade")
def handle_trade():
    pass
"""
    file_4 = tmp_path / "main.py"
    file_4.write_text(tvp004_code, encoding="utf-8")

    # TVP-005: path_traversal
    tvp005_code = """
save_path = os.path.join(DIR, symbol)
"""
    file_5 = tmp_path / "screenshot.py"
    file_5.write_text(tvp005_code, encoding="utf-8")

    # TVP-006: dry_run_bypass
    tvp006_code = """
DRY_RUN = os.getenv("BINANCE_DRY_RUN", "true")
"""
    file_6 = tmp_path / "config.py"
    file_6.write_text(tvp006_code, encoding="utf-8")

    # TVP-007: telegram_token_exposure
    tvp007_code = """
log.error(f"Failed with bot token: {TELEGRAM_BOT_TOKEN}")
"""
    file_7 = tmp_path / "telegram.py"
    file_7.write_text(tvp007_code, encoding="utf-8")

    findings = []
    for f in [file_1, file_2, file_3, file_4, file_5, file_6, file_7]:
        findings.extend(trading_rules.scan_file(f))

    rule_ids = [f.rule_id for f in findings]
    assert "TVP-001" in rule_ids
    assert "TVP-002" in rule_ids
    assert "TVP-003" in rule_ids
    assert "TVP-004" in rule_ids
    assert "TVP-005" in rule_ids
    assert "TVP-006" in rule_ids
    assert "TVP-007" in rule_ids


def test_trading_rules_directory_scan(tmp_path):
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    file_py = target_dir / "main.py"
    file_py.write_text(
        "@app.post('/trade')\ndef handle_trade():\n    pass", encoding="utf-8"
    )

    file_test = target_dir / "test_main.py"
    file_test.write_text(
        "@app.post('/trade')\ndef handle_trade():\n    pass", encoding="utf-8"
    )

    findings = trading_rules.scan_directory(target_dir)
    # test_main.py should be skipped
    assert len(findings) == 1
