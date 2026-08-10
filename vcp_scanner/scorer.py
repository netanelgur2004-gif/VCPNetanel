"""Combine trend template + VCP structural analysis into one 0-100 score."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .trend_template import TrendTemplateResult, evaluate_trend_template
from .vcp import VCPAnalysis, analyze_vcp

WEIGHTS = {
    "trend_template": 0.30,
    "contraction": 0.20,
    "volume_dryup": 0.15,
    "tightness": 0.10,
    "prior_uptrend": 0.10,
    "pivot_proximity": 0.15,
}

MAX_RISK_PCT = 8.0  # Minervini's usual hard cap on loss from entry


def suggest_stop_loss(
    last_close: float, structural_low: Optional[float], max_risk_pct: float = MAX_RISK_PCT
) -> tuple[float, float, str]:
    """Suggest a stop-loss price using Minervini's approach: the tighter of
    (a) just under the last contraction's low (a real support level breaking
    down would invalidate the base), or (b) a hard cap on loss from the
    current price. Never risk more than `max_risk_pct`, but take a tighter
    technical stop when the base offers one.
    """
    risk_cap_stop = last_close * (1 - max_risk_pct / 100.0)

    if structural_low is not None and 0 < structural_low < last_close:
        structural_stop = structural_low * 0.99  # a hair under the low, avoid whipsaw
        if structural_stop >= risk_cap_stop:
            stop_price, basis = structural_stop, "below last contraction's low"
        else:
            stop_price, basis = risk_cap_stop, f"{max_risk_pct:.0f}% max-risk cap"
    else:
        stop_price, basis = risk_cap_stop, f"{max_risk_pct:.0f}% max-risk cap"

    risk_pct = (last_close - stop_price) / last_close * 100.0
    return stop_price, risk_pct, basis


@dataclass
class VCPScore:
    ticker: str
    score: float
    trend: TrendTemplateResult
    vcp: VCPAnalysis
    rs_rating: Optional[float]
    last_close: float
    last_date: pd.Timestamp
    stop_loss_price: float = 0.0
    stop_loss_pct: float = 0.0
    stop_loss_basis: str = ""

    def component_scores(self) -> dict:
        return {
            "trend_template": self.trend.score,
            "contraction": self.vcp.contraction_score,
            "volume_dryup": self.vcp.volume_dryup_score,
            "tightness": self.vcp.tightness_score,
            "prior_uptrend": self.vcp.prior_uptrend_score,
            "pivot_proximity": self.vcp.pivot_proximity_score,
        }


def score_ticker(ticker: str, df: pd.DataFrame, rs_rating: Optional[float] = None) -> VCPScore:
    trend = evaluate_trend_template(df, rs_rating=rs_rating)
    vcp = analyze_vcp(df)

    components = {
        "trend_template": trend.score,
        "contraction": vcp.contraction_score,
        "volume_dryup": vcp.volume_dryup_score,
        "tightness": vcp.tightness_score,
        "prior_uptrend": vcp.prior_uptrend_score,
        "pivot_proximity": vcp.pivot_proximity_score,
    }
    total = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)

    last_close = float(df["Close"].iloc[-1])
    stop_price, stop_pct, stop_basis = suggest_stop_loss(last_close, vcp.last_contraction_low)

    return VCPScore(
        ticker=ticker,
        score=round(total, 1),
        trend=trend,
        vcp=vcp,
        rs_rating=rs_rating,
        last_close=last_close,
        last_date=df.index[-1],
        stop_loss_price=round(stop_price, 2),
        stop_loss_pct=round(stop_pct, 1),
        stop_loss_basis=stop_basis,
    )
