"""Setup 3.5 — Breaker Block (failed-OB reversal).

A breaker forms when an OB is broken (price closes through it) AND the
swing extreme it was defending is subsequently swept. The flipped OB then
acts as resistance/support from the opposite side; entry is on the retest.

`backend.smc_detector.find_breakers` does the heavy lifting; this Setup
just scores and packages the result.
"""
from __future__ import annotations

from typing import Optional

from backend.smc_analyst.context import AnalysisContext
from backend.smc_analyst.scoring import (
    best_target, find_overlapping_fvg, htf_alignment_bonus, session_bonus,
)
from backend.smc_analyst.setups.base import (
    Setup, SetupMatch,
    TIER_1_PTS, TIER_2_PTS, TIER_3_PTS,
    apply_counter_trend_penalty,
)
from backend.smc_detector import find_breakers


_RETEST_PROXIMITY_ATR = 0.7
_ATR_STOP_BUFFER = 0.25


class BreakerBlock(Setup):
    name = "Breaker Block"

    def evaluate(self, ctx: AnalysisContext) -> Optional[SetupMatch]:
        if ctx.ltf.empty or len(ctx.ltf.bars) < 30:
            return None

        breakers = find_breakers(ctx.ltf.bars, lookback=30, max_count=3)
        if not breakers:
            return None

        last_close = ctx.last_close
        atr = ctx.atr_ltf or 0.0
        tol = atr * _RETEST_PROXIMITY_ATR

        # Pick the most recent breaker whose flipped zone the price can reach
        candidate: Optional[dict] = None
        for b in reversed(breakers):
            within_zone = (b["bottom"] - tol) <= last_close <= (b["top"] + tol)
            if within_zone:
                candidate = b
                break
        if candidate is None:
            return None

        direction = "short" if candidate["bias_new"] == "bearish" else "long"

        bd: list[tuple[str, int]] = []
        raw = 0

        bd.append((
            f"Breaker zone (was {candidate['bias_orig']} OB) "
            f"{candidate['bottom']:.2f}–{candidate['top']:.2f}",
            TIER_1_PTS,
        ))
        raw += TIER_1_PTS

        bd.append((
            f"Liquidity sweep after break @ bar {candidate['sweep_bar']}",
            TIER_1_PTS,
        ))
        raw += TIER_1_PTS

        # Tier 2: LTF CHoCH inside breaker zone in trade direction
        choch = ctx.ltf.structure.get("last_choch")
        if choch:
            try:
                choch_bar = ctx.ltf.bars.index.get_loc(choch["index"])
            except KeyError:
                choch_bar = -1
            if choch_bar >= candidate["sweep_bar"]:
                going_down = choch["type"].endswith("_DOWN")
                if (direction == "short" and going_down) or (direction == "long" and not going_down):
                    bd.append((f"LTF {choch['type']} after sweep", TIER_2_PTS))
                    raw += TIER_2_PTS

        # Tier 2: FVG inside the breaker zone
        fvg_bias = "bearish" if direction == "short" else "bullish"
        fvg = find_overlapping_fvg(ctx, near_bar=candidate["sweep_bar"],
                                    max_bar_distance=8, bias=fvg_bias)
        if fvg:
            bd.append((f"{fvg_bias.capitalize()} FVG inside breaker "
                       f"{fvg['bottom']:.2f}–{fvg['top']:.2f}", TIER_2_PTS))
            raw += TIER_2_PTS

        # Tier 3: strong/weak alignment
        sw = ctx.strong_weak
        if direction == "short" and sw.get("strong_high") is not None:
            bd.append(("Strong High tag aligned", TIER_3_PTS))
            raw += TIER_3_PTS
        elif direction == "long" and sw.get("strong_low") is not None:
            bd.append(("Strong Low tag aligned", TIER_3_PTS))
            raw += TIER_3_PTS

        # Tier 3: MTF level overlap
        if ctx.mtf_levels:
            for key in ("pdh", "pdl", "pwh", "pwl"):
                v = ctx.mtf_levels.get(key)
                if v is None:
                    continue
                if candidate["bottom"] <= v <= candidate["top"]:
                    bd.append((f"{key.upper()} ({v:.2f}) inside breaker", TIER_3_PTS))
                    raw += TIER_3_PTS
                    break

        # Tier 3: session
        sb = session_bonus(ctx)
        if sb:
            bd.append((f"Trend-friendly session ({ctx.session_phase})", sb))
            raw += sb

        for label, pts in htf_alignment_bonus(ctx, direction):
            bd.append((label, pts)); raw += pts

        # Levels
        if direction == "short":
            entry = candidate["bottom"] if fvg is None else (fvg["top"] + fvg["bottom"]) / 2.0
            stop = candidate["top"] + atr * _ATR_STOP_BUFFER
        else:
            entry = candidate["top"] if fvg is None else (fvg["top"] + fvg["bottom"]) / 2.0
            stop = candidate["bottom"] - atr * _ATR_STOP_BUFFER

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
