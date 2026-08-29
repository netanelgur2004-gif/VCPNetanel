"""Best-effort recent-news lookup via Yahoo Finance's search endpoint.

Hits the same public endpoint the Yahoo Finance search box uses, via plain
`requests` rather than yfinance's session (which needs a cookie/crumb dance
that a restrictive/inspecting proxy can break — see the note in `data.py`).
"""

from __future__ import annotations

import datetime as dt
from typing import List, TypedDict

import requests

SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; vcp-scanner/0.1)"}

# Keywords that suggest a stock-specific catalyst rather than sector/market
# drift. Deliberately broad/heuristic — meant to flag headlines worth a human
# glance, not to be a precise classifier.
CATALYST_KEYWORDS = [
    "earnings", "eps", "guidance", "outlook", "upgrade", "downgrade",
    "price target", "raises", "cuts", "beat", "miss", "acquisition",
    "acquire", "merger", "fda", "approval", "lawsuit", "recall", "contract",
    "partnership", "buyback", "dividend", "ceo", "resign", "investigation",
    "outage", "breach", "bankruptcy", "spinoff", "ipo", "offering", "stake",
    "settlement", "layoffs", "restructuring",
]


class NewsItem(TypedDict):
    title: str
    publisher: str
    time: dt.datetime
    url: str


def fetch_recent_news(ticker: str, lookback_days: int = 20, limit: int = 10) -> List[NewsItem]:
    """Recent headlines for `ticker` within the last `lookback_days`.

    Returns an empty list on any failure (network, unexpected payload shape,
    etc.) — a missing-news lookup should never abort a scan.
    """
    try:
        resp = requests.get(
            SEARCH_URL,
            params={"q": ticker, "newsCount": limit, "quotesCount": 0},
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return []

    cutoff = dt.datetime.utcnow() - dt.timedelta(days=lookback_days)
    items: List[NewsItem] = []
    for n in payload.get("news", []):
        ts = n.get("providerPublishTime")
        if ts is None:
            continue
        published = dt.datetime.utcfromtimestamp(ts)
        if published < cutoff:
            continue
        items.append(
            NewsItem(
                title=n.get("title", ""),
                publisher=n.get("publisher", ""),
                time=published,
                url=n.get("link", ""),
            )
        )
    return items


def catalyst_headlines(news: List[NewsItem]) -> List[NewsItem]:
    """Subset of `news` whose title matches a catalyst keyword."""
    return [n for n in news if any(kw in n["title"].lower() for kw in CATALYST_KEYWORDS)]
