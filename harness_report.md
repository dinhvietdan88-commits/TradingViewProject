# AQH Verification Report

- **Time**: Sat, 20 Jun 2026 00:55:24 +07
## KG CONTEXT: LEAF
- **Blast Radius**: 0 dependents, 0 callers

- **Mode**: STRICT (Muscle Gate)

### 🟢 Build Gate: PASSED

### 🟡 Canary Gate: SKIPPED (registry error)
> canary registry not found: open C:\Users\pesil\EAIS\.agents\memory\canary_registry.json: The system cannot find the file specified.

### 🟢 Unit Test Gate: PASSED

### 🟢 Internal Integration Gate: PASSED

### 🔴 External QA Gate: FAILED
```
external QA did not yield GO verdict: [QA Bridge] [17:56:12] Starting STAGED Strict QA Pipeline (No-Fallback Protocol)...
[QA Bridge] [17:56:12] Exporting session...
[QA Bridge] [17:56:14] Export error: No Codex session found for cwd: C:\Users\pesil\working\mj_trading\TradingViewProject
{
  "status": "error",
  "error": "Session export failed"
}

```

