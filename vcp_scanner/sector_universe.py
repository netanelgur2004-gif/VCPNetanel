"""Config for the Leading Sectors module: the ETF universe and the GICS
sector -> SPDR ETF mapping used to tag individual stocks.

Plain data, easy to edit -- no logic lives here.
"""

from __future__ import annotations

BENCHMARK = "SPY"

# The 11 SPDR sector ETFs -- these map 1:1 onto GICS sectors (see
# GICS_SECTOR_TO_ETF below), so individual stocks get tagged with one of
# these, never a theme ETF.
SECTOR_ETFS = [
    "XLK", "XLE", "XLF", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
]

# Narrower industry/theme ETFs -- ranked and screened alongside the broad
# sectors, but not used for per-stock tagging (sub-industry matching is
# fuzzy; GICS sector matching is not).
THEME_ETFS = [
    "SMH", "IGV", "XOP", "OIH", "ITA", "URA", "TAN", "KRE", "XBI", "ITB", "COPX", "GDX",
]

ALL_SECTOR_UNIVERSE = SECTOR_ETFS + THEME_ETFS

# GICS Sector name (as it appears in the S&P 500 Wikipedia table) -> SPDR ETF.
GICS_SECTOR_TO_ETF = {
    "Information Technology": "XLK",
    "Energy": "XLE",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Industrials": "XLI",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}

# ETFs move smoother than individual stocks -- a separate, tighter ZigZag
# threshold for VCP contraction detection (vs. analyze_vcp's stock default
# of 8.0%).
ETF_VCP_PCT_THRESHOLD = 5.0

# How far past the pivot counts as "Extended" rather than a fresh "Breakout".
EXTENDED_PAST_PIVOT_PCT = 5.0

# Friendly names for chart titles/tables.
ETF_LABELS = {
    "XLK": "Technology", "XLE": "Energy", "XLF": "Financials", "XLV": "Health Care",
    "XLI": "Industrials", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples",
    "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate", "XLC": "Communication Services",
    "SMH": "Semiconductors", "IGV": "Software", "XOP": "Oil & Gas E&P", "OIH": "Oil Services",
    "ITA": "Aerospace & Defense", "URA": "Uranium", "TAN": "Solar", "KRE": "Regional Banks",
    "XBI": "Biotech", "ITB": "Homebuilders", "COPX": "Copper Miners", "GDX": "Gold Miners",
    "SPY": "S&P 500 (benchmark)",
}
