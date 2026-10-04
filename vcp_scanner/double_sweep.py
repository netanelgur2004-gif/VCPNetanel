"""Double-Sweep Base pattern detector.

A VCP-style consolidation where BOTH a prior swing high and a prior swing
low inside the base were liquidated ("swept") -- price poked beyond the
level on an intrabar basis but was never *accepted* there (no two
consecutive closes beyond it), reclaimed the range within a few bars, and
then the subsequent pullbacks tightened inside that same range.

This is a fully separate pattern module: it does not change anything in
vcp.py, scorer.py, or scanner.py, and importing/using it has zero effect on
the existing VCP scan, its scoring weights, or its hard filters. It reuses
two pieces of the existing pipeline directly (trend_template.py for the
Stage-2 gate, indicators.py for ATR/volume) rather than re-implementing
them, and uses its own fractal-based swing detector (a different method
from the percentage-ZigZag in swings.py, because this pattern specifically
needs "a prior swing level that was then swept", not shrinking contraction
legs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from .indicators import average_true_range, avg_volume
from .swings import SwingPoint
from .trend_template import evaluate_trend_template


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------


@dataclass
class DoubleSweepConfig:
    fractal_n: int = 4  # bars on each side for a fractal swing point (3-5 typical)
    lookback_bars: int = 60  # daily bars defining the base window (20-80 range)
    max_depth_pct: float = 35.0  # (range_high - range_low) / range_high

    min_sweep_pct: float = 0.1  # how far beyond the level the wick must reach
    max_sweep_pct: float = 3.0
    max_reclaim_bars: int = 3  # bars allowed before a close back inside the level
    sweep_volume_multiplier: float = 1.5  # bonus threshold vs 50-day avg volume

    max_final_contraction_pct: float = 8.0  # last leg must be tighter than this
    min_trend_template_checks: Optional[int] = None  # None = require all available checks

    sweep_zone_bars: int = 25  # most recent bars of the lookback reserved for sweeps+contraction


# ----------------------------------------------------------------------
# Fractal swing detection (distinct from swings.py's percentage ZigZag)
# ----------------------------------------------------------------------


def find_fractal_swings(df: pd.DataFrame, n: int = 4) -> List[SwingPoint]:
    """A bar is a swing high/low if it's more extreme than the `n` bars on
    each side of it (strict inequality). Unlike the ZigZag in swings.py,
    this doesn't alternate or filter by magnitude -- it just flags local
    extremes, which is what "a prior swing high/low" needs for sweep
    detection (the level swept is a literal local extreme, not a
    threshold-filtered trend pivot).
    """
    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    dates = df.index
    points: List[SwingPoint] = []

    for i in range(n, len(df) - n):
        window_high = highs[i - n : i + n + 1]
        if highs[i] == window_high.max() and (highs[i] > highs[i - n : i]).all() and (
            highs[i] > highs[i + 1 : i + n + 1]
        ).all():
            points.append(SwingPoint(dates[i], float(highs[i]), "high", i))

        window_low = lows[i - n : i + n + 1]
        if lows[i] == window_low.min() and (lows[i] < lows[i - n : i]).all() and (
            lows[i] < lows[i + 1 : i + n + 1]
        ).all():
            points.append(SwingPoint(dates[i], float(lows[i]), "low", i))

    points.sort(key=lambda p: p.index)
    return points


# ----------------------------------------------------------------------
# Small local helper (deliberately not imported from vcp.py -- this module
# stays decoupled from the existing VCP scorer's internals)
# ----------------------------------------------------------------------


def _ratio_to_score(ratio: float, best: float, worst: float) -> float:
    if best == worst:
        return 100.0
    t = (ratio - worst) / (best - worst)
    return 100.0 * max(0.0, min(1.0, t))


# ----------------------------------------------------------------------
# Base range
# ----------------------------------------------------------------------


@dataclass
class BaseRange:
    range_high: float
    range_low: float
    depth_pct: float
    window_start_idx: int  # positional index into the full df
    high_set_idx: int
    low_set_idx: int


def find_base_range(df: pd.DataFrame, cfg: DoubleSweepConfig) -> Optional[BaseRange]:
    """Establish the base's range_high/range_low from the *earlier* part of
    the lookback window only -- the most recent `sweep_zone_bars` are
    reserved for the sweeps and the post-sweep contraction. Without this
    split, a sweep bar (which by definition is more extreme than the range
    it swept) would just get picked up as the range extreme itself, making
    a sweep structurally impossible to detect.
    """
    window_df = df.tail(cfg.lookback_bars)
    if len(window_df) < cfg.fractal_n * 2 + 5:
        return None

    definition_len = max(len(window_df) - cfg.sweep_zone_bars, cfg.fractal_n * 2 + 1)
    definition_df = window_df.iloc[:definition_len]

    swings = find_fractal_swings(definition_df, cfg.fractal_n)
    highs = [p for p in swings if p.kind == "high"]
    lows = [p for p in swings if p.kind == "low"]
    if not highs or not lows:
        return None

    top = max(highs, key=lambda p: p.price)
    bottom = min(lows, key=lambda p: p.price)
    if top.price <= 0:
        return None

    depth_pct = (top.price - bottom.price) / top.price * 100.0
    if depth_pct > cfg.max_depth_pct or depth_pct <= 0:
        return None

    window_start_idx = len(df) - len(window_df)
    return BaseRange(
        range_high=top.price,
        range_low=bottom.price,
        depth_pct=depth_pct,
        window_start_idx=window_start_idx,
        high_set_idx=window_start_idx + top.index,
        low_set_idx=window_start_idx + bottom.index,
    )


# ----------------------------------------------------------------------
# Sweep detection
# ----------------------------------------------------------------------


@dataclass
class SweepEvent:
    kind: str  # "high" or "low"
    index: int  # positional index into df of the sweep bar
    date: pd.Timestamp
    level: float  # the swept level (range_high or range_low)
    extreme: float  # the bar's High (high sweep) or Low (low sweep)
    reclaim_index: int  # positional index of the bar that closed back inside
    reclaim_bars: int  # reclaim_index - index
    volume_ratio: float  # sweep-bar volume / 50-day avg volume at that point
    wick_quality: float  # 0-1, where the close sat in the bar's range
    quality_score: float = 0.0


def _resolve_excursion(closes, i: int, level: float, above: bool, horizon_end: int, max_reclaim_bars: int):
    """Starting at candidate bar `i` (the first bar poking beyond `level`),
    walk forward through the whole excursion as one unit: either it gets
    accepted (2+ consecutive closes beyond the level) or it reclaims
    (a close back on the inside) within `max_reclaim_bars`.

    Resolving bar-by-bar independently (checking each bar's own short
    forward window) misses this: in a multi-bar choppy breakout attempt, a
    later bar within the same excursion can look locally fine even though
    an earlier adjacent pair already closed beyond the level twice in a
    row -- that pair has to be caught from the excursion's start, not
    re-missed by restarting the window at every bar.

    Returns (reclaim_index_or_None, accepted: bool, resume_at: int) -- the
    caller should resume scanning for new candidates at `resume_at`.
    """
    j = i
    while j < horizon_end:
        beyond = (closes[j] >= level) if above else (closes[j] <= level)
        if beyond and j + 1 < horizon_end:
            next_beyond = (closes[j + 1] >= level) if above else (closes[j + 1] <= level)
            if next_beyond:
                return None, True, j + 2
        inside = (closes[j] < level) if above else (closes[j] > level)
        if inside:
            reclaim_index = j
            if reclaim_index - i <= max_reclaim_bars:
                return reclaim_index, False, reclaim_index + 1
            return None, False, j + 1
        j += 1
    return None, False, horizon_end


def find_high_sweep(
    df: pd.DataFrame, level: float, search_start: int, search_end: int, cfg: DoubleSweepConfig
) -> Optional[SweepEvent]:
    """Most recent qualifying high-sweep of `level` within df.iloc[search_start:search_end]."""
    highs = df["High"].to_numpy()
    closes = df["Close"].to_numpy()
    lows = df["Low"].to_numpy()
    vols = df["Volume"].to_numpy()
    vol50 = avg_volume(df, 50).to_numpy()

    if level <= 0:
        return None

    best: Optional[SweepEvent] = None
    horizon = max(cfg.max_reclaim_bars, 5) + 1
    end = min(search_end, len(df))
    i = search_start
    while i < end:
        sweep_pct = (highs[i] - level) / level * 100.0
        if not (cfg.min_sweep_pct <= sweep_pct <= cfg.max_sweep_pct):
            i += 1
            continue

        horizon_end = min(i + horizon, len(df))
        reclaim_index, accepted, resume_at = _resolve_excursion(
            closes, i, level, above=True, horizon_end=horizon_end, max_reclaim_bars=cfg.max_reclaim_bars
        )
        if accepted or reclaim_index is None:
            i = resume_at
            continue

        bar_range = highs[i] - lows[i]
        wick_quality = 1.0 - ((closes[i] - lows[i]) / bar_range) if bar_range > 0 else 0.5
        vol_ratio = float(vols[i] / vol50[i]) if pd.notna(vol50[i]) and vol50[i] > 0 else 1.0

        best = SweepEvent(
            kind="high",
            index=i,
            date=df.index[i],
            level=level,
            extreme=float(highs[i]),
            reclaim_index=reclaim_index,
            reclaim_bars=reclaim_index - i,
            volume_ratio=vol_ratio,
            wick_quality=wick_quality,
        )
        i = resume_at  # keep scanning afterward for a possibly more recent sweep

    return best


def find_low_sweep(
    df: pd.DataFrame, level: float, search_start: int, search_end: int, cfg: DoubleSweepConfig
) -> Optional[SweepEvent]:
    """Most recent qualifying low-sweep of `level` within df.iloc[search_start:search_end]."""
    lows = df["Low"].to_numpy()
    closes = df["Close"].to_numpy()
    highs = df["High"].to_numpy()
    vols = df["Volume"].to_numpy()
    vol50 = avg_volume(df, 50).to_numpy()

    if level <= 0:
        return None

    best: Optional[SweepEvent] = None
    horizon = max(cfg.max_reclaim_bars, 5) + 1
    end = min(search_end, len(df))
    i = search_start
    while i < end:
        sweep_pct = (level - lows[i]) / level * 100.0
        if not (cfg.min_sweep_pct <= sweep_pct <= cfg.max_sweep_pct):
            i += 1
            continue

        horizon_end = min(i + horizon, len(df))
        reclaim_index, accepted, resume_at = _resolve_excursion(
            closes, i, level, above=False, horizon_end=horizon_end, max_reclaim_bars=cfg.max_reclaim_bars
        )
        if accepted or reclaim_index is None:
            i = resume_at
            continue

        bar_range = highs[i] - lows[i]
        # "long lower wick, close in upper 50% of the bar's range" -> quality in [0,1]
        wick_quality = (closes[i] - lows[i]) / bar_range if bar_range > 0 else 0.5
        vol_ratio = float(vols[i] / vol50[i]) if pd.notna(vol50[i]) and vol50[i] > 0 else 1.0

        best = SweepEvent(
            kind="low",
            index=i,
            date=df.index[i],
            level=level,
            extreme=float(lows[i]),
            reclaim_index=reclaim_index,
            reclaim_bars=reclaim_index - i,
            volume_ratio=vol_ratio,
            wick_quality=wick_quality,
        )
        i = resume_at

    return best


def _sweep_quality_score(event: SweepEvent, cfg: DoubleSweepConfig) -> float:
    reclaim_score = _ratio_to_score(event.reclaim_bars, best=0, worst=cfg.max_reclaim_bars)
    volume_score = _ratio_to_score(event.volume_ratio, best=2.0, worst=1.0)
    wick_score = _ratio_to_score(event.wick_quality, best=1.0, worst=0.5)
    return round((reclaim_score + volume_score + wick_score) / 3.0, 1)


# ----------------------------------------------------------------------
# Post-sweep contraction
# ----------------------------------------------------------------------


@dataclass
class ContractionResult:
    legs_pct: List[float] = field(default_factory=list)
    final_contraction_pct: Optional[float] = None
    shrinking: bool = False
    atr10_at_sweep: Optional[float] = None
    atr10_now: Optional[float] = None
    atr_declining: bool = False
    volume_dryup_ratio: Optional[float] = None
    volume_dried_up: bool = False
    last_contraction_low: Optional[float] = None


def analyze_post_sweep_contraction(
    df: pd.DataFrame, from_idx: int, sweep_bar_idx: int, cfg: DoubleSweepConfig
) -> ContractionResult:
    result = ContractionResult()
    sub = df.iloc[from_idx:]
    if len(sub) < cfg.fractal_n * 2 + 3:
        return result

    swings = find_fractal_swings(sub, max(2, cfg.fractal_n - 1))
    legs: List[float] = []
    last_low = None
    # Pair each high with the next low that follows it chronologically.
    pending_high = None
    for p in swings:
        if p.kind == "high":
            pending_high = p
        elif p.kind == "low" and pending_high is not None and pending_high.price > 0:
            legs.append((pending_high.price - p.price) / pending_high.price * 100.0)
            last_low = p.price
            pending_high = None

    result.legs_pct = [round(x, 2) for x in legs]
    result.last_contraction_low = last_low
    if legs:
        result.final_contraction_pct = legs[-1]
        result.shrinking = all(legs[i + 1] < legs[i] for i in range(len(legs) - 1)) if len(legs) > 1 else True

    atr10 = average_true_range(df, 10)
    if sweep_bar_idx < len(atr10):
        atr_at_sweep = atr10.iloc[sweep_bar_idx]
        atr_now = atr10.iloc[-1]
        if pd.notna(atr_at_sweep) and pd.notna(atr_now):
            result.atr10_at_sweep = float(atr_at_sweep)
            result.atr10_now = float(atr_now)
            result.atr_declining = atr_now < atr_at_sweep

    vol10 = df["Volume"].tail(10).mean()
    vol50 = avg_volume(df, 50).iloc[-1]
    if pd.notna(vol50) and vol50 > 0:
        result.volume_dryup_ratio = float(vol10 / vol50)
        result.volume_dried_up = result.volume_dryup_ratio < 1.0

    return result


# ----------------------------------------------------------------------
# Full pattern analysis
# ----------------------------------------------------------------------


@dataclass
class DoubleSweepResult:
    ticker: str = ""
    matched: bool = False
    reason: str = ""

    base: Optional[BaseRange] = None
    high_sweep: Optional[SweepEvent] = None
    low_sweep: Optional[SweepEvent] = None
    contraction: Optional[ContractionResult] = None

    pivot_price: Optional[float] = None
    stop_price: Optional[float] = None
    distance_to_pivot_pct: Optional[float] = None

    score: float = 0.0
    last_close: Optional[float] = None
    last_date: Optional[pd.Timestamp] = None


def analyze_double_sweep(
    ticker: str, df: pd.DataFrame, cfg: Optional[DoubleSweepConfig] = None
) -> DoubleSweepResult:
    cfg = cfg or DoubleSweepConfig()
    result = DoubleSweepResult(ticker=ticker)
    if len(df) == 0:
        result.reason = "no data"
        return result

    result.last_close = float(df["Close"].iloc[-1])
    result.last_date = df.index[-1]

    # Gate: must already pass the existing trend template. Called, not
    # duplicated -- this module owns none of that logic.
    trend = evaluate_trend_template(df, rs_rating=None)
    required = cfg.min_trend_template_checks
    if required is None:
        required = trend.total
    if trend.passed < required:
        result.reason = f"trend template: {trend.passed}/{trend.total} (need {required})"
        return result

    base = find_base_range(df, cfg)
    if base is None:
        result.reason = "no valid base range found"
        return result
    result.base = base

    search_start = max(base.high_set_idx, base.low_set_idx) + 1
    search_end = len(df)

    high_sweep = find_high_sweep(df, base.range_high, search_start, search_end, cfg)
    low_sweep = find_low_sweep(df, base.range_low, search_start, search_end, cfg)
    result.high_sweep = high_sweep
    result.low_sweep = low_sweep

    if high_sweep is None and low_sweep is None:
        result.reason = "neither side swept"
        return result
    if high_sweep is None:
        result.reason = "high side never swept (low sweep only)"
        return result
    if low_sweep is None:
        result.reason = "low side never swept (high sweep only)"
        return result

    high_sweep.quality_score = _sweep_quality_score(high_sweep, cfg)
    low_sweep.quality_score = _sweep_quality_score(low_sweep, cfg)

    second_sweep = high_sweep if high_sweep.reclaim_index > low_sweep.reclaim_index else low_sweep
    after_second = second_sweep.reclaim_index + 1

    closes = df["Close"].to_numpy()
    if _has_range_acceptance_violation(closes, after_second, base.range_high, base.range_low):
        result.reason = "price broke and was accepted outside the range after the second sweep"
        return result

    contraction = analyze_post_sweep_contraction(df, after_second, second_sweep.index, cfg)
    result.contraction = contraction

    if not contraction.legs_pct:
        result.reason = "no contraction legs formed after the sweeps"
        return result
    if not contraction.shrinking:
        result.reason = "post-sweep pullbacks are not shrinking"
        return result
    if contraction.final_contraction_pct is None or contraction.final_contraction_pct >= cfg.max_final_contraction_pct:
        result.reason = (
            f"final contraction {contraction.final_contraction_pct}% "
            f">= max {cfg.max_final_contraction_pct}%"
        )
        return result
    if not contraction.atr_declining:
        result.reason = "ATR(10) is not declining vs. ATR at the sweep"
        return result
    if not contraction.volume_dried_up:
        result.reason = "10-day volume is not below the 50-day average"
        return result

    result.matched = True
    result.pivot_price = base.range_high
    result.stop_price = contraction.last_contraction_low or base.range_low
    result.distance_to_pivot_pct = (
        (result.last_close - result.pivot_price) / result.pivot_price * 100.0
    )

    contraction_tightness = _ratio_to_score(
        contraction.final_contraction_pct, best=2.0, worst=cfg.max_final_contraction_pct
    )
    sweep_quality = (high_sweep.quality_score + low_sweep.quality_score) / 2.0
    volume_dryup_score = _ratio_to_score(contraction.volume_dryup_ratio, best=0.5, worst=1.0)

    result.score = round(
        0.35 * sweep_quality + 0.35 * contraction_tightness + 0.30 * volume_dryup_score, 1
    )
    return result


def _has_range_acceptance_violation(closes, start_idx: int, range_high: float, range_low: float) -> bool:
    for j in range(start_idx, len(closes) - 1):
        above = closes[j] > range_high and closes[j + 1] > range_high
        below = closes[j] < range_low and closes[j + 1] < range_low
        if above or below:
            return True
    return False
