"""Shioaji → UDF bar-data adapter.

Maps TradingView UDF resolution strings ("1", "3", "D", ...) to the existing
shioaji fetchers and slices results to the requested [from, to] window.

UDF range semantics (from TradingView's docs):
    `from` and `to` are UNIX seconds, both INCLUSIVE.
    The response timestamps must be in seconds since epoch.

We intentionally treat naive Shioaji timestamps as Taipei-local-rendered-as-UTC
(see smc_report._to_unix_seconds), so the chart axis shows TWSE session times
regardless of the viewer's timezone.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Final, Literal, Optional

import pandas as pd

from backend.shioaji_fetcher import (
    shioaji_fetch_daily,
    shioaji_fetch_m1,
    shioaji_fetch_m3,
)

logger = logging.getLogger("tv-chart.data")

# UDF resolutions we expose. TV accepts both "1D"/"D", "1W"/"W", "1M"/"M".
SUPPORTED_RESOLUTIONS: Final[tuple[str, ...]] = (
    "1", "3", "5", "15", "30", "60",
    "1D", "D",
    "1W", "W",
    "1M", "M",
)

# How many trading days of 1-minute history to pull for each intraday TF.
# Bigger TF → fewer bars per day → need more days of source data.
_INTRADAY_BASE_DAYS: Final[dict[str, int]] = {
    "1":  5,    # 5 sessions × ~270 bars = ~1350 bars
    "3":  5,    # ~450
    "5":  10,   # ~540
    "15": 20,   # ~360
    "30": 30,   # ~270
    "60": 60,   # ~300  (TWSE only gives ~5 hourly bars/day)
}

# How many DAILY bars to pull when serving weekly / monthly resolutions.
_DAILY_BASE_LOOKBACK: Final[dict[str, int]] = {
    "1D": 120,
    "D":  120,
    "1W": 365,    # ~52 weekly bars
    "W":  365,
    "1M": 900,    # ~30 monthly bars
    "M":  900,
}

# Aggregation rules used by every resample step.
_RESAMPLE_AGG = {
    "open": "first", "high": "max",
    "low":  "min",   "close": "last",
    "volume": "sum",
}

Resolution = Literal["1", "3", "5", "15", "30", "60", "1D", "D", "1W", "W", "1M", "M"]


@dataclass(frozen=True)
class BarSlice:
    """A response payload for /history, already aligned to UDF's column-major form."""
    times: list[int]
    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]
    volumes: list[float]

    def to_udf(self) -> dict:
        if not self.times:
            return {"s": "no_data"}
        return {
            "s": "ok",
            "t": self.times,
            "o": self.opens,
            "h": self.highs,
            "l": self.lows,
            "c": self.closes,
            "v": self.volumes,
        }


def _df_to_bar_slice(df: pd.DataFrame, frm: int, to: int) -> BarSlice:
    if df is None or df.empty:
        return BarSlice([], [], [], [], [], [])

    # Treat naive timestamps as Taipei-local-rendered-as-UTC to match the
    # axis convention used in the matplotlib + lightweight-charts reports.
    times_ns = df.index.astype("int64")
    times = (times_ns // 1_000_000_000).tolist()

    # Slice to the requested window. UDF wants `from` and `to` both inclusive.
    mask = [(t >= frm and t <= to) for t in times]
    if not any(mask):
        return BarSlice([], [], [], [], [], [])

    keep_idx = [i for i, ok in enumerate(mask) if ok]
    return BarSlice(
        times=[times[i] for i in keep_idx],
        opens=[float(df["open"].iat[i]) for i in keep_idx],
        highs=[float(df["high"].iat[i]) for i in keep_idx],
        lows=[float(df["low"].iat[i]) for i in keep_idx],
        closes=[float(df["close"].iat[i]) for i in keep_idx],
        volumes=[float(df["volume"].iat[i]) for i in keep_idx],
    )


# ── internal helpers ─────────────────────────────────────────────────────────

def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    return df.resample(rule).agg(_RESAMPLE_AGG).dropna(subset=["open"])


def _days_for_intraday(resolution: str, frm: int, to: int) -> int:
    """How many days of m1 source to pull for a given intraday resolution."""
    base = _INTRADAY_BASE_DAYS.get(resolution, 5)
    window_days = max(1, int((to - frm) / 86400) + 2)
    # Cap to base × 2 so a wide TV pan doesn't trigger unbounded fetches.
    return min(max(base, window_days), base * 2)


async def _intraday_frame(symbol: str, resolution: str, frm: int, to: int) -> pd.DataFrame:
    """Fetch + resample m1 source data to the requested intraday resolution."""
    days = _days_for_intraday(resolution, frm, to)
    if resolution == "1":
        if days == 1:
            # one-day fast path uses the existing m3-style fetcher (no-op resample below)
            return await shioaji_fetch_m1(symbol, days=1)
        return await shioaji_fetch_m1(symbol, days=days)
    if resolution == "3" and days == 1:
        # use the dedicated single-day fetcher (slightly faster)
        return await shioaji_fetch_m3(symbol)
    m1 = await shioaji_fetch_m1(symbol, days=days)
    return _resample(m1, f"{resolution}min")


async def _daily_or_higher_frame(symbol: str, resolution: str) -> pd.DataFrame:
    """Daily / weekly / monthly bars, derived from the daily fetcher."""
    lookback = _DAILY_BASE_LOOKBACK.get(resolution, 120)
    daily = await shioaji_fetch_daily(symbol, lookback=lookback)
    if daily is None or daily.empty:
        return daily
    if resolution in ("1D", "D"):
        return daily
    # Pandas alias map: "W" = weekly (Sun-ending), "ME" = month-end.
    rule = "1W" if resolution in ("1W", "W") else "1ME"
    return _resample(daily, rule)


# ── public ────────────────────────────────────────────────────────────────────

async def fetch_bars(
    symbol: str,
    resolution: str,
    frm: int,
    to: int,
) -> BarSlice:
    """Pull bars for `symbol` at `resolution` covering [frm, to] in UNIX seconds.

    Daily / weekly / monthly derive from `shioaji_fetch_daily`; intraday
    resolutions (1/3/5/15/30/60) derive from `shioaji_fetch_m1` resampled by
    pandas. The window itself is sliced after the fetch so TV's range pans
    return only the relevant bars.
    """
    if resolution in _DAILY_BASE_LOOKBACK:
        df = await _daily_or_higher_frame(symbol, resolution)
        return _df_to_bar_slice(df, frm, to)

    if resolution in _INTRADAY_BASE_DAYS:
        df = await _intraday_frame(symbol, resolution, frm, to)
        return _df_to_bar_slice(df, frm, to)

    return BarSlice([], [], [], [], [], [])


async def fetch_full_for_marks(symbol: str, resolution: str, days: int = 5) -> pd.DataFrame:
    """Return a wide-window DataFrame used by /marks to recompute SMC events.

    SMC features need the whole series for context — slicing only the visible
    window can drop events that fired earlier. We grab the same lookback as
    `fetch_bars` would for that resolution.
    """
    if resolution in _DAILY_BASE_LOOKBACK:
        return await _daily_or_higher_frame(symbol, resolution)
    if resolution in _INTRADAY_BASE_DAYS:
        base_days = _INTRADAY_BASE_DAYS[resolution]
        return await _intraday_frame(symbol, resolution,
                                     frm=0, to=base_days * 86400)
    return pd.DataFrame()
