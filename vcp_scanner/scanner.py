"""CLI entry point: scan a universe of tickers and rank them by VCP match score."""

from __future__ import annotations

import argparse
import sys
from typing import List

from tabulate import tabulate

from .data import fetch_many
from .market_sentiment import fetch_fear_greed_index
from .report import write_html_report
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
    parser.add_argument("--html-report", help="Write full ranked results to this self-contained HTML report path")
    parser.add_argument("--workers", type=int, default=8, help="Parallel download threads (default 8)")
    parser.add_argument(
        "--max-extension",
        type=float,
        default=5.0,
        help="Exclude stocks already more than this %% above their confirmed pivot -- "
        "an actual VCP setup, not one that already broke out and ran (default 5.0; "
        "pass a large number like 1000 to disable)",
    )
    parser.add_argument(
        "--min-base-weeks",
        type=float,
        default=4.0,
        help="Require the detected base to have been forming for at least this many "
        "weeks of trading (default 4.0, i.e. about a month; 0 to disable)",
    )
    parser.add_argument(
        "--min-contractions",
        type=int,
        default=2,
        help="Require at least this many detected pullback legs in the current base "
        "(default 2) -- excludes stocks that just made a fresh high, dipped once, "
        "and are climbing again, which is normal uptrend noise, not a base; 0 to disable",
    )
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


def filter_setups(
    scores: List[VCPScore],
    max_extension_pct: float,
    min_base_weeks: float,
    min_contractions: int = 2,
) -> List[VCPScore]:
    """Keep only stocks with an actual, sufficiently-developed base that
    hasn't already run away from the pivot.

    This is a hard filter, not a scoring weight: a heavily-extended stock
    can still score well overall on trend strength alone, which isn't a
    useful answer to "give me VCP setups" -- those need to be actionable
    near the pivot, not stocks that already broke out weeks ago.

    `min_contractions` guards against a stock that just made a fresh high,
    dipped once, and is climbing again -- one shallow pullback is normal
    uptrend noise, not a "volatility contraction pattern". A real VCP needs
    multiple successively-tighter pullbacks under the same ceiling.
    """
    min_base_days = min_base_weeks * 5.0  # ~5 trading days per week
    kept = []
    for s in scores:
        ext = s.vcp.pivot_extension_pct
        if ext is not None and ext > max_extension_pct:
            continue
        if s.vcp.base_length_days < min_base_days:
            continue
        if s.vcp.num_contractions < min_contractions:
            continue
        kept.append(s)
    return kept


def format_table(scores: List[VCPScore]) -> str:
    rows = []
    for s in scores:
        vol_flag = "yes" if (s.vcp.volume_dryup_score or 0) >= 60 else "no"
        ext = s.vcp.pivot_extension_pct
        if ext is None:
            ext_str = "-"
        elif ext > 5:
            ext_str = f"+{ext:.1f}% (extended)"
        elif ext > 0:
            ext_str = f"+{ext:.1f}%"
        elif ext >= -5:
            ext_str = f"{ext:.1f}%"
        else:
            ext_str = f"{ext:.1f}% (in base)"
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
                f"{s.stop_loss_price:.2f} (-{s.stop_loss_pct:.1f}%)",
            ]
        )
    headers = [
        "Ticker", "VCP Score", "Trend", "Contractions", "Vol Dry-Up",
        "Tightness", "Prior Uptrend", "RS", "Last", "Pivot", "Vs. Pivot", "Stop-Loss",
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
                "pivot_extension_pct", "pivot_proximity_score",
                "stop_loss_price", "stop_loss_pct", "stop_loss_basis", "last_date",
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
                    s.stop_loss_price,
                    s.stop_loss_pct,
                    s.stop_loss_basis,
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

    candidates = filter_setups(
        scores, args.max_extension, args.min_base_weeks, args.min_contractions
    )
    print(
        f"{len(candidates)} of {len(scores)} scanned tickers pass the setup filters "
        f"(base >= {args.min_base_weeks:.0f}w with >= {args.min_contractions} pullback "
        f"legs, not more than {args.max_extension:.0f}% past pivot).",
        file=sys.stderr,
    )
    if not candidates:
        print(
            "No candidates passed the filters — try loosening --max-extension, "
            "--min-base-weeks, or --min-contractions.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.output:
        write_csv(candidates, args.output)
        print(f"Wrote {len(candidates)} results to {args.output}", file=sys.stderr)

    print("Fetching Fear & Greed Index...", file=sys.stderr)
    fear_greed = fetch_fear_greed_index()
    if fear_greed:
        print(
            f"Fear & Greed Index: {fear_greed['score']:.1f} ({fear_greed['rating']})",
            file=sys.stderr,
        )
    else:
        print("Fear & Greed Index unavailable this run.", file=sys.stderr)

    if args.html_report:
        universe_label = "S&P 500 constituents" if args.sp500 else "scanned tickers"
        filter_note = (
            f"Showing setups with a base of at least {args.min_base_weeks:.0f} weeks "
            f"and at least {args.min_contractions} pullback legs, within "
            f"{args.max_extension:.0f}% of their pivot — stocks already extended past "
            "breakout, or that only dipped once before pushing to new highs, are "
            "excluded, not just down-weighted."
        )
        write_html_report(
            candidates,
            args.html_report,
            universe_size=len(tickers),
            universe_label=universe_label,
            fear_greed=fear_greed,
            filter_note=filter_note,
            total_scored=len(scores),
        )
        print(f"Wrote HTML report to {args.html_report}", file=sys.stderr)

    filtered = [s for s in candidates if s.score >= args.min_score]
    if args.top:
        filtered = filtered[: args.top]

    print()
    print(format_table(filtered))


if __name__ == "__main__":
    main()
