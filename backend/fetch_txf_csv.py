"""Fetch TXF (台指期近月連續 TXFR1) 1-minute bars → data/txf_1min.csv

Data contract (do NOT change without updating all readers):
  file    : data/txf_1min.csv
  columns : datetime, open, high, low, close, volume
  datetime: Asia/Taipei-aware string  (e.g. 2024-06-13 08:46:00+08:00)
             = bar-OPEN timestamp; Shioaji labels bar-CLOSE, we subtract 1 min
  session : day only 08:45–13:45
  sort    : ascending by datetime, no duplicates

Usage:
    python -m backend.fetch_txf_csv              # last 500 trading days (~2 years)
    python -m backend.fetch_txf_csv --days 60    # shorter window
    python -m backend.fetch_txf_csv -v           # verbose logging
"""
from __future__ import annotations

from backend.env_guard import require
require("pandas", "shioaji", "dotenv")

import argparse
import asyncio
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from backend.shioaji_fetcher import _empty_ohlcv, _get_api, _kbars_to_df

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

logger = logging.getLogger("fetch_txf_csv")

SYMBOL = "TXFR1"                           # 台指期近月連續合約
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "txf_1min.csv"
TZ = "Asia/Taipei"
SESSION_START = time(8, 45)
SESSION_END   = time(13, 45)


# ── contract resolver ─────────────────────────────────────────────────────────

def _resolve_contract(api, symbol: str = SYMBOL):
    """Resolve TXF continuous contract from Shioaji Contracts tree.

    Tries three paths in order:
      1. Futures[symbol]          — direct index (some Shioaji builds)
      2. Futures.TXF.<symbol>     — attribute on the TXF category
      3. iterate Futures.TXF      — scan for code/symbol match
    """
    fut = api.Contracts.Futures
    try:
        contract = fut[symbol]
        if contract is not None:
            return contract
    except Exception:
        pass

    category = getattr(fut, "TXF", None)
    if category is not None:
        contract = getattr(category, symbol, None)
        if contract is not None:
            return contract
        try:
            for item in category:
                if symbol in (getattr(item, "code", None), getattr(item, "symbol", None)):
                    return item
        except TypeError:
            pass

    raise ValueError(
        f"Cannot resolve {symbol!r} from api.Contracts.Futures. "
        "Verify the account has FUTURES QUOTE permission."
    )


# ── single-day fetch (blocking) ───────────────────────────────────────────────

def _fetch_day(api, contract, day: date) -> pd.DataFrame:
    day_str = day.isoformat()
    try:
        kbars = api.kbars(contract, start=day_str, end=day_str)
        df = _kbars_to_df(kbars)
    except Exception as exc:
        logger.warning("kbars(%s, %s) failed: %s", SYMBOL, day_str, exc)
        return _empty_ohlcv()

    if df.empty:
        return df

    # keep only rows actually on this calendar day
    return df[df.index.date == day]


# ── main backfill ─────────────────────────────────────────────────────────────

def _backfill(days: int) -> pd.DataFrame:
    api = _get_api()
    contract = _resolve_contract(api)
    logger.info("contract resolved: %s", contract)

    frames: list[pd.DataFrame] = []
    cursor: date = datetime.now().date()
    collected = 0
    budget = days * 2 + 30          # tolerate weekends/holidays

    while collected < days and budget > 0:
        budget -= 1
        if cursor.weekday() >= 5:   # skip Sat/Sun
            cursor -= timedelta(days=1)
            continue

        df = _fetch_day(api, contract, cursor)
        if not df.empty:
            frames.append(df)
            collected += 1
            logger.debug("fetched %s (%d bars)", cursor, len(df))

        cursor -= timedelta(days=1)

    if not frames:
        raise RuntimeError("No data fetched — check Shioaji login and contract.")

    raw = pd.concat(frames).sort_index()
    raw = raw[~raw.index.duplicated(keep="first")]
    return raw


# ── post-processing ───────────────────────────────────────────────────────────

def _process(raw: pd.DataFrame) -> pd.DataFrame:
    # 1) convert index to tz-aware Asia/Taipei
    idx = pd.to_datetime(raw.index)
    if idx.tz is None:
        idx = idx.tz_localize(TZ)
    else:
        idx = idx.tz_convert(TZ)

    # 2) Shioaji labels bar at CLOSE → shift to bar-OPEN
    idx = idx - pd.Timedelta(minutes=1)

    raw = raw.copy()
    raw.index = idx

    # 3) day session only
    t = raw.index.time
    raw = raw[(t >= SESSION_START) & (t <= SESSION_END)]

    # 4) drop rows with any NaN in OHLCV
    raw = raw.dropna(subset=["open", "high", "low", "close", "volume"])

    # 5) build output DataFrame with contract columns
    out = raw[["open", "high", "low", "close", "volume"]].copy()
    out.index.name = "datetime"
    out = out.reset_index()
    out = out.sort_values("datetime").reset_index(drop=True)

    return out


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch TXF 1-min bars → data/txf_1min.csv")
    parser.add_argument("--days", type=int, default=500,
                        help="Trading days to back-fill (default 500 ≈ 2 years)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s | %(message)s",
    )

    logger.info("Starting TXF 1-min backfill (%d trading days)", args.days)
    raw = _backfill(args.days)
    df = _process(raw)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)

    # ── summary ──
    total = len(df)
    if total == 0:
        logger.error("Output is empty — nothing written.")
        return 1

    dt_col = df["datetime"]
    start_dt = dt_col.min()
    end_dt   = dt_col.max()
    trading_days = dt_col.dt.normalize().nunique()

    # expected trading days in range (rough: Mon-Fri)
    date_range_days = (end_dt.date() - start_dt.date()).days
    expected_days = sum(
        1 for i in range(date_range_days + 1)
        if (start_dt.date() + timedelta(days=i)).weekday() < 5
    )
    missing_days = max(0, expected_days - trading_days)

    logger.info("=" * 50)
    logger.info("Output  : %s", OUT_PATH)
    logger.info("Rows    : %d", total)
    logger.info("From    : %s", start_dt)
    logger.info("To      : %s", end_dt)
    logger.info("Days    : %d trading days", trading_days)
    logger.info("Missing : ~%d weekday gaps (holidays/no-data)", missing_days)
    logger.info("=" * 50)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
