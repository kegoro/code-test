"""Helpers used inside Setup.evaluate() to assemble the score breakdown
and pick the right target / stop levels from the context.

These are stateless utility functions, not classes.
"""
from __future__ import annotations

from typing import Literal, Optional

from backend.smc_analyst.context import AnalysisContext, Frame
from backend.smc_analyst.setups.base import (
    TIER_1_PTS, TIER_2_PTS, TIER_3_PTS,
)


def find_overlapping_fvg(
    ctx: AnalysisContext, *,
    near_bar: int, max_bar_distance: int = 5,
    bias: Optional[Literal["bullish", "bearish"]] = None,
) -> Optional[dict]:
    """Return the FVG whose formation bar is within `max_bar_distance` of
    `near_bar` (and matches `bias` if given). None if no match."""
    candidates = []
    for f in ctx.active_fvgs:
        if bias and f["bias"] != bias:
            continue
        if abs(f["formed_bar"] - near_bar) <= max_bar_distance:
            candidates.append(f)
    if not candidates:
        return None
    # Pick the one closest in bar-distance, ties broken by recency.
    candidates.sort(key=lambda f: (abs(f["formed_bar"] - near_bar), -f["formed_bar"]))
    return candidates[0]


def find_overlapping_ob(
    ctx: AnalysisContext, *,
    near_price: float, tolerance_atr_mult: float = 0.5,
    bias: Optional[Literal["bullish", "bearish"]] = None,
) -> Optional[dict]:
    """Return the OB whose [bottom, top] is within `tolerance` of `near_price`."""
    if not ctx.active_obs:
        return None
    tol = ctx.atr_ltf * tolerance_atr_mult
    candidates = []
    for ob in ctx.active_obs:
        if bias and ob["bias"] != bias:
            continue
        # Either price sits inside the OB, or within `tol` of either edge.
        if (ob["bottom"] - tol) <= near_price <= (ob["top"] + tol):
            candidates.append(ob)
    if not candidates:
        return None
    # Prefer the most recent OB.
    candidates.sort(key=lambda o: o["formed_bar"], reverse=True)
    return candidates[0]


def nearest_mtf_level(
    ctx: AnalysisContext, *,
    price: float, side: Literal["above", "below"],
) -> Optional[tuple[str, float]]:
    """Return the closest PDH/PDL/PWH/PWL above (or below) `price`."""
    if not ctx.mtf_levels:
        return None
    best: Optional[tuple[str, float]] = None
    best_dist = float("inf")
    for key in ("pdh", "pdl", "pwh", "pwl"):
        v = ctx.mtf_levels.get(key)
        if v is None:
            continue
        if side == "above" and v <= price:
            continue
        if side == "below" and v >= price:
            continue
        d = abs(v - price)
        if d < best_dist:
            best = (key.upper(), float(v))
            best_dist = d
    return best


def nearest_swing(
    ctx: AnalysisContext, *,
    price: float, side: Literal["above", "below"], kind: Literal["high", "low"],
) -> Optional[float]:
    """Closest LTF swing high above (or swing low below) `price`."""
    sp = ctx.ltf.structure.get("swing_points", {})
    key = "swing_highs" if kind == "high" else "swing_lows"
    pivots = sp.get(key) or []
    best: Optional[float] = None
    best_dist = float("inf")
    for p in pivots:
        v = float(p["price"])
        if side == "above" and v <= price:
            continue
        if side == "below" and v >= price:
            continue
        d = abs(v - price)
        if d < best_dist:
            best = v
            best_dist = d
    return best


def best_target(
    ctx: AnalysisContext, *,
    entry: float, direction: Literal["long", "short"],
) -> Optional[tuple[str, float]]:
    """Pick a structurally reasonable take-profit:
       prefer the nearest MTF level (PDH/PDL/PWH/PWL),
       falling back to the nearest LTF swing on the trade side.
    """
    if direction == "long":
        mtf = nearest_mtf_level(ctx, price=entry, side="above")
        if mtf:
            return mtf
        sw = nearest_swing(ctx, price=entry, side="above", kind="high")
        if sw is not None:
            return ("swing_high", sw)
    else:
        mtf = nearest_mtf_level(ctx, price=entry, side="below")
        if mtf:
            return mtf
        sw = nearest_swing(ctx, price=entry, side="below", kind="low")
        if sw is not None:
            return ("swing_low", sw)
    return None


def session_bonus(ctx: AnalysisContext) -> int:
    """+1 Tier-3 when we are in a trend-friendly session phase."""
    if ctx.session_phase in ("trend_morning", "trend_afternoon"):
        return TIER_3_PTS
    return 0


def htf_alignment_bonus(
    ctx: AnalysisContext, direction: Literal["long", "short"],
) -> list[tuple[str, int]]:
    """+1 Tier-3 ONLY when HTF is clearly trending in the trade direction.

    Ranging HTF is not penalised (see AnalysisContext.htf_aligned) but it
    also doesn't EARN a bonus here — bonus requires an active trend.
    """
    if direction == "long" and ctx.htf_bias == "bullish":
        return [("HTF (daily) bullish — trend support", TIER_3_PTS)]
    if direction == "short" and ctx.htf_bias == "bearish":
        return [("HTF (daily) bearish — trend support", TIER_3_PTS)]
    return []


def ob_recency_bonus(ob: dict, current_bar: int) -> list[tuple[str, int]]:
    """Recency-tiered bonus for how fresh the OB is."""
    age = current_bar - int(ob["formed_bar"])
    if age <= 30:
        return [(f"OB formed {age} bars ago — fresh", TIER_2_PTS)]
    if age <= 90:
        return [(f"OB formed {age} bars ago — recent", TIER_3_PTS)]
    return []


def proximity_bonus(
    ob: dict, last_close: float, atr: float,
) -> list[tuple[str, int]]:
    """Tighter proximity to the OB edge ⇒ stronger retest signal."""
    if atr <= 0:
        return []
    edge = ob["top"] if ob["bias"] == "bullish" else ob["bottom"]
    dist_atr = abs(last_close - edge) / atr
    if dist_atr <= 0.5:
        return [(f"Price within 0.5×ATR of OB edge ({dist_atr:.2f}×)", TIER_2_PTS)]
    if dist_atr <= 1.0:
        return [(f"Price within 1×ATR of OB edge ({dist_atr:.2f}×)", TIER_3_PTS)]
    return []


def rejection_bonus(
    ctx: AnalysisContext, ob: dict, *, lookback: int = 5,
) -> list[tuple[str, int]]:
    """+2 Tier-2 when a recent bar wicked into the OB then closed back outside."""
    df = ctx.ltf.bars
    if df is None or df.empty:
        return []
    n = len(df)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    bullish = ob["bias"] == "bullish"
    for t in range(max(0, n - lookback), n):
        if bullish:
            if l[t] <= ob["top"] and c[t] > ob["top"]:
                return [("Rejection candle at OB within last 5 bars", TIER_2_PTS)]
        else:
            if h[t] >= ob["bottom"] and c[t] < ob["bottom"]:
                return [("Rejection candle at OB within last 5 bars", TIER_2_PTS)]
    return []
