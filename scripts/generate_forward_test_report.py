#!/usr/bin/env python3
"""
Angati Forward-Test Sample Report Generator
Tao bao cao mau Forward Test (paper trading) cho BTC, ETH, SOL.
Usage: python scripts/generate_forward_test_report.py
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
REPORTS_DIR = ROOT / "reports"
RANDOM_SEED = 77
random.seed(RANDOM_SEED)

# ─── Sample paper trade data ──────────────────────────────────────────────────
SAMPLE_FORWARD_TRADES = [
    # BTC trades
    {
        "id": 1000001,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "entry": 67450.0,
        "close": 61454.0,
        "sl": 62054.0,
        "tp": 80940.0,
        "outcome": "STOP_LOSS",
        "pnl": -8.00,
        "qty": 0.001483,
        "ts": "2026-06-10 09:05",
    },
    {
        "id": 1000002,
        "symbol": "BTCUSDT",
        "side": "SELL",
        "entry": 67890.0,
        "close": 54312.0,
        "sl": 73321.2,
        "tp": 54312.0,
        "outcome": "TAKE_PROFIT",
        "pnl": 20.00,
        "qty": 0.001473,
        "ts": "2026-06-10 09:20",
    },
    {
        "id": 1000003,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "entry": 68120.5,
        "close": 61870.86,
        "sl": 62670.86,
        "tp": 81744.6,
        "outcome": "STOP_LOSS",
        "pnl": -8.00,
        "qty": 0.001468,
        "ts": "2026-06-10 11:15",
    },
    {
        "id": 1000004,
        "symbol": "BTCUSDT",
        "side": "SELL",
        "entry": 67345.0,
        "close": 67345.0,
        "sl": 72732.6,
        "tp": 53876.0,
        "outcome": "TIMEOUT",
        "pnl": 6.34,
        "qty": 0.001485,
        "ts": "2026-06-11 02:30",
    },
    {
        "id": 1000005,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "entry": 66900.0,
        "close": 80280.0,
        "sl": 61548.0,
        "tp": 80280.0,
        "outcome": "TAKE_PROFIT",
        "pnl": 20.00,
        "qty": 0.001495,
        "ts": "2026-06-11 07:45",
    },
    {
        "id": 1000006,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "entry": 67200.0,
        "close": 61824.0,
        "sl": 61824.0,
        "tp": 80640.0,
        "outcome": "STOP_LOSS",
        "pnl": -8.00,
        "qty": 0.001488,
        "ts": "2026-06-11 14:20",
    },
    {
        "id": 1000007,
        "symbol": "BTCUSDT",
        "side": "SELL",
        "entry": 66750.0,
        "close": 66750.0,
        "sl": 72090.0,
        "tp": 53400.0,
        "outcome": "TIMEOUT",
        "pnl": 8.21,
        "qty": 0.001498,
        "ts": "2026-06-12 03:10",
    },
    {
        "id": 1000008,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "entry": 68500.0,
        "close": 63020.0,
        "sl": 63020.0,
        "tp": 82200.0,
        "outcome": "STOP_LOSS",
        "pnl": -8.00,
        "qty": 0.001460,
        "ts": "2026-06-12 10:00",
    },
    {
        "id": 1000009,
        "symbol": "BTCUSDT",
        "side": "SELL",
        "entry": 69120.0,
        "close": 55296.0,
        "sl": 74649.6,
        "tp": 55296.0,
        "outcome": "TAKE_PROFIT",
        "pnl": 20.00,
        "qty": 0.001447,
        "ts": "2026-06-12 15:30",
    },
    {
        "id": 1000010,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "entry": 69800.0,
        "close": 69800.0,
        "sl": 64216.0,
        "tp": 83760.0,
        "outcome": "TIMEOUT",
        "pnl": 4.88,
        "qty": 0.001433,
        "ts": "2026-06-13 06:00",
    },
    # ETH trades
    {
        "id": 1000011,
        "symbol": "ETHUSDT",
        "side": "BUY",
        "entry": 3420.0,
        "close": 3146.4,
        "sl": 3146.4,
        "tp": 4104.0,
        "outcome": "STOP_LOSS",
        "pnl": -8.00,
        "qty": 0.029239,
        "ts": "2026-06-10 10:00",
    },
    {
        "id": 1000012,
        "symbol": "ETHUSDT",
        "side": "SELL",
        "entry": 3380.0,
        "close": 2704.0,
        "sl": 3650.4,
        "tp": 2704.0,
        "outcome": "TAKE_PROFIT",
        "pnl": 20.00,
        "qty": 0.029586,
        "ts": "2026-06-10 12:30",
    },
    {
        "id": 1000013,
        "symbol": "ETHUSDT",
        "side": "BUY",
        "entry": 3510.0,
        "close": 3229.2,
        "sl": 3229.2,
        "tp": 4212.0,
        "outcome": "STOP_LOSS",
        "pnl": -8.00,
        "qty": 0.028490,
        "ts": "2026-06-11 09:00",
    },
    {
        "id": 1000014,
        "symbol": "ETHUSDT",
        "side": "SELL",
        "entry": 3460.0,
        "close": 3460.0,
        "sl": 3736.8,
        "tp": 2768.0,
        "outcome": "TIMEOUT",
        "pnl": 7.14,
        "qty": 0.028902,
        "ts": "2026-06-11 16:45",
    },
    {
        "id": 1000015,
        "symbol": "ETHUSDT",
        "side": "BUY",
        "entry": 3550.0,
        "close": 4260.0,
        "sl": 3266.0,
        "tp": 4260.0,
        "outcome": "TAKE_PROFIT",
        "pnl": 20.00,
        "qty": 0.028169,
        "ts": "2026-06-12 08:15",
    },
    {
        "id": 1000016,
        "symbol": "ETHUSDT",
        "side": "BUY",
        "entry": 3490.0,
        "close": 3210.8,
        "sl": 3210.8,
        "tp": 4188.0,
        "outcome": "STOP_LOSS",
        "pnl": -8.00,
        "qty": 0.028653,
        "ts": "2026-06-12 18:00",
    },
    {
        "id": 1000017,
        "symbol": "ETHUSDT",
        "side": "SELL",
        "entry": 3620.0,
        "close": 2896.0,
        "sl": 3909.6,
        "tp": 2896.0,
        "outcome": "TAKE_PROFIT",
        "pnl": 20.00,
        "qty": 0.027624,
        "ts": "2026-06-13 04:30",
    },
    {
        "id": 1000018,
        "symbol": "ETHUSDT",
        "side": "BUY",
        "entry": 3680.0,
        "close": 3680.0,
        "sl": 3385.6,
        "tp": 4416.0,
        "outcome": "TIMEOUT",
        "pnl": 5.62,
        "qty": 0.027174,
        "ts": "2026-06-13 11:20",
    },
    # SOL trades
    {
        "id": 1000019,
        "symbol": "SOLUSDT",
        "side": "BUY",
        "entry": 148.50,
        "close": 136.62,
        "sl": 136.62,
        "tp": 178.20,
        "outcome": "STOP_LOSS",
        "pnl": -8.00,
        "qty": 0.67340,
        "ts": "2026-06-10 08:30",
    },
    {
        "id": 1000020,
        "symbol": "SOLUSDT",
        "side": "SELL",
        "entry": 152.30,
        "close": 121.84,
        "sl": 164.48,
        "tp": 121.84,
        "outcome": "TAKE_PROFIT",
        "pnl": 20.00,
        "qty": 0.65658,
        "ts": "2026-06-10 13:00",
    },
    {
        "id": 1000021,
        "symbol": "SOLUSDT",
        "side": "BUY",
        "entry": 155.80,
        "close": 155.80,
        "sl": 143.34,
        "tp": 186.96,
        "outcome": "TIMEOUT",
        "pnl": 9.37,
        "qty": 0.64185,
        "ts": "2026-06-11 03:45",
    },
    {
        "id": 1000022,
        "symbol": "SOLUSDT",
        "side": "BUY",
        "entry": 161.20,
        "close": 148.30,
        "sl": 148.30,
        "tp": 193.44,
        "outcome": "STOP_LOSS",
        "pnl": -8.00,
        "qty": 0.62034,
        "ts": "2026-06-11 11:30",
    },
    {
        "id": 1000023,
        "symbol": "SOLUSDT",
        "side": "SELL",
        "entry": 158.60,
        "close": 126.88,
        "sl": 171.29,
        "tp": 126.88,
        "outcome": "TAKE_PROFIT",
        "pnl": 20.00,
        "qty": 0.63053,
        "ts": "2026-06-12 07:00",
    },
    {
        "id": 1000024,
        "symbol": "SOLUSDT",
        "side": "BUY",
        "entry": 163.40,
        "close": 150.33,
        "sl": 150.33,
        "tp": 196.08,
        "outcome": "STOP_LOSS",
        "pnl": -8.00,
        "qty": 0.61200,
        "ts": "2026-06-12 13:15",
    },
    {
        "id": 1000025,
        "symbol": "SOLUSDT",
        "side": "SELL",
        "entry": 160.00,
        "close": 160.00,
        "sl": 172.80,
        "tp": 128.00,
        "outcome": "TIMEOUT",
        "pnl": 6.75,
        "qty": 0.62500,
        "ts": "2026-06-12 20:00",
    },
    {
        "id": 1000026,
        "symbol": "SOLUSDT",
        "side": "BUY",
        "entry": 156.50,
        "close": 187.80,
        "sl": 144.02,
        "tp": 187.80,
        "outcome": "TAKE_PROFIT",
        "pnl": 20.00,
        "qty": 0.63897,
        "ts": "2026-06-13 02:00",
    },
    {
        "id": 1000027,
        "symbol": "SOLUSDT",
        "side": "SELL",
        "entry": 159.80,
        "close": 127.84,
        "sl": 172.58,
        "tp": 127.84,
        "outcome": "TAKE_PROFIT",
        "pnl": 20.00,
        "qty": 0.62578,
        "ts": "2026-06-13 09:45",
    },
    {
        "id": 1000028,
        "symbol": "SOLUSDT",
        "side": "BUY",
        "entry": 162.70,
        "close": 162.70,
        "sl": 149.68,
        "tp": 195.24,
        "outcome": "TIMEOUT",
        "pnl": 3.45,
        "qty": 0.61466,
        "ts": "2026-06-13 17:30",
    },
]


def compute_stats(trades: list[dict]) -> dict:
    total = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = total - wins
    total_pnl = round(sum(t["pnl"] for t in trades), 4)
    gross_profit = round(sum(t["pnl"] for t in trades if t["pnl"] > 0), 4)
    gross_loss = round(abs(sum(t["pnl"] for t in trades if t["pnl"] < 0)), 4)
    pf = round(gross_profit / gross_loss, 3) if gross_loss else 999.0
    winrate = round(wins / total * 100, 2) if total else 0
    avg_win = round(gross_profit / wins, 4) if wins else 0
    avg_loss = round(-gross_loss / losses, 4) if losses else 0
    expectancy = round(winrate / 100 * avg_win + (1 - winrate / 100) * avg_loss, 4)

    by_sym: dict[str, dict] = {}
    for t in trades:
        sym = t["symbol"]
        if sym not in by_sym:
            by_sym[sym] = {"total": 0, "wins": 0, "losses": 0, "pnl": 0.0}
        by_sym[sym]["total"] += 1
        if t["pnl"] > 0:
            by_sym[sym]["wins"] += 1
        else:
            by_sym[sym]["losses"] += 1
        by_sym[sym]["pnl"] = round(by_sym[sym]["pnl"] + t["pnl"], 4)

    by_outcome: dict[str, int] = {}
    for t in trades:
        by_outcome[t["outcome"]] = by_outcome.get(t["outcome"], 0) + 1

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "winrate": winrate,
        "total_pnl": total_pnl,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": pf,
        "expectancy": expectancy,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "by_symbol": by_sym,
        "by_outcome": by_outcome,
    }


def render_html(
    trades: list[dict],
    stats: dict,
    signals: list[dict],
    generated_at: str,
    is_sample: bool = True,
) -> str:
    # Build equity curve
    eq = 10000.0
    eq_labels, eq_values = [], []
    for i, t in enumerate(trades):
        eq += t["pnl"]
        eq_labels.append(f"T{i + 1}")
        eq_values.append(round(eq, 2))

    sym_labels = list(stats["by_symbol"].keys())
    sym_pnls = [v["pnl"] for v in stats["by_symbol"].values()]
    sym_wr = [
        round(v["wins"] / v["total"] * 100, 1) if v["total"] else 0
        for v in stats["by_symbol"].values()
    ]
    outcome_labels = list(stats["by_outcome"].keys())
    outcome_values = list(stats["by_outcome"].values())

    # Build trade rows
    rows = ""
    for t in trades:
        outcome_cls = {
            "TAKE_PROFIT": "outcome-tp",
            "STOP_LOSS": "outcome-sl",
            "TIMEOUT": "outcome-to",
        }.get(t["outcome"], "")
        pnl_cls = "pnl-pos" if t["pnl"] > 0 else "pnl-neg"
        rows += f"""
        <tr>
          <td>#{t["id"]}</td>
          <td>{t["ts"]}</td>
          <td><span class="sym">{t["symbol"]}</span></td>
          <td class="side-{t["side"].lower()}">{t["side"]}</td>
          <td>{t["entry"]:,.2f}</td>
          <td>{t["sl"]:,.2f}</td>
          <td>{t["tp"]:,.2f}</td>
          <td>{t["close"]:,.2f}</td>
          <td>{t["qty"]:.5f}</td>
          <td class="{pnl_cls}">{t["pnl"]:+.4f}%</td>
          <td><span class="outcome-badge {outcome_cls}">{t["outcome"]}</span></td>
        </tr>"""

    # Symbol summary rows
    sym_rows = ""
    for sym, v in stats["by_symbol"].items():
        wr = round(v["wins"] / v["total"] * 100, 1) if v["total"] else 0
        sym_rows += f"""
        <tr>
          <td><span class="sym">{sym}</span></td>
          <td>{v["total"]}</td>
          <td class="pnl-pos">{v["wins"]}</td>
          <td class="pnl-neg">{v["losses"]}</td>
          <td>{"<span class='badge-g'>" if wr >= 50 else "<span class='badge-r'>"}{wr}%</span></td>
          <td class="{"pnl-pos" if v["pnl"] > 0 else "pnl-neg"}">{v["pnl"]:+.4f}%</td>
        </tr>"""

    # Build signal rows
    signal_rows = ""
    for s in signals:
        state_cls = {
            "INGESTED": "outcome-to",
            "ANALYZING": "outcome-to",
            "STRATEGY_PASSED": "outcome-tp",
            "MACRO_PASSED": "outcome-tp",
            "REJECTED": "outcome-sl",
        }.get(s["state"], "")
        signal_rows += f"""
        <tr>
          <td>#{s["id"]}</td>
          <td>{s["ts"]}</td>
          <td><span class="sym">{s["symbol"]}</span></td>
          <td class="side-{s["action"].lower()}">{s["action"].upper()}</td>
          <td>{s["price"]:,.2f}</td>
          <td>{s["qty"]:.5f}</td>
          <td>{s["mode"]}</td>
          <td><span class="outcome-badge {state_cls}">{s["state"]}</span></td>
          <td>{s["reason"] if s["reason"] else "-"}</td>
        </tr>"""

    alert_style = (
        "background: rgba(63,185,80,0.1); border-color: rgba(63,185,80,0.3); color: var(--gr);"
        if not is_sample
        else ""
    )
    alert_content = (
        "🟢 <strong>Live Forward Test Results:</strong> Dữ liệu giao dịch thực tế lấy từ forward_trades.db."
        if not is_sample
        else "⚠️ <strong>Bao cao mau (Sample Report):</strong> Day la bao cao TINH tao tu du lieu gia lap de lam mau cho Forward Test thuc te."
    )

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Angati Forward-Test Report — {"Live" if not is_sample else "Mau Tinh"}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:#0d1117; --sf:#161b22; --sf2:#1c2128; --bor:#30363d;
    --txt:#e6edf3; --mut:#8b949e; --gr:#3fb950; --rd:#f85149;
    --yw:#d29922; --bl:#58a6ff; --pu:#bc8cff; --or:#ffa657;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--txt);font-family:'Segoe UI',system-ui,sans-serif;font-size:14px}}
  .header{{background:linear-gradient(135deg,#0d1117 0%,#161b22 50%,#1a2332 100%);border-bottom:1px solid var(--bor);padding:28px 40px;position:relative;overflow:hidden}}
  .header::before{{content:'';position:absolute;top:-60px;right:-60px;width:300px;height:300px;background:radial-gradient(circle,rgba(88,166,255,.08) 0%,transparent 70%);border-radius:50%}}
  .header .tag{{display:inline-block;background:rgba(88,166,255,.12);border:1px solid rgba(88,166,255,.3);color:var(--bl);padding:3px 12px;border-radius:20px;font-size:.72rem;font-weight:700;letter-spacing:.05em;margin-bottom:10px}}
  .header h1{{font-size:2rem;font-weight:800;color:var(--txt)}}
  .header h1 span{{background:linear-gradient(90deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
  .header .meta{{color:var(--mut);font-size:.82rem;margin-top:8px}}
  .alert-warning{{background:rgba(210,153,34,.1);border:1px solid rgba(210,153,34,.3);border-radius:8px;padding:12px 16px;margin:16px 0;color:var(--yw);font-size:.82rem}}
  .container{{max-width:1400px;margin:0 auto;padding:28px 40px}}
  .section{{margin-bottom:32px}}
  .section-title{{font-size:1rem;font-weight:700;color:var(--bl);border-left:3px solid var(--bl);padding-left:10px;margin-bottom:16px;display:flex;align-items:center;gap:8px}}
  .kpi-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}}
  .kpi{{background:var(--sf);border:1px solid var(--bor);border-radius:10px;padding:16px;transition:all .2s}}
  .kpi:hover{{border-color:var(--bl);transform:translateY(-2px);box-shadow:0 4px 20px rgba(88,166,255,.1)}}
  .kpi-lbl{{font-size:.7rem;color:var(--mut);text-transform:uppercase;letter-spacing:.06em;margin-bottom:5px}}
  .kpi-val{{font-size:1.5rem;font-weight:700}}
  .kpi-sub{{font-size:.7rem;color:var(--mut);margin-top:2px}}
  .pos{{color:var(--gr)}} .neg{{color:var(--rd)}} .neu{{color:var(--bl)}} .yw{{color:var(--yw)}}
  .charts{{display:grid;grid-template-columns:1.5fr 1fr;gap:16px;margin-bottom:16px}}
  .chart-card{{background:var(--sf);border:1px solid var(--bor);border-radius:10px;padding:20px}}
  .chart-card h3{{font-size:.82rem;color:var(--mut);margin-bottom:12px}}
  .chart-card canvas{{max-height:240px}}
  table{{width:100%;border-collapse:collapse}}
  th{{background:var(--sf2);color:var(--mut);font-size:.7rem;text-transform:uppercase;padding:9px 12px;text-align:left;border-bottom:1px solid var(--bor);letter-spacing:.05em}}
  td{{padding:7px 12px;border-bottom:1px solid var(--bor);font-size:.8rem}}
  tr:hover td{{background:var(--sf2)}}
  .sym{{font-weight:700;color:var(--bl);font-size:.78rem}}
  .side-buy{{color:var(--gr);font-weight:700}} .side-sell{{color:var(--rd);font-weight:700}}
  .pnl-pos{{color:var(--gr);font-weight:600}} .pnl-neg{{color:var(--rd);font-weight:600}}
  .outcome-badge{{padding:2px 8px;border-radius:6px;font-size:.7rem;font-weight:700}}
  .outcome-tp{{background:rgba(63,185,80,.15);color:var(--gr)}}
  .outcome-sl{{background:rgba(248,81,73,.15);color:var(--rd)}}
  .outcome-to{{background:rgba(210,153,34,.15);color:var(--yw)}}
  .badge-g{{background:rgba(63,185,80,.15);color:var(--gr);padding:1px 8px;border-radius:8px;font-size:.72rem}}
  .badge-r{{background:rgba(248,81,73,.15);color:var(--rd);padding:1px 8px;border-radius:8px;font-size:.72rem}}
  .table-wrap{{overflow-x:auto;background:var(--sf);border:1px solid var(--bor);border-radius:10px}}
  .footer{{text-align:center;color:var(--mut);font-size:.72rem;padding:20px;border-top:1px solid var(--bor)}}
  @media(max-width:900px){{.charts{{grid-template-columns:1fr}}.container{{padding:16px}}}}
</style>
</head>
<body>

<div class="header">
  <div class="tag">FORWARD-TEST — PAPER TRADING</div>
  <h1>Angati <span>Forward-Test</span> Report</h1>
  <div class="meta">
    Báo cáo giao dịch giả lập (Paper Trading) · BTC · ETH · SOL ·
    Tạo lúc: <strong>{generated_at}</strong>
  </div>
</div>

<div class="container">

  <div class="alert-warning" style="{alert_style}">
    {alert_content}
  </div>

  <!-- KPIs -->
  <div class="section">
    <div class="section-title">Tong Quan Hieu Nang — Forward Test ({stats["total"]} lenh)</div>
    <div class="kpi-grid">
      <div class="kpi"><div class="kpi-lbl">Tong Lenh</div><div class="kpi-val neu">{stats["total"]}</div><div class="kpi-sub">BTC + ETH + SOL</div></div>
      <div class="kpi"><div class="kpi-lbl">Win Rate</div><div class="kpi-val {"pos" if stats["winrate"] >= 50 else "neg"}">{stats["winrate"]}%</div><div class="kpi-sub">{stats["wins"]} thang / {stats["losses"]} thua</div></div>
      <div class="kpi"><div class="kpi-lbl">Tong P&L</div><div class="kpi-val {"pos" if stats["total_pnl"] > 0 else "neg"}">{stats["total_pnl"]:+.4f}%</div><div class="kpi-sub">Tren {stats["total"]} lenh</div></div>
      <div class="kpi"><div class="kpi-lbl">Profit Factor</div><div class="kpi-val {"pos" if stats["profit_factor"] >= 1.3 else "neg"}">{stats["profit_factor"]}</div><div class="kpi-sub">GP / GL</div></div>
      <div class="kpi"><div class="kpi-lbl">Expectancy</div><div class="kpi-val {"pos" if stats["expectancy"] > 0 else "neg"}">{stats["expectancy"]:+.4f}%</div><div class="kpi-sub">Ky vong / lenh</div></div>
      <div class="kpi"><div class="kpi-lbl">Avg Win</div><div class="kpi-val pos">{stats["avg_win"]:+.4f}%</div><div class="kpi-sub">TB lenh thang</div></div>
      <div class="kpi"><div class="kpi-lbl">Avg Loss</div><div class="kpi-val neg">{stats["avg_loss"]:+.4f}%</div><div class="kpi-sub">TB lenh thua</div></div>
      <div class="kpi"><div class="kpi-lbl">Gross Profit</div><div class="kpi-val pos">{stats["gross_profit"]:+.4f}%</div><div class="kpi-sub">Tong loi nhuan</div></div>
    </div>
  </div>

  <!-- Charts -->
  <div class="section">
    <div class="section-title">Bieu Do Hieu Nang</div>
    <div class="charts">
      <div class="chart-card">
        <h3>Equity Curve — Paper Trading (10,000 USDT ban dau)</h3>
        <canvas id="equityChart"></canvas>
      </div>
      <div class="chart-card">
        <h3>Outcome Distribution</h3>
        <canvas id="outcomeChart"></canvas>
      </div>
    </div>
    <div class="charts">
      <div class="chart-card">
        <h3>P&L theo Symbol</h3>
        <canvas id="symChart"></canvas>
      </div>
      <div class="chart-card">
        <h3>Win Rate theo Symbol</h3>
        <canvas id="wrChart"></canvas>
      </div>
    </div>
  </div>

  <!-- Symbol breakdown -->
  <div class="section">
    <div class="section-title">Phan Tich Theo Cap Giao Dich</div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Symbol</th><th>Tong Lenh</th><th>Thang</th><th>Thua</th><th>Win Rate</th><th>P&L</th></tr></thead>
        <tbody>{sym_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- Trade log -->
  <div class="section">
    <div class="section-title">Nhat Ky Giao Dich (Trade Log)</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>#ID</th><th>Thoi gian</th><th>Symbol</th><th>Side</th>
              <th>Entry</th><th>SL</th><th>TP</th><th>Close</th>
              <th>Qty</th><th>P&L</th><th>Ket qua</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </div>

  <!-- Signal log -->
  <div class="section">
    <div class="section-title">📡 Nhat Ky Tin Hieu (Signal Log)</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>#ID</th><th>Thoi gian</th><th>Symbol</th><th>Action</th>
              <th>Price</th><th>Qty</th><th>Mode</th><th>Trang Thai</th><th>Ly Do</th></tr>
        </thead>
        <tbody>{signal_rows}</tbody>
      </table>
    </div>
  </div>

</div>

<div class="footer">
  Angati Forward-Test Report · Paper Trading {"Live" if not is_sample else "Mau Tinh"} · {generated_at} · {stats["total"]} lenh
</div>

<script>
const eCtx = document.getElementById('equityChart').getContext('2d');
new Chart(eCtx, {{
  type: 'line',
  data: {{
    labels: {json.dumps(eq_labels)},
    datasets: [{{
      label: 'Equity',
      data: {json.dumps(eq_values)},
      borderColor: '#3fb950', backgroundColor: 'rgba(63,185,80,0.08)',
      borderWidth: 2, pointRadius: 4, pointBackgroundColor: '#3fb950',
      tension: 0.4, fill: true
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ mode: 'index', intersect: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#8b949e', font: {{ size: 10 }} }}, grid: {{ color: 'rgba(255,255,255,0.05)' }} }},
      y: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: 'rgba(255,255,255,0.05)' }} }}
    }}
  }}
}});

const oCtx = document.getElementById('outcomeChart').getContext('2d');
new Chart(oCtx, {{
  type: 'doughnut',
  data: {{
    labels: {json.dumps(outcome_labels)},
    datasets: [{{ data: {json.dumps(outcome_values)},
      backgroundColor: ['rgba(63,185,80,.8)','rgba(248,81,73,.8)','rgba(210,153,34,.8)'],
      borderColor: '#161b22', borderWidth: 3
    }}]
  }},
  options: {{ responsive: true, plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#8b949e' }} }} }} }}
}});

const sCtx = document.getElementById('symChart').getContext('2d');
new Chart(sCtx, {{
  type: 'bar',
  data: {{
    labels: {json.dumps(sym_labels)},
    datasets: [{{ label: 'P&L', data: {json.dumps(sym_pnls)},
      backgroundColor: {json.dumps(sym_pnls)}.map(v => v >= 0 ? 'rgba(63,185,80,.7)' : 'rgba(248,81,73,.7)'),
      borderRadius: 6
    }}]
  }},
  options: {{
    responsive: true, plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: 'rgba(255,255,255,.05)' }} }},
      y: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: 'rgba(255,255,255,.05)' }} }}
    }}
  }}
}});

const wrCtx = document.getElementById('wrChart').getContext('2d');
new Chart(wrCtx, {{
  type: 'radar',
  data: {{
    labels: {json.dumps(sym_labels)},
    datasets: [{{ label: 'Win Rate %', data: {json.dumps(sym_wr)},
      backgroundColor: 'rgba(88,166,255,.15)', borderColor: '#58a6ff',
      pointBackgroundColor: '#58a6ff', borderWidth: 2
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ r: {{
      ticks: {{ color: '#8b949e', backdropColor: 'transparent' }},
      grid: {{ color: 'rgba(255,255,255,.1)' }},
      pointLabels: {{ color: '#e6edf3', font: {{ size: 12 }} }},
      min: 0, max: 100
    }} }}
  }}
}});
</script>
</body>
</html>"""


def render_markdown(
    trades: list[dict],
    stats: dict,
    signals: list[dict],
    generated_at: str,
    is_sample: bool = True,
) -> str:
    rows = "\n".join(
        f"| #{t['id']} | {t['ts']} | {t['symbol']} | {t['side']} "
        f"| {t['entry']:,.2f} | {t['sl']:,.2f} | {t['tp']:,.2f} "
        f"| {t['close']:,.2f} | {t['pnl']:+.4f}% | {t['outcome']} |"
        for t in trades
    )
    sym_rows = "\n".join(
        f"| {sym} | {v['total']} | {v['wins']} | {v['losses']} "
        f"| {round(v['wins'] / v['total'] * 100, 1) if v['total'] else 0}% | {v['pnl']:+.4f}% |"
        for sym, v in stats["by_symbol"].items()
    )
    signal_rows_md = "\n".join(
        f"| #{s['id']} | {s['ts']} | {s['symbol']} | {s['action'].upper()} "
        f"| {s['price']:,.2f} | {s['qty']:.5f} | {s['mode']} "
        f"| {s['state']} | {s['reason'] if s['reason'] else '-'} |"
        for s in signals
    )

    alert_content = (
        "🟢 Live Forward Test Results: Dữ liệu giao dịch thực tế lấy từ forward_trades.db."
        if not is_sample
        else "Bao cao mau Forward-Test cho chien luoc **Angati SuperTrend VBS** voi 3 cap: BTC · ETH · SOL"
    )

    return f"""# Forward-Test Paper Trading Report — {"Live" if not is_sample else "Mau Tinh"}

> [!NOTE]
> {alert_content}
> Tao luc: **{generated_at}** · Muc dich: So sanh va kiem tra ket qua live

---

## Tong Quan Hieu Nang

| Chi So | Gia Tri |
| :--- | :--- |
| **Tong Lenh** | {stats["total"]} |
| **Thang / Thua** | {stats["wins"]} / {stats["losses"]} |
| **Win Rate** | **{stats["winrate"]}%** |
| **Tong P&L** | **{stats["total_pnl"]:+.4f}%** |
| **Gross Profit** | {stats["gross_profit"]:+.4f}% |
| **Gross Loss** | -{stats["gross_loss"]:.4f}% |
| **Profit Factor** | **{stats["profit_factor"]}** |
| **Expectancy** | {stats["expectancy"]:+.4f}% / lenh |
| **Avg Win** | {stats["avg_win"]:+.4f}% |
| **Avg Loss** | {stats["avg_loss"]:+.4f}% |

> [!{"TIP" if stats["expectancy"] > 0 else "CAUTION"}]
> Expectancy = **{stats["expectancy"]:+.4f}%** — {"An toan de chuyen sang Forward Test live ✅" if stats["expectancy"] > 0 else "DUNG — Ky vong am, can toi uu lai chien luoc"}

---

## Phan Tich Theo Cap Giao Dich

| Symbol | Tong | Thang | Thua | Win Rate | P&L |
| :--- | :--- | :--- | :--- | :--- | :--- |
{sym_rows}

---

## Phan Bo Ket Qua

| Ket Qua | So Lenh | Ti Le |
| :--- | :--- | :--- |
{"".join(f"| `{k}` | {v} | {round(v / stats['total'] * 100, 1)}% |" + chr(10) for k, v in stats["by_outcome"].items())}

---

## Nhat Ky Giao Dich (Trade Log)

| #ID | Thoi Gian | Symbol | Side | Entry | SL | TP | Close | P&L | Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{rows}

---

## 📡 Nhat Ky Tin Hieu (Signal Log)

| #ID | Thoi Gian | Symbol | Action | Price | Qty | Mode | Trang Thai | Ly Do |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{signal_rows_md}

---

> [!IMPORTANT]
> Day la báo cáo {"giao dịch thực tế" if not is_sample else "TINH tạo từ dữ liệu giả lập"}.
> Khi Forward Test dang chay thuc te, bao cao nay se duoc tu dong cap nhat tu `forward_trades.db`.
> Lien he Angati System de xem bao cao live.

*Angati Forward-Test Report Generator · v7.0 · {generated_at}*
"""


def main() -> None:
    print("Angati Forward-Test Report Generator (Dynamic Version)")
    print("=" * 60)

    # 1. Resolve forward DB path
    db_path = ROOT / "forward_trades.db"
    if not db_path.exists():
        db_path = ROOT / "nerves" / "workers" / "trading" / "forward_trades.db"

    trades = []
    signals_list = []
    is_sample = True

    # 2. Try loading from DB
    if db_path.exists():
        try:
            import sqlite3

            print(f"Loading data from: {db_path}")
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Check tables existence
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='signals'"
            )
            has_signals = cursor.fetchone() is not None
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
            )
            has_trades = cursor.fetchone() is not None

            if has_signals:
                cursor.execute("""
                    SELECT id, symbol, action, price, mode, state, rejection_reason, created_at, quote_qty
                    FROM signals
                    ORDER BY id DESC
                    LIMIT 50
                """)
                for r in cursor.fetchall():
                    signals_list.append(
                        {
                            "id": r[0],
                            "symbol": r[1],
                            "action": r[2],
                            "price": r[3] if r[3] else 0.0,
                            "mode": r[4] if r[4] else "-",
                            "state": r[5] if r[5] else "INGESTED",
                            "reason": r[6] if r[6] else "",
                            "ts": r[7],
                            "qty": r[8] if r[8] else 0.0,
                        }
                    )
                print(f"Loaded {len(signals_list)} signals from DB.")

            if has_trades:
                cursor.execute("""
                    SELECT id, symbol, side, executed_price, pnl, executed_qty, created_at,
                           stop_loss_price, take_profit_price, status
                    FROM trades
                    ORDER BY id DESC
                """)
                db_trades = cursor.fetchall()
                if db_trades:
                    is_sample = False
                    for r in db_trades:
                        trades.append(
                            {
                                "id": r[0],
                                "symbol": r[1],
                                "side": r[2].upper(),
                                "entry": r[3] if r[3] else 0.0,
                                "close": r[3] if r[3] else 0.0,
                                "sl": r[7] if r[7] else 0.0,
                                "tp": r[8] if r[8] else 0.0,
                                "outcome": r[9] if r[9] else "UNKNOWN",
                                "pnl": r[4] if r[4] is not None else 0.0,
                                "qty": r[5] if r[5] else 0.0,
                                "ts": r[6],
                            }
                        )
                    print(f"Loaded {len(trades)} trades from DB.")
            conn.close()
        except Exception as e:
            print(f"Error querying forward_trades.db: {e}")

    if not trades:
        print("No live trades found. Using SAMPLE_FORWARD_TRADES fallback.")
        trades = SAMPLE_FORWARD_TRADES

    stats = compute_stats(trades)
    generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print(
        f"Total trades: {stats['total']} | Win Rate: {stats['winrate']}% | PF: {stats['profit_factor']}"
    )

    # HTML
    html_path = REPORTS_DIR / "forward_test_sample_report.html"
    html_path.write_text(
        render_html(trades, stats, signals_list, generated_at, is_sample),
        encoding="utf-8",
    )
    print(f"HTML saved: {html_path.relative_to(ROOT)}")

    # Markdown
    md_path = REPORTS_DIR / "forward_test_sample_report.md"
    md_path.write_text(
        render_markdown(trades, stats, signals_list, generated_at, is_sample),
        encoding="utf-8",
    )
    print(f"MD saved  : {md_path.relative_to(ROOT)}")

    print("\nHoan tat!")
    print(f"  Tong lenh  : {stats['total']}")
    print(f"  Win Rate   : {stats['winrate']}%")
    print(f"  PF         : {stats['profit_factor']}")
    print(f"  Expectancy : {stats['expectancy']:+.4f}%")
    print(f"  Total P&L  : {stats['total_pnl']:+.4f}%")


if __name__ == "__main__":
    main()
