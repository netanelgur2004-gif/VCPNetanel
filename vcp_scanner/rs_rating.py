"""IBD-style Relative Strength rating: percentile rank of weighted momentum
across the scanned universe.

IBD's formula weights the most recent quarter more heavily than the prior
three: roughly 40% * 3mo return + 20% each for 6/9/12mo returns. We rank the
resulting scores across whatever universe was scanned and convert to a 1-99
percentile, mirroring IBD's RS Rating scale (99 = best).
"""

from __future__ import annotations

from typing import Dict

import pandas as pd


def _pct_return(df: pd.DataFrame, trading_days: int) -> float:
    if len(df) <= trading_days:
        return 0.0
    past = df["Close"].iloc[-trading_days - 1]
    now = df["Close"].iloc[-1]
    if past <= 0:
        return 0.0
    return (now / past - 1.0) * 100.0


def weighted_momentum(df: pd.DataFrame) -> float:
    r3 = _pct_return(df, 63)
    r6 = _pct_return(df, 126)
    r9 = _pct_return(df, 189)
    r12 = _pct_return(df, 252)
    return 0.4 * r3 + 0.2 * r6 + 0.2 * r9 + 0.2 * r12


def compute_rs_ratings(histories: Dict[str, pd.DataFrame]) -> Dict[str, float]:
    """Given {ticker: OHLCV df}, return {ticker: RS rating in [1, 99]}."""
    momentum = {ticker: weighted_momentum(df) for ticker, df in histories.items()}
    if not momentum:
        return {}

    series = pd.Series(momentum)
    ranks = series.rank(pct=True)  # 0..1, higher momentum -> higher rank
    ratings = (ranks * 98 + 1).round(0)  # map to 1..99
    return ratings.to_dict()
