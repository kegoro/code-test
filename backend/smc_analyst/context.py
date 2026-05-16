"""Build the immutable AnalysisContext used by every Setup.

`gather_context(symbol)` pulls HTF (daily), MTF (60m), LTF (1m) frames in one
shot, runs every detector once, and packages the results so the setup
classes can read state without re-fetching or re-computing.

A TTL cache keyed on `(symbol, last_ltf_bar_timestamp)` shares the work
across multiple setups in the same pipeline invocation.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Any, Final, Literal, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backend.shioaji_fetcher import shioaji_fetch_daily, shioaji_fetch_m1
from backend.smc_detector import (
    _atr_series,
    classify_strong_weak,
    compute_mtf_levels,
    compute_premium_discount,
    compute_trendlines,
    detect_market_structure,
    find_fair_value_gaps,
    find_order_blocks,
    find_swing_points,
    mark_equal_pivots,
)

logger = logging.getLogger("smc-analyst.context")

_TZ_TW = ZoneInfo("Asia/Taipei")
_CACHE_TTL_SECONDS: Final[int] = 30
_MAX_CACHE: Final[int] = 64

# How wide a window each frame uses. Tunable; matches the doc.
_HTF_LOOKBACK_DAYS: Final[int] = 120
_MTF_DAYS_M1_SOURCE: Final[int] = 30      # 60m × 5 bars/day × 30 days = ~150 bars
_LTF_DAYS_M1: Final[int] = 5              # ≈ 1350 1-minute bars

# How many bars back a liquidity sweep counts as "recent" for setup triggers.
SWEEP_RECENCY_BARS: Final[int] = 30


SessionPhase = Literal["closed", "open_drive", "trend_morning", "lunch",
                       "trend_afternoon", "close_drive"]


# ── frame wrapper ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Frame:
    """One timeframe's bars + the structure detection run on it."""
    timeframe: str
    bars: pd.DataFrame
    swing_n: int
    structure: dict
    atr: float = 0.0

    @property
    def empty(self) -> bool:
        return self.bars is None or self.bars.empty

    @property
    def last_close(self) -> float:
        if self.empty:
            return float("nan")
        return float(self.bars["close"].iloc[-1])

    @property
    def last_bar_ts(self) -> int:
        if self.empty:
            return 0
        return int(self.bars.index[-1].value // 1_000_000_000)


# ── liquidity / sweep map ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class Sweep:
    """A confirmed liquidity sweep: wick pierced a level, close came back."""
    level: float
    target_kind: str     # "swing_high" / "swing_low" / "eqh" / "eql" / "pdh" / "pdl" / "pwh" / "pwl"
    direction: Literal["up", "down"]   # "up" = wick above (relevant for shorts)
    bar_idx: int
    bar_ts: int


@dataclass(frozen=True)
class LiquidityMap:
    """All sweeps detected on the LTF frame, plus the raw level list."""
    sweeps: tuple[Sweep, ...] = field(default_factory=tuple)
    levels: dict[str, list[float]] = field(default_factory=dict)

    def recent(self, *, within_bars: int, max_bar_idx: int) -> list[Sweep]:
        cutoff = max_bar_idx - within_bars
        return [s for s in self.sweeps if s.bar_idx >= cutoff]


def _detect_sweep_on_level(
    df: pd.DataFrame,
    level: float,
    target_kind: str,
    *,
    direction: Literal["up", "down"],
) -> Optional[Sweep]:
    """Return the most-recent sweep of `level` on `df`, or None.

    Upward sweep: high > level AND close < level (wick above, body back below).
    Downward sweep: low < level AND close > level (wick below, body back above).
    """
    if df is None or df.empty:
        return None
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(df)
    # Walk newest → oldest to take the latest sweep.
    for t in range(n - 1, -1, -1):
        if direction == "up":
            if high[t] > level and close[t] < level:
                ts = int(df.index[t].value // 1_000_000_000)
                return Sweep(level=float(level), target_kind=target_kind,
                             direction="up", bar_idx=t, bar_ts=ts)
        else:
            if low[t] < level and close[t] > level:
                ts = int(df.index[t].value // 1_000_000_000)
                return Sweep(level=float(level), target_kind=target_kind,
                             direction="down", bar_idx=t, bar_ts=ts)
    return None


def _build_liquidity_map(
    ltf: Frame,
    *,
    mtf_levels: dict,
    equal_pivots: dict,
) -> LiquidityMap:
    """Detect sweeps of every interesting level on the LTF frame."""
    if ltf.empty:
        return LiquidityMap()

    sweeps: list[Sweep] = []
    levels_by_kind: dict[str, list[float]] = {}

    # MTF levels (PDH/PDL/PWH/PWL)
    for kind in ("pdh", "pdl", "pwh", "pwl"):
        v = (mtf_levels or {}).get(kind)
        if v is None:
            continue
        levels_by_kind.setdefault(kind, []).append(float(v))
        direction = "up" if kind in ("pdh", "pwh") else "down"
        sweep = _detect_sweep_on_level(ltf.bars, v, kind, direction=direction)
        if sweep:
            sweeps.append(sweep)

    # Swing extremes from LTF structure (last swing high/low)
    sp = ltf.structure.get("swing_points", {})
    highs = sp.get("swing_highs") or []
    lows = sp.get("swing_lows") or []
    if highs:
        last_sh = highs[-1]
        levels_by_kind.setdefault("swing_high", []).append(last_sh["price"])
        sweep = _detect_sweep_on_level(
            ltf.bars.iloc[last_sh["bar_idx"] + 1:],
            last_sh["price"], "swing_high", direction="up",
        )
        if sweep:
            # rebase bar_idx onto the full ltf frame
            sweeps.append(Sweep(
                level=sweep.level, target_kind=sweep.target_kind,
                direction="up",
                bar_idx=sweep.bar_idx + last_sh["bar_idx"] + 1,
                bar_ts=sweep.bar_ts,
            ))
    if lows:
        last_sl = lows[-1]
        levels_by_kind.setdefault("swing_low", []).append(last_sl["price"])
        sweep = _detect_sweep_on_level(
            ltf.bars.iloc[last_sl["bar_idx"] + 1:],
            last_sl["price"], "swing_low", direction="down",
        )
        if sweep:
            sweeps.append(Sweep(
                level=sweep.level, target_kind=sweep.target_kind,
                direction="down",
                bar_idx=sweep.bar_idx + last_sl["bar_idx"] + 1,
                bar_ts=sweep.bar_ts,
            ))

    # EQH / EQL pairs — sweep of the matched level
    for _prev, curr in (equal_pivots or {}).get("equal_highs", []):
        level = curr["price"]
        levels_by_kind.setdefault("eqh", []).append(level)
        sweep = _detect_sweep_on_level(
            ltf.bars.iloc[curr["bar_idx"] + 1:],
            level, "eqh", direction="up",
        )
        if sweep:
            sweeps.append(Sweep(
                level=sweep.level, target_kind="eqh", direction="up",
                bar_idx=sweep.bar_idx + curr["bar_idx"] + 1,
                bar_ts=sweep.bar_ts,
            ))
    for _prev, curr in (equal_pivots or {}).get("equal_lows", []):
        level = curr["price"]
        levels_by_kind.setdefault("eql", []).append(level)
        sweep = _detect_sweep_on_level(
            ltf.bars.iloc[curr["bar_idx"] + 1:],
            level, "eql", direction="down",
        )
        if sweep:
            sweeps.append(Sweep(
                level=sweep.level, target_kind="eql", direction="down",
                bar_idx=sweep.bar_idx + curr["bar_idx"] + 1,
                bar_ts=sweep.bar_ts,
            ))

    # Keep latest sweep per target_kind (drop dupes), sorted by bar_idx asc
    by_kind: dict[str, Sweep] = {}
    for s in sweeps:
        if s.target_kind not in by_kind or s.bar_idx > by_kind[s.target_kind].bar_idx:
            by_kind[s.target_kind] = s
    unique = tuple(sorted(by_kind.values(), key=lambda s: s.bar_idx))
    return LiquidityMap(sweeps=unique, levels=levels_by_kind)


# ── analysis context (the immutable bundle) ───────────────────────────────────

@dataclass(frozen=True)
class AnalysisContext:
    """Everything a Setup needs to evaluate, computed once per (symbol, bar)."""

    symbol: str
    now_tw: datetime
    session_phase: SessionPhase

    htf: Frame
    mtf: Frame
    ltf: Frame

    liquidity: LiquidityMap
    pd_zones: Optional[dict]
    mtf_levels: dict
    equal_pivots: dict
    strong_weak: dict
    active_obs: list[dict]
    active_fvgs: list[dict]
    trendlines: Optional[dict]

    atr_ltf: float

    # convenience
    @property
    def last_close(self) -> float:
        return self.ltf.last_close

    @property
    def htf_bias(self) -> str:
        return self.htf.structure.get("structure", "ranging")

    def htf_aligned(self, direction: Literal["long", "short"]) -> bool:
        """True when HTF doesn't actively oppose the trade.

        Ranging HTF counts as aligned (no bias = no opposition) — the
        counter-trend penalty only fires when HTF is clearly trending
        against the trade direction.
        """
        if self.htf_bias == "ranging":
            return True
        if direction == "long" and self.htf_bias == "bullish":
            return True
        if direction == "short" and self.htf_bias == "bearish":
            return True
        return False


# ── session helpers ───────────────────────────────────────────────────────────

def _session_phase(now: datetime) -> SessionPhase:
    """TWSE session classification — see doc §6."""
    if now.weekday() >= 5:
        return "closed"
    t = now.time()
    if t < dtime(9, 0) or t > dtime(13, 30):
        return "closed"
    if t < dtime(9, 30):
        return "open_drive"
    if t < dtime(11, 30):
        return "trend_morning"
    if t < dtime(12, 30):
        return "lunch"
    if t < dtime(13, 0):
        return "trend_afternoon"
    return "close_drive"


# ── primary builder ───────────────────────────────────────────────────────────

# (symbol, last_ltf_bar_ts) → AnalysisContext + expiry epoch
_CONTEXT_CACHE: dict[tuple[str, int], tuple[AnalysisContext, float]] = {}


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    return df.resample(rule).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna(subset=["open"])


async def _build_context(symbol: str) -> AnalysisContext:
    """One-shot fetch + compute. Always returns a context (frames may be empty)."""
    daily_task = asyncio.create_task(shioaji_fetch_daily(symbol, lookback=_HTF_LOOKBACK_DAYS))
    m1_long_task = asyncio.create_task(shioaji_fetch_m1(symbol, days=_MTF_DAYS_M1_SOURCE))

    daily_df, m1_long_df = await asyncio.gather(daily_task, m1_long_task)

    # MTF (60m) is derived from m1 source.
    mtf_60m = _resample(m1_long_df, "60min") if m1_long_df is not None and not m1_long_df.empty else m1_long_df
    # LTF uses the most-recent 5 days of m1 (avoids re-fetching by slicing).
    if m1_long_df is not None and not m1_long_df.empty:
        cutoff = m1_long_df.index.max() - pd.Timedelta(days=_LTF_DAYS_M1 + 1)
        ltf_df = m1_long_df.loc[m1_long_df.index >= cutoff]
    else:
        ltf_df = m1_long_df

    # Run structure on each frame at its natural swing-n.
    htf_struct = detect_market_structure(daily_df, n=5) if daily_df is not None and not daily_df.empty else {"structure": "ranging", "swing_points": {"swing_highs": [], "swing_lows": []}, "last_bos": None, "last_choch": None}
    mtf_struct = detect_market_structure(mtf_60m, n=5) if mtf_60m is not None and not mtf_60m.empty else {"structure": "ranging", "swing_points": {"swing_highs": [], "swing_lows": []}, "last_bos": None, "last_choch": None}
    ltf_struct = detect_market_structure(ltf_df, n=10) if ltf_df is not None and not ltf_df.empty else {"structure": "ranging", "swing_points": {"swing_highs": [], "swing_lows": []}, "last_bos": None, "last_choch": None}

    htf = Frame("1D", daily_df, 5, htf_struct,
                atr=_atr(daily_df, 14))
    mtf = Frame("60m", mtf_60m, 5, mtf_struct,
                atr=_atr(mtf_60m, 14))
    ltf = Frame("1m", ltf_df, 10, ltf_struct,
                atr=_atr(ltf_df, 14))

    # LTF-derived enriched features.
    sp_ltf = ltf_struct.get("swing_points", {})
    eq = mark_equal_pivots(sp_ltf, ltf_df) if not ltf.empty else {"equal_highs": [], "equal_lows": [], "atr": 0.0}
    sw = classify_strong_weak(ltf_struct)
    obs = find_order_blocks(ltf_df, lookback=30, max_count=5) if not ltf.empty else []
    fvgs = [f for f in find_fair_value_gaps(ltf_df) if f["valid"]] if not ltf.empty else []
    tl = compute_trendlines(ltf_df, length=14) if not ltf.empty and len(ltf_df) > 30 else None
    pd_zones = compute_premium_discount(sp_ltf, ltf_df) if not ltf.empty else None
    mtf_levels = compute_mtf_levels(daily_df)
    liquidity = _build_liquidity_map(ltf, mtf_levels=mtf_levels, equal_pivots=eq)

    now_tw = datetime.now(_TZ_TW)
    return AnalysisContext(
        symbol=symbol,
        now_tw=now_tw,
        session_phase=_session_phase(now_tw),
        htf=htf, mtf=mtf, ltf=ltf,
        liquidity=liquidity,
        pd_zones=pd_zones,
        mtf_levels=mtf_levels,
        equal_pivots=eq,
        strong_weak=sw,
        active_obs=obs,
        active_fvgs=fvgs,
        trendlines=tl,
        atr_ltf=ltf.atr,
    )


def _atr(df: pd.DataFrame, length: int) -> float:
    """ATR value over the most-recent `length` bars; returns 0 on short series."""
    if df is None or df.empty or len(df) < 2:
        return 0.0
    series = _atr_series(df, length=length)
    if series is None or len(series) == 0:
        return 0.0
    return float(series[-1])


async def gather_context(symbol: str, *, force_refresh: bool = False) -> AnalysisContext:
    """Public entry-point. Caches the result for `_CACHE_TTL_SECONDS`."""
    now = time.time()
    # Trim expired entries opportunistically.
    if len(_CONTEXT_CACHE) > _MAX_CACHE:
        for key in list(_CONTEXT_CACHE.keys()):
            if _CONTEXT_CACHE[key][1] < now:
                del _CONTEXT_CACHE[key]

    if not force_refresh:
        for (sym, _ts), (ctx, expires) in _CONTEXT_CACHE.items():
            if sym == symbol and expires > now:
                return ctx

    ctx = await _build_context(symbol)
    key = (symbol, ctx.ltf.last_bar_ts)
    _CONTEXT_CACHE[key] = (ctx, now + _CACHE_TTL_SECONDS)
    return ctx
