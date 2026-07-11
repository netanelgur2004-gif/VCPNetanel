"""Swing high / swing low detection used to identify VCP contractions.

Uses a percentage-threshold ZigZag: a new pivot is only confirmed once price
reverses by at least `pct_threshold` percent from the last extreme. This
filters out ordinary daily noise and leaves the handful of structurally
meaningful swings a VCP base is built from (raw local-extrema detection on
daily bars produces dozens of spurious "contractions").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal

import pandas as pd


@dataclass
class SwingPoint:
    date: pd.Timestamp
    price: float
    kind: Literal["high", "low"]
    index: int  # positional index into the source dataframe


def find_swing_points(df: pd.DataFrame, pct_threshold: float = 3.0) -> List[SwingPoint]:
    """Find alternating swing highs/lows via a percentage-threshold ZigZag.

    A pivot is confirmed once price reverses by at least `pct_threshold`%
    from the running extreme since the prior pivot. Larger thresholds ->
    fewer, more significant swings.
    """
    n = len(df)
    if n < 2:
        return []

    dates = df.index
    high = df["High"].to_numpy()
    low = df["Low"].to_numpy()

    trend = 0  # 0 = undetermined, 1 = up, -1 = down
    extreme_high, extreme_high_idx = high[0], 0
    extreme_low, extreme_low_idx = low[0], 0

    pivots: List[tuple] = []

    for i in range(1, n):
        if high[i] > extreme_high:
            extreme_high, extreme_high_idx = high[i], i
        if low[i] < extreme_low:
            extreme_low, extreme_low_idx = low[i], i

        if trend == 0:
            up_move = (extreme_high - low[0]) / low[0] * 100.0 if low[0] > 0 else 0.0
            down_move = (high[0] - extreme_low) / high[0] * 100.0 if high[0] > 0 else 0.0
            if up_move >= pct_threshold and up_move >= down_move:
                trend = 1
                pivots.append((0, float(low[0]), "low"))
                extreme_high, extreme_high_idx = high[i], i
            elif down_move >= pct_threshold:
                trend = -1
                pivots.append((0, float(high[0]), "high"))
                extreme_low, extreme_low_idx = low[i], i
        elif trend == 1:
            retrace = (extreme_high - low[i]) / extreme_high * 100.0 if extreme_high > 0 else 0.0
            if retrace >= pct_threshold:
                pivots.append((extreme_high_idx, float(extreme_high), "high"))
                trend = -1
                extreme_low, extreme_low_idx = low[i], i
        else:  # trend == -1
            rally = (high[i] - extreme_low) / extreme_low * 100.0 if extreme_low > 0 else 0.0
            if rally >= pct_threshold:
                pivots.append((extreme_low_idx, float(extreme_low), "low"))
                trend = 1
                extreme_high, extreme_high_idx = high[i], i

    if trend == 1:
        pivots.append((extreme_high_idx, float(extreme_high), "high"))
    elif trend == -1:
        pivots.append((extreme_low_idx, float(extreme_low), "low"))

    return [SwingPoint(dates[i], price, kind, i) for i, price, kind in pivots]
