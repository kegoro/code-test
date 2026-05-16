"""Setup 3.8 — Unicorn (Breaker × FVG overlap).

Take a Breaker setup and require an FVG whose [bottom, top] overlaps the
breaker's range by at least 50%. When this confluence exists the setup
gets a +3 score bump on top of the Breaker base — typically lifting it
into HIGH_CONVICTION territory.

This setup rejects the trade entirely when no overlap is present; it does
not fall back to a plain Breaker.
"""
from __future__ import annotations

from typing import Optional

from backend.smc_analyst.context import AnalysisContext
from backend.smc_analyst.setups.base import (
    Setup, SetupMatch,
    TIER_1_PTS,
    apply_counter_trend_penalty,
)
from backend.smc_analyst.setups.breaker import BreakerBlock


def _overlap_fraction(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    """Fraction of `a` that overlaps with `b`."""
    if a_hi <= a_lo:
        return 0.0
    inter_lo = max(a_lo, b_lo)
    inter_hi = min(a_hi, b_hi)
    if inter_hi <= inter_lo:
        return 0.0
    return (inter_hi - inter_lo) / (a_hi - a_lo)


class Unicorn(Setup):
    name = "Unicorn (Breaker × FVG)"

    def __init__(self) -> None:
        self._breaker = BreakerBlock()

    def evaluate(self, ctx: AnalysisContext) -> Optional[SetupMatch]:
        base = self._breaker.evaluate(ctx)
        if base is None:
            return None

        # The breaker's [stop ↔ entry] range is roughly the flipped-OB zone.
        zone_lo = min(base.entry, base.stop)
        zone_hi = max(base.entry, base.stop)

        # Need an FVG that overlaps ≥50% with the breaker zone.
        fvg_bias_needed = "bearish" if base.direction == "short" else "bullish"
        overlap_fvg: Optional[dict] = None
        for f in ctx.active_fvgs:
            if f["bias"] != fvg_bias_needed:
                continue
            ratio = _overlap_fraction(f["bottom"], f["top"], zone_lo, zone_hi)
            if ratio >= 0.5:
                overlap_fvg = f
                break
        if overlap_fvg is None:
            return None

        # Reuse the Breaker's score breakdown, then stack on the +3 Unicorn bonus.
        new_breakdown = list(base.breakdown)
        new_breakdown.append((
            f"UNICORN: FVG overlaps breaker ≥50% "
            f"({overlap_fvg['bottom']:.2f}–{overlap_fvg['top']:.2f})",
            TIER_1_PTS,
        ))
        raw = base.raw_score + TIER_1_PTS
        score = apply_counter_trend_penalty(raw, base.htf_aligned)

        return SetupMatch(
            setup_name=self.name,
            direction=base.direction,
            raw_score=raw,
            score=score,
            breakdown=tuple(new_breakdown),
            entry=base.entry,
            stop=base.stop,
            target=base.target,
            reasoning=tuple(line for line, _ in new_breakdown),
            htf_aligned=base.htf_aligned,
        )
