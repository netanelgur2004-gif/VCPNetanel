"""Tests for the SMA20 extension/catalyst screen using synthetic OHLCV data."""

import numpy as np
import pandas as pd

from vcp_scanner.extension_scan import detect_price_shock, scan_sma20_extension
from vcp_scanner.news import catalyst_headlines


def _make_df(closes: list[float], volumes: list[float], start="2023-01-02") -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=len(closes))
    closes = np.array(closes, dtype=float)
    highs = closes * 1.01
    lows = closes * 0.99
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=dates,
    )


def _flat_series(n=280, level=100.0, vol=1_000_000.0):
    return [level] * n, [vol] * n


def test_detect_price_shock_flags_big_move_on_high_volume():
    closes, vols = _flat_series(n=60)
    # A single-day 10% gap on 3x volume near the end of the window.
    closes[-5] = closes[-6] * 1.10
    vols[-5] = vols[-6] * 3
    for i in range(-4, 0):
        closes[i] = closes[-5]
    df = _make_df(closes, vols)

    shock = detect_price_shock(df, lookback_days=20)
    assert shock is not None
    assert shock.move_pct > 6.0
    assert shock.volume_ratio > 1.5


def test_detect_price_shock_ignores_quiet_drift():
    rng = np.random.default_rng(0)
    closes = list(100 + np.cumsum(rng.normal(0, 0.2, 60)))
    vols = list(rng.uniform(900_000, 1_100_000, 60))
    df = _make_df(closes, vols)

    assert detect_price_shock(df, lookback_days=20) is None


def test_scan_sma20_extension_flags_stock_above_and_below_range():
    # Gradual drift over the last 20 days, sized so (last_close - SMA20) / SMA20
    # lands at ~17.5%: for a linear ramp the whole SMA20 window, deviation =
    # (X - 100) / (X + 100), so X = 142 gives +17.5% and X = 70 gives -17.5%.
    base_n = 260
    base_closes = [100.0] * base_n
    drift = list(np.linspace(100.0, 142.0, 20))
    up_closes = base_closes[: base_n - 20] + drift
    up_vols = [1_000_000.0] * base_n

    drift_down = list(np.linspace(100.0, 70.0, 20))
    down_closes = base_closes[: base_n - 20] + drift_down
    down_vols = [1_000_000.0] * base_n

    histories = {
        "UP": _make_df(up_closes, up_vols),
        "DOWN": _make_df(down_closes, down_vols),
    }

    results = scan_sma20_extension(histories, low_pct=15.0, high_pct=20.0, fetch_news=False)
    tickers = {r.ticker: r for r in results}

    assert tickers["UP"].direction == "above"
    assert tickers["DOWN"].direction == "below"
    assert not tickers["UP"].has_catalyst
    assert not tickers["DOWN"].has_catalyst


def test_scan_sma20_extension_skips_stocks_within_normal_range():
    closes = [100.0] * 260 + list(np.linspace(100.0, 103.0, 20))
    vols = [1_000_000.0] * 280
    histories = {"FLAT": _make_df(closes, vols)}

    results = scan_sma20_extension(histories, low_pct=15.0, high_pct=20.0, fetch_news=False)
    assert results == []


def test_catalyst_headlines_matches_keywords_case_insensitively():
    news = [
        {"title": "Company Beats EARNINGS Estimates", "publisher": "X", "time": None, "url": ""},
        {"title": "Stock drifts higher with broader market", "publisher": "X", "time": None, "url": ""},
    ]
    hits = catalyst_headlines(news)
    assert len(hits) == 1
    assert "Earnings" in hits[0]["title"] or "EARNINGS" in hits[0]["title"]
