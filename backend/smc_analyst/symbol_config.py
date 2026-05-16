"""Per-symbol trading constraints.

Defines which trade directions are allowed for each symbol. Used by
`pipeline.py` to filter SetupMatch results before they become TradeIdeas.

Symbols not listed default to allowing BOTH directions (backward compatible).
See LESSONS.md §2.3 for the policy rationale.
"""
from __future__ import annotations

from backend.smc_analyst.setups.base import Direction


# 2382 廣達: LESSONS.md §2.3 — AI trend leader, long-only (no shorts / fades).
SYMBOL_DIRECTIONS: dict[str, frozenset[Direction]] = {
    "2382": frozenset({"long"}),
}


def is_direction_allowed(symbol: str, direction: Direction) -> bool:
    """Return True if `direction` is permitted for `symbol`.

    Symbols not present in SYMBOL_DIRECTIONS default to True (both
    directions allowed) so existing behaviour is preserved.
    """
    allowed = SYMBOL_DIRECTIONS.get(symbol)
    if allowed is None:
        return True
    return direction in allowed
