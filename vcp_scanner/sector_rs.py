"""Relative-strength ranking of sector/theme ETFs against a benchmark (SPY).

Reuses rs_rating.weighted_momentum directly -- it's already the IBD-style
40/20/20/20 (3/6/9/12mo) weighted-return formula this module needs; RS score
here is just that momentum minus the benchmark's own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from .rs_rating import weighted_momentum


def rs_score(etf_df: pd.DataFrame, benchmark_df: pd.DataFrame) -> float:
    return weighted_momentum(etf_df) - weighted_momentum(benchmark_df)


def rs_line(etf_df: pd.DataFrame, benchmark_df: pd.DataFrame) -> pd.Series:
    """ETF close / benchmark close, aligned on shared trading days."""
    aligned = pd.concat(
        [etf_df["Close"].rename("etf"), benchmark_df["Close"].rename("bench")], axis=1, join="inner"
    ).dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    return aligned["etf"] / aligned["bench"]


def is_rs_line_at_52w_high(line: pd.Series, weeks: int = 52) -> bool:
    window = line.tail(weeks * 5)
    if window.empty:
        return False
    return bool(line.iloc[-1] >= window.max())


@dataclass
class SectorRS:
    ticker: str
    score: float
    at_52w_high: bool
    rank: int = 0


def rank_sectors(
    histories: Dict[str, pd.DataFrame], benchmark_df: pd.DataFrame, top_n: Optional[int] = None
) -> List[SectorRS]:
    """Rank every {ticker: df} in `histories` by RS score vs. the benchmark.

    Returns the full ranked list unless `top_n` is given, in which case only
    the top N are returned (rank still reflects position across all of them).
    """
    entries = []
    for ticker, df in histories.items():
        score = rs_score(df, benchmark_df)
        line = rs_line(df, benchmark_df)
        entries.append(SectorRS(ticker=ticker, score=round(score, 2), at_52w_high=is_rs_line_at_52w_high(line)))

    entries.sort(key=lambda e: e.score, reverse=True)
    for i, e in enumerate(entries, start=1):
        e.rank = i

    return entries[:top_n] if top_n is not None else entries
