# AQH Verification Report

- **Time**: Fri, 19 Jun 2026 21:10:24 +07
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
external QA did not yield GO verdict: [QA Bridge] [14:11:06] Starting STAGED Strict QA Pipeline (No-Fallback Protocol)...
[QA Bridge] [14:11:07] Exporting session...
[QA Bridge] [14:11:09] Export error: No Codex session found for cwd: C:\Users\pesil\working\mj_trading\TradingViewProject
{
  "status": "error",
  "error": "Session export failed"
}

```

