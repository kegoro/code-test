"""Layer B — Session structure: Opening Range + session classifier.

Reads data/txf_1min.csv (data contract from fetch_txf_csv.py) and produces
per-day session metadata:

  date          : trading date (Asia/Taipei)
  orh           : Opening Range High  (first OR_WINDOW_MIN of day session)
  orl           : Opening Range Low
  day_high      : full day-session high
  day_low       : full day-session low
  close         : last bar close of day session
  or_range_pts  : ORH - ORL (volatility proxy)
  bias_b        : +1 = day closed above ORH midpoint, -1 = below, 0 = inside OR

Usage:
    python -m backend.layer_b                 # print last 10 days
    python -m backend.layer_b --csv out.csv   # save to CSV

This module is also importable; call compute_sessions(df_1m) directly.
"""
from __future__ import annotations

from datetime import time
from pathlib import Path

import pandas as pd

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "txf_1min.csv"

# ── parameters (tune after backtesting) ─────────────────────────────────────
OR_WINDOW_MIN = 30        # opening range = first N minutes of day session
SESSION_START = time(8, 45)
SESSION_END   = time(13, 45)
OR_START      = time(8, 45)
OR_END_OFFSET = OR_WINDOW_MIN  # minutes after session open


def load_1m(path: Path = DATA_PATH) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["datetime"])
    if df["datetime"].dt.tz is None:
        df["datetime"] = df["datetime"].dt.tz_localize("Asia/Taipei")
    else:
        df["datetime"] = df["datetime"].dt.tz_convert("Asia/Taipei")
    t = df["datetime"].dt.time
    df = df.loc[(t >= SESSION_START) & (t <= SESSION_END)].copy()
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def compute_sessions(df: pd.DataFrame, or_window_min: int = OR_WINDOW_MIN) -> pd.DataFrame:
    """Compute per-day ORH/ORL and session stats from 1-min bar DataFrame.

    Input df must have columns: datetime (tz-aware), open, high, low, close, volume.
    Returns one row per trading date.
    """
    df = df.copy()
    df["date"] = df["datetime"].dt.normalize()

    rows = []
    for date, group in df.groupby("date"):
        group = group.sort_values("datetime")
        first_bar_time = group["datetime"].iloc[0]

        # opening range window
        or_cutoff = first_bar_time + pd.Timedelta(minutes=or_window_min)
        or_bars = group[group["datetime"] <= or_cutoff]
        session_bars = group  # full day session

        if or_bars.empty:
            continue

        orh = or_bars["high"].max()
        orl = or_bars["low"].min()
        or_mid = (orh + orl) / 2
        day_high = session_bars["high"].max()
        day_low  = session_bars["low"].min()
        close    = session_bars["close"].iloc[-1]

        # simple session bias: did price close above/below OR midpoint?
        if close > or_mid:
            bias_b = 1
        elif close < or_mid:
            bias_b = -1
        else:
            bias_b = 0

        rows.append({
            "date":         date.date(),
            "orh":          orh,
            "orl":          orl,
            "or_mid":       round(or_mid, 1),
            "or_range_pts": round(orh - orl, 1),
            "day_high":     day_high,
            "day_low":      day_low,
            "close":        close,
            "bias_b":       bias_b,
        })

    return pd.DataFrame(rows)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Layer B — session ORH/ORL stats")
    parser.add_argument("--csv", help="Save output to CSV path")
    parser.add_argument("--tail", type=int, default=10, help="Print last N days")
    parser.add_argument("--or-window", type=int, default=OR_WINDOW_MIN,
                        help="Opening range window in minutes (default 30)")
    args = parser.parse_args()

    df_1m = load_1m()
    sessions = compute_sessions(df_1m, or_window_min=args.or_window)

    print(sessions.tail(args.tail).to_string(index=False))
    print(f"\n{len(sessions)} trading days total")
    print(f"OR range mean: {sessions['or_range_pts'].mean():.1f} pts  "
          f"median: {sessions['or_range_pts'].median():.1f} pts")

    if args.csv:
        sessions.to_csv(args.csv, index=False)
        print(f"Saved to {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
