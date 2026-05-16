"""Setup 3.6 — Mitigation Block (with-trend continuation, strict).

Different from OB Continuation in three ways:
    * HTF alignment is a HARD GATE (no counter-trend mode).
    * Requires a rejection candle / MSS inside the OB on this tap.
    * Requires the OB to have delivered at least one full displacement leg
      (which `find_order_blocks` already verifies via the `valid` flag).
"""
from __future__ import annotations

from typing import Optional

from backend.smc_analyst.context import AnalysisContext
from backend.smc_analyst.scoring import (
    best_target, session_bonus,
    htf_alignment_bonus, ob_recency_bonus, proximity_bonus,
)
from backend.smc_analyst.setups.base import (
    Setup, SetupMatch,
    TIER_1_PTS, TIER_2_PTS, TIER_3_PTS,
    apply_counter_trend_penalty,
)


_TAP_PROXIMITY_ATR = 0.4
_REJECTION_LOOKBACK = 3
_ATR_STOP_BUFFER = 0.20


def _has_rejection_candle(df, ob, *, direction, lookback) -> bool:
    """Within the last `lookback` LTF bars, was there a rejection candle —
    i.e. wick into the OB followed by a close back outside?"""
    if df is None or df.empty:
        return False
    n = len(df)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    start = max(0, n - lookback)
    for t in range(start, n):
        if direction == "long":
            # bullish rejection: low pierced below ob_top, close back above
            if l[t] <= ob["top"] and c[t] > ob["top"]:
                return True
        else:
            if h[t] >= ob["bottom"] and c[t] < ob["bottom"]:
                return True
    return False


class MitigationBlock(Setup):
    name = "Mitigation Block"

    def evaluate(self, ctx: AnalysisContext) -> Optional[SetupMatch]:
        # HARD gate: HTF must be clearly aligned (ranging not enough)
        if ctx.htf_bias not in ("bullish", "bearish"):
            return None

        if ctx.ltf.empty or not ctx.active_obs:
            return None

        atr = ctx.atr_ltf or 0.0
        last_close = ctx.last_close
        tol = atr * _TAP_PROXIMITY_ATR

        direction = "long" if ctx.htf_bias == "bullish" else "short"
        ob_bias_needed = "bullish" if direction == "long" else "bearish"

        # Find the most-recent valid OB in the right direction, near the tap.
        candidate: Optional[dict] = None
        for ob in sorted(ctx.active_obs, key=lambda o: o["formed_bar"], reverse=True):
            if ob["bias"] != ob_bias_needed:
                continue
            if direction == "long":
                if (ob["top"] - tol) <= last_close <= (ob["top"] + 2 * tol):
                    candidate = ob
                    break
            else:
                if (ob["bottom"] - 2 * tol) <= last_close <= (ob["bottom"] + tol):
                    candidate = ob
                    break
        if candidate is None:
            return None

        # HARD gate: rejection candle within last few bars
        if not _has_rejection_candle(ctx.ltf.bars, candidate,
                                      direction=direction,
                                      lookback=_REJECTION_LOOKBACK):
            return None

        bd: list[tuple[str, int]] = []
        raw = 0

        bd.append((
            f"{ob_bias_needed.capitalize()} OB tap "
            f"{candidate['bottom']:.2f}–{candidate['top']:.2f}",
            TIER_1_PTS,
        ))
        raw += TIER_1_PTS

        bd.append(("Rejection candle confirmed at OB tap", TIER_1_PTS))
        raw += TIER_1_PTS

        bd.append((f"HTF ({ctx.htf_bias}) aligned with trade direction", TIER_1_PTS))
        raw += TIER_1_PTS

        # Tier 2: BOS in trade direction on LTF
        bos = ctx.ltf.structure.get("last_bos")
        if bos:
            going_up = bos["type"].endswith("_UP")
            if (direction == "long" and going_up) or (direction == "short" and not going_up):
                bd.append((f"LTF BOS in trade direction ({bos['type']})", TIER_2_PTS))
                raw += TIER_2_PTS

        # Tier 3: MTF level overlap
        if ctx.mtf_levels:
            for key in ("pdh", "pdl", "pwh", "pwl"):
                v = ctx.mtf_levels.get(key)
                if v is None:
                    continue
                if candidate["bottom"] <= v <= candidate["top"]:
                    bd.append((f"{key.upper()} ({v:.2f}) inside OB", TIER_3_PTS))
                    raw += TIER_3_PTS
                    break

        sb = session_bonus(ctx)
        if sb:
            bd.append((f"Trend-friendly session ({ctx.session_phase})", sb))
            raw += sb

        # Calibration bonuses
        last_bar_idx = len(ctx.ltf.bars) - 1
        for label, pts in proximity_bonus(candidate, last_close, atr):
            bd.append((label, pts)); raw += pts
        for label, pts in ob_recency_bonus(candidate, last_bar_idx):
            bd.append((label, pts)); raw += pts
        # HTF alignment bonus is implicit (it's a hard gate) so award explicitly.
        for label, pts in htf_alignment_bonus(ctx, direction):
            bd.append((label, pts)); raw += pts

        # Levels
        entry = candidate["top"] if direction == "long" else candidate["bottom"]
        buffer = atr * _ATR_STOP_BUFFER
        stop = (candidate["bottom"] - buffer) if direction == "long" \
            else (candidate["top"] + buffer)

        target_info = best_target(ctx, entry=entry, direction=direction)
        if not target_info:
            return None
        _name, target = target_info

        # HTF alignment is already a hard gate ⇒ always aligned here
        htf_aligned = True
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
