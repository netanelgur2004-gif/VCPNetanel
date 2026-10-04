#!/usr/bin/env python3
"""CLI: scan a universe of tickers for the Double-Sweep Base pattern.

Reuses the existing universe/data-fetching infrastructure (universe.py,
data.py) -- a separate script from scanner.py, so it has zero effect on
the main VCP scan.

Usage:
    python scripts/scan_double_sweep.py --sp500 --html-report out.html --output out.csv
    python scripts/scan_double_sweep.py --tickers AAPL,MSFT,NVDA
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from tabulate import tabulate

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vcp_scanner.data import fetch_many  # noqa: E402
from vcp_scanner.double_sweep import DoubleSweepConfig, DoubleSweepResult, analyze_double_sweep  # noqa: E402
from vcp_scanner.double_sweep_report import write_html_report  # noqa: E402
from vcp_scanner.universe import sp500_tickers, tickers_from_csv_arg, tickers_from_file  # noqa: E402


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan stocks for the Double-Sweep Base pattern (both a prior swing "
        "high and a prior swing low swept, then tightening contraction inside the range)."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tickers", help="Comma-separated list of tickers, e.g. AAPL,MSFT,NVDA")
    source.add_argument("--file", help="Path to a text file with one ticker per line")
    source.add_argument("--sp500", action="store_true", help="Scan the current S&P 500 constituents")

    parser.add_argument("--period", default="2y", help="History period to fetch (default: 2y)")
    parser.add_argument("--workers", type=int, default=8, help="Parallel download threads (default 8)")
    parser.add_argument("--output", help="Write matched results to this CSV path")
    parser.add_argument("--html-report", help="Write matched results to this self-contained HTML report path")

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
        help="Minimum trend-template checks required (default: all available -- the "
        "real production gate). Pass a lower number to loosen it.",
    )
    return parser.parse_args(argv)


def resolve_tickers(args: argparse.Namespace) -> List[str]:
    if args.tickers:
        return tickers_from_csv_arg(args.tickers)
    if args.file:
        return tickers_from_file(args.file)
    return sp500_tickers()


def run_scan(tickers: List[str], period: str, workers: int, cfg: DoubleSweepConfig) -> List[DoubleSweepResult]:
    print(f"Fetching price history for {len(tickers)} tickers...", file=sys.stderr)
    histories = fetch_many(tickers, period=period, max_workers=workers)
    skipped = len(tickers) - len(histories)
    if skipped:
        print(f"Skipped {skipped} ticker(s) with missing/insufficient data.", file=sys.stderr)

    print(f"Analyzing {len(histories)} tickers for the Double-Sweep Base pattern...", file=sys.stderr)
    results = [analyze_double_sweep(ticker, df, cfg) for ticker, df in histories.items()]
    results.sort(key=lambda r: r.score, reverse=True)
    return results


def format_table(results: List[DoubleSweepResult]) -> str:
    rows = []
    for r in results:
        rows.append(
            [
                r.ticker,
                f"{r.score:.1f}",
                f"{r.base.depth_pct:.1f}%" if r.base else "-",
                f"{r.high_sweep.date.date()} @ {r.high_sweep.level:.2f}" if r.high_sweep else "-",
                f"{r.low_sweep.date.date()} @ {r.low_sweep.level:.2f}" if r.low_sweep else "-",
                len(r.contraction.legs_pct) if r.contraction else "-",
                f"{r.contraction.final_contraction_pct:.1f}%" if r.contraction and r.contraction.final_contraction_pct is not None else "-",
                f"{r.last_close:.2f}",
                f"{r.distance_to_pivot_pct:+.1f}%" if r.distance_to_pivot_pct is not None else "-",
                f"{r.stop_price:.2f}" if r.stop_price is not None else "-",
            ]
        )
    headers = [
        "Ticker", "Score", "Base Depth", "High Sweep", "Low Sweep",
        "Legs", "Final Leg", "Last", "Vs. Pivot", "Stop",
    ]
    return tabulate(rows, headers=headers, tablefmt="simple")


def write_csv(results: List[DoubleSweepResult], path: str) -> None:
    import csv

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "ticker", "score", "base_range_high", "base_range_low", "base_depth_pct",
                "high_sweep_date", "high_sweep_level", "low_sweep_date", "low_sweep_level",
                "num_legs", "final_contraction_pct", "volume_dryup_ratio",
                "last_close", "pivot_price", "stop_price", "distance_to_pivot_pct", "last_date",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r.ticker,
                    r.score,
                    r.base.range_high if r.base else "",
                    r.base.range_low if r.base else "",
                    round(r.base.depth_pct, 1) if r.base else "",
                    r.high_sweep.date.date().isoformat() if r.high_sweep else "",
                    r.high_sweep.level if r.high_sweep else "",
                    r.low_sweep.date.date().isoformat() if r.low_sweep else "",
                    r.low_sweep.level if r.low_sweep else "",
                    len(r.contraction.legs_pct) if r.contraction else "",
                    r.contraction.final_contraction_pct if r.contraction else "",
                    round(r.contraction.volume_dryup_ratio, 2) if r.contraction and r.contraction.volume_dryup_ratio is not None else "",
                    r.last_close,
                    r.pivot_price if r.pivot_price is not None else "",
                    r.stop_price if r.stop_price is not None else "",
                    round(r.distance_to_pivot_pct, 1) if r.distance_to_pivot_pct is not None else "",
                    r.last_date.date().isoformat() if r.last_date is not None else "",
                ]
            )


def main(argv: List[str] | None = None) -> None:
    args = parse_args(argv)
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

    tickers = resolve_tickers(args)
    results = run_scan(tickers, period=args.period, workers=args.workers, cfg=cfg)
    total_scanned = len(results)
    matched = [r for r in results if r.matched]
    matched.sort(key=lambda r: r.score, reverse=True)

    print(
        f"{len(matched)} of {total_scanned} analyzed tickers show a complete "
        f"Double-Sweep Base.",
        file=sys.stderr,
    )

    if args.output:
        write_csv(matched, args.output)
        print(f"Wrote {len(matched)} results to {args.output}", file=sys.stderr)

    if args.html_report:
        universe_label = "S&P 500 constituents" if args.sp500 else "scanned tickers"
        filter_note = (
            f"Thresholds: base depth <= {cfg.max_depth_pct:.0f}%, sweep "
            f"{cfg.min_sweep_pct:.1f}-{cfg.max_sweep_pct:.1f}% beyond the level with a "
            f"reclaim within {cfg.max_reclaim_bars} bars, final contraction leg < "
            f"{cfg.max_final_contraction_pct:.0f}%."
        )
        write_html_report(
            matched,
            args.html_report,
            universe_size=len(tickers),
            universe_label=universe_label,
            filter_note=filter_note,
            total_scanned=total_scanned,
        )
        print(f"Wrote HTML report to {args.html_report}", file=sys.stderr)

    print()
    if matched:
        print(format_table(matched))
    else:
        print("No Double-Sweep Base matches this run.")


if __name__ == "__main__":
    main()
