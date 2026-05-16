"""Setup 3.2 — Order-Block Retest Continuation.

Trigger: HTF in clear trend; recent BOS in trend direction; price pulls back
to the OB that produced the displacement; OB still unmitigated.

Direction = same as HTF bias. Counter-trend cases get the half-score penalty
applied automatically.
"""
from __future__ import annotations

from typing import Optional

from backend.smc_analyst.context import AnalysisContext
from backend.smc_analyst.scoring import (
    best_target, find_overlapping_fvg, session_bonus,
    htf_alignment_bonus, ob_recency_bonus, proximity_bonus, rejection_bonus,
)
from backend.smc_analyst.setups.base import (
    Setup, SetupMatch,
    TIER_1_PTS, TIER_2_PTS, TIER_3_PTS,
    apply_counter_trend_penalty,
)


_RETEST_PROXIMITY_ATR = 0.5      # OB edge within this many ATRs of current price
_ATR_STOP_BUFFER = 0.20


class OrderBlockContinuation(Setup):
    name = "OB Retest Continuation"

    def evaluate(self, ctx: AnalysisContext) -> Optional[SetupMatch]:
        if ctx.ltf.empty or len(ctx.ltf.bars) < 30:
            return None
        if not ctx.active_obs:
            return None

        last_close = ctx.last_close
        atr = ctx.atr_ltf or 0.0
        tol = atr * _RETEST_PROXIMITY_ATR

        # Pick the most recent valid OB whose edge is within reach.
        candidates: list[dict] = []
        for ob in ctx.active_obs:
            if ob["bias"] == "bullish":
                # long retest: price approaching OB top from above
                if (ob["top"] - tol) <= last_close <= (ob["top"] + 3 * tol):
                    candidates.append(ob)
            else:
                if (ob["bottom"] - 3 * tol) <= last_close <= (ob["bottom"] + tol):
                    candidates.append(ob)
        if not candidates:
            return None
        ob = sorted(candidates, key=lambda o: o["formed_bar"], reverse=True)[0]
        direction = "long" if ob["bias"] == "bullish" else "short"

        # Score
        bd: list[tuple[str, int]] = []
        raw = 0

        bd.append((
            f"{ob['bias'].capitalize()} OB present at retest "
            f"{ob['bottom']:.2f}–{ob['top']:.2f}",
            TIER_1_PTS,
        ))
        raw += TIER_1_PTS

        # Tier 1: existing BOS in trend direction
        bos = ctx.ltf.structure.get("last_bos")
        if bos:
            bos_dir_up = bos["type"].endswith("_UP")
            if (direction == "long" and bos_dir_up) or (direction == "short" and not bos_dir_up):
                bd.append((f"LTF BOS in trade direction ({bos['type']})", TIER_1_PTS))
                raw += TIER_1_PTS

        # Tier 2: FVG inside / next to OB
        fvg_bias = "bullish" if direction == "long" else "bearish"
        fvg = find_overlapping_fvg(ctx, near_bar=ob["formed_bar"], max_bar_distance=4,
                                    bias=fvg_bias)
        if fvg:
            bd.append((f"{fvg_bias.capitalize()} FVG inside/near OB "
                       f"{fvg['bottom']:.2f}–{fvg['top']:.2f}", TIER_2_PTS))
            raw += TIER_2_PTS

        # Tier 2: PDH/PDL/PWH/PWL coincides with OB
        if ctx.mtf_levels:
            for key in ("pdh", "pdl", "pwh", "pwl"):
                v = ctx.mtf_levels.get(key)
                if v is None:
                    continue
                if ob["bottom"] <= v <= ob["top"]:
                    bd.append((f"{key.upper()} ({v:.2f}) inside OB", TIER_2_PTS))
                    raw += TIER_2_PTS
                    break

        # Tier 3: zone alignment
        if ctx.pd_zones:
            discount = ctx.pd_zones["discount"]
            premium = ctx.pd_zones["premium"]
            if direction == "long" and discount["bottom"] <= ob["bottom"] <= discount["top"]:
                bd.append(("OB sits in Discount Zone", TIER_3_PTS))
                raw += TIER_3_PTS
            elif direction == "short" and premium["bottom"] <= ob["top"] <= premium["top"]:
                bd.append(("OB sits in Premium Zone", TIER_3_PTS))
                raw += TIER_3_PTS

        # Tier 3: strong/weak alignment
        sw = ctx.strong_weak
        if direction == "long" and sw.get("strong_low") is not None:
            bd.append(("Strong Low tag in place", TIER_3_PTS))
            raw += TIER_3_PTS
        elif direction == "short" and sw.get("strong_high") is not None:
            bd.append(("Strong High tag in place", TIER_3_PTS))
            raw += TIER_3_PTS

        # Tier 3: session
        sb = session_bonus(ctx)
        if sb:
            bd.append((f"Trend-friendly session ({ctx.session_phase})", sb))
            raw += sb

        # Calibration bonuses (proximity / recency / HTF / rejection)
        last_bar_idx = len(ctx.ltf.bars) - 1
        for label, pts in proximity_bonus(ob, last_close, atr):
            bd.append((label, pts)); raw += pts
        for label, pts in ob_recency_bonus(ob, last_bar_idx):
            bd.append((label, pts)); raw += pts
        for label, pts in htf_alignment_bonus(ctx, direction):
            bd.append((label, pts)); raw += pts
        for label, pts in rejection_bonus(ctx, ob):
            bd.append((label, pts)); raw += pts

        # Levels
        entry = ob["top"] if direction == "long" else ob["bottom"]
        if fvg:
            entry = (fvg["top"] + fvg["bottom"]) / 2.0  # CE preferred

        buffer = atr * _ATR_STOP_BUFFER
        stop = (ob["bottom"] - buffer) if direction == "long" else (ob["top"] + buffer)

        target_info = best_target(ctx, entry=entry, direction=direction)
        if not target_info:
            return None
        _target_name, target = target_info

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
