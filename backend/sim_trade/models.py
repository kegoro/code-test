"""Shared immutable data models for the sim-trade module."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import NamedTuple


class BaseBar(NamedTuple):
    """One 1-minute base bar of the continuous TMF series (Asia/Taipei)."""

    ts: datetime          # bar-open wall-clock time, Asia/Taipei
    epoch_s: int          # UTC epoch seconds of ``ts``
    open: float
    high: float
    low: float
    close: float
    volume: int           # contracts (口)
    contract_month: str   # source contract, e.g. 'TMFR1' or '202606'


class AggBar(NamedTuple):
    """One aggregated bar at the active resolution (chart/WS payload shape)."""

    time: int             # bucket-open epoch seconds (lightweight-charts `time`)
    open: float
    high: float
    low: float
    close: float
    volume: int
    closed: bool          # True once the bucket is complete


@dataclass(frozen=True)
class KbarRow:
    """A persisted ``kbars_tmf`` row."""

    ts: datetime
    epoch_s: int
    session_date: date
    session: str          # 'day' | 'night'
    open: float
    high: float
    low: float
    close: float
    volume: int
    contract_month: str
    source: str = "shioaji"


@dataclass(frozen=True)
class Gap:
    """A flagged data gap inside one session."""

    session_date: date
    session: str
    start_ts: datetime
    end_ts: datetime
    reason: str = "missing"  # 'missing' | 'holiday' | 'halt'
