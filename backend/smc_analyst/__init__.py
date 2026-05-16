"""SMC Analyst — turns detection primitives into actionable trade ideas.

Public API:
    from backend.smc_analyst import analyse, TradeIdea
    idea = await analyse("2330")
    if idea:
        print(idea.telegram_text())
"""
from backend.smc_analyst.pipeline import analyse
from backend.smc_analyst.trade_idea import TradeIdea

__all__ = ["analyse", "TradeIdea"]
