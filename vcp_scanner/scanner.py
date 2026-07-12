"""CLI entry point: scan a universe of tickers and rank them by VCP match score."""

from __future__ import annotations

import argparse
import sys
from typing import List

from tabulate import tabulate

from .data import fetch_many
from .rs_rating import compute_rs_ratings
from .scorer import VCPScore, score_ticker
from .universe import sp500_tickers, tickers_from_csv_arg, tickers_from_file


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan stocks for Mark Minervini's Volatility Contraction Pattern (VCP) "
        "and rate each one 0-100% on how closely it matches."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tickers", help="Comma-separated list of tickers, e.g. AAPL,MSFT,NVDA")
    source.add_argument("--file", help="Path to a text file with one ticker per line")
    source.add_argument("--sp500", action="store_true", help="Scan the current S&P 500 constituents")

    parser.add_argument("--period", default="2y", help="History period to fetch (default: 2y)")
    parser.add_argument("--top", type=int, default=None, help="Only show the top N results")
    parser.add_argument(
        "--min-score", type=float, default=0.0, help="Only show results scoring >= this (0-100)"
    )
    parser.add_argument("--output", help="Write full ranked results to this CSV path")
    parser.add_argument("--workers", type=int, default=8, help="Parallel download threads (default 8)")
    return parser.parse_args(argv)


def resolve_tickers(args: argparse.Namespace) -> List[str]:
    if args.tickers:
        return tickers_from_csv_arg(args.tickers)
    if args.file:
        return tickers_from_file(args.file)
    return sp500_tickers()


def run_scan(tickers: List[str], period: str, workers: int) -> List[VCPScore]:
    print(f"Fetching price history for {len(tickers)} tickers...", file=sys.stderr)
    histories = fetch_many(tickers, period=period, max_workers=workers)
    skipped = len(tickers) - len(histories)
    if skipped:
        print(f"Skipped {skipped} ticker(s) with missing/insufficient data.", file=sys.stderr)

    if not histories:
        return []

    print("Computing relative strength ratings...", file=sys.stderr)
    rs_ratings = compute_rs_ratings(histories)

    print("Scoring VCP structure...", file=sys.stderr)
    scores = [
        score_ticker(ticker, df, rs_rating=rs_ratings.get(ticker))
        for ticker, df in histories.items()
    ]
    scores.sort(key=lambda s: s.score, reverse=True)
    return scores


def format_table(scores: List[VCPScore]) -> str:
    rows = []
    for s in scores:
        vol_flag = "yes" if (s.vcp.volume_dryup_score or 0) >= 60 else "no"
        if s.vcp.pivot_extension_pct is None:
            ext_str = "-"
        elif s.vcp.pivot_extension_pct <= 0:
            ext_str = f"-{abs(s.vcp.pivot_extension_pct):.1f}% (below pivot)"
        else:
            ext_str = f"+{s.vcp.pivot_extension_pct:.1f}% (extended)"
        rows.append(
            [
                s.ticker,
                f"{s.score:.1f}%",
                f"{s.trend.passed}/{s.trend.total}",
                s.vcp.num_contractions,
                vol_flag,
                f"{s.vcp.tightness_score:.0f}",
                f"{s.vcp.prior_uptrend_pct:.0f}%" if s.vcp.prior_uptrend_pct is not None else "-",
                f"{s.rs_rating:.0f}" if s.rs_rating is not None else "-",
                f"{s.last_close:.2f}",
                f"{s.vcp.pivot_price:.2f}" if s.vcp.pivot_price else "-",
                ext_str,
            ]
        )
    headers = [
        "Ticker", "VCP Score", "Trend", "Contractions", "Vol Dry-Up",
        "Tightness", "Prior Uptrend", "RS", "Last", "Pivot", "Vs. Pivot",
    ]
    return tabulate(rows, headers=headers, tablefmt="simple")


def write_csv(scores: List[VCPScore], path: str) -> None:
    import csv

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "ticker", "vcp_score", "trend_passed", "trend_total", "num_contractions",
                "contractions_pct", "volume_dryup_score", "tightness_score",
                "prior_uptrend_pct", "rs_rating", "last_close", "pivot_price",
                "pivot_extension_pct", "pivot_proximity_score", "last_date",
            ]
        )
        for s in scores:
            writer.writerow(
                [
                    s.ticker,
                    s.score,
                    s.trend.passed,
                    s.trend.total,
                    s.vcp.num_contractions,
                    ";".join(str(x) for x in s.vcp.contractions_pct),
                    round(s.vcp.volume_dryup_score, 1),
                    round(s.vcp.tightness_score, 1),
                    round(s.vcp.prior_uptrend_pct, 1) if s.vcp.prior_uptrend_pct is not None else "",
                    s.rs_rating if s.rs_rating is not None else "",
                    s.last_close,
                    s.vcp.pivot_price if s.vcp.pivot_price is not None else "",
                    round(s.vcp.pivot_extension_pct, 1) if s.vcp.pivot_extension_pct is not None else "",
                    round(s.vcp.pivot_proximity_score, 1),
                    s.last_date.date().isoformat(),
                ]
            )


def main(argv: List[str] | None = None) -> None:
    args = parse_args(argv)
    tickers = resolve_tickers(args)
    scores = run_scan(tickers, period=args.period, workers=args.workers)

    if not scores:
        print("No results — check your tickers or network connectivity.", file=sys.stderr)
        sys.exit(1)

    if args.output:
        write_csv(scores, args.output)
        print(f"Wrote {len(scores)} results to {args.output}", file=sys.stderr)

    filtered = [s for s in scores if s.score >= args.min_score]
    if args.top:
        filtered = filtered[: args.top]

    print()
    print(format_table(filtered))


if __name__ == "__main__":
    main()
