"""Core VCP (Volatility Contraction Pattern) structural analysis.

Looks at the most recent price base for:
  - a series of shrinking pullbacks ("contractions")
  - volume drying up as the base matures
  - the trading range tightening near the pivot
  - a genuine prior uptrend for the base to have contracted from
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from .indicators import avg_volume, daily_range_pct
from .swings import SwingPoint, find_swing_points


def _ratio_to_score(ratio: float, best: float, worst: float) -> float:
    """Linearly map ratio to a 0-100 score: `best` -> 100, `worst` -> 0.

    Works regardless of whether `best` is numerically above or below
    `worst` (e.g. best=0.4/worst=1.0 for "lower is better", or
    best=30/worst=5 for "higher is better").
    """
    if best == worst:
        return 100.0
    t = (ratio - worst) / (best - worst)
    return 100.0 * max(0.0, min(1.0, t))


def _count_score(n: int) -> float:
    table = {0: 0.0, 1: 30.0, 2: 80.0, 3: 100.0, 4: 100.0, 5: 80.0, 6: 60.0}
    if n in table:
        return table[n]
    return 40.0 if n > 6 else 0.0


@dataclass
class VCPAnalysis:
    contractions_pct: List[float] = field(default_factory=list)
    num_contractions: int = 0
    contraction_score: float = 0.0

    volume_dryup_ratio: Optional[float] = None
    recent_volume_ratio: Optional[float] = None
    volume_dryup_score: float = 0.0

    recent_range_pct: Optional[float] = None
    base_range_pct: Optional[float] = None
    tightness_score: float = 0.0

    prior_uptrend_pct: Optional[float] = None
    prior_uptrend_score: float = 0.0

    pivot_price: Optional[float] = None
    base_length_days: int = 0
    base_start_date: Optional[pd.Timestamp] = None

    pivot_extension_pct: Optional[float] = None
    pivot_proximity_score: float = 0.0

    last_contraction_low: Optional[float] = None


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample daily OHLCV to weekly bars.

    VCP contractions are a weeks-to-months-long structure; detecting swings
    directly on daily bars picks up ordinary day-to-day noise as spurious
    "contractions". Weekly bars smooth that out and match how the pattern is
    conventionally read on a chart.
    """
    weekly = df.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    return weekly.dropna(subset=["Close"])


def _find_base_sequence(window_df: pd.DataFrame, pct_threshold: float) -> List[SwingPoint]:
    """Slice the swing sequence down to the base currently being built.

    Anchoring at the *first* high in the lookback window is wrong: if a
    stock completed an earlier base, broke out, and ran hard to a much
    higher new high, that breakout leg would get counted as one of the
    base's own "contractions" -- chaining an old, already-resolved base to
    a fresh breakout rally as if it were one long, still-forming base. A
    stock that just broke out and kept climbing to new highs isn't
    currently basing, however shallow its one pullback looks.

    Instead, anchor at the highest *confirmed* peak (excluding the trailing
    swing, which is always just the still-forming current extreme -- see
    find_swing_points) so only genuine structure since that peak counts.
    """
    weekly = _resample_weekly(window_df)
    swings = find_swing_points(weekly, pct_threshold=pct_threshold)
    if not swings:
        return []

    confirmed = swings[:-1] if len(swings) > 1 else swings
    confirmed_high_idx = [i for i, p in enumerate(confirmed) if p.kind == "high"]
    if not confirmed_high_idx:
        return []

    peak_idx = max(confirmed_high_idx, key=lambda i: swings[i].price)
    return swings[peak_idx:]


def analyze_contractions(seq: List[SwingPoint]) -> tuple[List[float], float, List[tuple]]:
    down_legs: List[float] = []
    leg_prices: List[tuple] = []  # (high_price, low_price) per confirmed contraction, chronological
    for i in range(0, len(seq) - 1, 2):
        hi, lo = seq[i], seq[i + 1]
        if hi.kind == "high" and lo.kind == "low" and hi.price > 0:
            down_legs.append((hi.price - lo.price) / hi.price * 100.0)
            leg_prices.append((hi.price, lo.price))

    if not down_legs:
        return [], 0.0, []

    if len(down_legs) == 1:
        pattern_score = 50.0
    else:
        pair_scores = []
        for i in range(len(down_legs) - 1):
            prev_leg, next_leg = down_legs[i], down_legs[i + 1]
            r = (next_leg / prev_leg) if prev_leg > 0 else 1.0
            pair_scores.append(_ratio_to_score(r, best=0.6, worst=1.0))
        pattern_score = sum(pair_scores) / len(pair_scores)

    score = 0.6 * pattern_score + 0.4 * _count_score(len(down_legs))
    return down_legs, score, leg_prices


def analyze_volume_dryup(
    df: pd.DataFrame, window_df: pd.DataFrame, base_slice: pd.DataFrame
) -> tuple[Optional[float], Optional[float], float]:
    if len(base_slice) < 4:
        return None, None, 0.0

    mid = len(base_slice) // 2
    first_half_vol = base_slice["Volume"].iloc[:mid].mean()
    second_half_vol = base_slice["Volume"].iloc[mid:].mean()
    dryup_ratio = float(second_half_vol / first_half_vol) if first_half_vol > 0 else 1.0

    vol50 = avg_volume(df, 50)
    recent10 = df["Volume"].tail(10).mean()
    baseline50 = vol50.iloc[-1]
    recent_ratio = float(recent10 / baseline50) if pd.notna(baseline50) and baseline50 > 0 else 1.0

    score_a = _ratio_to_score(dryup_ratio, best=0.5, worst=1.2)
    score_b = _ratio_to_score(recent_ratio, best=0.6, worst=1.3)
    score = 0.5 * score_a + 0.5 * score_b
    return dryup_ratio, recent_ratio, score


def analyze_tightness(df: pd.DataFrame, base_slice: pd.DataFrame) -> tuple[Optional[float], Optional[float], float]:
    if len(base_slice) < 10:
        return None, None, 0.0

    ranges = daily_range_pct(df)
    recent = float(ranges.tail(10).mean())
    base_ranges = daily_range_pct(base_slice)
    earlier = base_ranges.iloc[: max(len(base_ranges) - 10, 1)]
    base_avg = float(earlier.mean()) if len(earlier) else recent

    ratio = recent / base_avg if base_avg > 0 else 1.0
    score = _ratio_to_score(ratio, best=0.4, worst=1.0)
    return recent, base_avg, score


def analyze_prior_uptrend(
    df: pd.DataFrame, base_start: SwingPoint, base_start_price: float, pct_threshold: float
) -> tuple[Optional[float], float]:
    lookback_df = df.tail(min(len(df), 520))
    all_swings = find_swing_points(_resample_weekly(lookback_df), pct_threshold=pct_threshold)

    base_start_date = base_start.date
    candidate_lows = [p for p in all_swings if p.kind == "low" and p.date < base_start_date]
    if not candidate_lows:
        return None, 0.0

    launch = max(candidate_lows, key=lambda p: p.date)
    if launch.price <= 0:
        return None, 0.0

    pct = (base_start_price - launch.price) / launch.price * 100.0
    score = _ratio_to_score(-pct, best=-30.0, worst=-5.0)  # >=30% gain -> 100, <=5% -> 0
    return pct, score


def analyze_pivot_proximity(last_close: float, pivot_price: Optional[float]) -> tuple[Optional[float], float]:
    """Score how close price is to the pivot (base high / breakout trigger).

    Minervini's ideal entry is right at the pivot, not a stock that has
    already run well past it. `extension_pct` is signed: negative means
    price is still below the pivot (not broken out yet), positive means
    price has already cleared it. Score peaks near 0% either side and
    decays as the stock sits deeper in the base or gets further extended
    above the breakout.
    """
    if not pivot_price or pivot_price <= 0 or last_close <= 0:
        return None, 0.0

    extension = (last_close - pivot_price) / pivot_price * 100.0
    if extension <= 0:
        score = _ratio_to_score(-extension, best=3.0, worst=25.0)
    else:
        score = _ratio_to_score(extension, best=3.0, worst=20.0)
    return extension, score


def analyze_vcp(df: pd.DataFrame, pct_threshold: float = 8.0, base_lookback: int = 260) -> VCPAnalysis:
    """Run the full structural VCP analysis on a ticker's price history.

    `pct_threshold` is the ZigZag reversal threshold applied to *weekly*
    bars (see `_resample_weekly`) — the default of 8% targets legs on the
    order of Minervini's typical VCP contractions rather than daily noise.
    """
    result = VCPAnalysis()

    window_df = df.tail(base_lookback)
    seq = _find_base_sequence(window_df, pct_threshold)
    if not seq:
        return result

    down_legs, contraction_score, leg_prices = analyze_contractions(seq)
    result.contractions_pct = [round(x, 2) for x in down_legs]
    result.num_contractions = len(down_legs)
    result.contraction_score = contraction_score
    result.last_contraction_low = leg_prices[-1][1] if leg_prices else None

    base_start = seq[0]
    daily_pos = int(window_df.index.searchsorted(base_start.date))
    daily_pos = min(daily_pos, len(window_df) - 1)
    base_slice = window_df.iloc[daily_pos:]
    result.base_length_days = len(base_slice)
    result.base_start_date = base_start.date

    # The ZigZag's last point is always a provisional "current extreme" that
    # hasn't been confirmed by a reversal (see find_swing_points) -- for a
    # stock still actively running post-breakout that point is essentially
    # today's price, which would make the pivot chase price and mask
    # extension. Only confirmed highs count as the base's actual pivot.
    confirmed_seq = seq[:-1] if len(seq) > 1 else seq
    highs_in_seq = [p.price for p in confirmed_seq if p.kind == "high"]
    result.pivot_price = max(highs_in_seq) if highs_in_seq else float(base_slice["High"].max())

    result.volume_dryup_ratio, result.recent_volume_ratio, result.volume_dryup_score = (
        analyze_volume_dryup(df, window_df, base_slice)
    )

    result.recent_range_pct, result.base_range_pct, result.tightness_score = analyze_tightness(
        df, base_slice
    )

    result.prior_uptrend_pct, result.prior_uptrend_score = analyze_prior_uptrend(
        df, base_start, base_start.price, pct_threshold
    )

    result.pivot_extension_pct, result.pivot_proximity_score = analyze_pivot_proximity(
        float(df["Close"].iloc[-1]), result.pivot_price
    )

    return result
