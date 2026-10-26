"""Orchestrates the Leading Sectors module: fetch ETFs, rank by RS vs. SPY,
run the existing trend-template + VCP analysis on each (with ETF-tuned
contraction thresholds), and tag individual stocks with their sector's rank.

Reuses evaluate_trend_template and analyze_vcp exactly as the stock
screener calls them -- nothing in trend_template.py or vcp.py is
duplicated or changed, only called with a different pct_threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from .sector_data import fetch_many_sectors
from .sector_rs import SectorRS, rank_sectors
from .sector_universe import (
    ALL_SECTOR_UNIVERSE,
    BENCHMARK,
    ETF_VCP_PCT_THRESHOLD,
    EXTENDED_PAST_PIVOT_PCT,
    GICS_SECTOR_TO_ETF,
)
from .trend_template import TrendTemplateResult, evaluate_trend_template
from .universe import sp500_sector_map
from .vcp import VCPAnalysis, analyze_vcp


@dataclass
class SectorResult:
    ticker: str
    rs: SectorRS
    trend: TrendTemplateResult
    vcp: VCPAnalysis
    last_close: float
    status: str


def _status_for(trend: TrendTemplateResult, vcp: VCPAnalysis) -> str:
    if trend.total == 0 or trend.passed < trend.total - 2:
        return "No setup"
    if not vcp.num_contractions or vcp.pivot_price is None or vcp.pivot_extension_pct is None:
        return "No setup"
    if vcp.pivot_extension_pct <= 0:
        return "VCP forming"
    if vcp.pivot_extension_pct <= EXTENDED_PAST_PIVOT_PCT:
        return "Breakout"
    return "Extended"


def scan_sectors(
    tickers: Optional[List[str]] = None,
    period: str = "2y",
    cache_dir=None,
    use_cache: bool = True,
) -> List[SectorResult]:
    """Fetch, rank, and analyze the full sector/theme ETF universe.

    `tickers` defaults to ALL_SECTOR_UNIVERSE (11 SPDR + 12 theme ETFs).
    SPY is always fetched as the benchmark even if not in `tickers`.
    Always returns the FULL ranked list (not just a top slice) -- callers
    slice for display/charts themselves, but tag_stocks_with_sector needs
    every sector's rank, not just the top N's, to tag stocks accurately.
    """
    universe = tickers if tickers is not None else list(ALL_SECTOR_UNIVERSE)
    fetch_set = list(dict.fromkeys(universe + [BENCHMARK]))

    kwargs = {"period": period, "use_cache": use_cache}
    if cache_dir is not None:
        kwargs["cache_dir"] = cache_dir
    histories = fetch_many_sectors(fetch_set, **kwargs)

    benchmark_df = histories.get(BENCHMARK)
    if benchmark_df is None:
        return []

    sector_histories = {t: df for t, df in histories.items() if t != BENCHMARK and t in universe}
    ranked = rank_sectors(sector_histories, benchmark_df, top_n=None)

    results = []
    for rs in ranked:
        df = sector_histories[rs.ticker]
        trend = evaluate_trend_template(df, rs_rating=None)
        vcp = analyze_vcp(df, pct_threshold=ETF_VCP_PCT_THRESHOLD)
        results.append(
            SectorResult(
                ticker=rs.ticker,
                rs=rs,
                trend=trend,
                vcp=vcp,
                last_close=float(df["Close"].iloc[-1]),
                status=_status_for(trend, vcp),
            )
        )
    return results


def tag_stocks_with_sector(
    tickers: List[str], sector_results: List[SectorResult], top_n: int = 5
) -> Dict[str, dict]:
    """{stock_ticker: {"sector_etf": ..., "sector_rank": ..., "in_top_sector": bool}}

    Maps each stock to its GICS sector's SPDR ETF (sp500_sector_map + the
    broad 11-sector GICS_SECTOR_TO_ETF table), then looks up that ETF's rank
    among `sector_results` (expected to be the FULL ranked list, so every
    sector has a real rank, not just the top N). `in_top_sector` flags
    whether that rank falls within `top_n`.
    """
    sector_map = sp500_sector_map()
    rank_by_etf = {r.ticker: r.rs.rank for r in sector_results}

    tags: Dict[str, dict] = {}
    for ticker in tickers:
        gics_sector = sector_map.get(ticker)
        etf = GICS_SECTOR_TO_ETF.get(gics_sector) if gics_sector else None
        rank = rank_by_etf.get(etf) if etf else None
        tags[ticker] = {
            "sector_etf": etf,
            "sector_rank": rank,
            "in_top_sector": rank is not None and rank <= top_n,
        }
    return tags
