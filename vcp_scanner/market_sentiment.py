"""Fetch CNN's Fear & Greed Index -- a market-wide sentiment gauge.

This is contextual information about overall market regime, not a per-stock
signal, so it does not feed into the VCP score. Minervini-style setups
generally work best in a healthy/greedy tape and are riskier to trade
through extreme fear, so it's useful context alongside the scan results.
"""

from __future__ import annotations

from typing import Optional

import requests

_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

# CNN's endpoint 418s a plain requests User-Agent; it wants to look like a
# browser request coming from its own site.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.cnn.com/markets/fear-and-greed",
    "Origin": "https://www.cnn.com",
}

_SUB_LABELS = {
    "market_momentum_sp500": "S&P 500 Momentum",
    "stock_price_strength": "Price Strength (52w highs/lows)",
    "stock_price_breadth": "Price Breadth",
    "put_call_options": "Put/Call Options",
    "market_volatility_vix": "Volatility (VIX)",
    "junk_bond_demand": "Junk Bond Demand",
    "safe_haven_demand": "Safe Haven Demand",
}


def fetch_fear_greed_index(timeout: float = 15.0) -> Optional[dict]:
    """Fetch the current Fear & Greed Index and its 7 components.

    Returns None if CNN's endpoint is unreachable or blocks the request --
    this is supplementary context, so callers should degrade gracefully
    rather than fail the whole scan over it.
    """
    try:
        resp = requests.get(_URL, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return None

    fng = payload.get("fear_and_greed")
    if not fng or "score" not in fng:
        return None

    components = []
    for key, label in _SUB_LABELS.items():
        c = payload.get(key)
        if c and "score" in c:
            components.append(
                {"label": label, "score": round(float(c["score"]), 1), "rating": c.get("rating", "")}
            )

    def _num(key: str) -> Optional[float]:
        v = fng.get(key)
        return round(float(v), 1) if v is not None else None

    return {
        "score": round(float(fng["score"]), 1),
        "rating": fng.get("rating", ""),
        "previous_close": _num("previous_close"),
        "previous_1_week": _num("previous_1_week"),
        "previous_1_month": _num("previous_1_month"),
        "previous_1_year": _num("previous_1_year"),
        "components": components,
    }
