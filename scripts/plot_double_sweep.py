#!/usr/bin/env python3
"""Debug tool: plot a ticker's chart with Double-Sweep Base detections marked.

Draws a simple OHLC bar chart (high-low wick + close tick) with:
  - the base's range_high / range_low as dashed horizontal lines
  - the high-sweep and low-sweep bars marked and dated
  - the pivot (= range_high) and suggested stop as solid/dotted lines
  - a volume panel underneath

Usage:
    python scripts/plot_double_sweep.py TICKER [--period 1y] [--out PATH.png]
    python scripts/plot_double_sweep.py CLSK WULF FRO FANG --period 1y --out-dir ./charts

Always saves a PNG (this runs in headless environments) and prints a text
summary of what was found either way, whether the pattern matched or not.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vcp_scanner.data import fetch_history  # noqa: E402
from vcp_scanner.double_sweep import DoubleSweepConfig, DoubleSweepResult, analyze_double_sweep  # noqa: E402


def print_summary(result: DoubleSweepResult) -> None:
    print(f"\n=== {result.ticker} ===")
    print(f"matched: {result.matched}")
    if not result.matched:
        print(f"reason:  {result.reason}")
    if result.base:
        print(
            f"base:    range_high={result.base.range_high:.2f}  "
            f"range_low={result.base.range_low:.2f}  depth={result.base.depth_pct:.1f}%"
        )
    if result.high_sweep:
        hs = result.high_sweep
        print(
            f"high sweep: {hs.date.date()}  level={hs.level:.2f}  extreme={hs.extreme:.2f}  "
            f"reclaim_bars={hs.reclaim_bars}  vol_ratio={hs.volume_ratio:.2f}  "
            f"wick_quality={hs.wick_quality:.2f}  quality_score={hs.quality_score:.1f}"
        )
    if result.low_sweep:
        ls = result.low_sweep
        print(
            f"low sweep:  {ls.date.date()}  level={ls.level:.2f}  extreme={ls.extreme:.2f}  "
            f"reclaim_bars={ls.reclaim_bars}  vol_ratio={ls.volume_ratio:.2f}  "
            f"wick_quality={ls.wick_quality:.2f}  quality_score={ls.quality_score:.1f}"
        )
    if result.contraction:
        c = result.contraction
        print(
            f"contraction: legs={c.legs_pct}  shrinking={c.shrinking}  "
            f"final={c.final_contraction_pct}  atr_declining={c.atr_declining}  "
            f"vol_dryup_ratio={c.volume_dryup_ratio}"
        )
    if result.matched:
        print(
            f"pivot={result.pivot_price:.2f}  stop={result.stop_price:.2f}  "
            f"distance_to_pivot={result.distance_to_pivot_pct:.1f}%  score={result.score:.1f}"
        )


def plot(ticker: str, df, result: DoubleSweepResult, out_path: Path, plot_bars: int = 260) -> None:
    window = df.tail(plot_bars)
    offset = len(df) - len(window)

    fig, (ax, vol_ax) = plt.subplots(
        2, 1, figsize=(13, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )

    xs = range(len(window))
    for x, (_, row) in zip(xs, window.iterrows()):
        color = "#3c7a56" if row["Close"] >= row["Open"] else "#a84a34"
        ax.vlines(x, row["Low"], row["High"], color=color, linewidth=1)
        ax.hlines(row["Close"], x - 0.3, x, color=color, linewidth=1.5)
        vol_ax.bar(x, row["Volume"], color=color, width=0.8, alpha=0.6)

    def to_plot_x(abs_idx: int) -> float:
        return abs_idx - offset

    if result.base:
        ax.axhline(result.base.range_high, color="#7c5219", linestyle="--", linewidth=1, label="range_high")
        ax.axhline(result.base.range_low, color="#7c5219", linestyle="--", linewidth=1, label="range_low")

    if result.high_sweep:
        hx = to_plot_x(result.high_sweep.index)
        if 0 <= hx < len(window):
            ax.scatter([hx], [result.high_sweep.extreme], marker="v", color="#a84a34", s=90, zorder=5)
            ax.annotate(
                "HIGH SWEEP",
                (hx, result.high_sweep.extreme),
                textcoords="offset points",
                xytext=(0, 12),
                ha="center",
                fontsize=8,
                color="#a84a34",
                zorder=6,
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none", alpha=0.85),
            )

    if result.low_sweep:
        lx = to_plot_x(result.low_sweep.index)
        if 0 <= lx < len(window):
            ax.scatter([lx], [result.low_sweep.extreme], marker="^", color="#3c7a56", s=90, zorder=5)
            ax.annotate(
                "LOW SWEEP",
                (lx, result.low_sweep.extreme),
                textcoords="offset points",
                xytext=(0, -16),
                ha="center",
                fontsize=8,
                color="#3c7a56",
                zorder=6,
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none", alpha=0.85),
            )

    if result.matched:
        ax.axhline(result.pivot_price, color="#1a2420", linewidth=1.5, label=f"pivot {result.pivot_price:.2f}")
        ax.axhline(
            result.stop_price, color="#a84a34", linestyle=":", linewidth=1.5, label=f"stop {result.stop_price:.2f}"
        )

    status = "MATCHED" if result.matched else f"no match ({result.reason})"
    score_str = f"  score={result.score:.1f}" if result.matched else ""
    ax.set_title(f"{ticker} — Double-Sweep Base: {status}{score_str}")
    if ax.get_legend_handles_labels()[0]:
        ax.legend(loc="upper left", fontsize=8)
    ax.set_ylabel("Price")
    vol_ax.set_ylabel("Volume")

    tick_step = max(len(window) // 10, 1)
    tick_positions = list(range(0, len(window), tick_step))
    tick_labels = [window.index[i].strftime("%Y-%m-%d") for i in tick_positions]
    vol_ax.set_xticks(tick_positions)
    vol_ax.set_xticklabels(tick_labels, rotation=45, ha="right", fontsize=8)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    print(f"saved chart: {out_path}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Plot Double-Sweep Base detections for one or more tickers.")
    parser.add_argument("tickers", nargs="+", help="Ticker symbol(s), e.g. CLSK WULF FRO FANG")
    parser.add_argument(
        "--period",
        default="2y",
        help="History period to fetch (default: 2y -- fetch_history requires >=260 rows "
        "for the trend-template's 200-day MA, which a bare 1y period doesn't clear; the "
        "chart itself still only shows the most recent ~year, via --plot-bars)",
    )
    parser.add_argument("--plot-bars", type=int, default=260, help="How many recent bars to draw (default: 260, ~1 trading year)")
    parser.add_argument("--out-dir", default=".", help="Directory to save PNGs into (default: cwd)")
    parser.add_argument("--fractal-n", type=int, default=4)
    parser.add_argument("--lookback-bars", type=int, default=60)
    parser.add_argument("--sweep-zone-bars", type=int, default=25)
    parser.add_argument("--max-depth-pct", type=float, default=35.0)
    parser.add_argument("--min-sweep-pct", type=float, default=0.1)
    parser.add_argument("--max-sweep-pct", type=float, default=3.0)
    parser.add_argument("--max-reclaim-bars", type=int, default=3)
    parser.add_argument("--max-final-contraction-pct", type=float, default=8.0)
    parser.add_argument(
        "--min-trend-checks",
        type=int,
        default=None,
        help="Minimum trend-template checks required to proceed to sweep detection "
        "(default: all available, i.e. the real production gate). Pass 0 to bypass "
        "the gate entirely and see the sweep/contraction geometry regardless of "
        "trend -- useful for visually checking the pattern on a ticker that fails "
        "the Stage-2 trend check, without that affecting the real scanner.",
    )
    args = parser.parse_args(argv)

    cfg = DoubleSweepConfig(
        fractal_n=args.fractal_n,
        lookback_bars=args.lookback_bars,
        sweep_zone_bars=args.sweep_zone_bars,
        max_depth_pct=args.max_depth_pct,
        min_sweep_pct=args.min_sweep_pct,
        max_sweep_pct=args.max_sweep_pct,
        max_reclaim_bars=args.max_reclaim_bars,
        max_final_contraction_pct=args.max_final_contraction_pct,
        min_trend_template_checks=args.min_trend_checks,
    )

    out_dir = Path(args.out_dir)
    for ticker in args.tickers:
        df = fetch_history(ticker, period=args.period)
        if df is None or df.empty:
            print(f"\n=== {ticker} ===\ncould not fetch data", file=sys.stderr)
            continue
        result = analyze_double_sweep(ticker, df, cfg)
        print_summary(result)
        plot(ticker, df, result, out_dir / f"{ticker}_double_sweep.png", plot_bars=args.plot_bars)


if __name__ == "__main__":
    main()
