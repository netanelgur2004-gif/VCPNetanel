"""Basic technical indicators used by the trend template and VCP analysis."""

from __future__ import annotations

import pandas as pd


def add_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with SMA50/150/200 columns added."""
    out = df.copy()
    out["SMA50"] = out["Close"].rolling(50).mean()
    out["SMA150"] = out["Close"].rolling(150).mean()
    out["SMA200"] = out["Close"].rolling(200).mean()
    return out


def week52_high_low(df: pd.DataFrame, weeks: int = 52) -> tuple[float, float]:
    """52-week (approx. 252 trading day) high and low of the Close series."""
    window = df.tail(weeks * 5)
    return float(window["High"].max()), float(window["Low"].min())


def sma200_trend_up(df: pd.DataFrame, lookback_days: int = 22) -> bool:
    """Whether the 200-day SMA has been rising over the last `lookback_days`."""
    sma200 = df["SMA200"].dropna()
    if len(sma200) < lookback_days + 1:
        return False
    recent = sma200.tail(lookback_days + 1)
    return bool(recent.iloc[-1] > recent.iloc[0])


def average_true_range(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def daily_range_pct(df: pd.DataFrame) -> pd.Series:
    """Daily high-low range as a percentage of the close."""
    return ((df["High"] - df["Low"]) / df["Close"]) * 100.0


def avg_volume(df: pd.DataFrame, period: int = 50) -> pd.Series:
    return df["Volume"].rolling(period).mean()
