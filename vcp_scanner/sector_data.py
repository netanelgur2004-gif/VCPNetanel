"""Local CSV caching around data.py's fetcher, for sector/theme ETF bars.

Reuses fetch_history for the actual network fetch and its MIN_ROWS gate
unchanged -- this module only adds a cache layer in front of it so reruns
on the same day don't refetch every ETF.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd

from .data import fetch_history

DEFAULT_CACHE_DIR = Path("data_cache") / "sectors"


def _cache_path(cache_dir: Path, ticker: str) -> Path:
    return cache_dir / f"{ticker}.csv"


def _load_cache(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception:
        return None
    if df.empty:
        return None
    return df


def _is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    mtime = _dt.date.fromtimestamp(path.stat().st_mtime)
    return mtime == _dt.date.today()


def fetch_sector_history(
    ticker: str, period: str = "2y", cache_dir: Path | str = DEFAULT_CACHE_DIR, use_cache: bool = True
) -> Optional[pd.DataFrame]:
    """Fetch one ETF's daily OHLCV, using a same-day local CSV cache.

    Returns None if the ticker can't be fetched or has too little history
    (same graceful short-history handling as fetch_history) -- never raises.
    """
    cache_dir = Path(cache_dir)
    path = _cache_path(cache_dir, ticker)

    if use_cache and _is_fresh(path):
        cached = _load_cache(path)
        if cached is not None:
            return cached

    df = fetch_history(ticker, period=period)
    if df is None or df.empty:
        # Fall back to a stale cache rather than dropping the ETF entirely.
        return _load_cache(path) if use_cache else None

    if use_cache:
        cache_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(path)

    return df


def fetch_many_sectors(
    tickers: Iterable[str], period: str = "2y", cache_dir: Path | str = DEFAULT_CACHE_DIR, use_cache: bool = True
) -> Dict[str, pd.DataFrame]:
    """Fetch many ETFs' history, skipping any that fail or are too short."""
    results: Dict[str, pd.DataFrame] = {}
    for ticker in dict.fromkeys(t.strip().upper() for t in tickers if t.strip()):
        df = fetch_sector_history(ticker, period=period, cache_dir=cache_dir, use_cache=use_cache)
        if df is not None:
            results[ticker] = df
    return results
