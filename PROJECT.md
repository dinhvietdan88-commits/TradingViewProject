# Project: Security Remediation & Code Quality Hardening (268 Alerts)

## Architecture
- Codebase-wide application of Ruff auto-fixes (SEC-01, SEC-02)
- `server/security/runtime_guard.py` containing SEC-04 mitigations (`safe_path`, `validate_exchange_params`, `safe_log_input`).
- Pre-commit hooks for continuous enforcement.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: Linting & Code Quality | Resolve 188 lint alerts (repeated-import, empty-except, etc.) using SEC-01 & SEC-02 | none | PLANNED |
| 2 | M2: SEC-04 Runtime Guards | Resolve 80 critical alerts (SSRF, Path Traversal, Log Injection, XSS) using SEC-04 | none | PLANNED |
| 3 | M3: Final Pipeline Audit | Execute SEC-03 to verify 0 open CodeQL alerts | M1, M2 | PLANNED |

## Interface Contracts
- All file reads/writes must use `safe_path`.
- All external HTTP calls must use `validate_exchange_params` / URL validators.
- All logs of user input must be sanitized via `safe_log_input`.
