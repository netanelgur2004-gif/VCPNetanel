#!/usr/bin/env python3
"""Run the full S&P 500 VCP screener, then tag the stocks that pass it with
their sector ETF's relative-strength rank from the Leading Sectors module.

Reuses scanner.py's resolve_tickers/run_scan/filter_setups and
sector_scan.py's scan_sectors/tag_stocks_with_sector exactly as they are --
this script only orchestrates and merges, it doesn't reimplement either
scan. Neither scanner.py nor sector_scan.py's own CLI/behavior changes.

Usage:
    python scripts/scan_sp500_with_sectors.py --html-report out.html --output out.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from tabulate import tabulate

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vcp_scanner.combined_report import write_html_report  # noqa: E402
from vcp_scanner.scanner import filter_setups, run_scan  # noqa: E402
from vcp_scanner.scorer import VCPScore  # noqa: E402
from vcp_scanner.sector_data import DEFAULT_CACHE_DIR  # noqa: E402
from vcp_scanner.sector_scan import scan_sectors, tag_stocks_with_sector  # noqa: E402
from vcp_scanner.sector_universe import ETF_LABELS  # noqa: E402
from vcp_scanner.universe import sp500_tickers  # noqa: E402


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan the full S&P 500 for VCP setups, then tag each result with "
        "its sector ETF's relative-strength rank (same sector universe/ranking as "
        "scripts/scan_sectors.py)."
    )
    parser.add_argument("--period", default="2y", help="History period to fetch (default: 2y)")
    parser.add_argument("--workers", type=int, default=8, help="Parallel download threads for the stock scan")
    parser.add_argument("--max-extension", type=float, default=5.0, help="Same as scanner.py's --max-extension")
    parser.add_argument("--min-base-weeks", type=float, default=4.0, help="Same as scanner.py's --min-base-weeks")
    parser.add_argument("--min-contractions", type=int, default=2, help="Same as scanner.py's --min-contractions")
    parser.add_argument("--sector-top", type=int, default=5, help="How many top-ranked sectors count as 'leading' (default 5)")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR), help="Local sector-ETF bar cache directory")
    parser.add_argument("--no-sector-cache", action="store_true", help="Bypass the sector ETF cache")
    parser.add_argument("--output", help="Write the combined ranked results to this CSV path")
    parser.add_argument("--html-report", help="Write the combined results to this self-contained HTML report path")
    return parser.parse_args(argv)


def write_csv(scores: List[VCPScore], tags: dict, path: str) -> None:
    import csv

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "ticker", "vcp_score", "sector_etf", "sector_name", "sector_rank", "in_top_sector",
                "trend_passed", "trend_total", "num_contractions", "rs_rating", "last_close",
                "pivot_extension_pct", "stop_loss_price", "stop_loss_pct",
            ]
        )
        for s in scores:
            tag = tags.get(s.ticker, {})
            etf = tag.get("sector_etf")
            writer.writerow(
                [
                    s.ticker, s.score, etf or "", ETF_LABELS.get(etf, "") if etf else "",
                    tag.get("sector_rank") or "", bool(tag.get("in_top_sector")),
                    s.trend.passed, s.trend.total, s.vcp.num_contractions,
                    s.rs_rating if s.rs_rating is not None else "", s.last_close,
                    round(s.vcp.pivot_extension_pct, 1) if s.vcp.pivot_extension_pct is not None else "",
                    s.stop_loss_price, s.stop_loss_pct,
                ]
            )


def format_table(scores: List[VCPScore], tags: dict) -> str:
    rows = []
    for s in scores:
        tag = tags.get(s.ticker, {})
        etf = tag.get("sector_etf")
        rank = tag.get("sector_rank")
        rank_str = f"#{rank}{' (top)' if tag.get('in_top_sector') else ''}" if rank else "-"
        rows.append(
            [
                s.ticker, f"{s.score:.1f}%", etf or "-", rank_str,
                f"{s.trend.passed}/{s.trend.total}", s.vcp.num_contractions,
                f"{s.last_close:.2f}", f"{s.stop_loss_price:.2f} (-{s.stop_loss_pct:.1f}%)",
            ]
        )
    headers = ["Ticker", "VCP Score", "Sector", "Sector Rank", "Trend", "Legs", "Last", "Stop-Loss"]
    return tabulate(rows, headers=headers, tablefmt="simple")


def main(argv: List[str] | None = None) -> None:
    args = parse_args(argv)

    tickers = sp500_tickers()
    print("=== Step 1/2: VCP scan ===", file=sys.stderr)
    scores = run_scan(tickers, period=args.period, workers=args.workers)
    if not scores:
        print("No results from the VCP scan — check network connectivity.", file=sys.stderr)
        sys.exit(1)

    candidates = filter_setups(scores, args.max_extension, args.min_base_weeks, args.min_contractions)
    print(
        f"{len(candidates)} of {len(scores)} scanned tickers pass the VCP setup filters.",
        file=sys.stderr,
    )
    if not candidates:
        print("No candidates passed the VCP filters.", file=sys.stderr)
        sys.exit(1)

    print("\n=== Step 2/2: Leading Sectors scan ===", file=sys.stderr)
    sector_results = scan_sectors(cache_dir=args.cache_dir, use_cache=not args.no_sector_cache)
    if not sector_results:
        print("No sector results -- check network connectivity or the SPY benchmark fetch.", file=sys.stderr)
        sys.exit(1)
    print(f"Ranked {len(sector_results)} sector/theme ETFs.", file=sys.stderr)

    tags = tag_stocks_with_sector([c.ticker for c in candidates], sector_results, top_n=args.sector_top)
    in_top = sum(1 for t in tags.values() if t["in_top_sector"])
    print(f"{in_top} of {len(candidates)} VCP setups sit in a top-{args.sector_top} sector.", file=sys.stderr)

    if args.output:
        write_csv(candidates, tags, args.output)
        print(f"Wrote {len(candidates)} results to {args.output}", file=sys.stderr)

    if args.html_report:
        write_html_report(
            candidates, tags, args.html_report, universe_size=len(tickers), top_n=args.sector_top
        )
        print(f"Wrote HTML report to {args.html_report}", file=sys.stderr)

    candidates_sorted = sorted(
        candidates, key=lambda s: (not tags.get(s.ticker, {}).get("in_top_sector"), -s.score)
    )
    print()
    print(format_table(candidates_sorted, tags))


if __name__ == "__main__":
    main()
