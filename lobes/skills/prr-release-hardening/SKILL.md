---
name: prr-release-hardening
description: >
  Unified quality and security gate verification for production readiness,
  including Windows-specific anti-hang guardrails for Semgrep and CodeQL CLI.
---

# PRR Release Hardening Skill

## Overview

This skill establishes and automates the Production Readiness Review (PRR) quality gates, ensuring code quality and security compliance from local development to staging and production. It incorporates physical and logical guardrails specifically configured to prevent process deadlocks and locks on Windows hosts.

## Core Workflows

### 1. Local Dev Quality & Security Hook (Git pre-commit)
Configures and runs fast static scans on staged files before a commit is allowed:
- **Lint/Format:** `ruff check`, `ruff format --check`
- **Secrets Scan:** `Mini-MDASH` scanner looking for high/critical credentials leaks.

### 2. Unified Security Gate CLI (`local_security_gate.py`)
Run this tool locally before opening a Pull Request or deploying:
- **Quick Mode:** Runs Ruff, Git pre-commit wrapper, and Mini-MDASH.
- **Default Mode:** Runs Ruff, Mini-MDASH, and Semgrep with anti-hang configurations.
- **Deep Mode:** Runs full static analysis including CodeQL CLI database generation and query execution.

### 3. Live Server Validation (`verify_server_c_gaps.py`)
Validates that the live server environment starts, responds to API health probes, has loaded vector chunks, and shuts down gracefully without leaking resources.

### 4. E2E Pipeline Simulation (`simulate_pipeline.py`)
Mocks the message routing path: Gateway (Server A) -> VPS Analyzer (Server C) -> Execution Mock (Server B) to verify full integration behavior.

---

## 🛠️ Windows Anti-Hang Guardrails

To prevent agent freezes, CPU saturation, and database locks on Windows, all workflows must strictly follow these rules:

### A. Semgrep Deadlock Prevention
- **Single Threading:** Semgrep must run with `--jobs=1` to prevent Windows process deadlock.
- **Virtualenv Exclusion:** The virtualenv directories (`.venv` or `venv`) must be explicitly ignored using Windows backslash formats in `.semgrepignore`:
  ```ignore
  .venv\
  **\.venv\
  venv\
  **\venv\
  ```

### B. CodeQL Lock & Finalization Recovery
- **No Premature Taskkill:** Do not forcefully kill CodeQL/Java processes while database creation or finalization is running; let them finish naturally.
- **Lock Cleanup:** If CodeQL crashes or leaves behind a `.lock` file, release locks with:
  ```powershell
  Stop-Process -Name java, codeql -Force -ErrorAction SilentlyContinue
  Remove-Item -Path ".codeql\db-python\db-python\default\cache\.lock" -Force -ErrorAction SilentlyContinue
  ```
- **Long Path Bypass:** To delete a corrupted `.codeql` database folder containing deep paths on Windows, use:
  ```powershell
  Remove-Item -LiteralPath "\\?\C:\Users\pesil\working\mj_trading\TradingViewProject\.codeql" -Recurse -Force -ErrorAction SilentlyContinue
  ```

---

## 💻 Commands Reference

### 1. Setup & Status
```powershell
# Install local Git pre-commit hooks
python scripts/setup_git_hooks.py

# Check status of the quality gate config
python scripts/local_security_gate.py status
```

### 2. Execution Gates
```powershell
# Run standard check (Ruff, Mini-MDASH, Semgrep --jobs=1)
python scripts/local_security_gate.py check

# Run deep check (includes CodeQL CLI database build & query run)
python scripts/local_security_gate.py check --deep
```

### 3. Dynamic Verification
```powershell
# Verify Server C (ChromaDB, FastAPI health, Graceful Shutdown)
python scripts/verify_server_c_gaps.py

# Simulate E2E routing pipeline
python scripts/simulate_pipeline.py
```
