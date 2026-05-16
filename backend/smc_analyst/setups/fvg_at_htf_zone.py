"""Setup 3.7 — FVG Fill at HTF Zone.

HTF (60m) FVG is unmitigated; price is currently filling it; LTF prints a
CHoCH inside the gap. Direction = with the HTF FVG (bullish FVG ⇒ long).

The MTF (60m) frame is reused from the analysis context; we compute FVGs
on it here to identify the HTF zone.
"""
from __future__ import annotations

from typing import Optional

from backend.smc_analyst.context import AnalysisContext
from backend.smc_analyst.scoring import (
    best_target, htf_alignment_bonus, session_bonus,
)
from backend.smc_analyst.setups.base import (
    Setup, SetupMatch,
    TIER_1_PTS, TIER_2_PTS, TIER_3_PTS,
    apply_counter_trend_penalty,
)
from backend.smc_detector import find_fair_value_gaps


_ATR_STOP_BUFFER = 0.20


def _mtf_fvg_containing_price(mtf_df, price: float, *, bias_needed: str | None = None) -> Optional[dict]:
    """Return the closest unmitigated MTF FVG whose [bottom, top] covers `price`."""
    if mtf_df is None or mtf_df.empty:
        return None
    fvgs = [f for f in find_fair_value_gaps(mtf_df) if f["valid"]]
    cands = []
    for f in fvgs:
        if bias_needed and f["bias"] != bias_needed:
            continue
        if f["bottom"] <= price <= f["top"]:
            cands.append(f)
    if not cands:
        return None
    cands.sort(key=lambda f: f["formed_bar"], reverse=True)
    return cands[0]


class FVGAtHTFZone(Setup):
    name = "FVG Fill @ HTF Zone"

    def evaluate(self, ctx: AnalysisContext) -> Optional[SetupMatch]:
        if ctx.ltf.empty or ctx.mtf.empty:
            return None

        last_close = ctx.last_close
        atr = ctx.atr_ltf or 0.0

        # Try both biases — the one that matches HTF wins.
        for direction, bias in (("long", "bullish"), ("short", "bearish")):
            htf_fvg = _mtf_fvg_containing_price(ctx.mtf.bars, last_close, bias_needed=bias)
            if htf_fvg is None:
                continue

            # Need LTF CHoCH inside the HTF FVG, same direction as the trade.
            choch = ctx.ltf.structure.get("last_choch")
            if not choch:
                continue
            going_up = not choch["type"].endswith("_DOWN")
            if (direction == "long") != going_up:
                continue
            # CHoCH price must lie inside the HTF FVG
            if not (htf_fvg["bottom"] <= choch["price"] <= htf_fvg["top"]):
                continue

            bd: list[tuple[str, int]] = []
            raw = 0

            bd.append((
                f"Unmitigated MTF {bias} FVG holds price "
                f"({htf_fvg['bottom']:.2f}–{htf_fvg['top']:.2f})",
                TIER_1_PTS,
            ))
            raw += TIER_1_PTS

            bd.append((f"LTF {choch['type']} inside HTF FVG", TIER_1_PTS))
            raw += TIER_1_PTS

            # Tier 2: matching LTF FVG inside the HTF zone
            ltf_fvgs = [f for f in ctx.active_fvgs
                        if f["bias"] == bias
                        and htf_fvg["bottom"] <= ((f["top"] + f["bottom"]) / 2) <= htf_fvg["top"]]
            if ltf_fvgs:
                ltf_fvgs.sort(key=lambda f: f["formed_bar"], reverse=True)
                ltf_fvg = ltf_fvgs[0]
                bd.append((f"LTF {bias} FVG nested inside "
                           f"{ltf_fvg['bottom']:.2f}–{ltf_fvg['top']:.2f}", TIER_2_PTS))
                raw += TIER_2_PTS

            # Tier 2: Premium/Discount alignment
            if ctx.pd_zones:
                discount = ctx.pd_zones["discount"]
                premium = ctx.pd_zones["premium"]
                if direction == "long" and discount["bottom"] <= last_close <= discount["top"]:
                    bd.append(("Filling within Discount Zone", TIER_2_PTS))
                    raw += TIER_2_PTS
                elif direction == "short" and premium["bottom"] <= last_close <= premium["top"]:
                    bd.append(("Filling within Premium Zone", TIER_2_PTS))
                    raw += TIER_2_PTS

            # Tier 3: MTF level overlap
            if ctx.mtf_levels:
                for key in ("pdh", "pdl", "pwh", "pwl"):
                    v = ctx.mtf_levels.get(key)
                    if v is None:
                        continue
                    if htf_fvg["bottom"] <= v <= htf_fvg["top"]:
                        bd.append((f"{key.upper()} ({v:.2f}) inside HTF FVG", TIER_3_PTS))
                        raw += TIER_3_PTS
                        break

            sb = session_bonus(ctx)
            if sb:
                bd.append((f"Trend-friendly session ({ctx.session_phase})", sb))
                raw += sb

            for label, pts in htf_alignment_bonus(ctx, direction):
                bd.append((label, pts)); raw += pts

            # Levels
            mid = (htf_fvg["top"] + htf_fvg["bottom"]) / 2.0
            entry = mid  # consequent encroachment (CE)
            stop = htf_fvg["bottom"] - atr * _ATR_STOP_BUFFER if direction == "long" \
                else htf_fvg["top"] + atr * _ATR_STOP_BUFFER

            target_info = best_target(ctx, entry=entry, direction=direction)
            if not target_info:
                continue
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

        return None
