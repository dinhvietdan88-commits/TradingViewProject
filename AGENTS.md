## Learned User Preferences

- Expect bug and security fixes to be backed by runtime evidence (pytest, repro scripts, harness output) before treating them as resolved.
- Run security scans from `server/` with `python -m security.cli scan`; reconcile findings against current code (especially `server/gateway/webhook.py`), not stale report artifacts.
- Do not create git commits unless explicitly requested.
- When implementing an attached plan, do not edit the plan file; use existing todos instead of recreating them.
- For live indicator smoke tests, use `PORT` / `SMOKE_BASE_URL` and `WEBHOOK_SECRET` from the environment (default API port is 5000).

## Learned Workspace Facts

- The canonical FastAPI app and event-driven pipeline live under `server/` (webhook ingress: `server/gateway/webhook.py`; trade execution: `server/engine/trade_engine.py`).
- Root `trading/engine.py` is only a stub pointer; the real trade engine is `server/engine/trade_engine.py`.
- TradingView indicator alerts use `source: "indicator"` and emit `IndicatorSignalReceived`; the dashboard Signals tab uses `/api/indicator-signals` and `server/static/js/dashboard-signals.js`.
- Indicator webhook payloads must validate `symbol` and `indicator_name` before `insert_signal` so invalid requests do not create orphan `signals` rows.
- Stealth `alert` flows must pass `exchange` on `AlertTriggered` through to downstream `SignalValidated` / `AnalysisComplete`.
- This client project stays isolated from global EAIS; local RAG uses ChromaDB in `server/rag.py` (see `CLAUDE.md`).

## Security SCARs (Prevention Rules)

- [SCAR-SEC-01] KHÔNG BAO GI? N?I CHU?I URL TR?C TI?P T? USER INPUT: Ph?i qua validate_exchange_url().
- [SCAR-SEC-02] B?T BU?C DÙNG safe_path() KHI Ð?C FILE: Ch?ng Path Traversal CWE-22.
- [SCAR-SEC-03] KHÔNG S? D?NG TRY-EXCEPT-PASS: Ph?i import logging và log l?i l?i (C?m nu?t l?i S110).
- [SCAR-SEC-04] QU?N LÝ SECRETS TRONG MÔI TRU?NG TEST: Không hardcode secret k? c? trong test (S105), dùng os.environ ho?c # noqa: S105.
- [SCAR-SEC-05] AUDIT URLLIB SCHEMES (S310): Validate protocol ho?c dùng requests thay cho urllib.request.urlopen.
