"""Shioaji (永豐) data fetcher — drop-in replacement for finmind_fetcher.

Public API is identical to finmind_fetcher so callers can swap without changes:
    shioaji_fetch_daily(symbol, lookback) -> pd.DataFrame
    shioaji_fetch_m3(symbol, date)        -> pd.DataFrame
    shioaji_fetch(symbol)                 -> tuple[pd.DataFrame, pd.DataFrame]
"""
from __future__ import annotations

import asyncio
import atexit
import logging
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

logger = logging.getLogger("shioaji-fetcher")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env.local")

# ── singleton state ────────────────────────────────────────────────────────────

_api = None          # shioaji.Shioaji instance
_login_lock = threading.Lock()
_logged_in: bool = False  # True only when _api is live


def _api_key() -> str | None:
    return os.getenv("SHIOAJI_API_KEY")


def _secret_key() -> str | None:
    # accept both env var names
    return os.getenv("SHIOAJI_SECRET_KEY") or os.getenv("SHIOAJI_API_SECRET")


def _get_api():
    """Return a logged-in Shioaji instance (singleton, thread-safe).

    Raises on failure; does NOT set a permanent failure flag — TTL cooldown is
    managed externally by DataSourceRouter.
    """
    global _api, _logged_in
    if _api is not None and _logged_in:
        return _api

    with _login_lock:
        if _api is not None and _logged_in:
            return _api
        try:
            import shioaji as sj  # imported here so missing package → clean error

            api_key = _api_key()
            secret = _secret_key()
            if not api_key or not secret:
                raise ValueError(
                    "SHIOAJI_API_KEY / SHIOAJI_SECRET_KEY not set in .env.local"
                )

            instance = sj.Shioaji()
            instance.login(
                api_key=api_key,
                secret_key=secret,
                contracts_cb=lambda t: logger.debug("contracts loaded: %s", t),
            )
            _api = instance
            _logged_in = True
            logger.info("Shioaji login OK")
        except Exception as exc:
            logger.warning("Shioaji login failed: %s", exc)
            raise
    return _api


async def warmup() -> bool:
    """Attempt login in a thread. Return True on success, False on failure."""
    try:
        await asyncio.to_thread(_get_api)
        return True
    except Exception:
        return False


def reset_login() -> None:
    """Clear login state so the next call to _get_api() will retry.

    重要：每次只清 Python 端的 `_api = None` 會在 shioaji server 端留下殭屍
    session，累積到單帳號連線額度上限就會回 451 「Too Many Connections」，
    後續 login 全部失敗甚至引發 pysolace native crash（SIGSEGV）。
    這裡先嘗試 `_api.logout()` 釋放 server 端連線，logout 失敗（已斷線）
    也忽略，然後再清 Python 端狀態。
    """
    global _api, _logged_in
    with _login_lock:
        old_api = _api
        _api = None
        _logged_in = False
    if old_api is not None:
        try:
            old_api.logout()
            logger.info("Shioaji logout OK before reset")
        except Exception as exc:
            logger.debug("Shioaji logout (best-effort) failed: %s", exc)
    logger.debug("Shioaji login state reset; will retry on next fetch")


@atexit.register
def _atexit_logout() -> None:
    """Process 正常結束時 logout，避免留殭屍 session 把連線額度用完。"""
    global _api
    if _api is None:
        return
    try:
        _api.logout()
        logger.info("Shioaji logout at exit")
    except Exception:
        pass
    _api = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _empty_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _kbars_to_df(kbars) -> pd.DataFrame:
    """Convert raw shioaji KBars object → normalised DataFrame."""
    df = pd.DataFrame({**kbars})
    if df.empty:
        return _empty_ohlcv()

    # shioaji returns ts (Unix-ns or datetime), Open, High, Low, Close, Volume
    df["ts"] = pd.to_datetime(df["ts"])
    rename = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    df = df.rename(columns=rename)
    required = ["ts", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.warning("shioaji kbars missing cols: %s", missing)
        return _empty_ohlcv()
    df = df[required].sort_values("ts").set_index("ts")
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def _resample_3m(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1-minute bars into 3-minute bars (every 3 rows, time-based)."""
    if df_1m.empty:
        return df_1m
    agg = df_1m.resample("3min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return agg.dropna(subset=["open", "high", "low", "close"])


def _to_date_str(d: date | str | None, *, offset_days: int = 0) -> str:
    if d is None:
        target = datetime.now().date()
    elif isinstance(d, str):
        target = datetime.fromisoformat(d[:10]).date()
    else:
        target = d
    if offset_days:
        target = target - timedelta(days=offset_days)
    return target.strftime("%Y-%m-%d")


# ── sync workers (run inside asyncio.to_thread) ───────────────────────────────

def _sync_fetch_daily(symbol: str, lookback: int) -> pd.DataFrame:
    api = _get_api()
    contract = api.Contracts.Stocks[symbol]
    if contract is None:
        raise ValueError(f"no contract for symbol {symbol}")

    end_str = _to_date_str(None)
    # fetch ~2× the lookback window to survive weekends/holidays
    start_str = _to_date_str(None, offset_days=lookback * 2 + 30)

    kbars = api.kbars(contract, start=start_str, end=end_str)
    df = _kbars_to_df(kbars)
    if df.empty:
        return df

    # Daily bars have date-only index; keep only rows where time == midnight
    # (shioaji daily bars have ts at 00:00 of each day)
    day_only = df[df.index.hour == 0] if hasattr(df.index, "hour") else df
    if day_only.empty:
        # fallback: resample to 1D
        day_only = df.resample("1D").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna(subset=["open"])

    return day_only.tail(lookback)


def _sync_fetch_1m(symbol: str, target_date: str) -> pd.DataFrame:
    """Fetch 1-minute bars for a single trading day.

    Shioaji returns minute bars when start == end (same calendar day).
    """
    api = _get_api()
    contract = api.Contracts.Stocks[symbol]
    if contract is None:
        raise ValueError(f"no contract for symbol {symbol}")

    kbars = api.kbars(contract, start=target_date, end=target_date)
    df = _kbars_to_df(kbars)

    if df.empty:
        return df

    # Keep only bars for the target date (filter out stray bars from other days)
    target = datetime.fromisoformat(target_date).date()
    df = df[df.index.date == target]
    return df


# ── public async API ──────────────────────────────────────────────────────────

async def shioaji_fetch_daily(symbol: str, lookback: int = 20) -> pd.DataFrame:
    """Fetch daily OHLCV; last `lookback` trading days.

    Returns DataFrame indexed by datetime with columns open/high/low/close/volume.
    """
    return await asyncio.to_thread(_sync_fetch_daily, symbol, lookback)


async def shioaji_fetch_m3(
    symbol: str, day: "date | str | None" = None
) -> pd.DataFrame:
    """Fetch 3-minute OHLCV for `symbol` on `day` (default = today).

    Fetches 1-minute bars from Shioaji and resamples to 3-minute bars.
    Aggregation: open=first, high=max, low=min, close=last, volume=sum.
    """
    target_str = _to_date_str(day)
    df_1m = await asyncio.to_thread(_sync_fetch_1m, symbol, target_str)
    if df_1m.empty:
        return _empty_ohlcv()
    return _resample_3m(df_1m)


async def shioaji_fetch_m1(symbol: str, days: int = 5) -> pd.DataFrame:
    """Fetch 1-minute OHLCV across the most-recent `days` trading days.

    Shioaji returns daily bars (not minute) when the kbars range spans more
    than one day, so we fetch one day at a time and concatenate. Walks backward
    from today, skipping weekends/holidays, until we have `days` non-empty
    sessions or run out of look-back budget.
    """
    return await asyncio.to_thread(_sync_fetch_m1_multi, symbol, days)


def _sync_fetch_m1_multi(symbol: str, days: int) -> pd.DataFrame:
    """Walk backward day-by-day collecting 1-minute bars."""
    api = _get_api()
    contract = api.Contracts.Stocks[symbol]
    if contract is None:
        raise ValueError(f"no contract for symbol {symbol}")

    frames: list[pd.DataFrame] = []
    cursor: date = datetime.now().date()
    sessions_collected = 0
    safety_budget = days * 4 + 7  # tolerate holidays / long weekends

    while sessions_collected < days and safety_budget > 0:
        d_str = cursor.strftime("%Y-%m-%d")
        try:
            kbars = api.kbars(contract, start=d_str, end=d_str)
            df = _kbars_to_df(kbars)
            if not df.empty:
                df = df[df.index.date == cursor]
                if not df.empty:
                    frames.append(df)
                    sessions_collected += 1
        except Exception as exc:
            logger.warning("kbars(%s, %s) failed: %s", symbol, d_str, exc)
        cursor = cursor - timedelta(days=1)
        safety_budget -= 1

    if not frames:
        return _empty_ohlcv()

    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="first")]
    return out


async def shioaji_fetch(symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Combined fetcher matching ScannerEngine.DataFetcher signature.

    Returns (daily_df, m3_df). Falls back to daily tail if m3 is empty.
    """
    daily, m3 = await asyncio.gather(
        shioaji_fetch_daily(symbol, lookback=60),
        shioaji_fetch_m3(symbol),
        return_exceptions=False,
    )
    if m3.empty and not daily.empty:
        m3 = daily.tail(30).copy()
    return daily, m3


def is_available() -> bool:
    """Return True if Shioaji credentials are configured."""
    return bool(_api_key() and _secret_key())
