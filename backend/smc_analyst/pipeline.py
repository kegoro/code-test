"""SMC analyst pipeline orchestrator.

    analyse(symbol)               → Optional[TradeIdea]   # best idea or None
    analyse_all(symbols)          → list[TradeIdea]       # one or none per symbol
    analyse_watchlist()           → list[TradeIdea]       # uses SMC_WATCHLIST env

Hard gates from doc §7 are enforced here, not in each setup:
    * Lunch session (11:30–12:30 TWSE) → no signals.
    * R:R < 1.5                       → discarded.
    * Score < MIN_TRADEABLE_SCORE     → discarded.
    * symbol_config direction policy  → discarded (LESSONS.md §2.3).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from backend.smc_analyst.context import AnalysisContext, gather_context
from backend.smc_analyst.setups import ALL_SETUPS
from backend.smc_analyst.setups.base import SetupMatch, passes_hard_gates
from backend.smc_analyst.symbol_config import is_direction_allowed
from backend.smc_analyst.trade_idea import TradeIdea

logger = logging.getLogger("smc-analyst.pipeline")


def _is_lunch(ctx: AnalysisContext) -> bool:
    return ctx.session_phase == "lunch"


def _is_closed(ctx: AnalysisContext) -> bool:
    return ctx.session_phase == "closed"


async def analyse(
    symbol: str,
    *,
    force_refresh: bool = False,
    allow_closed_session: bool = True,
) -> Optional[TradeIdea]:
    """Run every Setup against `symbol`'s current state. Return the best
    SetupMatch wrapped in a TradeIdea, or None.

    `allow_closed_session`: by default we still evaluate after-hours so the
    user can verify the pipeline; in real-time scanning, set this False.
    """
    ctx = await gather_context(symbol, force_refresh=force_refresh)

    # Hard gate: lunch chop — never trade through TWSE lunch.
    if _is_lunch(ctx):
        logger.debug("%s: lunch session, skipping", symbol)
        return None
    if _is_closed(ctx) and not allow_closed_session:
        logger.debug("%s: market closed, skipping", symbol)
        return None

    matches: list[SetupMatch] = []
    for setup in ALL_SETUPS:
        try:
            m = setup.evaluate(ctx)
        except Exception:
            logger.exception("setup %s failed for %s", setup.name, symbol)
            continue
        if m is None:
            continue
        if not is_direction_allowed(symbol, m.direction):
            logger.debug(
                "%s: %s direction=%s blocked by symbol_config",
                symbol, setup.name, m.direction,
            )
            continue
        if not passes_hard_gates(m):
            continue
        matches.append(m)

    if not matches:
        return None

    # Tie-breakers: highest score first, then highest R:R, then HTF-aligned first.
    matches.sort(key=lambda m: (m.score, m.risk_reward, m.htf_aligned), reverse=True)
    best = matches[0]

    return TradeIdea(
        symbol=symbol,
        timestamp=ctx.now_tw,
        session_phase=ctx.session_phase,
        htf_bias=ctx.htf_bias,
        match=best,
    )


async def analyse_all(symbols: list[str], **kwargs) -> list[TradeIdea]:
    """Run analyse() over each symbol in parallel; drop the Nones."""
    coros = [analyse(s, **kwargs) for s in symbols]
    results = await asyncio.gather(*coros, return_exceptions=True)
    out: list[TradeIdea] = []
    for r in results:
        if isinstance(r, Exception):
            logger.exception("analyse failed: %s", r)
            continue
        if r is not None:
            out.append(r)
    return out


async def analyse_watchlist(**kwargs) -> list[TradeIdea]:
    """掃 watchlist：優先讀 data/day_trade_watchlist.json（當沖動態），
    為空才 fallback 到 SMC_WATCHLIST env（LESSONS.md §2.7.6 P0 #3）。"""
    from backend import watchlist as wl_mod

    persistent = wl_mod.load()
    if persistent.entries:
        symbols = list(persistent.symbols)
        logger.info("analyse_watchlist: %d symbols from day_trade_watchlist.json", len(symbols))
    else:
        raw = os.getenv("SMC_WATCHLIST", "2330,2317,2382")
        symbols = [s.strip() for s in raw.split(",") if s.strip()]
        logger.info("analyse_watchlist: %d symbols from SMC_WATCHLIST env (fallback)", len(symbols))
    return await analyse_all(symbols, **kwargs)
