"""Price history fetching via yfinance."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Iterable, Optional

import pandas as pd
import requests
import yfinance as yf

REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
MIN_ROWS = 260  # need enough history for 200-day MA + trend checks

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; vcp-scanner/0.1)"}


def _fetch_via_yfinance(ticker: str, period: str) -> Optional[pd.DataFrame]:
    try:
        df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
    except Exception:
        return None

    if df is None or df.empty:
        return None
    if not all(col in df.columns for col in REQUIRED_COLUMNS):
        return None

    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df[REQUIRED_COLUMNS]


def _fetch_via_yahoo_chart_api(ticker: str, period: str) -> Optional[pd.DataFrame]:
    """Fallback fetcher hitting Yahoo's chart API directly via `requests`.

    Used when yfinance's curl_cffi-based session fails (e.g. TLS
    fingerprinting gets mangled by a restrictive/inspecting proxy). This
    mirrors auto_adjust=True by scaling OHLC with the adjclose/close ratio.
    """
    params = {"range": period, "interval": "1d", "events": "div,splits"}
    try:
        resp = requests.get(
            YAHOO_CHART_URL.format(ticker=ticker), params=params, headers=_HEADERS, timeout=15
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return None

    results = payload.get("chart", {}).get("result")
    if not results:
        return None
    result = results[0]

    timestamps = result.get("timestamp")
    indicators = result.get("indicators", {})
    quotes = indicators.get("quote", [{}])[0]
    adjclose_list = indicators.get("adjclose", [{}])
    adjclose = adjclose_list[0].get("adjclose") if adjclose_list else None

    if not timestamps or not quotes:
        return None

    open_ = quotes.get("open")
    high = quotes.get("high")
    low = quotes.get("low")
    close = quotes.get("close")
    volume = quotes.get("volume")
    if not (open_ and high and low and close and volume):
        return None

    full_index = pd.to_datetime(timestamps, unit="s").tz_localize(None)
    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=full_index,
    )
    df = df.dropna(subset=["Close"])
    if df.empty:
        return None

    if adjclose:
        # adjclose parallels the *original* timestamps array (before the
        # dropna above), so align it there first, then reindex onto the
        # post-dropna df.index by actual timestamp -- not by position, since
        # dropna may have removed different rows than a length mismatch here
        # would suggest.
        n = min(len(adjclose), len(full_index))
        adj_series = pd.Series(adjclose[:n], index=full_index[:n])
        adj_series = adj_series.reindex(df.index)
        ratio = (adj_series / df["Close"]).fillna(1.0)
        for col in ("Open", "High", "Low", "Close"):
            df[col] = df[col] * ratio

    return df[REQUIRED_COLUMNS]


def fetch_history_raw(ticker: str, period: str = "2y") -> Optional[pd.DataFrame]:
    """Fetch daily OHLCV history for a single ticker, with no minimum-length gate.

    Tries the direct Yahoo chart API first (fast, no session/crumb dance),
    then falls back to yfinance if that fails for some reason. Returns None
    if the data is missing or malformed. Prefer `fetch_history` unless you
    specifically need short/partial histories (e.g. checking the latest
    trading day via a few days of data).
    """
    df = _fetch_via_yahoo_chart_api(ticker, period)
    if df is None or df.empty:
        df = _fetch_via_yfinance(ticker, period)

    if df is None or df.empty:
        return None
    return df


def fetch_history(ticker: str, period: str = "2y") -> Optional[pd.DataFrame]:
    """Fetch daily OHLCV history for a single ticker.

    Same as `fetch_history_raw`, but additionally returns None if there's
    less than `MIN_ROWS` of history (not enough for the 200-day MA / trend
    checks).
    """
    df = fetch_history_raw(ticker, period)
    if df is None or len(df) < MIN_ROWS:
        return None
    return df


def fetch_many(
    tickers: Iterable[str], period: str = "2y", max_workers: int = 8
) -> Dict[str, pd.DataFrame]:
    """Fetch history for many tickers in parallel. Skips tickers that fail."""
    tickers = list(dict.fromkeys(t.strip().upper() for t in tickers if t.strip()))
    results: Dict[str, pd.DataFrame] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_ticker = {
            pool.submit(fetch_history, ticker, period): ticker for ticker in tickers
        }
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                df = future.result()
            except Exception:
                df = None
            if df is not None:
                results[ticker] = df

    return results
