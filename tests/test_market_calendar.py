"""Tests for the market-open-today check used to skip scheduled scans on
weekends/holidays."""

import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from vcp_scanner import market_calendar

_ET = ZoneInfo("America/New_York")


def _df_ending(last_date: dt.date, n: int = 5) -> pd.DataFrame:
    # Calendar days, not business days: bdate_range would silently roll `end`
    # back to the prior weekday if `last_date` itself falls on a weekend,
    # which would defeat the point of pinning the last row's date exactly.
    dates = pd.date_range(end=last_date, periods=n)
    closes = np.full(n, 100.0)
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [1_000_000.0] * n},
        index=dates,
    )


def test_market_was_open_today_true_when_latest_bar_is_today(monkeypatch):
    today = dt.datetime.now(_ET).date()
    monkeypatch.setattr(market_calendar, "fetch_history_raw", lambda ticker, period="5d": _df_ending(today))
    assert market_calendar.market_was_open_today() is True


def test_market_was_open_today_false_on_stale_data(monkeypatch):
    stale = dt.date(2020, 1, 2)
    monkeypatch.setattr(market_calendar, "fetch_history_raw", lambda ticker, period="5d": _df_ending(stale))
    assert market_calendar.market_was_open_today() is False


def test_market_was_open_today_false_when_data_unavailable(monkeypatch):
    monkeypatch.setattr(market_calendar, "fetch_history_raw", lambda ticker, period="5d": None)
    assert market_calendar.market_was_open_today() is False
