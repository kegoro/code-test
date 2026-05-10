"""Shioaji M3 history cache.

Fetches 1-minute bars from Shioaji for a multi-day window, aggregates them
into 3-minute bars, and persists per-symbol-per-day parquet files under
``data/shioaji_m3/``.

Public API
----------
- ``fetch_history_m3(symbol, days)`` -> dict[date, DataFrame]
- ``load_cached_m3(symbol)``         -> dict[date, DataFrame]
- ``build_cache(symbols, days)``     -> dict[symbol, dict[date, DataFrame]]
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

from backend.shioaji_fetcher import (
    _empty_ohlcv,
    _kbars_to_df,
    _resample_3m,
    _get_api,
)

logger = logging.getLogger("shioaji-history-cache")

CACHE_ROOT = Path("data/shioaji_m3")
TW_HOLIDAYS_LOOKAHEAD = 60  # how many calendar days to scan back for `days` trade days


def _cache_path(symbol: str, day: date) -> Path:
    sym_dir = CACHE_ROOT / symbol
    sym_dir.mkdir(parents=True, exist_ok=True)
    return sym_dir / f"{day.isoformat()}.parquet"


def _read_cached(symbol: str, day: date) -> pd.DataFrame | None:
    path = _cache_path(symbol, day)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        if df.empty:
            return df
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache read failed for %s %s: %s", symbol, day, exc)
        return None


def _write_cached(symbol: str, day: date, df: pd.DataFrame) -> None:
    path = _cache_path(symbol, day)
    try:
        df.to_parquet(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache write failed for %s %s: %s", symbol, day, exc)


def _trading_days(end: date, n: int) -> list[date]:
    """Return the last `n` weekday dates ending at `end` (rough approximation).

    Holidays are tolerated downstream — fetch returns empty for non-trading days
    and we simply skip them.
    """
    out: list[date] = []
    cursor = end
    safety = 0
    while len(out) < n and safety < TW_HOLIDAYS_LOOKAHEAD * 2:
        if cursor.weekday() < 5:  # Mon..Fri
            out.append(cursor)
        cursor -= timedelta(days=1)
        safety += 1
    return list(reversed(out))


def _sync_fetch_1m_range(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Fetch 1-minute bars for ``[start, end]`` in a single Shioaji call."""
    api = _get_api()
    contract = api.Contracts.Stocks[symbol]
    if contract is None:
        raise ValueError(f"no contract for symbol {symbol}")
    kbars = api.kbars(contract, start=start.isoformat(), end=end.isoformat())
    return _kbars_to_df(kbars)


async def fetch_history_m3(
    symbol: str,
    days: int = 30,
    *,
    end: date | None = None,
    refresh: bool = False,
) -> dict[date, pd.DataFrame]:
    """Return ``{day: m3_df}`` for the last `days` trading days.

    Cached per-day; only missing days are fetched. The fetch itself is one
    Shioaji request covering the full window.
    """
    end = end or datetime.now().date()
    target_days = _trading_days(end, days)

    cached: dict[date, pd.DataFrame] = {}
    missing: list[date] = []
    for d in target_days:
        if not refresh:
            cached_df = _read_cached(symbol, d)
            if cached_df is not None:
                cached[d] = cached_df
                continue
        missing.append(d)

    if missing:
        start = min(missing)
        stop = max(missing)
        logger.info(
            "fetching shioaji 1m %s [%s..%s] (%d missing days)",
            symbol, start, stop, len(missing),
        )
        try:
            df_1m = await asyncio.to_thread(_sync_fetch_1m_range, symbol, start, stop)
        except Exception as exc:  # noqa: BLE001
            logger.error("shioaji history fetch failed for %s: %s", symbol, exc)
            df_1m = _empty_ohlcv()

        for d in missing:
            day_1m = df_1m[df_1m.index.date == d] if not df_1m.empty else _empty_ohlcv()
            day_m3 = _resample_3m(day_1m) if not day_1m.empty else _empty_ohlcv()
            _write_cached(symbol, d, day_m3)
            cached[d] = day_m3

    return {d: cached[d] for d in target_days if d in cached}


def load_cached_m3(symbol: str) -> dict[date, pd.DataFrame]:
    """Load every cached day for ``symbol`` from disk (no network)."""
    sym_dir = CACHE_ROOT / symbol
    if not sym_dir.exists():
        return {}
    out: dict[date, pd.DataFrame] = {}
    for path in sorted(sym_dir.glob("*.parquet")):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        df = _read_cached(symbol, day)
        if df is not None:
            out[day] = df
    return out


async def build_cache(
    symbols: Iterable[str],
    days: int = 30,
    *,
    end: date | None = None,
    refresh: bool = False,
) -> dict[str, dict[date, pd.DataFrame]]:
    """Build cache for many symbols (sequential to respect Shioaji rate limits)."""
    out: dict[str, dict[date, pd.DataFrame]] = {}
    for sym in symbols:
        out[sym] = await fetch_history_m3(sym, days=days, end=end, refresh=refresh)
    return out


def concat_history(history: dict[date, pd.DataFrame]) -> pd.DataFrame:
    """Concatenate per-day M3 frames into one chronologically-sorted DataFrame."""
    frames = [df for df in history.values() if df is not None and not df.empty]
    if not frames:
        return _empty_ohlcv()
    return pd.concat(frames).sort_index()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build Shioaji M3 cache")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s | %(message)s",
    )
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    cache = asyncio.run(build_cache(symbols, days=args.days, refresh=args.refresh))
    for sym, days_map in cache.items():
        rows = sum(len(df) for df in days_map.values())
        logger.info("%s: %d days cached, %d total M3 bars", sym, len(days_map), rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
