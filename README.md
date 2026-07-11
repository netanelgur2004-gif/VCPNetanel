# VCP Scanner

A stock scanner that screens a universe of tickers for Mark Minervini's
**Volatility Contraction Pattern (VCP)** and rates each candidate on a
**0–100% match score**.

## What it checks

The score is a weighted blend of the pieces Minervini describes in
*Trade Like a Stock Market Wizard*:

| Component | Weight | What it measures |
|---|---|---|
| Trend Template | 35% | Minervini's 8-point "Stage 2 uptrend" checklist (price vs. 50/150/200-day MAs, MA stacking order, 200-day MA trending up, price vs. 52-week high/low, relative strength) |
| Contraction structure | 25% | Whether the stock is pulling back in a series of *shrinking* swings (e.g. -25% → -15% → -8% → -4%) |
| Volume dry-up | 20% | Whether volume is contracting alongside price (quiet, low-volume drift into the pivot) |
| Tightness near pivot | 10% | How tight the daily trading range has become in the most recent sessions |
| Prior uptrend | 10% | Whether there was a real advance *before* the base (a VCP needs something to contract from) |

Relative Strength is computed as a percentile rank of trailing momentum
(IBD-style, weighted toward the most recent quarter) **across the scanned
universe**, so it's most meaningful when you scan a broad list (e.g. S&P 500)
rather than one or two tickers.

This is a heuristic approximation of a discretionary chart pattern, not a
guarantee of anything — always eyeball the chart before trading a high-scoring
result.

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
- `--workers N` — parallel download threads (default 8)

## Output

Each row includes: ticker, overall VCP score, Trend Template pass count
(out of 8), number of detected contractions, whether volume is drying up,
tightness %, prior uptrend %, RS rating, last close, and an estimated pivot
(the high of the base — a breakout above this on strong volume is the
classic VCP buy trigger).

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
  universe.py     # ticker universe helpers (S&P 500, file, explicit list)
  scanner.py      # CLI entry point
```
