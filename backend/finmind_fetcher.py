"""FinMind data fetcher for the scanner.

Endpoints used (v4):
- TaiwanStockPrice           → daily OHLCV
- TaiwanStockPriceMinute     → 1-minute OHLCV (resampled to 3m for the scanner)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import httpx
import pandas as pd
from dotenv import load_dotenv


logger = logging.getLogger("finmind-fetcher")

# Load .env.local once at import time
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env.local")

FINMIND_BASE: Final[str] = os.getenv(
    "FINMIND_API_BASE", "https://api.finmindtrade.com/api/v4/data"
)

REQUEST_INTERVAL_SECONDS: Final[float] = 0.5
MAX_RETRIES: Final[int] = 3
HTTP_TIMEOUT_SECONDS: Final[float] = 15.0

_last_request_at: float = 0.0
_request_lock: asyncio.Lock | None = None


def _token() -> str | None:
    return os.getenv("FINMIND_API_TOKEN") or os.getenv("FINMIND_TOKEN")


def _get_lock() -> asyncio.Lock:
    global _request_lock
    if _request_lock is None:
        _request_lock = asyncio.Lock()
    return _request_lock


async def _rate_limit() -> None:
    global _last_request_at
    async with _get_lock():
        now = asyncio.get_event_loop().time()
        wait = REQUEST_INTERVAL_SECONDS - (now - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = asyncio.get_event_loop().time()


class FinMindPaywallError(RuntimeError):
    """FinMind responded that this dataset requires a higher tier."""


async def _request_json(params: dict[str, str]) -> dict[str, Any]:
    """GET FinMind with rate limit + exponential backoff.

    FinMind returns HTTP 400 with a JSON body for paywalled datasets — we parse
    the body before raising and surface that as a typed error so callers can
    fall back instead of retrying.
    """
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        await _rate_limit()
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                resp = await client.get(FINMIND_BASE, params=params)

            # Try to parse body even on 4xx — FinMind encodes paywall info there.
            try:
                payload = resp.json() if resp.content else {}
            except ValueError:
                payload = {}

            if isinstance(payload, dict):
                msg = str(payload.get("msg", ""))
                if "level is register" in msg or "update your user level" in msg:
                    raise FinMindPaywallError(msg)

            resp.raise_for_status()

            if not isinstance(payload, dict):
                raise RuntimeError("FinMind response not a JSON object")
            if payload.get("status") != 200:
                raise RuntimeError(f"FinMind error: {payload.get('msg')}")
            return payload
        except FinMindPaywallError:
            raise  # do not retry paywalled datasets
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            last_error = exc
            backoff = 0.5 * (2**attempt)
            logger.warning(
                "FinMind attempt %d failed: %s; retrying in %.1fs",
                attempt + 1,
                exc,
                backoff,
            )
            await asyncio.sleep(backoff)
    raise RuntimeError(f"FinMind exhausted retries: {last_error}")


def _to_iso(d: date | datetime | str) -> str:
    if isinstance(d, str):
        return d[:10]
    if isinstance(d, datetime):
        return d.date().isoformat()
    return d.isoformat()


def _empty_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _normalise_daily(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return _empty_ohlcv()
    df = pd.DataFrame(rows)
    rename = {"max": "high", "min": "low", "Trading_Volume": "volume"}
    df = df.rename(columns=rename)
    cols = ["date", "open", "high", "low", "close", "volume"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        logger.warning("daily missing cols: %s", missing)
        return _empty_ohlcv()
    df = df[cols].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def _normalise_minute(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return _empty_ohlcv()
    df = pd.DataFrame(rows)
    # FinMind minute schema: date (YYYY-MM-DD HH:MM:SS), open, max, min, close, Trading_Volume
    rename = {"max": "high", "min": "low", "Trading_Volume": "volume"}
    df = df.rename(columns=rename)
    if "date" not in df.columns:
        return _empty_ohlcv()
    df["ts"] = pd.to_datetime(df["date"])
    cols = ["ts", "open", "high", "low", "close", "volume"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        logger.warning("minute missing cols: %s", missing)
        return _empty_ohlcv()
    df = df[cols].sort_values("ts").set_index("ts")
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def _resample_3m(df_1m: pd.DataFrame) -> pd.DataFrame:
    if df_1m.empty:
        return df_1m
    agg = df_1m.resample("3min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return agg.dropna(subset=["open", "high", "low", "close"])


# ---------- public API ----------


async def finmind_fetch_daily(symbol: str, lookback: int = 20) -> pd.DataFrame:
    """Fetch daily OHLCV for `symbol`, last `lookback` trading days.

    Returns DataFrame indexed by date with columns open/high/low/close/volume.
    """
    if lookback <= 0:
        raise ValueError("lookback must be > 0")
    # Pull a generous window to survive holidays/weekends, slice tail at the end.
    start = (datetime.now() - timedelta(days=lookback * 2 + 30)).date()
    params: dict[str, str] = {
        "dataset": "TaiwanStockPrice",
        "data_id": symbol,
        "start_date": _to_iso(start),
    }
    tok = _token()
    if tok:
        params["token"] = tok

    payload = await _request_json(params)
    df = _normalise_daily(payload.get("data") or [])
    return df.tail(lookback)


_intraday_paywalled: bool = False


async def finmind_fetch_m3(symbol: str, day: date | str | None = None) -> pd.DataFrame:
    """Fetch 3-minute OHLCV for `symbol` on `day` (default = latest trading day).

    FinMind's intraday dataset (`TaiwanStockKBar`) requires a paid tier. On a free
    account we receive HTTP 400 with "Your level is register..." — we mark the
    flag and return an empty frame so callers can decide to fall back.
    """
    global _intraday_paywalled
    if _intraday_paywalled:
        return _empty_ohlcv()

    if day is None:
        target = datetime.now().date()
    else:
        target = day if isinstance(day, date) else datetime.fromisoformat(str(day)).date()

    start = target - timedelta(days=5)
    params: dict[str, str] = {
        "dataset": "TaiwanStockKBar",
        "data_id": symbol,
        "start_date": _to_iso(start),
    }
    tok = _token()
    if tok:
        params["token"] = tok

    try:
        payload = await _request_json(params)
    except FinMindPaywallError:
        logger.warning(
            "FinMind intraday paywalled for free tier; scanner will use daily-fallback mode"
        )
        _intraday_paywalled = True
        return _empty_ohlcv()

    df_1m = _normalise_minute(payload.get("data") or [])
    if df_1m.empty:
        return _empty_ohlcv()

    df_3m = _resample_3m(df_1m)
    if df_3m.empty:
        return df_3m

    last_day = df_3m.index.normalize().max()
    return df_3m.loc[df_3m.index.normalize() == last_day]


async def finmind_fetch(symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Combined fetcher matching ScannerEngine.DataFetcher signature.

    When intraday data is paywalled, returns (daily, daily_tail) so the scanner
    can still evaluate conditions on day-grain bars instead of returning empty.
    """
    daily = await finmind_fetch_daily(symbol, lookback=60)
    m3 = await finmind_fetch_m3(symbol)
    if m3.empty and not daily.empty:
        # Daily-fallback: use the most recent ~30 daily bars as pseudo-intraday.
        m3 = daily.tail(30).copy()
    return daily, m3


def is_intraday_paywalled() -> bool:
    return _intraday_paywalled


def parse_symbols_env() -> list[str]:
    """Parse SCANNER_SYMBOLS env var (comma-separated). Falls back to defaults."""
    raw = os.getenv("SCANNER_SYMBOLS", "").strip()
    if not raw:
        return ["2382", "2330", "2449", "2317", "3231", "6515"]
    return [s.strip() for s in raw.split(",") if s.strip()]
