# Sprint 7: Server Testing — Dat Chuan Production

## Muc tieu

Xay dung test suite day du cho FastAPI Webhook Server dam bao:
- Moi endpoint hoat dong dung — happy path + error cases
- Database CRUD chinh xac
- Security (auth, IP whitelist) hoat dong
- Performance co the do luong
- CI-ready: chay duoc bang `pytest` mot lenh

## Phan loai Tests

### 1. Unit Tests — `tests/unit/`
- `test_database.py`: CRUD operations (insert, query, stats, equity)
- `test_config.py`: env var loading
- `test_notifier.py`: notification formatting (mock HTTP calls)

### 2. Integration Tests — `tests/integration/`
- `test_health.py`: GET /tv_health_check
- `test_webhook.py`: POST /webhook (buy, sell, alert, invalid secret, empty payload)
- `test_trades.py`: GET /trades (pagination, filter)
- `test_stats.py`: GET /trades/stats (win rate, profit factor)
- `test_equity.py`: GET /trades/equity
- `test_dashboard.py`: GET /dashboard, GET /

### 3. Security Tests — `tests/security/`
- `test_auth.py`: secret mismatch, missing secret, header vs payload secret
- `test_ip.py`: IP whitelist middleware on/off

## Test Infrastructure

- **Framework**: pytest + pytest-asyncio
- **HTTP Client**: httpx.AsyncClient voi ASGITransport (khong can server chay)
- **DB Isolation**: moi test dung in-memory SQLite (:memory:) — khong anh huong trades.db that
- **Fixtures**: conftest.py setup DB + client theo tung test
- **CI**: pytest.ini, requirements-test.txt

## Chay Test

```bash
cd server
pip install -r requirements-test.txt
pytest tests/ -v --tb=short
```

## Tieu chi "Dat Chuan"

| Tieu chi | Nguong |
|----------|--------|
| Test pass rate | 100% |
| Coverage cac endpoint | 8/8 |
| Security cases | pass |
| DB isolation | moi test doc lap |
| Khong can .env | co fixture override |
