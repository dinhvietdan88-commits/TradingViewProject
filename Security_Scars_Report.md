# SEC-04 Security Scars Report

This report documents the security fixes applied across `nerves/workers/trading/` in response to the CodeQL SARIF scan results. These mitigations enforce SEC-04 (Runtime Guards) to prevent Path Traversal, ReDoS, and Stack Trace Exposure.

## 1. Path Injection (CWE-22)

**Vulnerability:** CodeQL flagged `py/path-injection` in 29 locations. This occurs when user-controlled input or system variables are used to construct file paths without proper sanitization, allowing arbitrary file system access.
**Affected Files:**
- `mcp_client.py`
- `capture_client.py`
- `utils/chart_generator_lw.py`
- `rag.py`
- `vision.py`
- `main.py`

**Mitigation (SEC-04 Guard `safe_path`):**
Applied the `safe_path` runtime guard from `security.runtime_guard` to enforce strict directory sandboxing.
- **`mcp_client.py` / `capture_client.py`**: Intercepted the `save_path` parameter and wrapped it with `safe_path` using `Path(__file__).parent.parent` as the base.
- **`utils/chart_generator_lw.py`**: Intercepted the screenshot `save_path`.
- **`rag.py`**: Enforced `safe_path` on the input `image_path`.

## 2. Stack Trace Exposure (CWE-209)

**Vulnerability:** CodeQL flagged `py/stack-trace-exposure` in 10 locations. The system leaked raw Exception strings (`str(e)`) in `HTTPException` responses and JSON payloads, which could expose internal system configurations or secrets.
**Affected Files:**
- `main.py`
- `auth/routes.py`
- `execution_server.py`
- `workers/vps_analyzer.py`

**Mitigation:**
Sanitized the exposed exceptions and replaced raw `str(e)` messages with generic system messages in the API responses. Detailed errors are now logged internally via `log.exception()` without returning them to the client.

## 3. Polynomial ReDoS (CWE-400)

**Vulnerability:** CodeQL flagged `py/polynomial-redos` in 2 locations in `notifier.py`, specifically regarding regex backtracking when processing Telegram Markdown-to-HTML conversion.
**Affected File:**
- `notifier.py`

**Mitigation (SEC-04 Guard `safe_regex_input`):**
The regex patterns were refactored to be pre-compiled with length limits (`{1,2000}?`). Furthermore, `safe_regex_input` from `security.runtime_guard` was applied to ensure the text payload truncates safely at 10,000 characters before attempting any regex replacements.

## 4. Weak Sensitive Data Hashing (CWE-327)

**Vulnerability:** CodeQL flagged `py/weak-sensitive-data-hashing` in `exchanges/bybit_adapter.py`.
**Affected File:**
- `exchanges/bybit_adapter.py`

**Mitigation:**
This is an intentional false-positive. The Bybit API V5 standard explicitly requires HMAC-SHA256 for request signing. The code correctly hashes `hashlib.sha256` and uses `hmac.new` with the API secret acting as the key, rather than hashing a password directly. No change is required here as this is standard and secure API behavior.

## 5. Insecure Socket Binding

**Vulnerability:** CodeQL flagged `py/bind-socket-all-network-interfaces` in `start_server.py`.
**Affected File:**
- `start_server.py`

**Mitigation:**
The file had previously been bound to `0.0.0.0`, but is already updated in the current repository to bind explicitly to `127.0.0.1`.

---
*Note: The SARIF report represents a static snapshot. Subsequent code scans are expected to resolve these rules based on the SEC-04 runtime guards applied above.*
