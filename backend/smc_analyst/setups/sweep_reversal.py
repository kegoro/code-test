"""Setup 3.1 — Liquidity-Sweep Reversal.

Trigger: a recent sweep of an obvious liquidity pool (EQH/EQL/swing/MTF
level) AND an opposite-direction CHoCH on the LTF within the last few bars.

Direction = opposite of the sweep direction.

This is the flagship setup — usually the highest scoring when it fires.
"""
from __future__ import annotations

from typing import Optional

from backend.smc_analyst.context import AnalysisContext, SWEEP_RECENCY_BARS
from backend.smc_analyst.scoring import (
    best_target,
    find_overlapping_fvg,
    find_overlapping_ob,
    htf_alignment_bonus,
    session_bonus,
)
from backend.smc_analyst.setups.base import (
    Setup, SetupMatch,
    TIER_1_PTS, TIER_2_PTS, TIER_3_PTS,
    apply_counter_trend_penalty,
)


_MAX_CHOCH_LAG_BARS = 10   # CHoCH must fire within this many bars after the sweep
_ATR_STOP_BUFFER = 0.15    # stop = sweep wick ± 0.15 × ATR


class LiquiditySweepReversal(Setup):
    name = "Liquidity-Sweep Reversal"

    def evaluate(self, ctx: AnalysisContext) -> Optional[SetupMatch]:
        if ctx.ltf.empty or len(ctx.ltf.bars) < 30:
            return None

        last_bar = len(ctx.ltf.bars) - 1
        recent = ctx.liquidity.recent(within_bars=SWEEP_RECENCY_BARS,
                                      max_bar_idx=last_bar)
        if not recent:
            return None

        # Use the most recent sweep
        sweep = recent[-1]

        # CHoCH must exist on LTF and fire AFTER the sweep, AGAINST it.
        choch = ctx.ltf.structure.get("last_choch")
        if not choch:
            return None
        try:
            choch_bar = ctx.ltf.bars.index.get_loc(choch["index"])
        except KeyError:
            return None
        if isinstance(choch_bar, slice):
            choch_bar = choch_bar.start

        if choch_bar < sweep.bar_idx:
            return None
        if (choch_bar - sweep.bar_idx) > _MAX_CHOCH_LAG_BARS:
            return None

        # Sweep up (wick above level) ⇒ short. Sweep down ⇒ long.
        going_up_sweep = sweep.direction == "up"
        choch_down = choch["type"].endswith("_DOWN")
        if going_up_sweep and not choch_down:
            return None
        if not going_up_sweep and choch_down:
            return None

        direction = "short" if going_up_sweep else "long"

        # ── Build score ──
        bd: list[tuple[str, int]] = []
        raw = 0

        bd.append((f"Liquidity sweep ({sweep.target_kind.upper()}) @ {sweep.level:.2f}", TIER_1_PTS))
        raw += TIER_1_PTS

        bd.append((f"LTF CHoCH against sweep ({choch['type']})", TIER_1_PTS))
        raw += TIER_1_PTS

        # Tier 2: FVG formed during the shift?
        fvg_bias = "bearish" if direction == "short" else "bullish"
        fvg = find_overlapping_fvg(ctx, near_bar=choch_bar, max_bar_distance=4, bias=fvg_bias)
        if fvg:
            bd.append((f"{fvg_bias.capitalize()} FVG formed in shift "
                       f"{fvg['bottom']:.2f}–{fvg['top']:.2f}", TIER_2_PTS))
            raw += TIER_2_PTS

        # Tier 2: OB at entry zone (near price now)?
        last_close = ctx.last_close
        ob_bias = "bearish" if direction == "short" else "bullish"
        ob = find_overlapping_ob(ctx, near_price=last_close, bias=ob_bias)
        if ob:
            bd.append((f"{ob_bias.capitalize()} OB at entry zone "
                       f"{ob['bottom']:.2f}–{ob['top']:.2f}", TIER_2_PTS))
            raw += TIER_2_PTS

        # Tier 2: was the swept level itself a Premium / Discount alignment?
        if ctx.pd_zones:
            premium = ctx.pd_zones["premium"]
            discount = ctx.pd_zones["discount"]
            if direction == "short" and premium["bottom"] <= sweep.level <= premium["top"]:
                bd.append(("Sweep landed in Premium Zone", TIER_2_PTS))
                raw += TIER_2_PTS
            elif direction == "long" and discount["bottom"] <= sweep.level <= discount["top"]:
                bd.append(("Sweep landed in Discount Zone", TIER_2_PTS))
                raw += TIER_2_PTS

        # Tier 3: trendline break in trade direction?
        if ctx.trendlines:
            tl_key = "lower_breaks" if direction == "short" else "upper_breaks"
            recent_breaks = [b for b in ctx.trendlines.get(tl_key, [])
                             if b["bar_idx"] >= sweep.bar_idx - 5]
            if recent_breaks:
                bd.append(("Trendline break in trade direction", TIER_3_PTS))
                raw += TIER_3_PTS

        # Tier 3: Strong/Weak swing tag aligns
        sw = ctx.strong_weak
        if direction == "short" and sw.get("strong_high") is not None:
            bd.append(("Strong High tag matches short bias", TIER_3_PTS))
            raw += TIER_3_PTS
        elif direction == "long" and sw.get("strong_low") is not None:
            bd.append(("Strong Low tag matches long bias", TIER_3_PTS))
            raw += TIER_3_PTS

        # Tier 3: session timing
        sb = session_bonus(ctx)
        if sb:
            bd.append((f"Trend-friendly session ({ctx.session_phase})", sb))
            raw += sb

        # Tier 3: HTF aligned with trade direction
        for label, pts in htf_alignment_bonus(ctx, direction):
            bd.append((label, pts)); raw += pts

        # ── Levels ──
        # Entry: prefer CE of the freshly-formed FVG; else current LTF close.
        if fvg:
            entry = (fvg["top"] + fvg["bottom"]) / 2.0
        elif ob:
            entry = ob["bottom"] if direction == "short" else ob["top"]
        else:
            entry = last_close

        # Stop: beyond the sweep wick + buffer
        buffer = ctx.atr_ltf * _ATR_STOP_BUFFER
        sweep_extreme = float(ctx.ltf.bars["high"].iloc[sweep.bar_idx]) if going_up_sweep \
            else float(ctx.ltf.bars["low"].iloc[sweep.bar_idx])
        stop = sweep_extreme + buffer if going_up_sweep else sweep_extreme - buffer

        # Target: structurally meaningful opposite level
        target_info = best_target(ctx, entry=entry, direction=direction)
        if not target_info:
            return None
        _target_name, target = target_info

        # ── HTF alignment + final score ──
        htf_aligned = ctx.htf_aligned(direction)
        score = apply_counter_trend_penalty(raw, htf_aligned)

        reasoning = tuple([line for line, _ in bd])

        return SetupMatch(
            setup_name=self.name,
            direction=direction,
            raw_score=raw,
            score=score,
            breakdown=tuple(bd),
            entry=round(float(entry), 2),
            stop=round(float(stop), 2),
            target=round(float(target), 2),
            reasoning=reasoning,
            htf_aligned=htf_aligned,
        )
