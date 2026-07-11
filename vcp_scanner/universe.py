"""Helpers for building the list of tickers to scan."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd

SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# Small offline fallback in case the Wikipedia fetch fails (e.g. no network).
FALLBACK_SP500_SAMPLE = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA", "BRK-B", "AVGO",
    "JPM", "LLY", "V", "XOM", "COST", "UNH", "MA", "HD", "PG", "NFLX", "MRK",
]


def tickers_from_file(path: str) -> List[str]:
    lines = Path(path).read_text().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def tickers_from_csv_arg(arg: str) -> List[str]:
    return [t.strip() for t in arg.split(",") if t.strip()]


def sp500_tickers() -> List[str]:
    try:
        tables = pd.read_html(SP500_WIKI_URL)
        df = tables[0]
        tickers = df["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
        if tickers:
            return tickers
    except Exception:
        pass
    return list(FALLBACK_SP500_SAMPLE)
