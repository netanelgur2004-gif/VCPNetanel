"""Screen for stocks extended 15-20% from their 20-day SMA, and flag whether
the move looks catalyst-driven (news, earnings-like price/volume shock) or
just sector/market drift with nothing stock-specific behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from .news import NewsItem, catalyst_headlines, fetch_recent_news

SHOCK_MOVE_PCT = 6.0  # single-day |move| considered an earnings/event-like shock
SHOCK_VOLUME_MULT = 1.5  # vs. 50-day average volume, to confirm it wasn't just noise


@dataclass
class PriceShock:
    date: pd.Timestamp
    move_pct: float
    volume_ratio: float


@dataclass
class ExtensionResult:
    ticker: str
    direction: str  # "above" or "below"
    deviation_pct: float
    last_close: float
    sma20: float
    sector: Optional[str]
    sector_avg_deviation: Optional[float]
    price_shock: Optional[PriceShock]
    news: List[NewsItem] = field(default_factory=list)
    catalyst_news: List[NewsItem] = field(default_factory=list)

    @property
    def has_catalyst(self) -> bool:
        return self.price_shock is not None or bool(self.catalyst_news)

    @property
    def reason(self) -> str:
        if self.price_shock:
            return (
                f"{self.price_shock.move_pct:+.1f}% single-day move on "
                f"{self.price_shock.volume_ratio:.1f}x avg volume "
                f"({self.price_shock.date.date()}) - looks event-driven"
            )
        if self.catalyst_news:
            return f"news: {self.catalyst_news[0]['title']}"
        if self.sector_avg_deviation is not None and abs(self.sector_avg_deviation) >= 8:
            return (
                f"sector-wide move ({self.sector} avg {self.sector_avg_deviation:+.1f}%), "
                "no stock-specific news found"
            )
        return "no earnings/news catalyst or sector move found - looks like unexplained drift"


def detect_price_shock(df: pd.DataFrame, lookback_days: int = 20) -> Optional[PriceShock]:
    """Largest single-day move in the lookback window, if it's big enough on
    high enough volume to look like an earnings/event reaction rather than
    ordinary daily noise.
    """
    window = df.tail(lookback_days)
    if len(window) < 2:
        return None

    returns = window["Close"].pct_change() * 100.0
    avg_volume = df["Volume"].rolling(50).mean().reindex(window.index)
    volume_ratio = window["Volume"] / avg_volume

    best_idx = returns.abs().idxmax()
    if pd.isna(best_idx):
        return None
    move = returns.loc[best_idx]
    vol_ratio = volume_ratio.loc[best_idx]
    if pd.isna(move) or pd.isna(vol_ratio):
        return None

    if abs(move) >= SHOCK_MOVE_PCT and vol_ratio >= SHOCK_VOLUME_MULT:
        return PriceShock(date=best_idx, move_pct=float(move), volume_ratio=float(vol_ratio))
    return None


def _sma20_deviations(histories: Dict[str, pd.DataFrame]) -> Dict[str, float]:
    deviations: Dict[str, float] = {}
    for ticker, df in histories.items():
        if len(df) < 20:
            continue
        sma20 = df["Close"].rolling(20).mean().iloc[-1]
        if pd.isna(sma20) or sma20 == 0:
            continue
        last_close = float(df["Close"].iloc[-1])
        deviations[ticker] = (last_close - sma20) / sma20 * 100.0
    return deviations


def _sector_avg_deviations(
    deviations: Dict[str, float], sector_map: Optional[Dict[str, str]]
) -> Dict[str, float]:
    sector_devs: Dict[str, List[float]] = {}
    if sector_map:
        for ticker, dev in deviations.items():
            sector = sector_map.get(ticker)
            if sector:
                sector_devs.setdefault(sector, []).append(dev)
    return {s: sum(v) / len(v) for s, v in sector_devs.items()}


def _build_result(
    ticker: str,
    dev: float,
    direction: str,
    histories: Dict[str, pd.DataFrame],
    sector_map: Optional[Dict[str, str]],
    sector_avg: Dict[str, float],
    lookback_days: int,
    fetch_news: bool,
) -> ExtensionResult:
    df = histories[ticker]
    sma20 = float(df["Close"].rolling(20).mean().iloc[-1])
    sector = sector_map.get(ticker) if sector_map else None
    shock = detect_price_shock(df, lookback_days=lookback_days)
    news = fetch_recent_news(ticker, lookback_days=lookback_days) if fetch_news else []
    catalyst_news = catalyst_headlines(news)

    return ExtensionResult(
        ticker=ticker,
        direction=direction,
        deviation_pct=round(dev, 2),
        last_close=round(float(df["Close"].iloc[-1]), 2),
        sma20=round(sma20, 2),
        sector=sector,
        sector_avg_deviation=round(sector_avg[sector], 2) if sector and sector in sector_avg else None,
        price_shock=shock,
        news=news,
        catalyst_news=catalyst_news,
    )


def scan_sma20_extension(
    histories: Dict[str, pd.DataFrame],
    sector_map: Optional[Dict[str, str]] = None,
    low_pct: float = 15.0,
    high_pct: float = 20.0,
    lookback_days: int = 20,
    fetch_news: bool = True,
) -> List[ExtensionResult]:
    """Flag tickers whose last close is `low_pct`-`high_pct`% away (either
    direction) from their 20-day SMA, and classify each as catalyst-driven or
    not.

    `sector_map` (ticker -> GICS sector) is optional; when given, results
    also carry the average deviation across the whole scanned universe's
    sector peers, so a sector-wide rally/selloff is visible even when no
    stock-specific news turns up.
    """
    deviations = _sma20_deviations(histories)
    sector_avg = _sector_avg_deviations(deviations, sector_map)

    results: List[ExtensionResult] = []
    for ticker, dev in deviations.items():
        if low_pct <= dev <= high_pct:
            direction = "above"
        elif -high_pct <= dev <= -low_pct:
            direction = "below"
        else:
            continue
        results.append(
            _build_result(ticker, dev, direction, histories, sector_map, sector_avg, lookback_days, fetch_news)
        )

    # No-catalyst names first (what you actually want to see), biggest |deviation| first within each group.
    results.sort(key=lambda r: (r.has_catalyst, -abs(r.deviation_pct)))
    return results


def top_sma20_extension(
    histories: Dict[str, pd.DataFrame],
    sector_map: Optional[Dict[str, str]] = None,
    top_n: int = 10,
    min_pct: float = 0.0,
    lookback_days: int = 20,
    fetch_news: bool = True,
) -> List[ExtensionResult]:
    """The `top_n` tickers furthest (either direction) from their 20-day SMA,
    ignoring the fixed 15-20% band -- for "just show me a real list" rather
    than a strict range that some days comes back nearly empty.

    `min_pct` optionally still requires at least this much |deviation|.
    """
    deviations = _sma20_deviations(histories)
    deviations = {t: d for t, d in deviations.items() if abs(d) >= min_pct}
    sector_avg = _sector_avg_deviations(deviations, sector_map)

    ranked = sorted(deviations.items(), key=lambda kv: abs(kv[1]), reverse=True)[:top_n]

    results = [
        _build_result(
            ticker, dev, "above" if dev >= 0 else "below", histories, sector_map, sector_avg, lookback_days, fetch_news
        )
        for ticker, dev in ranked
    ]
    results.sort(key=lambda r: (r.has_catalyst, -abs(r.deviation_pct)))
    return results
