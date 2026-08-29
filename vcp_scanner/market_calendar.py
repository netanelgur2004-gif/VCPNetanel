"""Detect whether the US stock market actually had a session today.

Used to make scheduled scans skip themselves on weekends and market
holidays: cron can restrict *days of the week*, but it has no idea about
Thanksgiving or Good Friday. Rather than hardcoding a holiday calendar (which
goes stale), this checks real price data: if the most recently published
daily bar for a liquid reference ticker isn't dated today, the market wasn't
open today.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional
from zoneinfo import ZoneInfo

from .data import fetch_history_raw

_ET = ZoneInfo("America/New_York")


def latest_trading_day(reference_ticker: str = "SPY") -> Optional[dt.date]:
    """Most recent date with a published daily bar for `reference_ticker`."""
    df = fetch_history_raw(reference_ticker, period="5d")
    if df is None or df.empty:
        return None
    return df.index[-1].date()


def market_was_open_today(reference_ticker: str = "SPY") -> bool:
    """Whether the most recently published trading day is today (US Eastern).

    On a weekend or market holiday there's no new session bar, so this
    returns False and a caller can skip re-reporting yesterday's numbers as
    if they were fresh.
    """
    today = dt.datetime.now(_ET).date()
    latest = latest_trading_day(reference_ticker)
    return latest == today
