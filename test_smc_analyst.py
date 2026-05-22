"""SMC Analyst — verification harness.

1. Runs the real-data pipeline against the watchlist and prints what comes
   back (or "no signal").
2. Builds a hand-crafted SYNTHETIC scenario for each of the four setups and
   asserts the analyst fires the right one with a sane TradeIdea.
3. Optionally pushes the synthetic ideas to Telegram so you can see the
   formatted output in your chat.

Usage:
    python test_smc_analyst.py                 # local-only verification
    python test_smc_analyst.py --telegram      # also push to Telegram
"""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from backend.smc_analyst import analyse
from backend.smc_analyst.context import (
    AnalysisContext, Frame, LiquidityMap, Sweep, _atr,
)
from backend.smc_analyst.setups import ALL_SETUPS
from backend.smc_analyst.setups.base import passes_hard_gates
from backend.smc_analyst.trade_idea import TradeIdea
from backend.smc_detector import (
    classify_strong_weak, compute_mtf_levels, compute_premium_discount,
    compute_trendlines, detect_market_structure, find_fair_value_gaps,
    find_order_blocks, mark_equal_pivots,
)

_TZ = ZoneInfo("Asia/Taipei")


# ── synthetic data builders ───────────────────────────────────────────────────

def _bar(open_p, close_p, *, hi_pad=0.3, lo_pad=0.3, vol=1000) -> tuple:
    high = max(open_p, close_p) + hi_pad
    low  = min(open_p, close_p) - lo_pad
    return (open_p, high, low, close_p, vol)


def _frame_from_rows(rows, start: datetime, freq="1min") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(rows), freq=freq)
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    return df


def _build_synth_ctx(
    symbol: str,
    ltf_df: pd.DataFrame,
    *,
    htf_bias: str = "bullish",
    htf_df: Optional[pd.DataFrame] = None,
    mtf_df: Optional[pd.DataFrame] = None,
    session_phase: str = "trend_morning",
) -> AnalysisContext:
    """Wrap a synthetic LTF frame with everything AnalysisContext needs."""
    if htf_df is None:
        # Build a trivially-trending daily frame matching the requested bias.
        rows = []
        base = 2200.0
        for i in range(60):
            delta = 2 if htf_bias == "bullish" else (-2 if htf_bias == "bearish" else 0)
            base += delta
            rows.append(_bar(base, base + delta, hi_pad=2, lo_pad=2))
        htf_df = _frame_from_rows(rows, datetime(2026, 3, 1), freq="1D")
    if mtf_df is None:
        mtf_df = ltf_df.resample("60min").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna(subset=["open"])

    htf_struct = detect_market_structure(htf_df, n=5)
    mtf_struct = detect_market_structure(mtf_df, n=5) if not mtf_df.empty else \
        {"structure": "ranging", "swing_points": {"swing_highs": [], "swing_lows": []},
         "last_bos": None, "last_choch": None}
    ltf_struct = detect_market_structure(ltf_df, n=10)

    htf = Frame("1D", htf_df, 5, htf_struct, atr=_atr(htf_df, 14))
    mtf = Frame("60m", mtf_df, 5, mtf_struct, atr=_atr(mtf_df, 14))
    ltf = Frame("1m", ltf_df, 10, ltf_struct, atr=_atr(ltf_df, 14))

    sp_ltf = ltf_struct.get("swing_points", {})
    eq = mark_equal_pivots(sp_ltf, ltf_df)
    sw = classify_strong_weak(ltf_struct)
    obs = find_order_blocks(ltf_df, lookback=30, max_count=5)
    fvgs = [f for f in find_fair_value_gaps(ltf_df) if f["valid"]]
    tl = compute_trendlines(ltf_df, length=14) if len(ltf_df) > 30 else None
    pd_zones = compute_premium_discount(sp_ltf, ltf_df)
    mtf_levels = compute_mtf_levels(htf_df)

    # Build a liquidity map by reusing the production logic on the same data.
    from backend.smc_analyst.context import _build_liquidity_map
    liquidity = _build_liquidity_map(ltf, mtf_levels=mtf_levels, equal_pivots=eq)

    return AnalysisContext(
        symbol=symbol,
        now_tw=datetime.now(_TZ),
        session_phase=session_phase,  # type: ignore[arg-type]
        htf=htf, mtf=mtf, ltf=ltf,
        liquidity=liquidity,
        pd_zones=pd_zones,
        mtf_levels=mtf_levels,
        equal_pivots=eq,
        strong_weak=sw,
        active_obs=obs,
        active_fvgs=fvgs,
        trendlines=tl,
        atr_ltf=ltf.atr,
    )


# ── one scenario per setup ────────────────────────────────────────────────────

def scenario_sweep_reversal() -> pd.DataFrame:
    """EQH at 105 swept by a wick to 107, then CHoCH_DOWN, then FVG forms."""
    rows = []
    # warm-up: zigzag with equal highs at 105
    seq = [100, 102, 105, 103, 100, 98, 100, 103, 105, 102, 99, 96, 99, 102, 105]
    for p in seq:
        rows.append(_bar(p - 0.2, p))
    # sweep: spike to 107 then close back at 104 (wick above EQH 105, close below)
    rows.append((104, 107, 103.5, 104, 5000))
    # CHoCH_DOWN: bunch of bear bars breaking prior swing low
    for p in [103, 101, 98, 95, 92, 89]:
        rows.append(_bar(p + 1, p))
    # FVG-creating displacement: huge bear gap
    rows.append((89, 89.5, 84, 84, 6000))   # gap between low[t]=84 and high[t-2]=98? need 3-bar pattern
    rows.append((84, 86, 81, 82, 5000))
    # pad
    for p in [82, 83, 82, 84, 83, 85, 84]:
        rows.append(_bar(p - 0.2, p))
    return _frame_from_rows(rows, datetime(2026, 5, 11, 9, 0))


def scenario_ob_continuation() -> pd.DataFrame:
    """Crisp uptrend: 30-bar climb → bearish OB candle → strong bull displacement
    (creates OB) → 40-bar continuation with several swing highs (so BOS triggers)
    → pullback to OB top. Final close sits 1 ATR above OB top.

    Length is ~120 bars so detect_market_structure with n=10 has room.
    """
    rng = np.random.default_rng(seed=7)
    rows = []
    p = 100.0

    def push(open_, close, hi_pad=0.4, lo_pad=0.4, vol=1000):
        rows.append(_bar(open_, close, hi_pad=hi_pad, lo_pad=lo_pad, vol=vol))

    # Phase 1: 30 bars of clean uptrend with a swing low at the start
    for i in range(30):
        wobble = rng.normal(0, 0.3)
        nxt = p + 0.3 + wobble
        push(p, nxt)
        p = nxt

    # Phase 2: bearish OB candidate (one bear bar)
    bear_open = p
    bear_close = p - 1.8
    push(bear_open, bear_close, hi_pad=0.2, lo_pad=0.5, vol=1500)
    ob_low = bear_close - 0.5

    # Phase 3: strong bullish displacement (>0.5% return; body in upper 30%)
    disp_open = bear_close
    disp_close = bear_close + 4.5     # +~4% — clear displacement
    push(disp_open, disp_close, hi_pad=0.2, lo_pad=0.3, vol=4000)
    p = disp_close
    ob_top = bear_open + 0.5   # top of the original bearish bar

    # Phase 4: 40 bars of continued rally, definitely breaks the prior swing
    # high (~104 from phase 1) and creates new swing highs/lows.
    last_swing_high_target = 100 + 30 * 0.3   # ≈ 109 from phase 1
    for i in range(40):
        wobble = rng.normal(0, 0.4)
        nxt = p + 0.5 + wobble
        push(p, nxt)
        p = nxt
    rally_top = p

    # Phase 5: 30-bar pullback ending just above the OB top
    target_price = ob_top + 1.0     # ~1 unit above OB → "just above"
    pullback_step = (p - target_price) / 30
    for i in range(30):
        wobble = rng.normal(0, 0.3)
        nxt = p - pullback_step + wobble
        push(p, nxt)
        p = nxt

    # Snap last bar's close exactly to ob_top + 1 to guarantee the proximity gate.
    last = rows[-1]
    rows[-1] = (last[0], max(last[1], target_price + 0.3),
                 min(last[2], target_price - 0.3),
                 target_price, last[4])
    return _frame_from_rows(rows, datetime(2026, 5, 11, 9, 0))


def scenario_premium_fade() -> pd.DataFrame:
    """Range with clear swings, price runs up into Premium Zone, bearish OB
    forms there, current bar still in Premium zone."""
    rows = []
    p = 100
    # zigzag forming swing low at 100, swing high at 120, low at 105, high at 119
    for q in [100, 102, 105, 110, 115, 120, 117, 112, 108, 105]:
        rows.append(_bar(p, q)); p = q
    for q in [107, 110, 115, 119]:
        rows.append(_bar(p, q)); p = q
    # bullish bar (OB candidate)
    rows.append(_bar(p, p + 1)); p += 1   # bull bar 120
    # strong BEAR displacement (creates bearish OB out of the bull bar above)
    rows.append((p, p + 0.3, p - 3.5, p - 3.5, 5000))
    p -= 3.5
    # mild pullback up into Premium
    for q in [118, 119, 118.5, 119.3, 119.0]:
        rows.append(_bar(p, q)); p = q
    return _frame_from_rows(rows, datetime(2026, 5, 11, 9, 0))


def scenario_discount_rally() -> pd.DataFrame:
    """Mirror of premium_fade — price near Discount low, bullish OB forms."""
    rows = []
    p = 120
    for q in [120, 118, 115, 110, 105, 100, 103, 108, 112, 115]:
        rows.append(_bar(p, q)); p = q
    for q in [113, 110, 105, 101]:
        rows.append(_bar(p, q)); p = q
    rows.append(_bar(p, p - 1)); p -= 1   # bear bar
    rows.append((p, p + 3.5, p - 0.3, p + 3.5, 5000))   # strong bull displacement
    p += 3.5
    for q in [102, 101, 101.5, 100.7, 101.0]:
        rows.append(_bar(p, q)); p = q
    return _frame_from_rows(rows, datetime(2026, 5, 11, 9, 0))


# ── run all scenarios ─────────────────────────────────────────────────────────

SCENARIOS = [
    ("Liquidity-Sweep Reversal", "ranging",  scenario_sweep_reversal),
    ("OB Retest Continuation",   "bullish",  scenario_ob_continuation),
    ("Premium Fade",             "bearish",  scenario_premium_fade),
    ("Discount Rally",           "bullish",  scenario_discount_rally),
]


def _evaluate_synthetic(ctx: AnalysisContext):
    matches = []
    for s in ALL_SETUPS:
        try:
            m = s.evaluate(ctx)
        except Exception as e:
            print(f"    ERROR in {s.name}: {e!r}")
            continue
        if m is not None:
            matches.append((s.name, m))
    return matches


def run_synthetic():
    print("\n══════ SYNTHETIC POSITIVE-CONTROL ══════")
    fires = []
    for label, htf_bias, builder in SCENARIOS:
        print(f"\n── {label}  (HTF={htf_bias}) ──")
        ltf_df = builder()
        ctx = _build_synth_ctx(symbol="TEST", ltf_df=ltf_df, htf_bias=htf_bias)
        matches = _evaluate_synthetic(ctx)
        if not matches:
            print("  (no setup fired)")
            continue
        for name, m in matches:
            gate = "✓" if passes_hard_gates(m) else "✗"
            print(f"  {gate} {name:30s} {m.direction:5s} score={m.score}/{m.raw_score}  "
                  f"R:R={m.risk_reward:.2f}  entry={m.entry:.2f} stop={m.stop:.2f} target={m.target:.2f}")
            if passes_hard_gates(m):
                idea = TradeIdea(symbol="TEST", timestamp=ctx.now_tw,
                                 session_phase=ctx.session_phase, htf_bias=ctx.htf_bias,
                                 match=m)
                fires.append((label, idea))
    return fires


async def run_real_watchlist():
    print("\n══════ REAL WATCHLIST ══════")
    syms = (os.getenv("SMC_WATCHLIST") or "2330,2317,2382").split(",")
    syms = [s.strip() for s in syms if s.strip()]
    ideas = []
    for sym in syms:
        idea = await analyse(sym, force_refresh=True)
        if idea is None:
            print(f"  {sym}: (no signal)")
        else:
            print(f"  {sym}: 🎯 {idea.match.setup_name} {idea.match.direction} "
                  f"score={idea.match.score} R:R={idea.match.risk_reward:.2f}")
            ideas.append(idea)
    return ideas


async def push_to_telegram(real_ideas, synth_ideas) -> None:
    """Send a summary report to Telegram for verification."""
    load_dotenv(Path(".env.local"))
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("TELEGRAM creds missing; skipping push")
        return
    from telegram import Bot
    bot = Bot(token=token)

    intro = (
        "🧪 SMC Analyst — Phase P0–P3 驗收\n"
        f"真實 watchlist: {len(real_ideas)} 個訊號\n"
        f"合成 positive control: {len(synth_ideas)} 個訊號"
    )
    await bot.send_message(chat_id=chat, text=intro)

    for idea in real_ideas:
        await bot.send_message(chat_id=chat, text="📈 (REAL DATA)\n" + idea.telegram_text())

    for label, idea in synth_ideas:
        await bot.send_message(chat_id=chat,
                                text=f"🧬 (SYNTHETIC: {label})\n" + idea.telegram_text())

    await bot.send_message(chat_id=chat, text="✅ 驗收推送完畢。")


async def main():
    push_tg = "--telegram" in sys.argv
    synth = run_synthetic()
    real = await run_real_watchlist()
    print(f"\nSummary: real={len(real)} synth={len(synth)}")
    if push_tg:
        await push_to_telegram(real, synth)


if __name__ == "__main__":
    asyncio.run(main())
