"""
OBV × 籌碼集中度背離偵測（PoC indicator layer）.

Pipeline (per evaluation day t):
    raw OBV/CONC    →  EMA smooth      →  N-day linear slope
                                       →  z-score vs trailing history
                                       →  divergence level
                                       →  K-day persistence confirm

Background:
  - OBV 衡量量能淨流向（量增於上漲日累積、下跌日扣除）。
  - 集中度衡量主力買盤是否集中（HiStock focus5 = 5 日 rolling 主力買賣超 / 量）。
  - 兩者方向相反 = 量能流入但籌碼分散 = 主力疑似出貨警示（純警示、不下單）。

Calibration thresholds and windows are exposed as module-level constants so
they can be re-tuned from historical backtests without touching pure logic.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Final

import numpy as np
import pandas as pd
from scipy.stats import linregress


# ── Tunable parameters (PoC defaults) ──────────────────────────────────────
EMA_SPAN: Final[int] = 5          # smoothing window
SLOPE_N: Final[int] = 5           # bars used for linregress slope
Z_HISTORY_MIN: Final[int] = 60    # min trailing bars to use z-score
Z_HISTORY_MAX: Final[int] = 120   # max trailing window for stable baseline

# Divergence thresholds (z-score units). Calibrated from PoC backtest.
THRESHOLD_WEAK: Final[float] = 0.0
THRESHOLD_MEDIUM: Final[float] = 0.5
THRESHOLD_STRONG: Final[float] = 1.0

PERSIST_K: Final[int] = 2          # consecutive days >= medium to confirm
ZONE_LOOKBACK: Final[int] = 20    # bars for swing high/low (Premium/Discount split)


class DivergenceLevel(str, Enum):
    """Bearish divergence grading: OBV up while concentration down."""
    NONE = "none"
    WEAK = "weak"
    MEDIUM = "medium"
    STRONG = "strong"


class PriceZone(str, Enum):
    """Where last close sits within the recent swing range.

    Bearish divergence is most relevant in Premium Zone (price near recent
    high) — distribution by 主力 is meaningful only when price is rich.
    A Discount-Zone divergence is treated as noise, not a warning.
    """
    PREMIUM = "premium"
    DISCOUNT = "discount"
    UNKNOWN = "unknown"   # too few bars to determine


@dataclass(frozen=True)
class DivergencePoint:
    """Per-day divergence evaluation result."""
    date: pd.Timestamp
    obv_slope: float
    conc_slope: float
    obv_slope_z: float        # NaN when insufficient history
    conc_slope_z: float       # NaN when insufficient history
    used_zscore: bool         # False = fell back to percentile (no z-score)
    level: DivergenceLevel
    price_zone: PriceZone
    confirmed: bool           # PERSIST_K days >= MEDIUM AND price_zone == PREMIUM


# ── Pure functions ─────────────────────────────────────────────────────────


def compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Standard cumulative On-Balance Volume."""
    if len(close) != len(volume):
        raise ValueError("close and volume must have equal length")
    delta = close.diff().fillna(0)
    sign = np.sign(delta)
    return (sign * volume).cumsum()


def _ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=span, adjust=False).mean()


def _rolling_slopes(series: pd.Series, n: int) -> pd.Series:
    """Per-index linear regression slope over the trailing `n` points.

    Returns NaN for indices where fewer than n preceding points exist.
    """
    out = np.full(len(series), np.nan)
    x = np.arange(n, dtype=float)
    values = series.to_numpy(dtype=float)
    for i in range(n - 1, len(values)):
        window = values[i - n + 1 : i + 1]
        if np.isnan(window).any():
            continue
        result = linregress(x, window)
        out[i] = float(result.slope)
    return pd.Series(out, index=series.index, name=f"{series.name}_slope")


def _zscore_or_percentile(
    slope_series: pd.Series, history_min: int, history_max: int
) -> tuple[pd.Series, pd.Series]:
    """Normalise slope per index using trailing history.

    Returns (normalised_values, used_zscore_flags).
      - Uses z-score when >= history_min trailing non-NaN points are available.
      - Falls back to percentile rank (centred at 0, scaled to roughly [-2, 2])
        when history is shorter — avoids fake precision from tiny samples.
    """
    arr = slope_series.to_numpy(dtype=float)
    norm = np.full(len(arr), np.nan)
    used_z = np.zeros(len(arr), dtype=bool)

    for i in range(len(arr)):
        start = max(0, i - history_max)
        window = arr[start:i]
        window = window[~np.isnan(window)]
        if window.size < history_min:
            # Percentile fallback: rank in [0, 1] → re-centred to [-2, 2]
            if window.size < 10 or np.isnan(arr[i]):
                continue
            rank = float((window < arr[i]).sum()) / window.size
            norm[i] = (rank - 0.5) * 4.0
            used_z[i] = False
        else:
            mean = float(window.mean())
            std = float(window.std(ddof=1))
            if std == 0.0 or np.isnan(arr[i]):
                continue
            norm[i] = (arr[i] - mean) / std
            used_z[i] = True

    return (
        pd.Series(norm, index=slope_series.index, name=f"{slope_series.name}_z"),
        pd.Series(used_z, index=slope_series.index, name="used_zscore"),
    )


def _classify(obv_z: float, conc_z: float) -> DivergenceLevel:
    """Map (OBV z, CONC z) to a bearish-divergence level.

    Bearish divergence pattern: OBV slope rising while CONC slope falling.
    """
    if np.isnan(obv_z) or np.isnan(conc_z):
        return DivergenceLevel.NONE
    if obv_z > THRESHOLD_STRONG and conc_z < -THRESHOLD_STRONG:
        return DivergenceLevel.STRONG
    if obv_z > THRESHOLD_MEDIUM and conc_z < -THRESHOLD_MEDIUM:
        return DivergenceLevel.MEDIUM
    if obv_z > THRESHOLD_WEAK and conc_z < -THRESHOLD_WEAK:
        return DivergenceLevel.WEAK
    return DivergenceLevel.NONE


def _confirm_persistence(levels: list[DivergenceLevel], k: int) -> list[bool]:
    """Mark indices where the last k entries are all >= MEDIUM."""
    medium_or_strong = {DivergenceLevel.MEDIUM, DivergenceLevel.STRONG}
    out = [False] * len(levels)
    for i in range(k - 1, len(levels)):
        window = levels[i - k + 1 : i + 1]
        out[i] = all(level in medium_or_strong for level in window)
    return out


def _compute_price_zones(close: pd.Series, lookback: int) -> list[PriceZone]:
    """Classify each bar by where its close sits within the trailing swing.

    Simplified swing range = rolling max/min of close over `lookback` bars.
    Below `lookback` bars of history → UNKNOWN (cannot decide).
    """
    out: list[PriceZone] = []
    values = close.to_numpy(dtype=float)
    for i in range(len(values)):
        if i < lookback - 1:
            out.append(PriceZone.UNKNOWN)
            continue
        window = values[i - lookback + 1 : i + 1]
        hi = float(np.nanmax(window))
        lo = float(np.nanmin(window))
        if hi == lo:
            out.append(PriceZone.UNKNOWN)
            continue
        midpoint = (hi + lo) / 2.0
        out.append(PriceZone.PREMIUM if values[i] >= midpoint else PriceZone.DISCOUNT)
    return out


def evaluate(
    chartdata: pd.DataFrame,
    *,
    ema_span: int = EMA_SPAN,
    slope_n: int = SLOPE_N,
    persist_k: int = PERSIST_K,
) -> list[DivergencePoint]:
    """Run the full pipeline over a chronologically sorted chartdata frame.

    `chartdata` must contain columns: date, close, volume, conc_5d.
    Returns one DivergencePoint per input row.
    """
    required = {"date", "close", "volume", "conc_5d"}
    missing = required - set(chartdata.columns)
    if missing:
        raise ValueError(f"chartdata missing columns: {missing}")
    if chartdata["date"].is_monotonic_increasing is False:
        chartdata = chartdata.sort_values("date").reset_index(drop=True)

    obv = compute_obv(chartdata["close"], chartdata["volume"])
    obv.name = "obv"
    conc = chartdata["conc_5d"].copy()
    conc.name = "conc"

    obv_smooth = _ema(obv, ema_span)
    conc_smooth = _ema(conc.ffill(), ema_span)

    obv_slope = _rolling_slopes(obv_smooth, slope_n)
    conc_slope = _rolling_slopes(conc_smooth, slope_n)

    obv_z, used_z_obv = _zscore_or_percentile(obv_slope, Z_HISTORY_MIN, Z_HISTORY_MAX)
    conc_z, _ = _zscore_or_percentile(conc_slope, Z_HISTORY_MIN, Z_HISTORY_MAX)

    levels = [_classify(float(z1), float(z2)) for z1, z2 in zip(obv_z, conc_z)]
    persist_flags = _confirm_persistence(levels, persist_k)
    zones = _compute_price_zones(chartdata["close"], ZONE_LOOKBACK)

    # Final confirmation gate: persistence AND price is in Premium Zone.
    confirmed = [
        persist_flags[i] and zones[i] == PriceZone.PREMIUM
        for i in range(len(levels))
    ]

    return [
        DivergencePoint(
            date=row.date,
            obv_slope=float(obv_slope.iloc[i]) if not np.isnan(obv_slope.iloc[i]) else float("nan"),
            conc_slope=float(conc_slope.iloc[i]) if not np.isnan(conc_slope.iloc[i]) else float("nan"),
            obv_slope_z=float(obv_z.iloc[i]) if not np.isnan(obv_z.iloc[i]) else float("nan"),
            conc_slope_z=float(conc_z.iloc[i]) if not np.isnan(conc_z.iloc[i]) else float("nan"),
            used_zscore=bool(used_z_obv.iloc[i]),
            level=levels[i],
            price_zone=zones[i],
            confirmed=confirmed[i],
        )
        for i, row in enumerate(chartdata.itertuples())
    ]


def summarise(points: list[DivergencePoint]) -> dict[str, int]:
    """Aggregate divergence counts by level (for PoC reporting)."""
    counts = {lvl.value: 0 for lvl in DivergenceLevel}
    confirmed = 0
    for p in points:
        counts[p.level.value] += 1
        if p.confirmed:
            confirmed += 1
    return {**counts, "confirmed": confirmed, "total": len(points)}
