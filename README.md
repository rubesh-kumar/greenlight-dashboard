# Greenlight Momentum Strategy

A rules-based monthly momentum strategy for the Nifty 500, with a full workflow
from data collection to backtesting to a live stock-selection dashboard.

The name comes from the core idea: a stock is only bought when the broader
market gives a "green light." A weekly trend filter on the Nifty 500 index acts
as a master switch — when the market is in a confirmed uptrend the strategy
invests, and when it turns down the strategy moves fully to cash.

---

## What this project does

The system has three parts that run in sequence:

1. **Data collection** — downloads five years of daily price data for the
   Nifty 500 from Yahoo Finance and stores it locally.
2. **Backtesting** — tests the strategy on that historical data and reports
   performance.
3. **Live dashboard** — a web app that ranks the universe every day using the
   same rules, so you can see which stocks to buy on each rebalancing date.

All three share the same logic, so the stocks the dashboard surfaces are the
same ones the backtest would actually trade.

---

## The strategy rules

**Capital and sizing**

- Hold 5 stocks at any time, equal weight (capital split evenly across the five)
- Rebalance on the first trading day on or after the 15th of each month
- Universe: Nifty 500
- Brokerage: zero (delivery / CNC trades)

**Step 0 — the market filter (the green light)**

Before anything else, check the weekly Supertrend on the Nifty 500 index
(ATR period 1, multiplier 2.5).

- Bullish → proceed with the rules below.
- Bearish → sell all holdings, hold cash, make no new buys until it turns
  bullish again.

**Entry rules (only when the market is bullish)**

- Rank all Nifty 500 stocks by their 126-day rate of change (about six months
  of price performance).
- A stock is eligible to buy only if it trades above its 220-day moving
  average (DMA).
- Buy from the Top 5 ranked stocks that you do not already own and that are
  above their 220 DMA.
- Fill only the empty slots — holdings you are keeping are left untouched.

**Exit rules — the FRR rule, checked on each rebalancing day**

Sell a stock you hold if either of these is true:

- It has dropped outside the Top 10 by momentum rank, or
- It has fallen below its 220-day moving average.

Keep every holding that is still inside the Top 10 and still above its 220 DMA.

**The keep buffer**

You buy only from the Top 5, but you hold as long as a stock stays in the
Top 10. The gap between rank 5 and rank 10 is deliberate — it prevents churning
a stock in and out every month over small changes in rank.

---

## Repository structure

```
.
├── README.md                          This file
├── requirements.txt                   Python packages needed
│
├── fetch_nifty500_ohlcv.py            Step 1: download price data
├── backtest_momentum.py               Step 2: backtest the strategy
├── momentum_dashboard.py              Live stock-selection dashboard
├── prepare_dashboard_data.py          Helper: trims data for the cloud
│
├── Greenlight_Momentum_Rules.pdf      One-page rules reference card
│
└── data/
    ├── Nifty500/
    │   └── nifty500_constituents.csv  The Nifty 500 symbol list
    └── raw/
        ├── individual/                One CSV per stock (local only)
        ├── nifty500_combined.csv      All stocks in one file (local only)
        └── nifty500_recent.csv        Trimmed file for the dashboard
```

Note: the large data files (`individual/` and `nifty500_combined.csv`) are
used locally. Only the small files (`nifty500_constituents.csv` and
`nifty500_recent.csv`) are needed by the deployed dashboard.

---

## Setup

You need Python 3.9 or newer.

```bash
pip install -r requirements.txt
```

This installs pandas, numpy, yfinance, and streamlit.

---

## How to use it

### Step 1 — Collect the data

```bash
python3 fetch_nifty500_ohlcv.py
```

This downloads five years of daily data for the Nifty 500 and saves it under
`data/`. It creates one CSV per stock, one combined CSV, the constituents list,
and a log of any tickers that failed to download.

### Step 2 — Run the backtest

```bash
python3 backtest_momentum.py
```

This reads the local data, applies the strategy, and prints performance
metrics. Detailed results (equity curve, trade log, closed trades) are saved
under `data/backtest_results/`.

### Run the dashboard locally

```bash
streamlit run momentum_dashboard.py
```

Your browser opens at `http://localhost:8501`. The dashboard shows the market
regime, the ranked stock table, and the day's buy candidates.

---

## The dashboard's two data modes

The dashboard has a "Data source" toggle in the sidebar:

- **Live (Yahoo Finance)** — pulls fresh prices for the whole universe. Best
  on your own machine. This is the default.
- **Stored CSVs (fast)** — reads the trimmed `nifty500_recent.csv` file. Best
  on the cloud, where downloading 500 stocks live can be slow. The data is as
  fresh as the last time you ran Step 1 and the trimmer.

The market regime banner stays live in both modes, because that is just one
small index download.

---

## Deploying the dashboard (Streamlit Community Cloud)

The dashboard can be hosted for free so you get a permanent URL.

1. Run the trimmer once to create the small data file:

   ```bash
   python3 prepare_dashboard_data.py
   ```

   This writes `data/raw/nifty500_recent.csv` (around 5 MB).

2. Commit these files to a GitHub repository:

   ```
   momentum_dashboard.py
   requirements.txt
   data/Nifty500/nifty500_constituents.csv
   data/raw/nifty500_recent.csv
   ```

3. Go to share.streamlit.io, sign in with GitHub, click "Create app," and point
   it at your repository with `momentum_dashboard.py` as the main file.

4. Deploy. After a few minutes you get your live URL.

To make the cloud app open in fast mode automatically, set
`DEFAULT_DATA_SOURCE = SOURCE_STORED` near the top of the committed dashboard.

---

## Keeping the cloud data fresh

The cloud dashboard reads stored data, so to update it:

1. Re-run Step 1 to download the latest prices.
2. Re-run the trimmer (`prepare_dashboard_data.py`).
3. Re-upload `data/raw/nifty500_recent.csv` to GitHub.

The dashboard updates on its own once the new file lands in the repo.

---

## Backtest results

Tested on Nifty 500 data from April 2022 to June 2026:

| Metric            | Value      |
|-------------------|------------|
| Total return      | 155%       |
| CAGR              | 25.6%      |
| Max drawdown      | -14.8%     |
| Annual volatility | 15.8%      |
| Sharpe ratio      | 1.56       |
| Closed trades     | 65         |
| Win rate          | 50.8%      |
| Win/loss ratio    | about 3.8x |

The strategy works through asymmetry: it wins only about half the time, but the
average win is nearly four times the average loss. The weekly market filter
keeps drawdowns contained by moving to cash during downturns.

---

## Important limitations

These caveats matter when reading the backtest numbers:

- **Survivorship bias.** The universe is the *current* Nifty 500. Stocks that
  were dropped from the index over the test period — often poor performers — are
  not in the data, which inflates returns somewhat.
- **Favourable test window.** April 2022 to June 2026 was, on balance, a strong
  period for Indian equities. The strategy has not been stress-tested through a
  long bear market in this data.
- **Statutory costs not included.** Delivery brokerage on the broker used is
  zero, but small charges (STT, stamp duty, exchange and SEBI fees, GST) are not
  yet modelled. They reduce the true net return slightly.
- **Trade-at-close assumption.** The backtest executes at the closing price on
  the rebalancing day, which is a standard but simplified convention.

---

## Open work

- Add the small statutory trading costs to the backtest for a truer net return.
- Run a parameter sensitivity test on the 126-day lookback and the Supertrend
  settings, to confirm the strategy is not overfit.
- Add a volatility filter to the eligibility check (currently parked for later).

---

## Disclaimer

This project is for personal research and education. It is not investment
advice. Past backtested performance does not guarantee future results. Always
do your own analysis before trading.
