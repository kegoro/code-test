"""Setup 3.9 — Trendline Break + Structure Shift.

A trendline (from `compute_trendlines`) is broken, AND a CHoCH fires within
5 bars in the same direction. The combination confirms a real character
change rather than a one-bar fakeout.
"""
from __future__ import annotations

from typing import Optional

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


_BREAK_CHOCH_WINDOW = 5      # CHoCH must fire within this many bars of the break
_ATR_STOP_BUFFER = 0.20


class TrendlineBreakStructure(Setup):
    name = "Trendline Break + Shift"

    def evaluate(self, ctx: AnalysisContext) -> Optional[SetupMatch]:
        if ctx.ltf.empty or ctx.trendlines is None:
            return None

        upper_breaks = ctx.trendlines.get("upper_breaks") or []
        lower_breaks = ctx.trendlines.get("lower_breaks") or []
        if not upper_breaks and not lower_breaks:
            return None

        choch = ctx.ltf.structure.get("last_choch")
        if not choch:
            return None
        try:
            choch_bar = ctx.ltf.bars.index.get_loc(choch["index"])
        except KeyError:
            return None
        if isinstance(choch_bar, slice):
            choch_bar = choch_bar.start

        choch_up = choch["type"].endswith("_UP")

        # Find the most recent break in the CHoCH direction within the window.
        candidate_breaks = upper_breaks if choch_up else lower_breaks
        match_break: Optional[dict] = None
        for b in reversed(candidate_breaks):
            if abs(choch_bar - b["bar_idx"]) <= _BREAK_CHOCH_WINDOW:
                match_break = b
                break
        if match_break is None:
            return None

        direction = "long" if choch_up else "short"
        last_close = ctx.last_close
        atr = ctx.atr_ltf or 0.0

        bd: list[tuple[str, int]] = []
        raw = 0

        bd.append((
            f"{('↑' if choch_up else '↓')} Trendline break @ {match_break['price']:.2f} "
            f"+ matching CHoCH within {_BREAK_CHOCH_WINDOW} bars",
            TIER_1_PTS,
        ))
        raw += TIER_1_PTS
        bd.append((f"LTF {choch['type']} confirms shift", TIER_1_PTS))
        raw += TIER_1_PTS

        # Tier 2: OB at the break zone
        ob_bias = "bullish" if direction == "long" else "bearish"
        ob = find_overlapping_ob(ctx, near_price=last_close, bias=ob_bias)
        if ob:
            bd.append((f"{ob_bias.capitalize()} OB at break zone "
                       f"{ob['bottom']:.2f}–{ob['top']:.2f}", TIER_2_PTS))
            raw += TIER_2_PTS

        # Tier 2: FVG near the break
        fvg = find_overlapping_fvg(ctx, near_bar=match_break["bar_idx"],
                                    max_bar_distance=5, bias=ob_bias)
        if fvg:
            bd.append((f"{ob_bias.capitalize()} FVG near break "
                       f"{fvg['bottom']:.2f}–{fvg['top']:.2f}", TIER_2_PTS))
            raw += TIER_2_PTS

        # Tier 3: Strong/Weak alignment
        sw = ctx.strong_weak
        if direction == "long" and sw.get("strong_low") is not None:
            bd.append(("Strong Low tag aligned", TIER_3_PTS))
            raw += TIER_3_PTS
        elif direction == "short" and sw.get("strong_high") is not None:
            bd.append(("Strong High tag aligned", TIER_3_PTS))
            raw += TIER_3_PTS

        # Tier 3: MTF level proximity
        if ctx.mtf_levels:
            for key in ("pdh", "pdl", "pwh", "pwl"):
                v = ctx.mtf_levels.get(key)
                if v is None:
                    continue
                if abs(v - match_break["price"]) <= atr:
                    bd.append((f"{key.upper()} within 1 ATR of break", TIER_3_PTS))
                    raw += TIER_3_PTS
                    break

        sb = session_bonus(ctx)
        if sb:
            bd.append((f"Trend-friendly session ({ctx.session_phase})", sb))
            raw += sb

        for label, pts in htf_alignment_bonus(ctx, direction):
            bd.append((label, pts)); raw += pts

        # Levels
        if ob:
            entry = ob["top"] if direction == "long" else ob["bottom"]
            stop = (ob["bottom"] - atr * _ATR_STOP_BUFFER) if direction == "long" \
                else (ob["top"] + atr * _ATR_STOP_BUFFER)
        else:
            entry = float(match_break["price"])
            stop = (entry - 2 * atr) if direction == "long" else (entry + 2 * atr)

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
