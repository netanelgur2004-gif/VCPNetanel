"""CLI entry point: flag S&P 500 stocks 15-20% away from their 20-day SMA,
and whether the move looks catalyst-driven (earnings/news) or just
sector/market drift with nothing stock-specific behind it.
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from tabulate import tabulate

from .data import fetch_many
from .extension_scan import ExtensionResult, scan_sma20_extension
from .market_calendar import market_was_open_today
from .universe import sp500_constituents


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Flag S&P 500 stocks 15-20%% away from their 20-day SMA, and "
        "whether the move looks catalyst-driven or just sector/market drift."
    )
    parser.add_argument("--low", type=float, default=15.0, help="Lower bound of |deviation| %% (default 15)")
    parser.add_argument("--high", type=float, default=20.0, help="Upper bound of |deviation| %% (default 20)")
    parser.add_argument(
        "--lookback-days", type=int, default=20, help="Days to look back for news/price shocks (default 20)"
    )
    parser.add_argument("--period", default="2y", help="History period to fetch (default: 2y)")
    parser.add_argument("--workers", type=int, default=8, help="Parallel download threads (default 8)")
    parser.add_argument(
        "--no-news", action="store_true", help="Skip the news fetch (faster; price-shock detection only)"
    )
    parser.add_argument(
        "--require-market-open",
        action="store_true",
        help="Exit immediately (no output) if the US market wasn't open today (weekend/holiday). "
        "Meant for scheduled/cron runs so they don't re-report yesterday's close as new.",
    )
    return parser.parse_args(argv)


def _table(results: List[ExtensionResult]) -> str:
    if not results:
        return "(none)"
    rows = [
        [
            r.ticker,
            r.direction,
            f"{r.deviation_pct:+.1f}%",
            r.sector or "-",
            f"{r.sector_avg_deviation:+.1f}%" if r.sector_avg_deviation is not None else "-",
            r.reason,
        ]
        for r in results
    ]
    return tabulate(
        rows, headers=["Ticker", "Dir", "Vs SMA20", "Sector", "Sector Avg", "Reason"], tablefmt="simple"
    )


def format_results(results: List[ExtensionResult]) -> str:
    no_catalyst = [r for r in results if not r.has_catalyst]
    has_catalyst = [r for r in results if r.has_catalyst]

    parts = [
        f"\n=== NO CLEAR CATALYST ({len(no_catalyst)}) - sector/market drift, worth a closer look ===",
        _table(no_catalyst),
        f"\n=== HAS CATALYST ({len(has_catalyst)}) - news/earnings/gap explains the move ===",
        _table(has_catalyst),
    ]
    return "\n".join(parts)


def run_scan(args: argparse.Namespace) -> List[ExtensionResult]:
    constituents = sp500_constituents()
    tickers = constituents["Symbol"].tolist()
    sector_map = dict(zip(constituents["Symbol"], constituents["Sector"]))

    print(f"Fetching price history for {len(tickers)} tickers...", file=sys.stderr)
    histories = fetch_many(tickers, period=args.period, max_workers=args.workers)
    print(f"Fetched {len(histories)} tickers", file=sys.stderr)

    return scan_sma20_extension(
        histories,
        sector_map=sector_map,
        low_pct=args.low,
        high_pct=args.high,
        lookback_days=args.lookback_days,
        fetch_news=not args.no_news,
    )


def main(argv: List[str] | None = None) -> None:
    args = parse_args(argv)

    if args.require_market_open and not market_was_open_today():
        print("Market wasn't open today (weekend/holiday) - skipping scan.", file=sys.stderr)
        return

    results = run_scan(args)
    print(format_results(results))


if __name__ == "__main__":
    main()
