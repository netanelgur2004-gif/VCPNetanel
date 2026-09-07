"""Sanity tests using synthetic OHLCV data with a hand-built VCP shape."""

import numpy as np
import pandas as pd
import pytest

from vcp_scanner.market_sentiment import fetch_fear_greed_index
from vcp_scanner.scanner import filter_setups
from vcp_scanner.scorer import VCPScore, score_ticker, suggest_stop_loss
from vcp_scanner.swings import find_swing_points
from vcp_scanner.trend_template import TrendTemplateResult, evaluate_trend_template
from vcp_scanner.vcp import VCPAnalysis


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


def test_extended_stock_scores_lower_pivot_proximity_than_near_pivot():
    prices, vols = _synthetic_vcp_series()
    df = _make_df(prices, vols)
    near = score_ticker("NEAR", df, rs_rating=85)

    # Same base, but tack on a strong rally well past the pivot -- an
    # already-extended breakout, not an about-to-break-out setup.
    rng = np.random.default_rng(99)
    runup_n = 15
    runup = list(np.linspace(prices[-1], prices[-1] * 1.3, runup_n) + rng.normal(0, 0.3, runup_n))
    ext_prices = list(prices) + runup
    ext_vols = list(vols) + list(np.linspace(vols[-1], vols[-1] * 1.5, runup_n))
    ext_df = _make_df(ext_prices, ext_vols)
    extended = score_ticker("EXT", ext_df, rs_rating=85)

    assert extended.vcp.pivot_extension_pct is not None
    assert extended.vcp.pivot_extension_pct > 10  # meaningfully through the pivot
    assert extended.vcp.pivot_proximity_score < near.vcp.pivot_proximity_score


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


def test_suggest_stop_loss_uses_tighter_of_structural_and_risk_cap():
    # Structural low is tighter than the 8% cap -> use it.
    stop, pct, basis = suggest_stop_loss(last_close=100.0, structural_low=95.0)
    assert stop == pytest.approx(95.0 * 0.99)
    assert pct < 8.0
    assert "contraction" in basis

    # Structural low is far below entry -> the 8% cap is tighter, use it instead.
    stop, pct, basis = suggest_stop_loss(last_close=100.0, structural_low=70.0)
    assert stop == pytest.approx(92.0)
    assert pct == pytest.approx(8.0)
    assert "max-risk" in basis

    # No structural low available -> fall back to the risk cap.
    stop, pct, basis = suggest_stop_loss(last_close=50.0, structural_low=None)
    assert stop == pytest.approx(46.0)
    assert pct == pytest.approx(8.0)


def test_score_ticker_includes_sane_stop_loss():
    prices, vols = _synthetic_vcp_series()
    df = _make_df(prices, vols)
    result = score_ticker("TEST", df, rs_rating=85)

    assert 0 < result.stop_loss_price < result.last_close
    assert 0 < result.stop_loss_pct <= 8.1  # small tolerance for the 1% whipsaw buffer
    assert result.stop_loss_basis


def test_fear_greed_index_degrades_gracefully_on_network_failure(monkeypatch):
    def _boom(*args, **kwargs):
        raise ConnectionError("no network in this test")

    monkeypatch.setattr("vcp_scanner.market_sentiment.requests.get", _boom)
    assert fetch_fear_greed_index() is None


def _fake_score(ticker: str, pivot_extension_pct, base_length_days: int) -> VCPScore:
    vcp = VCPAnalysis(pivot_extension_pct=pivot_extension_pct, base_length_days=base_length_days)
    return VCPScore(
        ticker=ticker,
        score=50.0,
        trend=TrendTemplateResult(),
        vcp=vcp,
        rs_rating=50,
        last_close=100.0,
        last_date=pd.Timestamp("2024-01-01"),
    )


def test_filter_setups_excludes_extended_and_short_bases():
    scores = [
        _fake_score("NEAR", pivot_extension_pct=1.0, base_length_days=30),
        _fake_score("EXTENDED", pivot_extension_pct=12.0, base_length_days=30),
        _fake_score("SHORTBASE", pivot_extension_pct=1.0, base_length_days=10),
        _fake_score("NOBASE", pivot_extension_pct=None, base_length_days=0),
    ]
    kept = filter_setups(scores, max_extension_pct=5.0, min_base_weeks=4.0)
    assert [s.ticker for s in kept] == ["NEAR"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
