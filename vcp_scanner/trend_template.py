"""Mark Minervini's 8-point Trend Template (Stage 2 uptrend checklist)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import pandas as pd

from .indicators import add_moving_averages, sma200_trend_up, week52_high_low


@dataclass
class TrendTemplateResult:
    checks: List[bool] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    price: float = 0.0
    sma50: float = 0.0
    sma150: float = 0.0
    sma200: float = 0.0
    high_52w: float = 0.0
    low_52w: float = 0.0
    pct_above_52w_low: float = 0.0
    pct_below_52w_high: float = 0.0

    @property
    def passed(self) -> int:
        return sum(self.checks)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def score(self) -> float:
        """0-100 score, weighted slightly toward the criteria Minervini treats as hard gates."""
        if not self.checks:
            return 0.0
        return 100.0 * self.passed / self.total


def evaluate_trend_template(df: pd.DataFrame, rs_rating: float | None = None) -> TrendTemplateResult:
    """Evaluate the 8-point trend template on the most recent bar of df.

    `rs_rating` is an optional 1-99 percentile relative-strength rating
    (see rs_rating.py). If not supplied, criterion 8 is skipped and the
    score is based on the remaining 7 criteria.
    """
    data = add_moving_averages(df)
    last = data.iloc[-1]

    price = float(last["Close"])
    sma50 = float(last["SMA50"]) if pd.notna(last["SMA50"]) else float("nan")
    sma150 = float(last["SMA150"]) if pd.notna(last["SMA150"]) else float("nan")
    sma200 = float(last["SMA200"]) if pd.notna(last["SMA200"]) else float("nan")
    high_52w, low_52w = week52_high_low(data)

    pct_above_low = ((price - low_52w) / low_52w * 100.0) if low_52w else 0.0
    pct_below_high = ((high_52w - price) / high_52w * 100.0) if high_52w else 100.0

    result = TrendTemplateResult(
        price=price,
        sma50=sma50,
        sma150=sma150,
        sma200=sma200,
        high_52w=high_52w,
        low_52w=low_52w,
        pct_above_52w_low=pct_above_low,
        pct_below_52w_high=pct_below_high,
    )

    def check(label: str, cond: bool) -> None:
        result.labels.append(label)
        result.checks.append(bool(cond))

    check("Price > 150-day & 200-day MA", price > sma150 and price > sma200)
    check("150-day MA > 200-day MA", sma150 > sma200)
    check("200-day MA trending up (>=1 month)", sma200_trend_up(data))
    check("50-day MA > 150-day MA & 200-day MA", sma50 > sma150 and sma50 > sma200)
    check("Price > 50-day MA", price > sma50)
    check("Price >= 25% above 52-week low", pct_above_low >= 25.0)
    check("Price within 25% of 52-week high", pct_below_high <= 25.0)

    if rs_rating is not None:
        check("Relative Strength rating >= 70", rs_rating >= 70.0)

    return result
