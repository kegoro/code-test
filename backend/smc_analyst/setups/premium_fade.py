"""Setups 3.3 + 3.4 — Premium Fade (short) & Discount Rally (long).

Trade idea: price has run into the upper 5% (Premium) band; a Bearish OB or
Bearish FVG just formed there ⇒ sell back toward Equilibrium. Mirror for
Discount Rally (long from the lower 5%).
"""
from __future__ import annotations

from typing import Literal, Optional

from backend.smc_analyst.context import AnalysisContext
from backend.smc_analyst.scoring import (
    best_target, find_overlapping_fvg, find_overlapping_ob,
    htf_alignment_bonus, session_bonus,
)
from backend.smc_analyst.setups.base import (
    Setup, SetupMatch,
    TIER_1_PTS, TIER_2_PTS, TIER_3_PTS,
    apply_counter_trend_penalty,
)


_ATR_STOP_BUFFER = 0.20


def _evaluate(
    self: Setup,
    ctx: AnalysisContext,
    *,
    direction: Literal["long", "short"],
) -> Optional[SetupMatch]:
    """Shared body used by both PremiumFade (short) and DiscountRally (long)."""
    if ctx.ltf.empty or not ctx.pd_zones:
        return None
    if ctx.htf.empty:
        return None

    last_close = ctx.last_close
    atr = ctx.atr_ltf or 0.0

    pd_zones = ctx.pd_zones
    zone = pd_zones["premium"] if direction == "short" else pd_zones["discount"]
    # Tier-1 prerequisite: price currently inside the zone.
    if not (zone["bottom"] <= last_close <= zone["top"]):
        return None

    bias_name = "bearish" if direction == "short" else "bullish"
    ob = find_overlapping_ob(ctx, near_price=last_close, bias=bias_name)
    fvg = None
    for f in ctx.active_fvgs:
        if f["bias"] != bias_name:
            continue
        midpoint = (f["top"] + f["bottom"]) / 2.0
        if zone["bottom"] <= midpoint <= zone["top"]:
            fvg = f
            break
    if ob is None and fvg is None:
        return None   # need at least one of the two

    bd: list[tuple[str, int]] = []
    raw = 0

    zone_name = "Premium" if direction == "short" else "Discount"
    bd.append((f"Price inside {zone_name} Zone "
               f"({zone['bottom']:.2f}–{zone['top']:.2f})", TIER_1_PTS))
    raw += TIER_1_PTS

    if ob:
        bd.append((f"{bias_name.capitalize()} OB in zone "
                   f"{ob['bottom']:.2f}–{ob['top']:.2f}", TIER_1_PTS))
        raw += TIER_1_PTS
    if fvg:
        bd.append((f"{bias_name.capitalize()} FVG in zone "
                   f"{fvg['bottom']:.2f}–{fvg['top']:.2f}", TIER_2_PTS))
        raw += TIER_2_PTS

    # Tier 2: LTF CHoCH in trade direction
    choch = ctx.ltf.structure.get("last_choch")
    if choch:
        going_down = choch["type"].endswith("_DOWN")
        if (direction == "short" and going_down) or (direction == "long" and not going_down):
            bd.append((f"LTF {choch['type']} confirms direction", TIER_2_PTS))
            raw += TIER_2_PTS

    # Tier 2: Strong/Weak alignment
    sw = ctx.strong_weak
    if direction == "short" and sw.get("weak_high") is not None:
        bd.append(("Weak High classification at the top", TIER_2_PTS))
        raw += TIER_2_PTS
    if direction == "long" and sw.get("weak_low") is not None:
        bd.append(("Weak Low classification at the bottom", TIER_2_PTS))
        raw += TIER_2_PTS

    # Tier 3: MTF level coincides with the zone
    if ctx.mtf_levels:
        for key in ("pdh", "pdl", "pwh", "pwl"):
            v = ctx.mtf_levels.get(key)
            if v is None:
                continue
            if zone["bottom"] <= v <= zone["top"]:
                bd.append((f"{key.upper()} ({v:.2f}) inside {zone_name} zone", TIER_3_PTS))
                raw += TIER_3_PTS
                break

    # Tier 3: trendline break
    if ctx.trendlines:
        tl_key = "lower_breaks" if direction == "short" else "upper_breaks"
        breaks = ctx.trendlines.get(tl_key, [])
        if breaks:
            bd.append((f"{'Down' if direction == 'short' else 'Up'} "
                       f"trendline break present", TIER_3_PTS))
            raw += TIER_3_PTS

    sb = session_bonus(ctx)
    if sb:
        bd.append((f"Trend-friendly session ({ctx.session_phase})", sb))
        raw += sb

    for label, pts in htf_alignment_bonus(ctx, direction):
        bd.append((label, pts)); raw += pts

    # Entry: prefer OB edge nearest current price; else FVG CE; else last_close
    if ob:
        entry = ob["bottom"] if direction == "short" else ob["top"]
    elif fvg:
        entry = (fvg["top"] + fvg["bottom"]) / 2.0
    else:
        entry = last_close

    buffer = atr * _ATR_STOP_BUFFER
    if direction == "short":
        stop = max(zone["top"], ob["top"] if ob else 0.0) + buffer
    else:
        stop = min(zone["bottom"], ob["bottom"] if ob else float("inf")) - buffer

    # Target: equilibrium midpoint first; fall back to structural target
    eq_top = pd_zones["equilibrium"]["top"]
    eq_bottom = pd_zones["equilibrium"]["bottom"]
    eq_mid = (eq_top + eq_bottom) / 2.0
    if direction == "short" and eq_mid < entry:
        target = eq_mid
    elif direction == "long" and eq_mid > entry:
        target = eq_mid
    else:
        # fallback to structural target
        target_info = best_target(ctx, entry=entry, direction=direction)
        if not target_info:
            return None
        _name, target = target_info

    htf_aligned = ctx.htf_aligned(direction)
    score = apply_counter_trend_penalty(raw, htf_aligned)

    return SetupMatch(
        setup_name=self.name,
        direction=direction,
        raw_score=raw,
        score=score,
        breakdown=tuple(bd),
        entry=round(float(entry), 2),
        stop=round(float(stop), 2),
        target=round(float(target), 2),
        reasoning=tuple(line for line, _ in bd),
        htf_aligned=htf_aligned,
    )


class PremiumFade(Setup):
    name = "Premium Fade"

    def evaluate(self, ctx: AnalysisContext) -> Optional[SetupMatch]:
        return _evaluate(self, ctx, direction="short")


class DiscountRally(Setup):
    name = "Discount Rally"

    def evaluate(self, ctx: AnalysisContext) -> Optional[SetupMatch]:
        return _evaluate(self, ctx, direction="long")
