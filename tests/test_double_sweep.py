"""Tests for the Double-Sweep Base pattern (vcp_scanner/double_sweep.py).

A fully separate module from the existing VCP pipeline -- these tests only
import from double_sweep.py (plus pandas/numpy for building synthetic
OHLCV), and don't touch vcp.py, scorer.py, or scanner.py at all.
"""

import numpy as np
import pandas as pd
import pytest

from vcp_scanner.double_sweep import DoubleSweepConfig, analyze_double_sweep


def _build_df(opens, highs, lows, closes, vols, start="2023-01-02") -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=len(closes))
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols}, index=dates
    )


def _simple_bar(c: float, rng_pct: float = 0.4) -> tuple[float, float, float, float]:
    """A plain daily bar with no sweep character: High/Low a small % off Close."""
    return c, c * (1 + rng_pct / 100), c * (1 - rng_pct / 100), c


# Config used across these tests: smaller fractal window and a shorter
# lookback than production defaults, purely to keep the synthetic series
# (hand-built bar by bar below) a manageable length. `sweep_zone_bars=40`
# reserves the back half of the 76-bar window for the two sweeps and the
# post-sweep contraction, keeping the base-range definition (the earlier
# swing high/low) clear of them.
TEST_CFG = DoubleSweepConfig(
    fractal_n=3,
    lookback_bars=76,
    max_reclaim_bars=2,
    max_final_contraction_pct=10.0,
    sweep_zone_bars=40,
)


def _build_double_sweep_series(variant: str = "valid") -> pd.DataFrame:
    """Hand-built OHLCV: a long uptrend (for the trend-template gate), a
    base with a clear swing high (100) and swing low (~84.7), then -- per
    `variant` -- a clean double sweep with tightening contraction, or one
    of three ways that should make it NOT match.
    """
    rng = np.random.default_rng(3)
    O, H, L, C, V = [], [], [], [], []

    def push(o, h, l, c, v):
        O.append(o)
        H.append(h)
        L.append(l)
        C.append(c)
        V.append(v)

    # Long uptrend: satisfies the trend template gate (MAs stacked & rising).
    n_up = 230
    trend_closes = np.linspace(20, 100, n_up) + rng.normal(0, 0.15, n_up)
    for c in trend_closes:
        push(*_simple_bar(c), 3_000_000)

    # Base: establishes swing high (d4=100) and swing low (d13=85), plus
    # interior structure, all within the "definition zone" of the window
    # (i.e. more than sweep_zone_bars=40 bars before the window's end).
    base_closes = [
        96, 97, 98, 99, 100,  # d0-4: swing high at d4 = 100
        99, 98, 97, 96,  # d5-8
        94, 92, 90, 88, 85,  # d9-13: swing low at d13 = 85
        87, 89, 91, 93,  # d14-17
        94, 95, 96, 97,  # d18-21: lower high (below 100, doesn't change range)
        96, 95, 94, 93,  # d22-25
        92, 90, 89, 88,  # d26-29: higher low (above 85, doesn't change range)
        89, 91, 93, 95,  # d30-33
        96, 97, 98, 99,  # d34-37
    ]
    for c in base_closes:
        push(*_simple_bar(c), 1_800_000)

    # --- HIGH SWEEP candidate bar (d38): wick to 101.5, ~1.1% above 100.4 ---
    if variant == "accepted_breakout":
        # Genuine breakout: 2 consecutive closes above the level, straight away.
        push(99.5, 101.5, 99.3, 100.8, 2_800_000)
    else:
        push(99.5, 101.5, 99.0, 99.3, 2_800_000)  # closes back under, same bar

    if variant == "accepted_breakout":
        post_sweep1 = [101.0, 101.3, 100.5, 99.0, 96.0, 93.0, 90.0, 87.0]
    else:
        post_sweep1 = [98, 97, 96, 94, 92, 90, 88, 86]
    for c in post_sweep1:
        push(*_simple_bar(c), 1_600_000)

    # --- LOW SWEEP candidate bar (d47): wick to 83.725, ~1.1% below range_low ---
    if variant == "only_one_side":
        # Shallow dip only -- never actually reaches the sweep-% band.
        push(86.5, 87.0, 85.8, 86.3, 2_900_000)
    else:
        push(85.5, 86.0, 83.725, 85.3, 2_900_000)  # closes back above, same bar

    if variant == "loose_contraction":
        # Legs that do NOT shrink (leg2 > leg1), but stay inside the range
        # throughout, so this isolates the "not shrinking" rejection from
        # a range-breakdown rejection.
        contraction_closes = [
            87, 91, 94, 95,  # swing high = 95
            94, 92, 91, 90,  # swing low = 90   -> leg1 = (95-90)/95  = 5.26%
            91, 93, 95, 96,  # swing high = 96
            94, 92, 90, 88,  # swing low = 88   -> leg2 = (96-88)/96  = 8.33% (bigger!)
            90, 92, 95, 97,  # swing high = 97
            95, 94, 93.5, 93,  # swing low = 93 -> leg3 = (97-93)/97  = 4.12%
            94, 95, 94.5, 94,  # trailing
        ]
        vols_tail = [1_600_000] * len(contraction_closes)
    else:
        contraction_closes = [
            87, 89, 91, 93,  # swing high = 93
            92, 91, 90, 89,  # swing low = 89   -> leg1 = (93-89)/93  = 4.30%
            90, 91, 92, 93.5,  # swing high = 93.5
            92.5, 91.5, 90.8, 90.2,  # swing low = 90.2 -> leg2 = 3.53%
            91, 91.8, 92.5, 93.8,  # swing high = 93.8
            93.2, 92.9, 92.8, 92.7,  # swing low = 92.7 -> leg3 = 1.17% (final, tight)
            93.0, 93.1, 93.0, 92.95,  # trailing
        ]
        vols_tail = (
            [1_500_000, 1_450_000, 1_400_000, 1_400_000] * 2
            + [1_300_000, 1_250_000, 1_200_000, 1_150_000]
            + [900_000, 850_000, 820_000, 800_000]  # volume dry-up into the close
        )
    for i, c in enumerate(contraction_closes):
        o, h, l, cl = _simple_bar(c, rng_pct=0.3)
        push(o, h, l, cl, vols_tail[i] if i < len(vols_tail) else 800_000)

    return _build_df(O, H, L, C, V)


def test_valid_double_sweep_is_detected():
    df = _build_double_sweep_series("valid")
    result = analyze_double_sweep("TEST", df, TEST_CFG)

    assert result.matched, result.reason
    assert result.high_sweep is not None
    assert result.low_sweep is not None
    assert result.base is not None
    assert result.contraction is not None
    assert result.contraction.shrinking
    assert result.pivot_price == pytest.approx(result.base.range_high)
    assert 0 < result.score <= 100


def test_accepted_breakout_is_rejected_not_counted_as_sweep():
    # High break WITH acceptance (2+ consecutive closes beyond the level)
    # is a breakout, not a sweep -- must not match.
    df = _build_double_sweep_series("accepted_breakout")
    result = analyze_double_sweep("TEST", df, TEST_CFG)

    assert not result.matched
    assert result.high_sweep is None
    assert result.low_sweep is not None  # low side alone isn't enough


def test_single_side_sweep_is_rejected():
    df = _build_double_sweep_series("only_one_side")
    result = analyze_double_sweep("TEST", df, TEST_CFG)

    assert not result.matched
    assert result.high_sweep is not None
    assert result.low_sweep is None


def test_loose_post_sweep_contraction_is_rejected():
    df = _build_double_sweep_series("loose_contraction")
    result = analyze_double_sweep("TEST", df, TEST_CFG)

    assert not result.matched
    assert result.high_sweep is not None
    assert result.low_sweep is not None  # both sides swept...
    assert result.contraction is not None
    assert not result.contraction.shrinking  # ...but the pullbacks widen, not tighten
    assert "shrink" in result.reason.lower()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
