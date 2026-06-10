# Sprint 6: Performance Dashboard — Web UI

## Muc tieu

Xay dung **Performance Dashboard** dang web, serve truc tiep tu FastAPI server,
hien thi tat ca metrics giao dich tu SQLite database:
- KPI Cards: Win Rate, Profit Factor, Total P&L, Max Drawdown
- Equity Curve chart (tich luy P&L theo thoi gian)
- Trade History table voi pagination
- Filter theo symbol va khoang thoi gian
- Dark mode, glassmorphism, premium design

## Kien truc

```
Browser (localhost:5000/dashboard)
    |
    v
FastAPI Static Files + Jinja2 Template
    |
    v
API Endpoints: /trades, /trades/stats, /trades/equity
    |
    v
SQLite Database (trades.db)
```

**Khong su dung framework frontend** (React, Vue, etc.) — giu don gian:
- 1 file HTML (Jinja2 template hoac pure static)
- Vanilla JS fetch API endpoints
- CSS custom voi glassmorphism + dark theme
- Chart.js (CDN) cho Equity Curve

## Files se tao/sua

| File | Hanh dong |
|------|-----------|
| `server/static/dashboard.html` | [NEW] Single-page dashboard |
| `server/static/css/dashboard.css` | [NEW] Premium dark theme CSS |
| `server/static/js/dashboard.js` | [NEW] Fetch API + Chart.js |
| `server/main.py` | [MODIFY] Mount static files + add /trades/equity endpoint |
| `server/database.py` | [MODIFY] Add get_equity_curve() query |
| `server/requirements.txt` | [MODIFY] Add jinja2 (optional) |
| `docs/plans/sprint6_dashboard.md` | [NEW] This plan |
| `README.md` | [MODIFY] Update roadmap |

## Dashboard Layout

```
+----------------------------------------------------------+
|  Minervini SEPA — Performance Dashboard          [Filter] |
+----------------------------------------------------------+
|  [ Win Rate ]  [ Profit Factor ]  [ Total P&L ]  [ DD ]  |
|   62.2%           2.1              +$1,250        -$180   |
+----------------------------------------------------------+
|                                                          |
|               Equity Curve (Chart.js)                    |
|               ~~~~~~~~~~~~~~~~~~~~~~~~~~                 |
|                                                          |
+----------------------------------------------------------+
|  Trade History                                           |
|  # | Time | Symbol | Side | Qty | Price | P&L | Status  |
|  1 | ...  | BTCUSD | BUY  | 0.5 | 68000 | +$120 | FILLED|
|  ...                                                     |
+----------------------------------------------------------+
```

## API Endpoint moi

### GET /trades/equity

Tra ve equity curve data cho Chart.js:

```json
{
  "labels": ["2026-05-01", "2026-05-02", ...],
  "cumulative_pnl": [0, 120, 85, 210, ...]
}
```

## Ke hoach thuc thi

1. Them get_equity_curve() vao database.py
2. Them endpoint /trades/equity + mount static files trong main.py
3. Tao dashboard.html voi premium dark UI
4. Tao dashboard.css voi glassmorphism
5. Tao dashboard.js voi Chart.js CDN
6. Commit + Push feat branch
7. Merge vao main
