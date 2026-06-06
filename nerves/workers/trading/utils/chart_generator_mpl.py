import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import pandas as pd
import matplotlib

# Use non-interactive backend for headless execution
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf

log = logging.getLogger(__name__)


def generate_chart_mpl(
    symbol: str,
    timeframe: str,
    ohlcv_data: Union[List[List[Any]], List[Dict[str, Any]]],
    drawings: Optional[List[Dict[str, Any]]] = None,
    strategy_table: Optional[Dict[str, Any]] = None,
    save_path: Optional[Union[str, Path]] = None,
    parent_timeframe: Optional[str] = None,
    parent_ohlcv: Optional[Union[List[List[Any]], List[Dict[str, Any]]]] = None,
    pattern_overlays: Optional[Any] = None,
) -> Path:
    """
    Renders a candlestick chart locally using mplfinance/matplotlib.

    Parameters:
        symbol: Ticker symbol (e.g., BTCUSDT)
        timeframe: Chart interval (e.g., 1h, 15)
        ohlcv_data: OHLCV candles data.
                    Either list of dicts: [{"time": timestamp, "open": o, ...}]
                    Or list of lists: [[timestamp, open, high, low, close, volume], ...]
        drawings: Optional list of horizontal line drawings:
                  [{"price": 95100.5, "label": "Entry", "color": "#26a69a"}]
        strategy_table: Optional dict for a side/overlay table metrics:
                        {"title": "SEPA Setup", "rows": [("Trend", "Bullish"), ("ATR", "4.2")]}
        save_path: Optional file path to save the PNG image.

    Returns:
        Path object pointing to the generated PNG file.
    """
    if not ohlcv_data:
        raise ValueError("OHLCV data is empty")

    # 1. Standardize and load into Pandas DataFrame
    records = []
    if isinstance(ohlcv_data[0], dict):
        for candle in ohlcv_data:
            # handle both integer timestamp and string ISO date
            t = candle.get("time") or candle.get("timestamp")
            records.append(
                {
                    "Date": pd.to_datetime(
                        t, unit="ms" if isinstance(t, (int, float)) else None
                    ),
                    "Open": float(candle["open"]),
                    "High": float(candle["high"]),
                    "Low": float(candle["low"]),
                    "Close": float(candle["close"]),
                    "Volume": float(candle.get("volume", 0)),
                }
            )
    else:
        for candle in ohlcv_data:
            t = candle[0]
            records.append(
                {
                    "Date": pd.to_datetime(
                        t, unit="ms" if isinstance(t, (int, float)) else None
                    ),
                    "Open": float(candle[1]),
                    "High": float(candle[2]),
                    "Low": float(candle[3]),
                    "Close": float(candle[4]),
                    "Volume": float(candle[5]) if len(candle) > 5 else 0.0,
                }
            )

    df = pd.DataFrame(records)
    df.set_index("Date", inplace=True)
    df.sort_index(inplace=True)

    # 2. Design the Custom Dark Theme (TradingView theme)
    # Background: #131722
    # Grid: #2a2e39
    # Candles: Green #26a69a, Red #ef5350
    mc = mpf.make_marketcolors(
        up="#26a69a",
        down="#ef5350",
        edge="inherit",
        wick="inherit",
        volume="#26a69a",
        inherit=True,
    )

    style = mpf.make_mpf_style(
        base_mpf_style="charles",
        marketcolors=mc,
        gridcolor="#2a2e39",
        gridstyle="--",
        facecolor="#131722",
        figcolor="#131722",
    )

    # 3. Setup the plot parameters
    # Increase right padding to fit price labels nicely
    plot_kwargs = {
        "type": "candle",
        "style": style,
        "volume": True,
        "figsize": (12, 7),
        "returnfig": True,
        "tight_layout": False,
    }

    # Render moving averages automatically if enough candles
    add_plots = []
    if len(df) >= 20:
        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        add_plots.append(mpf.make_addplot(df["EMA20"], color="#2962ff", width=1.0))
    if len(df) >= 50:
        df["SMA50"] = df["Close"].rolling(window=50).mean()
        add_plots.append(mpf.make_addplot(df["SMA50"], color="#ff9800", width=1.0))

    if add_plots:
        plot_kwargs["addplot"] = add_plots

    # 4. Generate the plot
    fig, axlist = mpf.plot(df, **plot_kwargs)

    main_ax = axlist[0]
    # Set text colors to light grey
    main_ax.tick_params(colors="#b2b5be")
    main_ax.yaxis.label.set_color("#b2b5be")
    main_ax.xaxis.label.set_color("#b2b5be")

    # Title overlay
    title_text = f"{symbol} {timeframe}"
    main_ax.text(
        0.02,
        0.95,
        title_text,
        transform=main_ax.transAxes,
        color="#ffffff",
        fontsize=16,
        fontweight="bold",
        va="top",
    )

    # Adjust margins to leave room for price flags on the right
    fig.subplots_adjust(right=0.88, left=0.08, top=0.92, bottom=0.08)

    # 5. Render custom drawings (Entry, Stop Loss, Take Profit lines)
    if drawings:
        xlim = main_ax.get_xlim()
        for draw in drawings:
            price = float(draw.get("price", 0))
            if price <= 0:
                continue
            label = draw.get("label", "")
            color = draw.get("color", "#2962ff")

            # Plot the horizontal line
            main_ax.axhline(
                y=price, color=color, linestyle="--", linewidth=1.5, alpha=0.85
            )

            # Plot the text label in a nice box at the right edge
            main_ax.text(
                xlim[1] * 1.002,
                price,
                f"  {label}: {price:.2f}",
                color="#ffffff",
                va="center",
                ha="left",
                fontsize=8,
                fontweight="bold",
                bbox=dict(
                    facecolor=color,
                    edgecolor=color,
                    boxstyle="round,pad=0.2",
                    alpha=0.9,
                ),
            )

    # 6. Render the Strategy Table (SEPA metrics/parameters)
    if strategy_table:
        table_title = strategy_table.get("title", "Strategy Specs")
        rows = strategy_table.get("rows", [])

        if rows:
            # Build table text lines
            text_lines = [f"■ {table_title.upper()}"]
            for k, v in rows:
                text_lines.append(f"  • {k}: {v}")
            table_text = "\n".join(text_lines)

            # Position box in the top-right corner of the plot
            main_ax.text(
                0.98,
                0.95,
                table_text,
                transform=main_ax.transAxes,
                color="#b2b5be",
                fontsize=9,
                fontfamily="monospace",
                va="top",
                ha="right",
                bbox=dict(
                    facecolor="#1e222d",
                    edgecolor="#2a2e39",
                    boxstyle="round,pad=0.5",
                    alpha=0.85,
                ),
            )

    # 6b. Render Pattern Overlays (VCP, Cup&Handle, Double Bottom)
    if pattern_overlays:
        try:
            from utils.pattern_overlay import (
                VCPOverlay,
                CupHandleOverlay,
                DoubleBottomOverlay,
                PatternOverlayResult,
            )

            overlays = pattern_overlays
            if isinstance(overlays, PatternOverlayResult):
                overlays = overlays  # already a result object

            # ── VCP Overlay: contraction waves ──
            vcp = getattr(overlays, "vcp", None)
            if (
                vcp
                and isinstance(vcp, VCPOverlay)
                and vcp.detected
                and vcp.contractions
            ):
                # Draw descending pivot highs line
                pivot_xs = [c.pivot_high_idx for c in vcp.contractions]
                pivot_ys = [c.pivot_high_price for c in vcp.contractions]

                if pivot_xs and all(x < len(df) for x in pivot_xs):
                    main_ax.plot(
                        pivot_xs,
                        pivot_ys,
                        color="#ff9800",
                        linestyle="--",
                        linewidth=1.5,
                        alpha=0.8,
                        marker="v",
                        markersize=6,
                        label="VCP Pivots",
                    )

                    # Label each contraction depth
                    for c in vcp.contractions:
                        if c.trough_idx < len(df):
                            main_ax.annotate(
                                f"-{c.depth_pct:.0f}%",
                                xy=(c.trough_idx, c.trough_price),
                                xytext=(c.trough_idx + 2, c.trough_price * 0.997),
                                color="#ff9800",
                                fontsize=7,
                                fontweight="bold",
                                arrowprops=dict(
                                    arrowstyle="->", color="#ff9800", lw=0.8
                                ),
                            )

                    # Pivot breakout line
                    if vcp.pivot_line_price > 0:
                        main_ax.axhline(
                            y=vcp.pivot_line_price,
                            color="#ff9800",
                            linestyle=":",
                            linewidth=1.0,
                            alpha=0.6,
                        )
                        xlim = main_ax.get_xlim()
                        main_ax.text(
                            xlim[0] + 1,
                            vcp.pivot_line_price * 1.002,
                            f"VCP Pivot {vcp.pivot_line_price:.2f} (Q={vcp.quality_score:.0f})",
                            color="#ff9800",
                            fontsize=7,
                            fontweight="bold",
                            bbox=dict(
                                facecolor="#131722",
                                edgecolor="#ff9800",
                                boxstyle="round,pad=0.2",
                                alpha=0.8,
                            ),
                        )

            # ── Cup & Handle Overlay ──
            cup = getattr(overlays, "cup_handle", None)
            if cup and isinstance(cup, CupHandleOverlay) and cup.detected:
                # Draw cup arc (simplified: line from left rim → bottom → right rim)
                cup_points_x = [cup.cup_start_idx, cup.cup_bottom_idx, cup.cup_end_idx]
                closes_list = (
                    _extract_closes(ohlcv_data)  # noqa: F821
                    if callable(globals().get("_extract_closes", None))
                    else []
                )
                if closes_list and all(x < len(closes_list) for x in cup_points_x):
                    cup_points_y = [closes_list[x] for x in cup_points_x]
                    main_ax.plot(
                        cup_points_x,
                        cup_points_y,
                        color="#4caf50",
                        linestyle="-",
                        linewidth=2.0,
                        alpha=0.6,
                        marker="o",
                        markersize=4,
                    )

                # Neckline
                if cup.neckline_price > 0:
                    main_ax.axhline(
                        y=cup.neckline_price,
                        color="#4caf50",
                        linestyle=":",
                        linewidth=1.0,
                        alpha=0.5,
                    )

            # ── Double Bottom Overlay ──
            db = getattr(overlays, "double_bottom", None)
            if db and isinstance(db, DoubleBottomOverlay) and db.detected:
                # Mark the two bottoms
                for bx, by, label in [
                    (db.first_bottom_idx, db.first_bottom_price, "B1"),
                    (db.second_bottom_idx, db.second_bottom_price, "B2"),
                ]:
                    if bx < len(df):
                        main_ax.plot(
                            bx, by, marker="^", color="#2196f3", markersize=10, zorder=5
                        )
                        main_ax.annotate(
                            label,
                            xy=(bx, by),
                            xytext=(bx + 1, by * 0.998),
                            color="#2196f3",
                            fontsize=8,
                            fontweight="bold",
                        )

                # Neckline
                if db.neckline_price > 0:
                    main_ax.axhline(
                        y=db.neckline_price,
                        color="#2196f3",
                        linestyle="--",
                        linewidth=1.0,
                        alpha=0.6,
                    )
                    xlim = main_ax.get_xlim()
                    main_ax.text(
                        xlim[0] + 1,
                        db.neckline_price * 1.001,
                        f"Neckline {db.neckline_price:.2f}",
                        color="#2196f3",
                        fontsize=7,
                        bbox=dict(
                            facecolor="#131722",
                            edgecolor="#2196f3",
                            boxstyle="round,pad=0.2",
                            alpha=0.8,
                        ),
                    )
        except Exception as overlay_err:
            log.warning(f"Pattern overlay rendering failed (non-fatal): {overlay_err}")
    # 7. Save output
    if not save_path:
        # Default save path under worker's screenshots folder
        base_dir = Path(__file__).resolve().parent.parent
        screenshots_dir = base_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        save_path = screenshots_dir / f"chart_{symbol}_{timeframe}.png"
    else:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

    plt.savefig(save_path, facecolor="#131722", edgecolor="none", dpi=150)
    plt.close(fig)

    log.info(f"Successfully generated local matplotlib chart at {save_path}")
    return save_path
