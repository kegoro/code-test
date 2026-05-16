"""Setup ABC + SetupMatch dataclass.

Each concrete Setup subclass implements `evaluate(ctx)` and returns either
`None` (setup doesn't apply right now) or a `SetupMatch` (it applies, with
specific entry/stop/target/score).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional

from backend.smc_analyst.context import AnalysisContext


# Confluence weight table (matches doc §4)
TIER_1_PTS = 3
TIER_2_PTS = 2
TIER_3_PTS = 1

# Score thresholds (matches doc §4)
MIN_TRADEABLE_SCORE = 7
HIGH_CONVICTION_SCORE = 10

# Hard gates (matches doc §7)
MIN_RR = 1.5


Direction = Literal["long", "short"]


@dataclass(frozen=True)
class SetupMatch:
    """The result of one Setup successfully matching a context.

    `raw_score` is the un-penalised tier sum. `score` is the final score
    after counter-trend halving (if HTF disagrees with direction).
    """
    setup_name: str
    direction: Direction
    raw_score: int
    score: int
    breakdown: tuple[tuple[str, int], ...]
    entry: float
    stop: float
    target: float
    reasoning: tuple[str, ...]
    htf_aligned: bool

    # ── derived ──
    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward(self) -> float:
        return abs(self.target - self.entry)

    @property
    def risk_reward(self) -> float:
        return (self.reward / self.risk) if self.risk > 0 else 0.0

    @property
    def confidence(self) -> int:
        """Map score (0..15) → confidence (1..10)."""
        if self.score <= 0:
            return 1
        c = round(self.score / 1.5)
        return max(1, min(10, c))

    @property
    def is_high_conviction(self) -> bool:
        return self.score >= HIGH_CONVICTION_SCORE


class Setup(ABC):
    """A concrete trade-setup playbook.

    Subclasses override:
        name: str
        evaluate(ctx) → Optional[SetupMatch]
    """
    name: str = "Unnamed"

    @abstractmethod
    def evaluate(self, ctx: AnalysisContext) -> Optional[SetupMatch]:
        ...


# ── shared helpers used by multiple Setups ────────────────────────────────────

def apply_counter_trend_penalty(raw_score: int, htf_aligned: bool) -> int:
    """Doc §4: counter-trend setups have their score halved before threshold."""
    return raw_score if htf_aligned else raw_score // 2


def passes_hard_gates(match: SetupMatch) -> bool:
    """Doc §7: enforce R:R ≥ 1.5 and score ≥ MIN_TRADEABLE_SCORE."""
    if match.risk_reward < MIN_RR:
        return False
    if match.score < MIN_TRADEABLE_SCORE:
        return False
    if match.risk <= 0 or match.reward <= 0:
        return False
    return True
