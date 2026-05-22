"""Crypto OHLCV fetcher via ccxt — drop-in shape-compatible with
backend.shioaji_fetcher.

Public API (matches shioaji_fetcher signatures so callers can swap):

    crypto_fetch_daily(symbol, lookback) -> pd.DataFrame
    crypto_fetch_m1(symbol, days)        -> pd.DataFrame
    crypto_fetch_m3(symbol, day=None)    -> pd.DataFrame

Defaults to Binance public REST (no API key needed for OHLCV).
Index is tz-naive UTC datetime; columns: open/high/low/close/volume.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger("crypto-fetcher")

_EXCHANGE = None
_EXCHANGE_ID = os.getenv("CRYPTO_EXCHANGE", "binance")
_PAGE_LIMIT = 1000  # binance max per request for 1m


def _get_exchange():
    """Lazy-init ccxt exchange (sync client; we wrap calls in to_thread)."""
    global _EXCHANGE
    if _EXCHANGE is not None:
        return _EXCHANGE
    import ccxt

    ex_cls = getattr(ccxt, _EXCHANGE_ID)
    _EXCHANGE = ex_cls({"enableRateLimit": True, "timeout": 30_000})
    logger.info("ccxt exchange ready: %s", _EXCHANGE_ID)
    return _EXCHANGE


def _empty_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _rows_to_df(rows: list) -> pd.DataFrame:
    if not rows:
        return _empty_ohlcv()
    df = pd.DataFrame(
        rows, columns=["ts", "open", "high", "low", "close", "volume"]
    )
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_convert(None)
    df = df.set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def _sync_fetch_ohlcv_window(
    symbol: str, timeframe: str, since_ms: int, until_ms: int
) -> list:
    """Walk forward in `_PAGE_LIMIT`-sized chunks from since_ms until until_ms."""
    ex = _get_exchange()
    out: list = []
    cursor = since_ms
    tf_ms = ex.parse_timeframe(timeframe) * 1000

    while cursor < until_ms:
        try:
            batch = ex.fetch_ohlcv(
                symbol, timeframe=timeframe, since=cursor, limit=_PAGE_LIMIT
            )
        except Exception as exc:
            logger.warning(
                "fetch_ohlcv %s %s since=%s failed: %s",
                symbol, timeframe, cursor, exc,
            )
            break
        if not batch:
            break
        out.extend(batch)
        last_ts = batch[-1][0]
        next_cursor = last_ts + tf_ms
        if next_cursor <= cursor:  # safety
            break
        cursor = next_cursor
        if len(batch) < _PAGE_LIMIT:
            # binance hit the present — stop
            break
    return out


async def crypto_fetch_m1(symbol: str = "BTC/USDT", days: int = 30) -> pd.DataFrame:
    """Fetch 1-minute OHLCV for the last `days` days."""
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    since_ms = now_ms - days * 24 * 60 * 60 * 1000
    rows = await asyncio.to_thread(
        _sync_fetch_ohlcv_window, symbol, "1m", since_ms, now_ms
    )
    df = _rows_to_df(rows)
    if df.empty:
        logger.warning("crypto_fetch_m1 returned empty for %s", symbol)
    else:
        logger.info(
            "crypto_fetch_m1 %s: %d bars (%s → %s)",
            symbol, len(df), df.index[0], df.index[-1],
        )
    return df


async def crypto_fetch_daily(
    symbol: str = "BTC/USDT", lookback: int = 120
) -> pd.DataFrame:
    """Fetch daily OHLCV; last `lookback` trading days (no holidays for crypto)."""
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    since_ms = now_ms - (lookback + 5) * 24 * 60 * 60 * 1000
    rows = await asyncio.to_thread(
        _sync_fetch_ohlcv_window, symbol, "1d", since_ms, now_ms
    )
    df = _rows_to_df(rows)
    if df.empty:
        return df
    return df.tail(lookback)


async def crypto_fetch_m3(
    symbol: str = "BTC/USDT", day: Optional[datetime] = None
) -> pd.DataFrame:
    """Fetch 3-minute OHLCV (resampled from 1m) for one UTC day.

    `day=None` → today UTC.
    """
    target = (day or datetime.now(tz=timezone.utc)).date()
    start = datetime.combine(target, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    rows = await asyncio.to_thread(
        _sync_fetch_ohlcv_window,
        symbol, "1m",
        int(start.timestamp() * 1000),
        int(end.timestamp() * 1000),
    )
    df_1m = _rows_to_df(rows)
    if df_1m.empty:
        return df_1m
    return df_1m.resample("3min").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna(subset=["open"])


def is_available() -> bool:
    """ccxt + public Binance endpoint — always available (no creds needed)."""
    try:
        import ccxt  # noqa
        return True
    except ImportError:
        return False
