"""
momentum_dashboard.py
---------------------
Greenlight Momentum - Live Stock Selection Dashboard (Nifty 500)

Surfaces the top-performing stocks using the SAME logic as the backtest:
  - Performance score : 126-trading-day rate of change (ROC)
  - Eligibility        : price must be above its 220-day moving average (DMA)
  - Market regime      : weekly Supertrend on the Nifty 500 index
                         (ATR period 1, multiplier 2.5)

DATA SOURCE (sidebar toggle):
  - Live (Yahoo Finance) : pulls fresh prices for the whole universe.
                           Best on your local machine. This is the default.
  - Stored CSVs (fast)   : reads the Step 1 CSVs committed to the repo.
                           Best on Streamlit Community Cloud's small server,
                           where 500 live downloads can be slow or rate-limited.
                           Data is as fresh as your last Step 1 run / upload.

HOW TO RUN
  pip install streamlit yfinance pandas numpy
  streamlit run momentum_dashboard.py
"""

import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf


# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

CONSTITUENTS_CSV = Path("data/Nifty500/nifty500_constituents.csv")
INDIVIDUAL_DIR   = Path("data/raw/individual")
COMBINED_CSV     = Path("data/raw/nifty500_combined.csv")
RECENT_CSV       = Path("data/raw/nifty500_recent.csv")   # small trimmed file (for cloud)

# Default data source. Keep "Live" so a local run behaves exactly as before.
# On Streamlit Cloud you can flip the sidebar toggle, or set this to
# "Stored CSVs (fast)" in the committed copy so the cloud app defaults to fast.
SOURCE_LIVE   = "Live (Yahoo Finance)"
SOURCE_STORED = "Stored CSVs (fast)"
DEFAULT_DATA_SOURCE = SOURCE_LIVE

MOMENTUM_LOOKBACK = 126     # trading days (~6 months)
DMA_PERIOD        = 220     # trading days
TOP_KEEP          = 10
TOP_BUY           = 5

HISTORY_DAYS      = 420     # calendar days to pull in live mode
BATCH_SIZE        = 50      # tickers per Yahoo download call (live mode)

ST_ATR_PERIOD     = 1
ST_MULTIPLIER     = 2.5
INDEX_TICKERS     = ["^CRSLDX", "NIFTY500.NS"]


# ---------------------------------------------------------------------------
# UNIVERSE
# ---------------------------------------------------------------------------

def load_universe() -> List[str]:
    """Read the Nifty 500 symbol list from the Step 1 constituents CSV.
    Falls back to scanning the individual-CSV folder."""
    if CONSTITUENTS_CSV.exists():
        df = pd.read_csv(CONSTITUENTS_CSV)
        if "Symbol" in df.columns:
            return df["Symbol"].dropna().astype(str).str.strip().tolist()
    if INDIVIDUAL_DIR.exists():
        return sorted(p.stem for p in INDIVIDUAL_DIR.glob("*.csv"))
    return []


def to_yahoo(symbol: str) -> str:
    return f"{symbol.strip()}.NS"


# ---------------------------------------------------------------------------
# DATA SOURCE 1: LIVE (Yahoo Finance)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def download_prices(yahoo_tickers: List[str], history_days: int) -> Dict[str, pd.Series]:
    """Download recent daily close prices for the universe from Yahoo Finance,
    in batches. Returns dict: NSE symbol -> close-price Series."""
    end   = datetime.today()
    start = end - pd.Timedelta(days=history_days)
    closes: Dict[str, pd.Series] = {}

    progress = st.progress(0.0, text="Downloading prices from Yahoo Finance ...")
    total_batches = (len(yahoo_tickers) + BATCH_SIZE - 1) // BATCH_SIZE

    for b, i in enumerate(range(0, len(yahoo_tickers), BATCH_SIZE), start=1):
        batch = yahoo_tickers[i:i + BATCH_SIZE]
        try:
            raw = yf.download(batch, start=start, end=end, interval="1d",
                              auto_adjust=True, progress=False, group_by="ticker",
                              threads=True)
        except Exception:
            raw = None

        if raw is not None and not raw.empty:
            for yt in batch:
                nse = yt.replace(".NS", "")
                try:
                    if isinstance(raw.columns, pd.MultiIndex):
                        if yt in raw.columns.get_level_values(0):
                            s = raw[yt]["Close"].dropna()
                        else:
                            continue
                    else:
                        s = raw["Close"].dropna()
                    if not s.empty:
                        s.index = pd.to_datetime(s.index).normalize()
                        closes[nse] = s
                except Exception:
                    continue

        progress.progress(b / total_batches,
                          text=f"Downloading prices ... batch {b}/{total_batches}")
        time.sleep(0.2)

    progress.empty()
    return closes


# ---------------------------------------------------------------------------
# DATA SOURCE 2: STORED CSVs (fast, for the cloud)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_stored_prices() -> Dict[str, pd.Series]:
    """
    Read close prices from the Step 1 CSVs committed to the repo.
    Prefers the single combined CSV; falls back to the individual-CSV folder.
    Only the Date/Symbol/Adj_Close columns are read, to stay light on memory.
    """
    closes: Dict[str, pd.Series] = {}

    # Prefer the small trimmed file (RECENT_CSV), then the full combined CSV.
    source_file = RECENT_CSV if RECENT_CSV.exists() else COMBINED_CSV

    if source_file.exists():
        df = pd.read_csv(source_file, usecols=["Date", "Symbol", "Adj_Close"],
                         parse_dates=["Date"])
        for sym, grp in df.groupby("Symbol"):
            s = grp.set_index("Date")["Adj_Close"].sort_index()
            s = s[~s.index.duplicated(keep="last")]
            closes[str(sym)] = s
        return closes

    if INDIVIDUAL_DIR.exists():
        for fp in sorted(INDIVIDUAL_DIR.glob("*.csv")):
            try:
                d = pd.read_csv(fp, usecols=["Date", "Adj_Close"], parse_dates=["Date"])
                s = d.set_index("Date")["Adj_Close"].sort_index()
                closes[fp.stem] = s[~s.index.duplicated(keep="last")]
            except Exception:
                continue

    return closes


# ---------------------------------------------------------------------------
# INDICATORS
# ---------------------------------------------------------------------------

def compute_supertrend(df: pd.DataFrame, period: int, multiplier: float) -> pd.DataFrame:
    """Supertrend (Kivanc Ozbilgic). direction: +1 bull, -1 bear."""
    high, low, close = df["High"], df["Low"], df["Close"]
    hl2 = (high + low) / 2.0
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    n = len(df)
    fu, fl, direction, st_line = [np.nan]*n, [np.nan]*n, [np.nan]*n, [np.nan]*n
    ub, lb, cl = upper.values, lower.values, close.values

    for i in range(n):
        if i == 0:
            fu[i], fl[i], direction[i], st_line[i] = ub[i], lb[i], 1, lb[i]
            continue
        fu[i] = ub[i] if (ub[i] < fu[i-1] or cl[i-1] > fu[i-1]) else fu[i-1]
        fl[i] = lb[i] if (lb[i] > fl[i-1] or cl[i-1] < fl[i-1]) else fl[i-1]
        if st_line[i-1] == fu[i-1]:
            direction[i], st_line[i] = (1, fl[i]) if cl[i] > fu[i] else (-1, fu[i])
        else:
            direction[i], st_line[i] = (-1, fu[i]) if cl[i] < fl[i] else (1, fl[i])

    out = df.copy()
    out["direction"] = direction
    return out


@st.cache_data(show_spinner=False)
def get_market_regime() -> Dict:
    """Download the Nifty 500 index (one ticker), compute the weekly Supertrend,
    and return the latest completed-week regime. Used for the bull/bear banner.
    This stays live even in Stored mode because it is just one small download."""
    end   = datetime.today()
    start = end - pd.Timedelta(days=HISTORY_DAYS * 3)

    for ticker in INDEX_TICKERS:
        try:
            raw = yf.download(ticker, start=start, end=end, interval="1d",
                              auto_adjust=False, progress=False, multi_level_index=False)
            if raw is None or raw.empty or "Close" not in raw.columns:
                continue
            weekly = pd.DataFrame({
                "High":  raw["High"].resample("W-FRI").max(),
                "Low":   raw["Low"].resample("W-FRI").min(),
                "Close": raw["Close"].resample("W-FRI").last(),
            }).dropna()
            st_df = compute_supertrend(weekly, ST_ATR_PERIOD, ST_MULTIPLIER)
            return {"ticker": ticker, "bullish": bool(st_df["direction"].iloc[-1] == 1),
                    "as_of": st_df.index[-1].strftime("%Y-%m-%d")}
        except Exception:
            continue

    return {"ticker": None, "bullish": None, "as_of": None}


def build_screen(closes: Dict[str, pd.Series], lookback: int, dma_period: int) -> pd.DataFrame:
    """Compute the momentum screen table from close prices."""
    rows = []
    need = max(lookback, dma_period) + 1
    for sym, close in closes.items():
        close = close.dropna()
        if len(close) < need:
            continue
        price   = close.iloc[-1]
        score   = (close.iloc[-1] / close.iloc[-1 - lookback] - 1) * 100
        dma_val = close.iloc[-dma_period:].mean()
        above   = price > dma_val
        dist    = (price / dma_val - 1) * 100
        r1m     = (close.iloc[-1] / close.iloc[-1 - 21] - 1) * 100 if len(close) > 22 else np.nan
        r3m     = (close.iloc[-1] / close.iloc[-1 - 63] - 1) * 100 if len(close) > 64 else np.nan
        rows.append({
            "Symbol": sym,
            "Price": round(price, 2),
            "Score (126d %)": round(score, 2),
            "Above 220DMA": "Yes" if above else "No",
            "Dist 220DMA %": round(dist, 2),
            "1M %": round(r1m, 2) if pd.notna(r1m) else None,
            "3M %": round(r3m, 2) if pd.notna(r3m) else None,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("Score (126d %)", ascending=False).reset_index(drop=True)
    df.insert(0, "Rank", df.index + 1)
    return df


# ---------------------------------------------------------------------------
# STREAMLIT UI
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Greenlight Momentum", layout="wide")
    st.title("Greenlight Momentum - Stock Selector")
    st.caption("Top momentum stocks (Nifty 500), using the same rules as the backtest.")

    # ---- Sidebar ----
    st.sidebar.header("Settings")

    source = st.sidebar.radio(
        "Data source",
        [SOURCE_LIVE, SOURCE_STORED],
        index=0 if DEFAULT_DATA_SOURCE == SOURCE_LIVE else 1,
        help="Live pulls fresh prices (best locally). Stored reads the committed "
             "Step 1 CSVs (best on the cloud's small server).",
    )

    top_n      = st.sidebar.slider("Stocks to show", 5, 50, 20, step=5)
    lookback   = st.sidebar.number_input("Momentum lookback (days)", 20, 300, MOMENTUM_LOOKBACK, step=1)
    dma_period = st.sidebar.number_input("DMA period (days)", 20, 300, DMA_PERIOD, step=1)
    only_eligible = st.sidebar.checkbox("Show only stocks above 220 DMA", value=False)

    st.sidebar.markdown("---")
    if st.sidebar.button("Refresh data", type="primary"):
        st.cache_data.clear()
        st.rerun()

    # ---- Universe ----
    universe = load_universe()
    if not universe and source == SOURCE_LIVE:
        st.error("No universe found. Run Step 1 so data/Nifty500/nifty500_constituents.csv exists.")
        st.stop()

    # ---- Load prices from the chosen source ----
    data_as_of = None
    with st.spinner("Loading prices ..."):
        if source == SOURCE_LIVE:
            yahoo_tickers = [to_yahoo(s) for s in universe]
            closes = download_prices(yahoo_tickers, HISTORY_DAYS)
        else:
            closes = load_stored_prices()
            if closes:
                data_as_of = max(s.index.max() for s in closes.values()).strftime("%Y-%m-%d")

    if not closes:
        if source == SOURCE_STORED:
            st.error("No stored data found. Run prepare_dashboard_data.py and commit "
                     "data/raw/nifty500_recent.csv to the repo, or switch to Live mode.")
        else:
            st.error("No price data could be loaded from Yahoo Finance. Try again or switch source.")
        st.stop()

    screen = build_screen(closes, int(lookback), int(dma_period))
    if screen.empty:
        st.warning("No stocks had enough history to rank. Try increasing the history window.")
        st.stop()

    # ---- Market regime banner ----
    regime = get_market_regime()
    c1, c2, c3 = st.columns([3, 2, 2])
    with c1:
        if regime["bullish"] is True:
            st.success(f"Market regime: BULL RUN  (weekly Supertrend, as of {regime['as_of']})")
        elif regime["bullish"] is False:
            st.error(f"Market regime: BEAR  (weekly Supertrend, as of {regime['as_of']})")
        else:
            st.warning("Market regime: unavailable (index download failed)")
    with c2:
        st.metric("Universe loaded", f"{len(closes)} stocks")
    with c3:
        if source == SOURCE_STORED and data_as_of:
            st.metric("Data as of", data_as_of)
        else:
            st.metric("Last updated", datetime.now().strftime("%Y-%m-%d %H:%M"))

    if source == SOURCE_STORED:
        st.caption(f"Reading stored Step 1 data (prices as of {data_as_of}). "
                   "Switch to Live mode for real-time prices.")

    if regime["bullish"] is False:
        st.info("The strategy sits in cash during a bear regime. The ranking below is for "
                "monitoring only - no new entries while the market filter is bearish.")

    # ---- Apply eligibility filter ----
    if only_eligible:
        screen = screen[screen["Above 220DMA"] == "Yes"].reset_index(drop=True)
        screen["Rank"] = screen.index + 1

    view = screen.head(top_n).copy()

    def highlight_zone(row):
        if row["Rank"] <= TOP_BUY:
            return ["background-color: #1b5e20; color: white"] * len(row)
        if row["Rank"] <= TOP_KEEP:
            return ["background-color: #33691e; color: white"] * len(row)
        return [""] * len(row)

    st.subheader(f"Top {len(view)} momentum stocks")
    st.caption("Dark green = Top 5 (buy zone).  Green = Top 6-10 (keep zone).")
    st.dataframe(view.style.apply(highlight_zone, axis=1),
                 use_container_width=True, hide_index=True)

    # ---- Buy candidates ----
    buy_candidates = screen[(screen["Rank"] <= TOP_BUY) & (screen["Above 220DMA"] == "Yes")]
    st.subheader("Buy candidates (Top 5, above 220 DMA)")
    if regime["bullish"] is False:
        st.write("Market is bearish - no buys today.")
    elif buy_candidates.empty:
        st.write("None of the Top 5 are above their 220 DMA right now.")
    else:
        st.write(", ".join(buy_candidates["Symbol"].tolist()))

    # ---- Download ----
    st.download_button(
        "Download full ranking as CSV",
        data=screen.to_csv(index=False).encode("utf-8"),
        file_name=f"greenlight_screen_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
