# VCP Scanner

A stock scanner that screens a universe of tickers for Mark Minervini's
**Volatility Contraction Pattern (VCP)** and rates each candidate on a
**0–100% match score**.

## What it checks

The score is a weighted blend of the pieces Minervini describes in
*Trade Like a Stock Market Wizard*:

| Component | Weight | What it measures |
|---|---|---|
| Trend Template | 30% | Minervini's 8-point "Stage 2 uptrend" checklist (price vs. 50/150/200-day MAs, MA stacking order, 200-day MA trending up, price vs. 52-week high/low, relative strength) |
| Contraction structure | 20% | Whether the stock is pulling back in a series of *shrinking* swings (e.g. -25% → -15% → -8% → -4%) |
| Volume dry-up | 15% | Whether volume is contracting alongside price (quiet, low-volume drift into the pivot) |
| Tightness near pivot | 10% | How tight the daily trading range has become in the most recent sessions |
| Prior uptrend | 10% | Whether there was a real advance *before* the base (a VCP needs something to contract from) |
| Pivot proximity | 15% | How close price is to the pivot (base high / breakout trigger) — peaks for setups sitting right at the pivot; stocks already extended well past it get marked down as no longer an ideal entry |

Relative Strength is computed as a percentile rank of trailing momentum
(IBD-style, weighted toward the most recent quarter) **across the scanned
universe**, so it's most meaningful when you scan a broad list (e.g. S&P 500)
rather than one or two tickers.

This is a heuristic approximation of a discretionary chart pattern, not a
guarantee of anything — always eyeball the chart before trading a high-scoring
result.

Each run also fetches CNN's **Fear & Greed Index** (overall market sentiment
across 7 signals: momentum, price strength/breadth, put/call ratio, volatility,
junk bond demand, safe-haven demand) and shows it at the top of the HTML
dashboard. It's market-wide context, not a per-stock signal, so it doesn't
affect any individual VCP score — but Minervini-style breakouts tend to work
best when the broader tape is healthy rather than in extreme-fear conditions.
If CNN's endpoint is unreachable, the scan still runs fine; the gauge is just
omitted for that run.

## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Scan an explicit list of tickers
python -m vcp_scanner.scanner --tickers AAPL,MSFT,NVDA,COST

# Scan tickers from a file (one per line)
python -m vcp_scanner.scanner --file my_tickers.txt

# Scan the S&P 500 (fetched from Wikipedia) and show only the top 25
python -m vcp_scanner.scanner --sp500 --top 25

# Only show scores above 60%, and save full results to CSV
python -m vcp_scanner.scanner --sp500 --min-score 60 --output results.csv
```

### Options

- `--tickers TICK1,TICK2,...` — comma-separated list of tickers to scan
- `--file PATH` — path to a text file with one ticker per line
- `--sp500` — scan the current S&P 500 constituents
- `--period` — how much history to pull (default `2y`)
- `--top N` — only display the top N results
- `--min-score N` — only display results scoring at or above N (0-100)
- `--output PATH.csv` — write the full ranked results to a CSV file
- `--html-report PATH.html` — write the full ranked results to a self-contained, sortable/searchable HTML dashboard
- `--workers N` — parallel download threads (default 8)

## Output

Each row includes: ticker, overall VCP score, Trend Template pass count
(out of 8), number of detected contractions, whether volume is drying up,
tightness %, prior uptrend %, RS rating, last close, an estimated pivot
(the high of the base — a breakout above this on strong volume is the
classic VCP buy trigger), how far price currently sits above or below
that pivot, and a suggested stop-loss: whichever is tighter of (a) just
under the low of the most recent contraction, or (b) an 8% hard cap on
loss from the last close (Minervini's usual max-risk rule).

## Using the HTML dashboard as a home-screen app

`--html-report` produces a self-contained page with a web app manifest and
iOS meta tags, so it can be installed like an app instead of just bookmarked:

- **iPhone (Safari):** open the page → Share button → "Add to Home Screen".
- **Android (Chrome):** open the page → menu (⋮) → "Add to Home Screen" / "Install app".

It then launches full-screen from your home screen icon, no browser chrome.
This isn't a native App Store app — no push notifications, background
refresh, or app-store listing — but it behaves like an app for viewing the
latest scan.

## SMA20 extension / catalyst screen

Separate from the VCP score, `vcp_scanner.extension_alert` flags S&P 500
stocks trading 15-20% above or below their 20-day SMA (a looser "is this name
unusually extended" screen, not a VCP setup check), and tries to explain
*why*: a big single-day price/volume shock, keyword-matched recent news
(earnings, guidance, M&A, FDA, upgrades/downgrades, etc. — see
`news.CATALYST_KEYWORDS`), or a sector-wide move (via each stock's GICS
sector average deviation across the scanned universe). Results are sorted
with the no-catalyst names first, since those are the ones worth a second
look — extended purely by sector/market drift rather than a name-specific
event.

```bash
# Default 15-20% band, 20-day lookback for news/price-shock detection
python -m vcp_scanner.extension_alert

# Wider/narrower band, shorter lookback, skip the news fetch (faster)
python -m vcp_scanner.extension_alert --low 10 --high 25 --lookback-days 10 --no-news
```

News comes from Yahoo Finance's public search endpoint via plain `requests`
(same TLS-fingerprinting workaround as `data.py`'s price fetch) and is
best-effort/heuristic — keyword matches can occasionally pick up an
off-target headline, so treat the "Reason" column as a lead to verify, not a
verdict.

Pass `--require-market-open` for scheduled/cron runs so the scan skips itself
(no output, exit 0) on weekends and market holidays, rather than re-reporting
yesterday's close as if it were new. This checks SPY's most recently
published daily bar against today's date (`market_calendar.py`) instead of a
hardcoded holiday list, so it doesn't need updating year to year.

## Project layout

```
vcp_scanner/
  data.py         # price history fetching (yfinance)
  indicators.py   # moving averages, ATR, 52w high/low
  swings.py       # swing high/low detection
  vcp.py          # contraction / volume-dryup / tightness / prior-uptrend analysis
  trend_template.py  # Minervini 8-point trend template
  rs_rating.py    # relative strength percentile ranking
  scorer.py       # combines everything into the final 0-100 score
  universe.py     # ticker universe helpers (S&P 500 + sector, file, explicit list)
  market_sentiment.py  # CNN Fear & Greed Index fetcher
  news.py         # best-effort recent-news lookup + catalyst-keyword matching
  extension_scan.py  # SMA20 extension screen + catalyst/price-shock/sector classification
  market_calendar.py  # was the market open today? (for skipping scheduled runs on holidays)
  report.py       # renders results into the sortable/searchable HTML dashboard
  templates/report_template.html  # dashboard markup/CSS/JS, tokens filled in by report.py
  scanner.py      # CLI entry point (VCP score)
  extension_alert.py  # CLI entry point (SMA20 extension/catalyst screen)
```
