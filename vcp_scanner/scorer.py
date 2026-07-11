"""Combine trend template + VCP structural analysis into one 0-100 score."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .trend_template import TrendTemplateResult, evaluate_trend_template
from .vcp import VCPAnalysis, analyze_vcp

WEIGHTS = {
    "trend_template": 0.35,
    "contraction": 0.25,
    "volume_dryup": 0.20,
    "tightness": 0.10,
    "prior_uptrend": 0.10,
}


@dataclass
class VCPScore:
    ticker: str
    score: float
    trend: TrendTemplateResult
    vcp: VCPAnalysis
    rs_rating: Optional[float]
    last_close: float
    last_date: pd.Timestamp

    def component_scores(self) -> dict:
        return {
            "trend_template": self.trend.score,
            "contraction": self.vcp.contraction_score,
            "volume_dryup": self.vcp.volume_dryup_score,
            "tightness": self.vcp.tightness_score,
            "prior_uptrend": self.vcp.prior_uptrend_score,
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
    }
    total = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)

    return VCPScore(
        ticker=ticker,
        score=round(total, 1),
        trend=trend,
        vcp=vcp,
        rs_rating=rs_rating,
        last_close=float(df["Close"].iloc[-1]),
        last_date=df.index[-1],
    )
