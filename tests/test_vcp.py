"""Sanity tests using synthetic OHLCV data with a hand-built VCP shape."""

import numpy as np
import pandas as pd
import pytest

from vcp_scanner.scorer import score_ticker
from vcp_scanner.swings import find_swing_points
from vcp_scanner.trend_template import evaluate_trend_template


def _make_df(closes: list[float], volumes: list[float], start="2023-01-02") -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=len(closes))
    closes = np.array(closes, dtype=float)
    highs = closes * 1.01
    lows = closes * 0.99
    opens = closes
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=dates,
    )


def _synthetic_vcp_series() -> tuple[list[float], list[float]]:
    rng = np.random.default_rng(42)

    # Prior uptrend: ~1 year rising from 20 to 100 (+400%)
    uptrend = list(np.linspace(20, 100, 220) + rng.normal(0, 0.3, 220))

    # Contraction 1: -25%, contraction 2: -15%, contraction 3: -8%, contraction 4: -4%
    def leg(start, pct_down, n_down, n_up_recover_frac):
        low = start * (1 - pct_down / 100)
        down = list(np.linspace(start, low, n_down) + rng.normal(0, 0.15, n_down))
        recover_to = start * (1 - (pct_down / 100) * (1 - n_up_recover_frac))
        up = list(np.linspace(low, recover_to, max(n_down // 2, 3)) + rng.normal(0, 0.15, max(n_down // 2, 3)))
        return down + up, recover_to

    base = 100.0
    prices = list(uptrend)
    vols = list(np.linspace(3_000_000, 6_000_000, len(uptrend)) + rng.normal(0, 50_000, len(uptrend)))

    pct_steps = [25, 15, 8, 4]
    n_downs = [20, 16, 12, 8]
    cur = base
    for pct, n in zip(pct_steps, n_downs):
        seg, cur = leg(cur, pct, n, 0.9)
        prices.extend(seg)

    total_base_len = sum(n + max(n // 2, 3) for n in n_downs)
    base_vol = np.linspace(5_000_000, 1_200_000, total_base_len) + rng.normal(0, 30_000, total_base_len)
    vols.extend(base_vol)

    # Tight final drift near the pivot, very low volume
    tail_n = 10
    tail = list(cur + rng.normal(0, 0.3, tail_n))
    prices.extend(tail)
    vols.extend(np.linspace(1_000_000, 800_000, tail_n))

    vols = [max(float(v), 1000.0) for v in vols]
    return prices, vols


def test_swing_detection_finds_points():
    prices, vols = _synthetic_vcp_series()
    df = _make_df(prices, vols)
    swings = find_swing_points(df, pct_threshold=3.0)
    assert len(swings) >= 4
    kinds = {p.kind for p in swings}
    assert "high" in kinds and "low" in kinds


def test_trend_template_passes_most_criteria_in_uptrend():
    prices, vols = _synthetic_vcp_series()
    df = _make_df(prices, vols)
    result = evaluate_trend_template(df, rs_rating=90)
    assert result.passed >= 5
    assert 0 <= result.score <= 100


def test_score_ticker_produces_bounded_score_and_detects_contractions():
    prices, vols = _synthetic_vcp_series()
    df = _make_df(prices, vols)
    result = score_ticker("TEST", df, rs_rating=85)

    assert 0 <= result.score <= 100
    assert result.vcp.num_contractions >= 2
    # Should be a reasonably strong match given the hand-built decreasing contractions
    assert result.score >= 40


def test_flat_random_walk_scores_lower_than_clean_vcp():
    rng = np.random.default_rng(7)
    flat_prices = list(100 + np.cumsum(rng.normal(0, 1.0, 260)))
    flat_prices = [max(p, 1.0) for p in flat_prices]
    flat_vols = list(rng.uniform(1_000_000, 2_000_000, 260))
    flat_df = _make_df(flat_prices, flat_vols)

    vcp_prices, vcp_vols = _synthetic_vcp_series()
    vcp_df = _make_df(vcp_prices, vcp_vols)

    flat_score = score_ticker("FLAT", flat_df, rs_rating=50).score
    vcp_score = score_ticker("VCP", vcp_df, rs_rating=85).score

    assert vcp_score > flat_score


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
