"""SMC (Smart Money Concept) detection — pure functions, zero IO.

Public API:
    find_swing_points(df, n=5)              -> dict[str, list[dict]]
    detect_market_structure(df, n=5)        -> dict
    find_demand_zones(df, swing_points)     -> list[dict]
    find_supply_zones(df, swing_points)     -> list[dict]
    detect_signals(df, symbol, timeframe)   -> list[SMCSignal]

All functions accept a pandas DataFrame with columns
    ["open", "high", "low", "close", "volume"]
indexed by datetime. They never read disk, network, env or globals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal, Optional

import numpy as np
import pandas as pd


# ── tunables ──────────────────────────────────────────────────────────────────

DISPLACEMENT_RETURN: Final[float] = 0.005   # 0.5% close-to-close move qualifies as displacement
ZONE_PADDING: Final[float] = 0.0            # currently no padding; raise if zones too tight
MIN_BARS: Final[int] = 20                   # caller should skip series shorter than this

# EQH/EQL detection (LuxAlgo: equalHighsLowsThresholdInput=0.1, atr=ATR(200))
EQUAL_THRESHOLD: Final[float] = 0.1         # tighter = stricter equality
EQUAL_ATR_LENGTH: Final[int] = 200

# Swing layers (LuxAlgo: internalLength=5, swingLength=50)
INTERNAL_SWING_N: Final[int] = 5
SWING_N: Final[int] = 10                    # 50 in LuxAlgo, smaller here since we work with shorter series

SignalType = Literal[
    "BOS_UP", "BOS_DOWN", "CHoCH_UP", "CHoCH_DOWN"
]
Structure = Literal["bullish", "bearish", "ranging"]


@dataclass(frozen=True)
class SMCSignal:
    """A single SMC signal at a point in time. Immutable."""

    symbol: str
    timeframe: str                # "1D" | "3m" | "1m"
    signal_type: SignalType
    price: float
    market_structure: Structure
    timestamp: datetime
    strength: int = 1             # 1..3 (3 = multi-timeframe confluence)
    demand_zone: Optional[dict[str, Any]] = None
    supply_zone: Optional[dict[str, Any]] = None
    meta: dict[str, Any] = field(default_factory=dict)


# ── swing points ──────────────────────────────────────────────────────────────

def find_swing_points(df: pd.DataFrame, n: int = 5) -> dict[str, list[dict]]:
    """Locate fractal swing highs / lows.

    A bar at index t is a Swing High when high[t] is strictly greater than the
    highs of the surrounding `n` bars on each side. Swing Lows are the mirror.

    Returns
    -------
    {
        "swing_highs": [ {index, price, bar_idx}, ... ],   # sorted by bar_idx ascending
        "swing_lows":  [ {index, price, bar_idx}, ... ],
    }
    """
    out: dict[str, list[dict]] = {"swing_highs": [], "swing_lows": []}
    if df is None or len(df) < (2 * n + 1):
        return out

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    idx = df.index

    # PineScript ta.pivothigh / ta.pivotlow convention:
    #   left side allowed equal, right side strictly less (or greater for lows).
    # This handles plateaus correctly — the LAST bar of an equal-high plateau
    # becomes the swing high — and works on tick-quantised data where many
    # bars share the same high or low.
    last = len(df) - n
    for t in range(n, last):
        left_h = high[t - n : t]
        right_h = high[t + 1 : t + n + 1]
        if high[t] >= left_h.max() and high[t] > right_h.max():
            out["swing_highs"].append({
                "index": idx[t],
                "price": float(high[t]),
                "bar_idx": t,
            })
        left_l = low[t - n : t]
        right_l = low[t + 1 : t + n + 1]
        if low[t] <= left_l.min() and low[t] < right_l.min():
            out["swing_lows"].append({
                "index": idx[t],
                "price": float(low[t]),
                "bar_idx": t,
            })

    return out


# ── market structure ──────────────────────────────────────────────────────────

def detect_market_structure(df: pd.DataFrame, n: int = 5) -> dict:
    """Classify trend, plus the most recent BOS and CHoCH events.

    Trend rules (using the last two swings of each kind):
      * bullish  : last swing high > prior swing high  AND  last swing low > prior swing low
      * bearish  : last swing high < prior swing high  AND  last swing low < prior swing low
      * ranging  : neither

    BOS  : close breaks the most recent swing in the prevailing trend direction.
    CHoCH: close breaks the most recent swing against the prevailing trend.

    Returns
    -------
    {
        "structure":   "bullish" | "bearish" | "ranging",
        "last_bos":    {type, price, index} | None,
        "last_choch":  {type, price, index} | None,
        "swing_points": {...},   # passthrough from find_swing_points
    }
    """
    sp = find_swing_points(df, n=n)
    highs = sp["swing_highs"]
    lows = sp["swing_lows"]

    structure: Structure = "ranging"
    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1]["price"] > highs[-2]["price"]
        hl = lows[-1]["price"] > lows[-2]["price"]
        lh = highs[-1]["price"] < highs[-2]["price"]
        ll = lows[-1]["price"] < lows[-2]["price"]
        if hh and hl:
            structure = "bullish"
        elif lh and ll:
            structure = "bearish"

    last_bos: Optional[dict] = None
    last_choch: Optional[dict] = None

    if df is not None and not df.empty:
        closes = df["close"].to_numpy(dtype=float)
        idx = df.index
        n_bars = len(df)

        # most recent swing pivots
        last_sh = highs[-1] if highs else None
        last_sl = lows[-1] if lows else None

        if last_sh is not None:
            # search bars after the swing-high formation for a close > swing-high price
            start = last_sh["bar_idx"] + 1
            for t in range(start, n_bars):
                if closes[t] > last_sh["price"]:
                    event = {
                        "type": "BOS_UP" if structure == "bullish" else "CHoCH_UP",
                        "price": float(closes[t]),
                        "index": idx[t],
                    }
                    if event["type"] == "BOS_UP":
                        last_bos = event
                    else:
                        last_choch = event
                    break

        if last_sl is not None:
            start = last_sl["bar_idx"] + 1
            for t in range(start, n_bars):
                if closes[t] < last_sl["price"]:
                    event = {
                        "type": "BOS_DOWN" if structure == "bearish" else "CHoCH_DOWN",
                        "price": float(closes[t]),
                        "index": idx[t],
                    }
                    if event["type"] == "BOS_DOWN":
                        # only overwrite if more recent than existing bos
                        if last_bos is None or event["index"] >= last_bos["index"]:
                            last_bos = event
                    else:
                        if last_choch is None or event["index"] >= last_choch["index"]:
                            last_choch = event
                    break

    return {
        "structure": structure,
        "last_bos": last_bos,
        "last_choch": last_choch,
        "swing_points": sp,
    }


# ── demand / supply zones ─────────────────────────────────────────────────────

def find_demand_zones(df: pd.DataFrame, swing_points: dict) -> list[dict]:
    """Find Demand Zones rooted at swing-low formations.

    For each swing low, look backward up to 6 bars for the last "strong bullish"
    candle (close-over-prev-close return >= 0.5%). That candle's [low, high]
    becomes the zone. The zone is `valid` while no subsequent bar's close
    pierces below `bottom`.
    """
    if df is None or len(df) < 3 or not swing_points.get("swing_lows"):
        return []

    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    idx = df.index

    zones: list[dict] = []
    for sl in swing_points["swing_lows"]:
        t = sl["bar_idx"]
        anchor: Optional[int] = None
        for k in range(max(t - 6, 1), t + 1):
            if close[k - 1] <= 0:
                continue
            ret = close[k] / close[k - 1] - 1.0
            if ret >= DISPLACEMENT_RETURN:
                anchor = k
        if anchor is None:
            continue

        bottom = float(low[anchor])
        top = float(high[anchor])
        valid = True
        for j in range(anchor + 1, len(df)):
            if close[j] < bottom:
                valid = False
                break
        zones.append({
            "type": "demand",
            "top": top,
            "bottom": bottom,
            "formed_at": idx[anchor],
            "bar_idx": anchor,
            "valid": valid,
        })

    return zones


def find_supply_zones(df: pd.DataFrame, swing_points: dict) -> list[dict]:
    """Find Supply Zones rooted at swing-high formations (mirror of demand)."""
    if df is None or len(df) < 3 or not swing_points.get("swing_highs"):
        return []

    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    idx = df.index

    zones: list[dict] = []
    for sh in swing_points["swing_highs"]:
        t = sh["bar_idx"]
        anchor: Optional[int] = None
        for k in range(max(t - 6, 1), t + 1):
            if close[k - 1] <= 0:
                continue
            ret = close[k] / close[k - 1] - 1.0
            if ret <= -DISPLACEMENT_RETURN:
                anchor = k
        if anchor is None:
            continue

        bottom = float(low[anchor])
        top = float(high[anchor])
        valid = True
        for j in range(anchor + 1, len(df)):
            if close[j] > top:
                valid = False
                break
        zones.append({
            "type": "supply",
            "top": top,
            "bottom": bottom,
            "formed_at": idx[anchor],
            "bar_idx": anchor,
            "valid": valid,
        })

    return zones


# ── signal aggregation ────────────────────────────────────────────────────────

def _latest_valid_zone(zones: list[dict]) -> Optional[dict]:
    """Pick the most recently formed still-valid zone, or None."""
    valids = [z for z in zones if z.get("valid")]
    if not valids:
        return None
    return max(valids, key=lambda z: z["bar_idx"])


def detect_signals(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    n: int = 5,
) -> list[SMCSignal]:
    """Combine structure + zones into a list of actionable SMC signals.

    Emits one SMCSignal for each detected BOS / CHoCH event regardless of
    whether the breaking bar is the last bar of the frame — what matters is
    that the event currently exists in the structure. Repeated emission is
    handled at the scanner layer via a per-(symbol, signal_type) cooldown.
    Strength defaults to 1; multi-timeframe confluence is applied by the
    caller (see smc_scanner.py).
    """
    if df is None or len(df) < MIN_BARS:
        return []

    ms = detect_market_structure(df, n=n)
    sp = ms["swing_points"]
    demand = find_demand_zones(df, sp)
    supply = find_supply_zones(df, sp)

    last_close = float(df["close"].iloc[-1])

    out: list[SMCSignal] = []
    for evt_key in ("last_bos", "last_choch"):
        evt = ms[evt_key]
        if evt is None:
            continue
        evt_ts = evt["index"]
        timestamp = (
            evt_ts.to_pydatetime()
            if hasattr(evt_ts, "to_pydatetime")
            else (evt_ts if isinstance(evt_ts, datetime) else datetime.now())
        )
        out.append(SMCSignal(
            symbol=symbol,
            timeframe=timeframe,
            signal_type=evt["type"],   # type: ignore[arg-type]
            price=float(evt["price"]),
            market_structure=ms["structure"],
            timestamp=timestamp,
            strength=1,
            demand_zone=_latest_valid_zone(demand),
            supply_zone=_latest_valid_zone(supply),
            meta={"last_close": last_close, "event_at": str(evt_ts)},
        ))

    return out


# ── Fair Value Gaps ───────────────────────────────────────────────────────────

def _atr(df: pd.DataFrame, length: int = 14) -> float:
    """Wilder ATR over the trailing `length` bars. Returns 0 on short series."""
    if df is None or len(df) < 2:
        return 0.0
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    tr = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - close[:-1]),
        np.abs(low[1:] - close[:-1]),
    ])
    span = min(length, len(tr))
    if span <= 0:
        return 0.0
    return float(tr[-span:].mean())


def find_fair_value_gaps(
    df: pd.DataFrame,
    *,
    auto_threshold: bool = True,
) -> list[dict]:
    """Detect 3-bar Fair Value Gaps (FVG) and tag mitigation.

    Bullish FVG : low[t]  > high[t-2]  AND  close[t-1] > high[t-2]  AND  body[t-1] > threshold
    Bearish FVG : high[t] < low[t-2]   AND  close[t-1] < low[t-2]   AND  body[t-1] < -threshold

    Mitigation rule (LuxAlgo):
        Bullish FVG cleared when a later bar's low penetrates the gap bottom.
        Bearish FVG cleared when a later bar's high penetrates the gap top.

    Returns list of {bias, top, bottom, formed_at, formed_bar, valid}.
    """
    if df is None or len(df) < 3:
        return []

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    idx = df.index
    n = len(df)

    body_pct = np.where(open_ > 0, (close - open_) / open_, 0.0)
    threshold = (np.abs(body_pct).mean() * 2.0) if auto_threshold else 0.0

    out: list[dict] = []
    for t in range(2, n):
        # Bullish FVG: gap between low[t] (above) and high[t-2] (below)
        if (
            low[t] > high[t - 2]
            and close[t - 1] > high[t - 2]
            and body_pct[t - 1] > threshold
        ):
            top, bottom = float(low[t]), float(high[t - 2])
            valid = True
            for j in range(t + 1, n):
                if low[j] < bottom:
                    valid = False
                    break
            out.append({
                "bias": "bullish",
                "top": top,
                "bottom": bottom,
                "formed_at": idx[t],
                "formed_bar": t,
                "valid": valid,
            })

        # Bearish FVG: gap between high[t] (below) and low[t-2] (above)
        if (
            high[t] < low[t - 2]
            and close[t - 1] < low[t - 2]
            and body_pct[t - 1] < -threshold
        ):
            top, bottom = float(low[t - 2]), float(high[t])
            valid = True
            for j in range(t + 1, n):
                if high[j] > top:
                    valid = False
                    break
            out.append({
                "bias": "bearish",
                "top": top,
                "bottom": bottom,
                "formed_at": idx[t],
                "formed_bar": t,
                "valid": valid,
            })

    return out


# ── Equal Highs / Equal Lows ──────────────────────────────────────────────────

def mark_equal_pivots(
    swing_points: dict,
    df: pd.DataFrame,
    *,
    threshold: float = EQUAL_THRESHOLD,
    atr_length: int = EQUAL_ATR_LENGTH,
) -> dict:
    """Annotate consecutive swing pairs whose level matches.

    LuxAlgo rule: |current.level - prior.level| < threshold × ATR.

    Returns
    -------
    {
        "equal_highs": [(prev_swing, curr_swing), ...],
        "equal_lows":  [(prev_swing, curr_swing), ...],
        "atr": float,
    }
    """
    if df is None or df.empty:
        return {"equal_highs": [], "equal_lows": [], "atr": 0.0}

    atr = _atr(df, length=atr_length)
    tolerance = threshold * atr if atr > 0 else 0.0
    out_high: list[tuple] = []
    out_low: list[tuple] = []

    if tolerance > 0:
        highs = swing_points.get("swing_highs") or []
        for prev, curr in zip(highs[:-1], highs[1:]):
            if abs(curr["price"] - prev["price"]) < tolerance:
                out_high.append((prev, curr))

        lows = swing_points.get("swing_lows") or []
        for prev, curr in zip(lows[:-1], lows[1:]):
            if abs(curr["price"] - prev["price"]) < tolerance:
                out_low.append((prev, curr))

    return {"equal_highs": out_high, "equal_lows": out_low, "atr": atr}


# ── Strong / Weak High & Low ──────────────────────────────────────────────────

def classify_strong_weak(structure_result: dict) -> dict:
    """Tag the *latest* swing high / swing low as Strong or Weak per LuxAlgo.

    LuxAlgo convention:
        swing trend = bearish ⇒ top "Strong High",   bottom "Weak Low"
        swing trend = bullish ⇒ top "Weak High",     bottom "Strong Low"
        ranging               ⇒ bias by most-recent CHoCH or BOS direction.

    Returns {strong_high, strong_low, weak_high, weak_low}; each is either a
    swing-point dict ({bar_idx, price, index}) or None.
    """
    structure: Structure = structure_result.get("structure", "ranging")  # type: ignore[assignment]
    sp = structure_result.get("swing_points") or {}
    highs = sp.get("swing_highs") or []
    lows = sp.get("swing_lows") or []
    last_high = highs[-1] if highs else None
    last_low = lows[-1] if lows else None

    out = {"strong_high": None, "strong_low": None,
           "weak_high": None,   "weak_low": None}

    if structure == "bearish":
        out["strong_high"] = last_high
        out["weak_low"] = last_low
    elif structure == "bullish":
        out["weak_high"] = last_high
        out["strong_low"] = last_low
    else:
        event = structure_result.get("last_choch") or structure_result.get("last_bos")
        if event and event["type"].endswith("_DOWN"):
            out["strong_high"] = last_high
            out["weak_low"] = last_low
        elif event and event["type"].endswith("_UP"):
            out["weak_high"] = last_high
            out["strong_low"] = last_low

    return out


# ── Dual structure (Internal + Swing) ─────────────────────────────────────────

def detect_dual_structure(
    df: pd.DataFrame,
    *,
    internal_n: int = INTERNAL_SWING_N,
    swing_n: int = SWING_N,
) -> dict:
    """Compute both internal and swing market structures in one call."""
    return {
        "internal": detect_market_structure(df, n=internal_n),
        "swing":    detect_market_structure(df, n=swing_n),
    }


# ── Order Blocks (bar-indexed; merges bull + bear; prunes to N most recent) ───

_OB_DISPLACEMENT: Final[float] = 0.005
_OB_BODY_POS: Final[float] = 0.70
_OB_BACK_SEARCH: Final[int] = 6


def find_order_blocks(
    df: pd.DataFrame,
    *,
    lookback: int = 20,
    max_count: int = 5,
) -> list[dict]:
    """Detect Bullish & Bearish Order Blocks with bar-index metadata.

    A *Bullish OB* is the most recent bearish candle before a strong bull
    displacement (close-vs-prev close > +0.5% and body in upper 30%). A
    *Bearish OB* is the mirror. An OB is `valid` while no later close within
    `lookback` bars has penetrated it.

    Returns the `max_count` most recently formed STILL-VALID order blocks,
    sorted oldest-first.
    """
    if df is None or len(df) < 3:
        return []

    open_ = df["open"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    idx = df.index
    n = len(df)

    out: list[dict] = []
    for t in range(1, n):
        if close[t - 1] <= 0:
            continue
        ret = close[t] / close[t - 1] - 1.0
        rng = high[t] - low[t]
        body_pos = ((close[t] - low[t]) / rng) if rng > 0 else 0.5

        # ── Bullish OB ──
        if ret > _OB_DISPLACEMENT and body_pos >= _OB_BODY_POS:
            ob_bar: Optional[int] = None
            for k in range(t - 1, max(-1, t - 1 - _OB_BACK_SEARCH), -1):
                if close[k] < open_[k]:
                    ob_bar = k
                    break
            if ob_bar is not None:
                ob_low = float(low[ob_bar])
                ob_high = float(high[ob_bar])
                valid = True
                end = min(n, t + 1 + lookback)
                for j in range(t + 1, end):
                    if close[j] < ob_low:
                        valid = False
                        break
                out.append({
                    "bias": "bullish",
                    "top": ob_high,
                    "bottom": ob_low,
                    "formed_bar": ob_bar,
                    "formed_at": idx[ob_bar],
                    "displacement_bar": t,
                    "valid": valid,
                })

        # ── Bearish OB ──
        if ret < -_OB_DISPLACEMENT and body_pos <= (1.0 - _OB_BODY_POS):
            ob_bar = None
            for k in range(t - 1, max(-1, t - 1 - _OB_BACK_SEARCH), -1):
                if close[k] > open_[k]:
                    ob_bar = k
                    break
            if ob_bar is not None:
                ob_low = float(low[ob_bar])
                ob_high = float(high[ob_bar])
                valid = True
                end = min(n, t + 1 + lookback)
                for j in range(t + 1, end):
                    if close[j] > ob_high:
                        valid = False
                        break
                out.append({
                    "bias": "bearish",
                    "top": ob_high,
                    "bottom": ob_low,
                    "formed_bar": ob_bar,
                    "formed_at": idx[ob_bar],
                    "displacement_bar": t,
                    "valid": valid,
                })

    # Dedupe: many displacement bars in sequence point back to the same bear/bull
    # bar. Keep one entry per (bias, formed_bar), preferring the earliest
    # displacement that revealed it.
    seen: set[tuple[str, int]] = set()
    deduped: list[dict] = []
    for o in out:
        key = (o["bias"], o["formed_bar"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(o)

    valid_obs = sorted([o for o in deduped if o["valid"]],
                       key=lambda o: o["displacement_bar"])
    return valid_obs[-max_count:]


# ── Breaker Blocks ────────────────────────────────────────────────────────────

def find_breakers(
    df: pd.DataFrame,
    *,
    lookback: int = 20,
    max_count: int = 3,
) -> list[dict]:
    """Detect Breaker Blocks (broken OB whose role flipped).

    A breaker requires:
        1. An OB was formed (bear bar before bull displacement, or vice versa).
        2. Price later closed THROUGH the OB extreme (the OB failed).
        3. After that break, price swept the swing high/low that the OB was
           defending (liquidity grab beyond the original structural extreme).
        4. Price then returned toward the broken OB, which now acts as
           resistance/support from the opposite side.

    Returns the `max_count` most recent breakers with bar-indexed metadata:
        {bias_orig, bias_new, top, bottom, formed_bar, broke_bar, sweep_bar}
    """
    if df is None or len(df) < 5:
        return []

    open_ = df["open"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(df)

    out: list[dict] = []

    for t in range(1, n):
        if close[t - 1] <= 0:
            continue
        ret = close[t] / close[t - 1] - 1.0
        rng = high[t] - low[t]
        body_pos = ((close[t] - low[t]) / rng) if rng > 0 else 0.5

        # Find bullish-OB candidate (bear bar before bull displacement)
        if ret > _OB_DISPLACEMENT and body_pos >= _OB_BODY_POS:
            for k in range(t - 1, max(-1, t - 1 - _OB_BACK_SEARCH), -1):
                if close[k] < open_[k]:
                    out.extend(_check_breaker(
                        df, n, ob_bar=k, ob_bias="bullish",
                        ob_top=float(high[k]), ob_bottom=float(low[k]),
                        formed_after=t, lookback=lookback,
                    ))
                    break

        if ret < -_OB_DISPLACEMENT and body_pos <= (1.0 - _OB_BODY_POS):
            for k in range(t - 1, max(-1, t - 1 - _OB_BACK_SEARCH), -1):
                if close[k] > open_[k]:
                    out.extend(_check_breaker(
                        df, n, ob_bar=k, ob_bias="bearish",
                        ob_top=float(high[k]), ob_bottom=float(low[k]),
                        formed_after=t, lookback=lookback,
                    ))
                    break

    # Dedupe by formed_bar — only keep the latest breaker per OB
    seen: set[int] = set()
    deduped: list[dict] = []
    for b in out:
        if b["formed_bar"] in seen:
            continue
        seen.add(b["formed_bar"])
        deduped.append(b)

    deduped.sort(key=lambda b: b["broke_bar"])
    return deduped[-max_count:]


def _check_breaker(
    df: pd.DataFrame,
    n: int,
    *,
    ob_bar: int,
    ob_bias: str,
    ob_top: float,
    ob_bottom: float,
    formed_after: int,
    lookback: int,
) -> list[dict]:
    """Helper: was this OB broken + liquidity-swept after the break?"""
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    idx = df.index

    # Look forward for the break event
    # bullish OB is broken when a later close goes BELOW ob_bottom (failed support)
    # bearish OB is broken when a later close goes ABOVE ob_top (failed resistance)
    broke_bar: Optional[int] = None
    for j in range(formed_after + 1, min(n, formed_after + 1 + lookback * 2)):
        if ob_bias == "bullish" and close[j] < ob_bottom:
            broke_bar = j
            break
        if ob_bias == "bearish" and close[j] > ob_top:
            broke_bar = j
            break
    if broke_bar is None:
        return []

    # After the break, look for a liquidity sweep of the original structural
    # extreme. For a bullish OB that broke down, the "structural extreme" is
    # the lowest low between ob_bar and broke_bar — we want a later bar to dip
    # below it (sweep the SSL).
    if ob_bias == "bullish":
        protected_level = float(low[ob_bar : broke_bar + 1].min())
        sweep_bar: Optional[int] = None
        for j in range(broke_bar + 1, n):
            if low[j] < protected_level and close[j] > protected_level:
                sweep_bar = j
                break
    else:
        protected_level = float(high[ob_bar : broke_bar + 1].max())
        sweep_bar = None
        for j in range(broke_bar + 1, n):
            if high[j] > protected_level and close[j] < protected_level:
                sweep_bar = j
                break

    if sweep_bar is None:
        return []

    # Confirm price has returned toward the broken OB (last bar within OB range)
    if not (ob_bottom <= close[n - 1] <= ob_top * 1.005 and close[n - 1] >= ob_bottom * 0.995):
        # not currently retesting; still record the breaker but mark untested
        pass

    return [{
        "bias_orig": ob_bias,
        "bias_new": "bearish" if ob_bias == "bullish" else "bullish",
        "top": ob_top,
        "bottom": ob_bottom,
        "formed_bar": ob_bar,
        "formed_at": idx[ob_bar],
        "broke_bar": broke_bar,
        "sweep_bar": sweep_bar,
        "protected_level": float(protected_level),
    }]


# ── Premium / Equilibrium / Discount zones ────────────────────────────────────

def compute_premium_discount(
    swing_points: dict,
    df: pd.DataFrame,
) -> Optional[dict]:
    """LuxAlgo trailing-range Premium / Equilibrium / Discount bands.

    Bands (per LuxAlgo source):
      Premium     = top 5%   of range
      Equilibrium = 5% band centred on the midpoint
      Discount    = bottom 5% of range

    Range = (max swing-high, min swing-low) over the visible swings; falls back
    to (df.high.max, df.low.min) when there are no swings.
    """
    if df is None or df.empty:
        return None

    highs = (swing_points or {}).get("swing_highs") or []
    lows = (swing_points or {}).get("swing_lows") or []

    top = max((h["price"] for h in highs), default=float(df["high"].max()))
    bottom = min((l["price"] for l in lows), default=float(df["low"].min()))
    if top <= bottom:
        return None

    return {
        "top": float(top),
        "bottom": float(bottom),
        "premium":     {"top": float(top),
                        "bottom": float(0.95 * top + 0.05 * bottom)},
        "equilibrium": {"top": float(0.525 * top + 0.475 * bottom),
                        "bottom": float(0.475 * top + 0.525 * bottom)},
        "discount":    {"top": float(0.05 * top + 0.95 * bottom),
                        "bottom": float(bottom)},
    }


# ── Trendlines with Breaks (LuxAlgo port) ─────────────────────────────────────

def _atr_series(df: pd.DataFrame, length: int = 14) -> np.ndarray:
    """Per-bar simple-mean ATR (matches PineScript ta.atr default)."""
    n = len(df)
    if n == 0:
        return np.zeros(0)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    if n > 1:
        prev_c = c[:-1]
        tr[1:] = np.maximum.reduce([
            h[1:] - l[1:],
            np.abs(h[1:] - prev_c),
            np.abs(l[1:] - prev_c),
        ])
    atr = np.zeros(n)
    for t in range(n):
        start = max(0, t - length + 1)
        atr[t] = tr[start : t + 1].mean()
    return atr


def _pine_pivots(arr: np.ndarray, length: int, *, kind: str = "high") -> list[Optional[float]]:
    """Pine-style ta.pivothigh/low.

    Bar `t` reports the price of a pivot formed at bar `t - length`, ONLY if
    that bar was a strict extremum in its ±length window.
    """
    n = len(arr)
    out: list[Optional[float]] = [None] * n
    if n < 2 * length + 1:
        return out
    for t in range(2 * length, n):
        center = t - length
        v = arr[center]
        is_pivot = True
        for k in range(center - length, center + length + 1):
            if k == center:
                continue
            if kind == "high":
                if arr[k] >= v:
                    is_pivot = False
                    break
            else:
                if arr[k] <= v:
                    is_pivot = False
                    break
        if is_pivot:
            out[t] = float(v)
    return out


def compute_trendlines(
    df: pd.DataFrame,
    *,
    length: int = 14,
    slope_mult: float = 1.0,
) -> Optional[dict]:
    """LuxAlgo Trendlines with Breaks (ATR slope method).

    Returns
    -------
    {
        "upper":         np.ndarray[float],   # down-sloping resistance per bar
        "lower":         np.ndarray[float],   # up-sloping support per bar
        "upper_breaks":  [ {bar_idx, index, price}, ...  ],  # close > upper - slope * length
        "lower_breaks":  [ ... ],
        "length":        int,
    }

    The plotted line at bar `t` is anchored to the pivot at bar `t - length`
    (Pine `backpaint=true` convention); use the bar index for chart placement.
    """
    if df is None or len(df) < length * 2 + 2:
        return None

    n = len(df)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    idx = df.index

    atr = _atr_series(df, length=length)
    slope_arr = atr / max(length, 1) * slope_mult

    ph = _pine_pivots(h, length, kind="high")
    pl = _pine_pivots(l, length, kind="low")

    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    slope_ph = 0.0
    slope_pl = 0.0
    upper_v = 0.0
    lower_v = 0.0
    upper_init = False
    lower_init = False
    upos = 0
    dnos = 0
    prev_upos = 0
    prev_dnos = 0
    upper_breaks: list[dict] = []
    lower_breaks: list[dict] = []

    for t in range(n):
        if ph[t] is not None:
            slope_ph = slope_arr[t]
            upper_v = ph[t]
            upper_init = True
        elif upper_init:
            upper_v = upper_v - slope_ph
        if pl[t] is not None:
            slope_pl = slope_arr[t]
            lower_v = pl[t]
            lower_init = True
        elif lower_init:
            lower_v = lower_v + slope_pl
        if upper_init:
            upper[t] = upper_v
        if lower_init:
            lower[t] = lower_v

        if ph[t] is not None:
            upos = 0
        elif upper_init and c[t] > upper_v - slope_ph * length:
            upos = 1
        if pl[t] is not None:
            dnos = 0
        elif lower_init and c[t] < lower_v + slope_pl * length:
            dnos = 1

        if upos > prev_upos:
            upper_breaks.append({
                "bar_idx": t, "index": idx[t], "price": float(l[t]),
            })
        if dnos > prev_dnos:
            lower_breaks.append({
                "bar_idx": t, "index": idx[t], "price": float(h[t]),
            })
        prev_upos = upos
        prev_dnos = dnos

    return {
        "upper": upper,
        "lower": lower,
        "upper_breaks": upper_breaks,
        "lower_breaks": lower_breaks,
        "length": length,
    }


# ── Multi-timeframe key levels (PDH/PDL/PWH/PWL) ──────────────────────────────

def compute_mtf_levels(daily_df: pd.DataFrame) -> dict:
    """Previous-day and previous-week High / Low from a daily frame.

    Returns {pdh, pdl, pwh, pwl, pdh_date, pwh_period} — values are None when
    insufficient history is available.
    """
    out: dict[str, Any] = {
        "pdh": None, "pdl": None, "pwh": None, "pwl": None,
        "pdh_date": None, "pwh_period": None,
    }
    if daily_df is None or daily_df.empty:
        return out

    if len(daily_df) >= 2:
        out["pdh"] = float(daily_df["high"].iloc[-2])
        out["pdl"] = float(daily_df["low"].iloc[-2])
        try:
            out["pdh_date"] = daily_df.index[-2].date().isoformat()
        except Exception:
            out["pdh_date"] = None

    try:
        weeks = daily_df.index.to_period("W")
    except Exception:
        return out
    unique_weeks = sorted(set(weeks))
    if len(unique_weeks) >= 2:
        prev = unique_weeks[-2]
        mask = weeks == prev
        prev_week = daily_df[mask]
        if not prev_week.empty:
            out["pwh"] = float(prev_week["high"].max())
            out["pwl"] = float(prev_week["low"].min())
            out["pwh_period"] = str(prev)
    return out
