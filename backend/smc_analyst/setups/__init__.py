"""Setup registry — the canonical ordered list the pipeline iterates."""
from backend.smc_analyst.setups.base import Setup, SetupMatch

# The order influences nothing — pipeline.py sorts matches by score — but we
# keep the high-conviction setups first for readability when debugging.
from backend.smc_analyst.setups.unicorn import Unicorn
from backend.smc_analyst.setups.sweep_reversal import LiquiditySweepReversal
from backend.smc_analyst.setups.breaker import BreakerBlock
from backend.smc_analyst.setups.mitigation import MitigationBlock
from backend.smc_analyst.setups.fvg_at_htf_zone import FVGAtHTFZone
from backend.smc_analyst.setups.ob_continuation import OrderBlockContinuation
from backend.smc_analyst.setups.trendline_break import TrendlineBreakStructure
from backend.smc_analyst.setups.n_pattern import NPattern
# PremiumFade & DiscountRally disabled 2026-05-16 — see LESSONS.md §2.5
# from backend.smc_analyst.setups.premium_fade import PremiumFade, DiscountRally


ALL_SETUPS: list[Setup] = [
    Unicorn(),
    LiquiditySweepReversal(),
    BreakerBlock(),
    MitigationBlock(),
    FVGAtHTFZone(),
    OrderBlockContinuation(),
    TrendlineBreakStructure(),
    NPattern(),  # 2026-05-16 added — 當沖 N 字戰法（LESSONS.md §2.7）
    # PremiumFade(), DiscountRally() — disabled 2026-05-16 (LESSONS.md §2.5)
]

__all__ = ["Setup", "SetupMatch", "ALL_SETUPS"]
