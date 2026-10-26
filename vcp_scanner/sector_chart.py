"""Per-sector PNG chart: candles + 50/150/200 MA + shaded VCP contraction
boxes + pivot line + volume (dry-up highlighted) + RS-line subpanel.

Plain matplotlib (Agg, headless), same pattern as scripts/plot_double_sweep.py,
with a dark theme. Reuses indicators.add_moving_averages and the VCPAnalysis
already computed by sector_scan.scan_sectors -- no chart-time recomputation
of MAs, contractions, or RS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

import pandas as pd  # noqa: E402

from .indicators import add_moving_averages  # noqa: E402
from .sector_rs import rs_line as compute_rs_line  # noqa: E402
from .sector_universe import ETF_LABELS  # noqa: E402
from .trend_template import TrendTemplateResult  # noqa: E402
from .vcp import VCPAnalysis  # noqa: E402

# GitHub-dark-ish palette.
_BG = "#0d1117"
_PANEL_BG = "#0d1117"
_GRID = "#21262d"
_TEXT = "#c9d1d9"
_TEXT_DIM = "#8b949e"
_UP = "#3fb950"
_DOWN = "#f85149"
_MA50 = "#58a6ff"
_MA150 = "#d29922"
_MA200 = "#bc8cff"
_PIVOT = "#e6edf3"
_BOX = "#58a6ff"
_DRYUP = "#2ea04344"  # translucent green-ish for the volume dry-up highlight


def _style_axis(ax) -> None:
    ax.set_facecolor(_PANEL_BG)
    ax.tick_params(colors=_TEXT_DIM, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(_GRID)
    ax.grid(True, color=_GRID, linewidth=0.6, alpha=0.6)
    ax.yaxis.label.set_color(_TEXT_DIM)


def plot_sector(
    ticker: str,
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    vcp: VCPAnalysis,
    trend: TrendTemplateResult,
    rs_score: float,
    rs_rank: int,
    status: str,
    out_path: Path,
    plot_bars: int = 190,
) -> None:
    data = add_moving_averages(df)
    window = data.tail(plot_bars)
    offset = len(data) - len(window)

    fig = plt.figure(figsize=(13, 9), facecolor=_BG, layout="constrained")
    gs = fig.add_gridspec(3, 1, height_ratios=[3, 1, 1], hspace=0.08)
    ax = fig.add_subplot(gs[0])
    vol_ax = fig.add_subplot(gs[1], sharex=ax)
    rs_ax = fig.add_subplot(gs[2], sharex=ax)

    for a in (ax, vol_ax, rs_ax):
        _style_axis(a)

    xs = range(len(window))
    for x, (_, row) in zip(xs, window.iterrows()):
        color = _UP if row["Close"] >= row["Open"] else _DOWN
        ax.vlines(x, row["Low"], row["High"], color=color, linewidth=1)
        ax.hlines(row["Close"], x - 0.3, x, color=color, linewidth=1.5)
        vol_ax.bar(x, row["Volume"], color=color, width=0.8, alpha=0.7)

    if window["SMA50"].notna().any():
        ax.plot(xs, window["SMA50"], color=_MA50, linewidth=1.1, label="50 MA")
    if window["SMA150"].notna().any():
        ax.plot(xs, window["SMA150"], color=_MA150, linewidth=1.1, label="150 MA")
    if window["SMA200"].notna().any():
        ax.plot(xs, window["SMA200"], color=_MA200, linewidth=1.1, label="200 MA")

    def to_plot_x(date) -> Optional[float]:
        pos = data.index.searchsorted(date) - offset
        return float(pos) if 0 <= pos < len(window) else None

    for hi_date, hi_price, lo_date, lo_price in vcp.contraction_legs:
        x0, x1 = to_plot_x(hi_date), to_plot_x(lo_date)
        if x0 is None or x1 is None:
            continue
        left, right = min(x0, x1), max(x0, x1)
        depth_pct = (hi_price - lo_price) / hi_price * 100.0 if hi_price > 0 else 0.0
        ax.add_patch(
            Rectangle(
                (left, lo_price), right - left, hi_price - lo_price,
                facecolor=_BOX, alpha=0.15, edgecolor=_BOX, linewidth=0.8, zorder=2,
            )
        )
        ax.annotate(
            f"-{depth_pct:.1f}%", ((left + right) / 2, hi_price), textcoords="offset points",
            xytext=(0, 4), ha="center", fontsize=8, color=_BOX,
        )

    if vcp.pivot_price:
        ax.axhline(vcp.pivot_price, color=_PIVOT, linewidth=1.2, linestyle="--", label=f"pivot {vcp.pivot_price:.2f}")

    dryup_days = 10
    if len(window) > dryup_days:
        vol_ax.axvspan(
            len(window) - dryup_days, len(window) - 1, color=_DRYUP, zorder=0,
            label="dry-up window" if vcp.volume_dryup_ratio and vcp.volume_dryup_ratio < 1.0 else None,
        )

    rs_series = compute_rs_line(df, benchmark_df)
    rs_window = rs_series.tail(plot_bars)
    if not rs_window.empty:
        rs_xs = range(len(rs_window))
        rs_ax.plot(rs_xs, rs_window.to_numpy(), color=_MA50, linewidth=1.2)
        rs_ax.set_ylabel("RS vs SPY", fontsize=9)
    else:
        rs_ax.text(0.5, 0.5, "RS line unavailable", color=_TEXT_DIM, ha="center", va="center", transform=rs_ax.transAxes)

    sector_name = ETF_LABELS.get(ticker, ticker)
    title = f"{ticker} — {sector_name}  ·  RS rank #{rs_rank} (score {rs_score:+.1f})  ·  {status}"
    ax.set_title(title, color=_TEXT, fontsize=12, loc="left")
    ax.set_ylabel("Price", fontsize=9)
    vol_ax.set_ylabel("Volume", fontsize=9)
    legend = ax.legend(loc="upper left", fontsize=8, facecolor=_PANEL_BG, edgecolor=_GRID, labelcolor=_TEXT)
    if legend:
        legend.get_frame().set_alpha(0.8)
    vol_legend_handles, vol_legend_labels = vol_ax.get_legend_handles_labels()
    if vol_legend_labels:
        vleg = vol_ax.legend(loc="upper left", fontsize=7, facecolor=_PANEL_BG, edgecolor=_GRID, labelcolor=_TEXT)
        vleg.get_frame().set_alpha(0.8)

    tick_step = max(len(window) // 10, 1)
    tick_positions = list(range(0, len(window), tick_step))
    tick_labels = [window.index[i].strftime("%Y-%m-%d") for i in tick_positions]
    rs_ax.set_xticks(tick_positions)
    rs_ax.set_xticklabels(tick_labels, rotation=45, ha="right", fontsize=8, color=_TEXT_DIM)
    plt.setp(ax.get_xticklabels(), visible=False)
    plt.setp(vol_ax.get_xticklabels(), visible=False)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, facecolor=_BG)
    plt.close(fig)
