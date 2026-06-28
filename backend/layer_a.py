"""Layer A — Daily macro bias (US bonds + DXY + US indexes).

Downloads via yfinance and computes a daily bias score for Taiwan futures:

  A1  US 10Y yield vs MA20  : rising yield → bearish (-1), falling → (+1)
  A2  DXY vs MA20           : strong USD   → bearish (-1), weak    → (+1)
  A3  US index alignment    : all 3 green  → (+1), all red → (-1), mixed → 0

  bias_a = A1 + A2 + A3  ∈ {-3 … +3}

Output: data/layer_a_daily.csv  (one row per calendar date)

Usage:
    python -m backend.layer_a               # fetch & save
    python -m backend.layer_a --tail 10     # also print last N rows
"""
from __future__ import annotations

from backend.env_guard import require
require("pandas", "yfinance")

import argparse
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger("layer_a")

TICKERS = {
    "tnx": "^TNX",      # US 10Y yield
    "dxy": "DX-Y.NYB",  # US dollar index
    "dji": "^DJI",
    "spx": "^GSPC",
    "ndx": "^IXIC",
}
MA_WINDOW = 20
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "layer_a_daily.csv"


def _download(years: int = 3) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("pip install yfinance")

    period = f"{years}y"
    frames = {}
    for name, ticker in TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
            if hist.empty:
                logger.warning("empty history for %s", ticker)
                continue
            close = hist["Close"]
            close.index = pd.to_datetime(close.index).tz_localize(None)
            frames[name] = close.rename(name)
        except Exception as exc:
            logger.warning("download %s failed: %s", ticker, exc)

    if not frames:
        raise RuntimeError("All downloads failed — check network / yfinance install")

    combined = pd.concat(list(frames.values()), axis=1, sort=True)
    combined.index = pd.to_datetime(combined.index).tz_localize(None)
    return combined.sort_index().dropna(how="all")


def compute_bias(raw: pd.DataFrame, ma_window: int = MA_WINDOW) -> pd.DataFrame:
    df = raw.copy()

    # A1: 10Y yield direction vs MA
    if "tnx" in df.columns:
        df["tnx_ma"] = df["tnx"].rolling(ma_window).mean()
        df["a1"] = (df["tnx"] < df["tnx_ma"]).map({True: 1, False: -1})
    else:
        df["a1"] = 0

    # A2: DXY direction vs MA  (strong DXY = bearish for TW stocks)
    if "dxy" in df.columns:
        df["dxy_ma"] = df["dxy"].rolling(ma_window).mean()
        df["a2"] = (df["dxy"] < df["dxy_ma"]).map({True: 1, False: -1})
    else:
        df["a2"] = 0

    # A3: US index daily return alignment
    index_cols = [c for c in ["dji", "spx", "ndx"] if c in df.columns]
    if index_cols:
        for col in index_cols:
            df[f"{col}_ret"] = df[col].pct_change()
        ret_cols = [f"{c}_ret" for c in index_cols]
        all_pos = (df[ret_cols] > 0).all(axis=1)
        all_neg = (df[ret_cols] < 0).all(axis=1)
        df["a3"] = 0
        df.loc[all_pos, "a3"] = 1
        df.loc[all_neg, "a3"] = -1
    else:
        df["a3"] = 0

    df["bias_a"] = df["a1"] + df["a2"] + df["a3"]

    keep = ["tnx", "dxy", "dji", "spx", "ndx", "a1", "a2", "a3", "bias_a"]
    out = df[[c for c in keep if c in df.columns]].copy()
    out.index.name = "date"
    return out.dropna(subset=["bias_a"])


def fetch_and_save(years: int = 3) -> pd.DataFrame:
    raw = _download(years)
    bias = compute_bias(raw)
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    bias.to_csv(DATA_PATH)
    logger.info("Saved %d rows → %s", len(bias), DATA_PATH)
    return bias


def load() -> pd.DataFrame:
    """Load pre-computed layer_a_daily.csv; run fetch_and_save() first."""
    df = pd.read_csv(DATA_PATH, parse_dates=["date"], index_col="date")
    return df


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch macro bias → layer_a_daily.csv")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--tail", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s | %(message)s")
    bias = fetch_and_save(args.years)
    if args.tail:
        print(bias.tail(args.tail).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
