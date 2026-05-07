"""Domain models for the A-Grade Setup scanner (A1 / A2)."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


# ---------- Constants ----------

A1_REQUIRED_TOTAL = 6
A1_GRADE_A_MIN = 6
A1_GRADE_B_MIN = 5

A2_REQUIRED_TOTAL = 5
A2_GRADE_A_MIN = 5
A2_GRADE_B_MIN = 4

DEDUP_WINDOW_MINUTES = 30
SCAN_INTERVAL_SECONDS = 180

TW_MARKET_OPEN = "09:00"
TW_MARKET_CLOSE = "13:35"


# ---------- Enums ----------

class SetupType(str, Enum):
    A1 = "A1"
    A2 = "A2"


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SignalGrade(str, Enum):
    A = "A"
    B = "B"


class SignalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


# ---------- Value objects ----------

@dataclass(frozen=True)
class ConditionCheck:
    code: str
    label: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class VolumeProfileSnapshot:
    vah: float
    val: float
    poc: float
    lvn_levels: tuple[float, ...]
    hvn_levels: tuple[float, ...]
    lookback_bars: int
    price_step: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "vah": self.vah,
            "val": self.val,
            "poc": self.poc,
            "lvn_levels": list(self.lvn_levels),
            "hvn_levels": list(self.hvn_levels),
            "lookback_bars": self.lookback_bars,
            "price_step": self.price_step,
        }


# ---------- Signal ----------

@dataclass(frozen=True)
class SetupSignal:
    symbol: str
    setup: SetupType
    direction: Direction
    grade: SignalGrade
    status: SignalStatus
    score_passed: int
    score_total: int
    entry_price: float
    stop_price: float
    target_price: float
    profile: VolumeProfileSnapshot
    conditions: tuple[ConditionCheck, ...]
    cancel_conditions: tuple[str, ...]
    triggered_at: datetime
    bar_timestamp: datetime
    timeframe: str = "5m"
    note: str = ""

    @property
    def signal_id(self) -> str:
        ts = self.triggered_at.strftime("%Y%m%dT%H%M%S")
        return f"{self.symbol}-{self.setup.value}-{self.direction.value}-{ts}"

    @property
    def dedup_key(self) -> str:
        window = self.bar_timestamp - timedelta(
            minutes=self.bar_timestamp.minute % DEDUP_WINDOW_MINUTES,
            seconds=self.bar_timestamp.second,
            microseconds=self.bar_timestamp.microsecond,
        )
        bucket = window.strftime("%Y%m%dT%H%M")
        return f"{self.symbol}:{self.setup.value}:{self.direction.value}:{bucket}"

    def with_status(self, status: SignalStatus, note: str | None = None) -> "SetupSignal":
        return replace(self, status=status, note=note if note is not None else self.note)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "dedup_key": self.dedup_key,
            "symbol": self.symbol,
            "setup": self.setup.value,
            "direction": self.direction.value,
            "grade": self.grade.value,
            "status": self.status.value,
            "score_passed": self.score_passed,
            "score_total": self.score_total,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "profile": self.profile.to_dict(),
            "conditions": [c.to_dict() for c in self.conditions],
            "cancel_conditions": list(self.cancel_conditions),
            "triggered_at": self.triggered_at.isoformat(),
            "bar_timestamp": self.bar_timestamp.isoformat(),
            "timeframe": self.timeframe,
            "note": self.note,
        }
