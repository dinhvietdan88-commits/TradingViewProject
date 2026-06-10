# AGY (Antigravity CLI) Usage Guide

> Generated from Server C agy agent session. Documents all usage patterns.

---

## 1. Using the `agy` CLI Directly

You can run the `agy` tool from the terminal with these common flags and commands:

### Single-Shot Prompt (Non-interactive)
```bash
agy --print "Analyze the latest code quality in nerves/"
# or using the short alias:
agy -p "your prompt"
```

### Interactive Session (Start with a prompt)
```bash
agy -i "Let's debug the connection issue"
```

### Continue Last Session
```bash
agy --continue
# or short alias:
agy -c
```

### Resume a Specific Conversation
```bash
agy --conversation <CONVERSATION_ID>
```

### Auto-Approve Tool Prompts (Dangerously Skip Permissions)
```bash
agy --print "run unit tests" --dangerously-skip-permissions
```

---

## 2. Using `agy` with the Trading Bot (as the RAG Provider)

The trading bot uses `agy` to generate market analysis and trading recommendations
based on the Minervini SEPA knowledge base.

### Configuration

1. Set the following in your environment (`.env`):
   ```env
   AI_PROVIDER=agy
   AGY_BRIDGE_URL=http://host.docker.internal:9100
   AGY_MODEL=gemini-2.5-flash
   AGY_TIMEOUT_SEC=25
   ```

2. When the bot processes a signal inside `rag.py`, it initializes `AgyHarness`
   (defined in `agy_harness.py`) which handles HTTP calls to the sidecar bridge.

### Pipeline Flow
```
Signal received → rag.py → agy_harness.py → HTTP POST /analyze
  → agy-bridge.py (host :9100) → google-genai SDK → Gemini 2.5 Flash
  → AI analysis → APPROVED/REJECTED → Telegram → Forward Server B
```

---

## 3. Running `agy` in a Docker/Containerized Environment (`agy-bridge`)

Because the `agy` binary requires a PTY (pseudo-terminal) and local file access,
containers run it through a FastAPI sidecar service called `agy-bridge.py`
running on the **host machine**.

### Manual Start
```bash
ANTIGRAVITY_API_KEY=your_key python3 deploy/agy-bridge.py
```

### Deploy as systemd Service
```bash
bash deploy/deploy-agy-bridge.sh
```

### Architecture
```
┌─────────────────────────┐     ┌──────────────────────────┐
│  Docker Container       │     │  Host (Server C)         │
│  tradingbot-analyzer    │     │                          │
│                         │     │  agy-bridge.py (:9100)   │
│  rag.py                 │────▶│  ├─ google-genai SDK     │
│  └─ AgyHarness          │HTTP │  └─ Gemini 2.5 Flash     │
│                         │     │                          │
│  GEMINI_API_KEY ─────────────▶│  GEMINI_API_KEY          │
└─────────────────────────┘     └──────────────────────────┘
```

- Bridge listens on port `:9100`
- Processes HTTP requests from Docker at `/analyze`
- Health check at `/health`

### SCAR Notes
- **SCAR-005**: `agy` requires PTY — bridge uses file redirect `< file.txt`
- **SCAR-006**: `ANTIGRAVITY_API_KEY` must be Tier 1 to avoid quota issues
- **SCAR-007**: `agy CLI --print` + PIPE stdin = full agent session (explores workspace)
  → Fix: file redirect + `--dangerously-skip-permissions` = single-shot (~13s)
- **SCAR-008**: systemd `ProtectHome=read-only` blocks `~/.antigravity/` writes → hang
  → Fix: `ProtectHome=false`, `PrivateTmp=false`, temp file in `~/.cache/`

### Performance Optimizations
- **Adaptive Strategy** (SCAR-007b): Auto-switches between sequential and parallel
  based on CLI health metrics (rolling 10-call window):
  - CLI **healthy** → Sequential fallback (1x tokens, ~0 extra latency)
  - CLI **degraded** → Parallel race (2x tokens, saves ~8s on failover)
  - Degraded triggers: avg latency >18s, failure rate >40%, or 2+ consecutive fails
- **Response Cache**: SHA256-keyed, 5min TTL (configurable via `AGY_CACHE_TTL`).
  Duplicate signals return **<100ms** instead of ~13s.
- **Prompt Compression**: RAG chunks trimmed 800→400 chars, prompt compacted ~40%.
  Reduces Gemini thinking time by ~2-3s.

---

## 4. Using `agy` with A2A (Agent-to-Agent / Satellite) Protocol

For remote orchestrations (e.g. Server C communication), the project uses the
A2A Integration protocol to allow your local IDE agent to command `agy` on the
server over a Tailscale VPN.

- Active design and deployment roadmap: `docs/SETUPS/08_A2A_INTEGRATION_ROADMAP.md`
- Gateway operates on port `:9108` using ed25519 challenge-response authentication

---

## Summary

| Method | Use Case | Speed | Status |
|--------|----------|-------|--------|
| Bridge → agy CLI binary | Docker containers (primary) | ~11-13s | ✅ **Primary** |
| Bridge → google-genai SDK | Docker containers (adaptive fallback) | ~8s | ✅ **Adaptive Fallback** |
| Response Cache | Duplicate signals | **<100ms** | ✅ **Active (5min TTL)** |
| `agy -p "prompt"` | Interactive terminal agent | ~30s-10min+ | ✅ Available |
| `agy -i "prompt"` | Interactive session | N/A | ✅ Available |
| A2A Gateway :9108 | Remote orchestration | TBD | 🔮 Planned |
| `google.antigravity` Agent SDK | In-container direct | >20s timeout | ❌ Not suitable |
