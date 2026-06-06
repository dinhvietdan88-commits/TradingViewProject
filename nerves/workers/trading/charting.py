"""
charting.py — Backtest & Performance Chart Generator for Telegram.

Generates multi-panel PNG charts from trade history data using matplotlib.
Returns BytesIO objects ready to be sent via bot.send_photo().

Charts produced:
  - generate_backtest_chart()  : 3-panel equity + drawdown + per-trade PnL
  - generate_mode_chart()      : MTT vs MIS win-rate & PnL comparison bar chart

Design:
  - Dark theme (#1a1a2e / #16213e) matching Minervini strategy aesthetic
  - No external deps beyond matplotlib (already installed)
  - All functions are synchronous (wrap in asyncio.to_thread for async callers)
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List, Optional

import matplotlib

matplotlib.use("Agg")  # Non-interactive backend — safe for server threads
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec


# ── Design Tokens ─────────────────────────────────────────────────────────────
BG_DARK = "#0f0f1a"
BG_PANEL = "#1a1a2e"
BG_CARD = "#16213e"
ACCENT_CYAN = "#00d4ff"
ACCENT_GOLD = "#ffd700"
GREEN = "#00e676"
RED = "#ff1744"
GREY_DIM = "#4a4a6a"
TEXT_MAIN = "#e0e0ff"
TEXT_DIM = "#8888aa"
GRID_COLOR = "#2a2a4a"


def _apply_dark_theme(fig, axes):
    """Apply consistent dark theme to figure and all axes."""
    fig.patch.set_facecolor(BG_DARK)
    for ax in axes:
        ax.set_facecolor(BG_PANEL)
        ax.tick_params(colors=TEXT_DIM, labelsize=8)
        ax.xaxis.label.set_color(TEXT_DIM)
        ax.yaxis.label.set_color(TEXT_DIM)
        for spine in ax.spines.values():
            spine.set_color(GRID_COLOR)
        ax.grid(True, color=GRID_COLOR, linewidth=0.5, alpha=0.7)


def _fmt_date(ts: str) -> str:
    """Parse ISO datetime string to short MM/DD label."""
    try:
        return datetime.fromisoformat(ts[:10]).strftime("%m/%d")
    except Exception:
        return ts[:5]


# ── Main Backtest Chart ────────────────────────────────────────────────────────


def generate_backtest_chart(
    equity_data: Dict[str, Any],
    title: str = "Backtest Performance",
    symbol: Optional[str] = None,
) -> io.BytesIO:
    """Generate a 3-panel backtest chart.

    Args:
        equity_data: Output of get_equity_curve() — keys: labels, cumulative_pnl,
                     drawdown_pct, trades.
        title:       Chart title (shown at top).
        symbol:      Optional symbol filter label.

    Returns:
        BytesIO PNG image, seeked to position 0, ready for bot.send_photo().
    """
    labels = equity_data.get("labels", [])
    cum_pnl = equity_data.get("cumulative_pnl", [])
    drawdown = equity_data.get("drawdown_pct", [])
    trades = equity_data.get("trades", [])

    n = len(labels)
    if n == 0:
        return _no_data_chart(title)

    # ── X axis: use integer indices, set date labels manually ─────────────────
    x = list(range(n))
    date_labels = [_fmt_date(str(l)) for l in labels]  # noqa: E741

    # ── Per-trade PnL bar colors ───────────────────────────────────────────────
    pnl_values = [t["pnl"] for t in trades]
    bar_colors = [GREEN if p > 0 else RED for p in pnl_values]

    # ── Figure layout ─────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(12, 8), dpi=110)
    gs = GridSpec(3, 1, figure=fig, hspace=0.45, height_ratios=[3, 1.5, 1.5])

    ax_equity = fig.add_subplot(gs[0])
    ax_dd = fig.add_subplot(gs[1])
    ax_pnl_bar = fig.add_subplot(gs[2])

    _apply_dark_theme(fig, [ax_equity, ax_dd, ax_pnl_bar])

    # ── Panel 1: Equity Curve ─────────────────────────────────────────────────
    ax_equity.plot(x, cum_pnl, color=ACCENT_CYAN, linewidth=2, zorder=3, label="Equity")
    ax_equity.fill_between(
        x,
        0,
        cum_pnl,
        where=[v >= 0 for v in cum_pnl],
        alpha=0.15,
        color=GREEN,
        interpolate=True,
    )
    ax_equity.fill_between(
        x,
        0,
        cum_pnl,
        where=[v < 0 for v in cum_pnl],
        alpha=0.15,
        color=RED,
        interpolate=True,
    )
    ax_equity.axhline(0, color=GREY_DIM, linewidth=0.8, linestyle="--", alpha=0.6)

    # Annotate final PnL
    final = cum_pnl[-1]
    final_color = GREEN if final >= 0 else RED
    ax_equity.annotate(
        f"  ${final:+,.2f}",
        xy=(x[-1], final),
        color=final_color,
        fontsize=9,
        fontweight="bold",
        va="center",
    )

    # Peak marker
    peak_idx = cum_pnl.index(max(cum_pnl))
    ax_equity.scatter(
        [x[peak_idx]],
        [cum_pnl[peak_idx]],
        color=ACCENT_GOLD,
        s=60,
        zorder=5,
        marker="^",
    )
    ax_equity.annotate(
        f"Peak ${cum_pnl[peak_idx]:+,.2f}",
        xy=(x[peak_idx], cum_pnl[peak_idx]),
        xytext=(5, 8),
        textcoords="offset points",
        color=ACCENT_GOLD,
        fontsize=7.5,
    )

    ax_equity.set_ylabel("Cumulative P&L ($)", fontsize=8)
    ax_equity.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"${v:,.0f}")
    )

    # ── Panel 2: Drawdown ─────────────────────────────────────────────────────
    ax_dd.fill_between(x, 0, [-d for d in drawdown], color=RED, alpha=0.5)
    ax_dd.plot(x, [-d for d in drawdown], color=RED, linewidth=1)
    ax_dd.axhline(0, color=GREY_DIM, linewidth=0.5, linestyle="--", alpha=0.5)

    max_dd = max(drawdown) if drawdown else 0
    if max_dd > 0:
        dd_idx = drawdown.index(max_dd)
        ax_dd.annotate(
            f"Max DD: {max_dd:.1f}%",
            xy=(x[dd_idx], -max_dd),
            xytext=(5, -12),
            textcoords="offset points",
            color=RED,
            fontsize=7.5,
        )

    ax_dd.set_ylabel("Drawdown (%)", fontsize=8)
    ax_dd.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.1f}%"))

    # ── Panel 3: Per-Trade PnL Bars ───────────────────────────────────────────
    ax_pnl_bar.bar(x, pnl_values, color=bar_colors, alpha=0.85, width=0.7)
    ax_pnl_bar.axhline(0, color=GREY_DIM, linewidth=0.5, linestyle="--", alpha=0.6)
    ax_pnl_bar.set_ylabel("Trade P&L ($)", fontsize=8)
    ax_pnl_bar.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"${v:,.0f}")
    )

    # ── X-axis ticks (shared, show on bottom panel only) ─────────────────────
    tick_step = max(1, n // 12)
    tick_idx = x[::tick_step]
    tick_lbl = date_labels[::tick_step]
    for ax in [ax_equity, ax_dd]:
        ax.set_xticks([])
    ax_pnl_bar.set_xticks(tick_idx)
    ax_pnl_bar.set_xticklabels(tick_lbl, rotation=30, ha="right", fontsize=7)

    # ── Stats summary bar at top ───────────────────────────────────────────────
    wins = sum(1 for p in pnl_values if p > 0)
    losses = sum(1 for p in pnl_values if p <= 0)
    wr = wins / n * 100 if n > 0 else 0
    total_win = sum(p for p in pnl_values if p > 0)
    total_loss = abs(sum(p for p in pnl_values if p <= 0))
    pf = total_win / total_loss if total_loss > 0 else float("inf")
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"

    sym_label = f" [{symbol}]" if symbol else ""
    subtitle = (
        f"Trades: {n}  |  Win: {wins}  Loss: {losses}  |  "
        f"Win Rate: {wr:.1f}%  |  PF: {pf_str}  |  "
        f"Net P&L: ${final:+,.2f}"
    )

    fig.suptitle(
        f"{title}{sym_label}",
        color=TEXT_MAIN,
        fontsize=13,
        fontweight="bold",
        y=0.97,
    )
    fig.text(
        0.5,
        0.935,
        subtitle,
        ha="center",
        color=TEXT_DIM,
        fontsize=8.5,
    )

    # ── Legend patches ────────────────────────────────────────────────────────
    ax_equity.legend(
        handles=[
            mpatches.Patch(color=ACCENT_CYAN, label="Equity Curve"),
            mpatches.Patch(color=ACCENT_GOLD, label="Peak"),
        ],
        loc="upper left",
        fontsize=7.5,
        facecolor=BG_CARD,
        edgecolor=GRID_COLOR,
        labelcolor=TEXT_DIM,
    )

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", facecolor=BG_DARK, dpi=110)
    plt.close(fig)
    buf.seek(0)
    return buf


# ── Mode Comparison Chart ─────────────────────────────────────────────────────


def generate_mode_chart(stats_by_mode: Dict[str, Any]) -> io.BytesIO:
    """Generate a 2-panel MTT vs MIS bar comparison chart.

    Args:
        stats_by_mode: Output of get_stats_by_mode() — keys: overall, by_mode.

    Returns:
        BytesIO PNG image.
    """
    by_mode = stats_by_mode.get("by_mode", {})
    overall = stats_by_mode.get("overall", {})

    modes = ["MTT", "MIS", "OVERALL"]
    labels_display = ["[MTT]\nDaily Trend", "[MIS]\n1H Momentum", "Overall"]

    def _get(mode_key, field):
        if mode_key == "OVERALL":
            return overall.get(field, 0)
        return by_mode.get(mode_key, {}).get(field, 0)

    win_rates = [_get(m, "win_rate") for m in modes]
    pnls = [_get(m, "total_pnl") for m in modes]
    pf_vals = [_get(m, "profit_factor") for m in modes]
    pf_vals = [
        min(v, 10) if v != float("inf") else 10 for v in pf_vals
    ]  # cap ∞ at 10 for display
    trade_cnt = [_get(m, "total_trades") for m in modes]

    fig, (ax_wr, ax_pnl) = plt.subplots(1, 2, figsize=(11, 5), dpi=110)
    _apply_dark_theme(fig, [ax_wr, ax_pnl])

    x = [0, 1, 2]
    width = 0.55
    colors = [ACCENT_CYAN, ACCENT_GOLD, GREY_DIM]

    # ── Panel 1: Win Rate bars ────────────────────────────────────────────────
    bars = ax_wr.bar(x, win_rates, width=width, color=colors, alpha=0.85)
    ax_wr.axhline(50, color=GREY_DIM, linestyle="--", linewidth=0.8, alpha=0.6)
    ax_wr.set_ylabel("Win Rate (%)", fontsize=9, color=TEXT_DIM)
    ax_wr.set_xticks(x)
    ax_wr.set_xticklabels(labels_display, fontsize=8.5, color=TEXT_MAIN)
    ax_wr.set_ylim(0, 110)
    ax_wr.set_title("Win Rate & Profit Factor", color=TEXT_MAIN, fontsize=10, pad=8)

    for bar, wr, pf, cnt in zip(bars, win_rates, pf_vals, trade_cnt, strict=False):
        ax_wr.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 2,
            f"{wr:.1f}%\nPF: {pf:.2f}\n({cnt}T)",
            ha="center",
            va="bottom",
            fontsize=8,
            color=TEXT_MAIN,
            fontweight="bold",
        )

    # ── Panel 2: PnL bars ────────────────────────────────────────────────────
    pnl_colors = [GREEN if p >= 0 else RED for p in pnls]
    bars2 = ax_pnl.bar(x, pnls, width=width, color=pnl_colors, alpha=0.85)
    ax_pnl.axhline(0, color=GREY_DIM, linestyle="--", linewidth=0.8, alpha=0.6)
    ax_pnl.set_ylabel("Net P&L ($)", fontsize=9, color=TEXT_DIM)
    ax_pnl.set_xticks(x)
    ax_pnl.set_xticklabels(labels_display, fontsize=8.5, color=TEXT_MAIN)
    ax_pnl.set_title("Net P&L by Mode", color=TEXT_MAIN, fontsize=10, pad=8)
    ax_pnl.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))

    for bar, pnl in zip(bars2, pnls, strict=False):
        offset = 0.5 if pnl >= 0 else -2
        ax_pnl.text(
            bar.get_x() + bar.get_width() / 2,
            pnl + offset,
            f"${pnl:+,.2f}",
            ha="center",
            va="bottom" if pnl >= 0 else "top",
            fontsize=8.5,
            color=TEXT_MAIN,
            fontweight="bold",
        )

    fig.suptitle(
        "Strategy Mode Comparison  MTT vs MIS",
        color=TEXT_MAIN,
        fontsize=12,
        fontweight="bold",
        y=1.01,
    )
    fig.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", facecolor=BG_DARK, dpi=110)
    plt.close(fig)
    buf.seek(0)
    return buf


# ── Fallback: No Data Chart ───────────────────────────────────────────────────


def _no_data_chart(title: str) -> io.BytesIO:
    """Return a minimal 'No Data' placeholder image."""
    fig, ax = plt.subplots(figsize=(8, 3), dpi=100)
    fig.patch.set_facecolor(BG_DARK)
    ax.set_facecolor(BG_PANEL)
    ax.text(
        0.5,
        0.5,
        f"📭  Chưa có dữ liệu giao dịch\n({title})",
        ha="center",
        va="center",
        transform=ax.transAxes,
        color=TEXT_DIM,
        fontsize=12,
    )
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", facecolor=BG_DARK, dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf


# ── Trade History Table Chart ─────────────────────────────────────────────────


def generate_history_chart(
    recent_trades: List[Dict[str, Any]],
    title: str = "Trade History (Last 10)",
) -> io.BytesIO:
    """Generate a styled table PNG of recent trade history.

    Args:
        recent_trades: List of dicts from get_recent_trades().
                       Each dict: id, created_at, symbol, side, mode,
                                  executed_price, stop_loss_price,
                                  take_profit_price, pnl
        title:         Chart title string.

    Returns:
        BytesIO PNG.
    """
    if not recent_trades:
        return _no_data_chart(title)

    # ── Build table data ───────────────────────────────────────────────────────
    headers = ["#", "Date", "Symbol", "Mode", "Side", "Entry", "SL", "TP", "P&L"]
    rows_data = []
    pnl_vals = []

    for t in recent_trades:
        date = _fmt_date(str(t.get("created_at", "")))
        sym = str(t.get("symbol", ""))[:8]
        mode = str(t.get("mode", ""))[:4]
        side = str(t.get("side", ""))[:4].upper()
        entry = t.get("executed_price") or 0
        sl = t.get("stop_loss_price") or 0
        tp = t.get("take_profit_price") or 0
        pnl = t.get("pnl") or 0
        tid = t.get("id", "")
        pnl_vals.append(pnl)

        rows_data.append(
            [
                f"#{tid}",
                date,
                sym,
                mode,
                side,
                f"${entry:,.2f}" if entry else "--",
                f"${sl:,.2f}" if sl else "--",
                f"${tp:,.2f}" if tp else "--",
                f"${pnl:+,.2f}",
            ]
        )

    n_rows = len(rows_data)
    fig_h = max(3.5, 0.45 * (n_rows + 2))
    fig, ax = plt.subplots(figsize=(13, fig_h), dpi=110)
    fig.patch.set_facecolor(BG_DARK)
    ax.set_facecolor(BG_DARK)
    ax.set_axis_off()

    # ── Draw table ────────────────────────────────────────────────────────────
    col_widths = [0.05, 0.07, 0.10, 0.07, 0.06, 0.12, 0.12, 0.12, 0.11]
    tbl = ax.table(
        cellText=rows_data,
        colLabels=headers,
        cellLoc="center",
        loc="center",
        colWidths=col_widths,
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1, 1.5)

    # Style header row
    for col_idx in range(len(headers)):
        cell = tbl[0, col_idx]
        cell.set_facecolor(BG_CARD)
        cell.set_text_props(color=ACCENT_CYAN, fontweight="bold")
        cell.set_edgecolor(GRID_COLOR)

    # Style data rows
    for row_idx, pnl in enumerate(pnl_vals, start=1):
        for col_idx in range(len(headers)):
            cell = tbl[row_idx, col_idx]
            cell.set_facecolor("#1e1e35" if row_idx % 2 == 0 else BG_PANEL)
            cell.set_edgecolor(GRID_COLOR)
            if col_idx == len(headers) - 1:  # P&L column
                cell.set_text_props(
                    color=GREEN if pnl > 0 else RED,
                    fontweight="bold",
                )
            else:
                cell.set_text_props(color=TEXT_MAIN)

    # ── Title & subtitle ──────────────────────────────────────────────────────
    total_pnl = sum(pnl_vals)
    wins = sum(1 for p in pnl_vals if p > 0)
    net_color = GREEN if total_pnl >= 0 else RED
    subtitle = f"Last {n_rows} trades  |  {wins}W/{n_rows - wins}L  |  Net P&L: ${total_pnl:+,.2f}"

    ax.set_title(title, color=TEXT_MAIN, fontsize=11, fontweight="bold", pad=18)
    ax.text(
        0.5,
        1.02,
        subtitle,
        ha="center",
        va="bottom",
        transform=ax.transAxes,
        color=net_color,
        fontsize=8.5,
    )

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", facecolor=BG_DARK, dpi=110)
    plt.close(fig)
    buf.seek(0)
    return buf
