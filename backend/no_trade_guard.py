"""Hard NO TRADE guard — 8 rules to block low-quality setups."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Final

from backend.scanner_models import Direction, VolumeProfileSnapshot


DAILY_LOSS_LIMIT_PCT: Final[float] = 0.02
MAX_DAILY_TRADES: Final[int] = 3
MAX_CONSECUTIVE_LOSSES: Final[int] = 2
MIN_RR_AFTER_COSTS: Final[float] = 1.5
EVENT_BLOCK_BEFORE_MIN: Final[int] = 15
EVENT_BLOCK_AFTER_MIN: Final[int] = 30
VA_CENTER_DEAD_ZONE_PCT: Final[float] = 0.30


@dataclass(frozen=True)
class TradeContext:
    symbol: str
    direction: Direction
    current_time: datetime
    current_price: float
    entry: float
    stop: float
    target: float
    profile: VolumeProfileSnapshot
    daily_loss_pct: float
    daily_trades: int
    consecutive_losses: int
    htf_bias: str | None
    body_close_mss: bool
    footprint_extension_aligned: bool
    spread_normal: bool
    data_feed_ok: bool
    upcoming_events: tuple[datetime, ...] = ()
    cost_per_trade_pct: float = 0.002


def _within_event_window(now: datetime, events: tuple[datetime, ...]) -> bool:
    for ev in events:
        if ev - timedelta(minutes=EVENT_BLOCK_BEFORE_MIN) <= now <= ev + timedelta(minutes=EVENT_BLOCK_AFTER_MIN):
            return True
    return False


def _in_va_center_dead_zone(price: float, profile: VolumeProfileSnapshot) -> bool:
    if profile.vah <= profile.val:
        return False
    width = profile.vah - profile.val
    margin = width * VA_CENTER_DEAD_ZONE_PCT
    return (profile.val + margin) < price < (profile.vah - margin)


def check_no_trade(ctx: TradeContext) -> tuple[bool, str]:
    """Return (blocked, reason). True = NO TRADE."""
    if _within_event_window(ctx.current_time, ctx.upcoming_events):
        return True, "NT1: within major event blackout window"

    if _in_va_center_dead_zone(ctx.current_price, ctx.profile):
        return True, "NT2: price in VA center dead zone"

    if ctx.htf_bias is None:
        return True, "NT3: HTF bias undefined"

    if not ctx.body_close_mss:
        return True, "NT4: no body-close MSS confirmation"

    if not ctx.footprint_extension_aligned:
        return True, "NT5: footprint extension conflicts with direction"

    risk = abs(ctx.entry - ctx.stop)
    reward = abs(ctx.target - ctx.entry)
    if risk <= 0:
        return True, "NT6: invalid risk (entry==stop)"
    cost_drag = ctx.entry * ctx.cost_per_trade_pct
    rr = (reward - cost_drag) / risk
    if rr < MIN_RR_AFTER_COSTS:
        return True, f"NT6: R:R after costs {rr:.2f} < {MIN_RR_AFTER_COSTS}"

    if (
        ctx.consecutive_losses >= MAX_CONSECUTIVE_LOSSES
        or ctx.daily_loss_pct >= DAILY_LOSS_LIMIT_PCT
        or ctx.daily_trades >= MAX_DAILY_TRADES
    ):
        return True, "NT7: daily risk envelope exhausted"

    if not ctx.spread_normal or not ctx.data_feed_ok:
        return True, "NT8: spread/feed abnormal"

    return False, ""


def is_market_open(now: datetime) -> bool:
    t = now.time()
    return time(9, 0) <= t <= time(13, 35)
