#!/usr/bin/env python3
"""CLI: rank sector/theme ETFs by relative strength vs. SPY, run the trend
template + VCP structural analysis on each, chart the top N, and optionally
tag a list of stocks with their sector's rank.

A fully separate script from scanner.py -- the stock screener's CLI and
default behavior are untouched.

Usage:
    python scripts/scan_sectors.py --test                      # 3 ETFs, charts only
    python scripts/scan_sectors.py                              # full universe, top 5 charted
    python scripts/scan_sectors.py --top 8 --charts-top 3
    python scripts/scan_sectors.py --tag-sp500 --output tags.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from tabulate import tabulate

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vcp_scanner.sector_chart import plot_sector  # noqa: E402
from vcp_scanner.sector_data import DEFAULT_CACHE_DIR, fetch_sector_history  # noqa: E402
from vcp_scanner.sector_report import write_html_report  # noqa: E402
from vcp_scanner.sector_scan import SectorResult, scan_sectors, tag_stocks_with_sector  # noqa: E402
from vcp_scanner.sector_universe import BENCHMARK  # noqa: E402
from vcp_scanner.universe import sp500_tickers, tickers_from_csv_arg  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("output") / "sectors"


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank sector/theme ETFs by RS vs. SPY and run the VCP screener's "
        "trend-template + contraction analysis on each."
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Quick smoke test: only XLK, SMH, XLE, charts all three regardless of --charts-top.",
    )
    parser.add_argument("--tickers", help="Comma-separated ETF list to scan instead of the full universe.")
    parser.add_argument("--period", default="2y", help="History period to fetch (default: 2y)")
    parser.add_argument("--top", type=int, default=5, help="How many top-ranked sectors to show/save (default 5)")
    parser.add_argument(
        "--charts-top", type=int, default=None,
        help="How many of the top-ranked sectors to chart (default: same as --top)",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Where to save the CSV + charts")
    parser.add_argument("--html-report", help="Also write a self-contained HTML dashboard to this path")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR), help="Local bar cache directory")
    parser.add_argument("--no-cache", action="store_true", help="Bypass the local CSV cache")

    tag_group = parser.add_mutually_exclusive_group()
    tag_group.add_argument("--tag-sp500", action="store_true", help="Also tag all S&P 500 stocks with their sector's rank")
    tag_group.add_argument("--tag-tickers", help="Comma-separated stock tickers to tag with their sector's rank")

    return parser.parse_args(argv)


def write_csv(results: List[SectorResult], path: Path) -> None:
    import csv

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "ticker", "rs_score", "rs_52w_high", "status", "trend_passed", "trend_total", "num_contractions", "pivot_price", "pivot_extension_pct", "last_close"])
        for r in results:
            writer.writerow(
                [
                    r.rs.rank, r.ticker, r.rs.score, r.rs.at_52w_high, r.status,
                    r.trend.passed, r.trend.total, r.vcp.num_contractions,
                    round(r.vcp.pivot_price, 2) if r.vcp.pivot_price else "",
                    round(r.vcp.pivot_extension_pct, 1) if r.vcp.pivot_extension_pct is not None else "",
                    round(r.last_close, 2),
                ]
            )


def format_table(results: List[SectorResult]) -> str:
    from vcp_scanner.sector_universe import ETF_LABELS

    rows = []
    for r in results:
        dist = r.vcp.pivot_extension_pct
        dist_str = f"{dist:+.1f}%" if dist is not None else "-"
        rows.append(
            [
                r.rs.rank, r.ticker, ETF_LABELS.get(r.ticker, ""), f"{r.rs.score:+.1f}",
                "yes" if r.rs.at_52w_high else "no", r.status, f"{r.trend.passed}/{r.trend.total}",
                r.vcp.num_contractions, dist_str, f"{r.last_close:.2f}",
            ]
        )
    headers = ["Rank", "Ticker", "Sector", "RS Score", "RS 52w High", "Status", "Trend", "Legs", "Vs. Pivot", "Last"]
    return tabulate(rows, headers=headers, tablefmt="simple")


def main(argv: List[str] | None = None) -> None:
    args = parse_args(argv)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.test:
        tickers = ["XLK", "SMH", "XLE"]
        charts_top = len(tickers)
    else:
        tickers = tickers_from_csv_arg(args.tickers) if args.tickers else None
        charts_top = args.charts_top if args.charts_top is not None else args.top

    print(f"Fetching sector/theme ETF history ({BENCHMARK} benchmark + {'custom list' if tickers else 'full universe'})...", file=sys.stderr)
    all_results = scan_sectors(
        tickers=tickers, period=args.period, cache_dir=args.cache_dir, use_cache=not args.no_cache
    )
    if not all_results:
        print("No sector results -- check network connectivity or the SPY benchmark fetch.", file=sys.stderr)
        sys.exit(1)

    top_results = all_results[: args.top]
    print(f"Ranked {len(all_results)} ETFs by RS vs. {BENCHMARK}.", file=sys.stderr)

    csv_path = out_dir / "sector_rankings.csv"
    write_csv(all_results, csv_path)
    print(f"Wrote {len(all_results)} ranked sectors to {csv_path}", file=sys.stderr)

    if args.html_report:
        write_html_report(all_results, args.html_report)
        print(f"Wrote HTML report to {args.html_report}", file=sys.stderr)

    chart_targets = top_results[:charts_top] if not args.test else top_results
    benchmark_df = fetch_sector_history(BENCHMARK, period=args.period, cache_dir=args.cache_dir, use_cache=not args.no_cache)
    for r in chart_targets:
        etf_df = fetch_sector_history(r.ticker, period=args.period, cache_dir=args.cache_dir, use_cache=not args.no_cache)
        if etf_df is None or benchmark_df is None:
            print(f"Skipping chart for {r.ticker}: missing data.", file=sys.stderr)
            continue
        chart_path = out_dir / f"{r.ticker}.png"
        plot_sector(
            r.ticker, etf_df, benchmark_df, r.vcp, r.trend, r.rs.score, r.rs.rank, r.status, chart_path,
        )
        print(f"Saved chart: {chart_path}", file=sys.stderr)

    if args.tag_sp500 or args.tag_tickers:
        stock_tickers = sp500_tickers() if args.tag_sp500 else tickers_from_csv_arg(args.tag_tickers)
        tags = tag_stocks_with_sector(stock_tickers, all_results, top_n=args.top)
        tags_path = out_dir / "stock_sector_tags.csv"
        import csv as _csv

        with open(tags_path, "w", newline="") as f:
            writer = _csv.writer(f)
            writer.writerow(["ticker", "sector_etf", "sector_rank", "in_top_sector"])
            for ticker, tag in tags.items():
                writer.writerow([ticker, tag["sector_etf"] or "", tag["sector_rank"] or "", tag["in_top_sector"]])
        print(f"Wrote {len(tags)} stock sector tags to {tags_path}", file=sys.stderr)

    print()
    print(format_table(top_results))


if __name__ == "__main__":
    main()
