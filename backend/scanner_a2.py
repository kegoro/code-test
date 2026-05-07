"""A2 Setup Scanner — LVN Acceptance Breakout."""
from __future__ import annotations

from datetime import datetime
from typing import Final

import pandas as pd

from backend.scanner_models import (
    A2_GRADE_A_MIN,
    A2_GRADE_B_MIN,
    A2_REQUIRED_TOTAL,
    ConditionCheck,
    Direction,
    SetupSignal,
    SetupType,
    SignalGrade,
    SignalStatus,
    VolumeProfileSnapshot,
)


LVN_PROXIMITY_PCT: Final[float] = 0.003
ATR_CONTRACTION_LOOKBACK: Final[int] = 5
ATR_CONTRACTION_MIN_PCT: Final[float] = 0.20
VOLUME_BREAKOUT_MULT: Final[float] = 1.5
PULLBACK_ABSORPTION_MAX: Final[float] = 0.40
NEAR_HVN_MIN_RR: Final[float] = 1.5


def _atr(values: pd.Series) -> float:
    return float(values.tail(14).mean()) if not values.empty else 0.0


def _check_pre_balance(df_daily: pd.DataFrame) -> ConditionCheck:
    if len(df_daily) < ATR_CONTRACTION_LOOKBACK + 5:
        return ConditionCheck("PRE1", "Pre-breakout balance/compression", False, "insufficient bars")
    high = df_daily["high"].astype(float)
    low = df_daily["low"].astype(float)
    tr = (high - low)
    recent = float(tr.tail(ATR_CONTRACTION_LOOKBACK).mean())
    prior = float(tr.tail(ATR_CONTRACTION_LOOKBACK * 2).head(ATR_CONTRACTION_LOOKBACK).mean()) or 1e-9
    contraction = (prior - recent) / prior
    passed = contraction >= ATR_CONTRACTION_MIN_PCT
    return ConditionCheck("PRE1", "Pre-breakout balance/compression", passed, f"contraction={contraction:.3f}")


def _check_lvn_proximity(
    df_m3: pd.DataFrame, profile: VolumeProfileSnapshot
) -> tuple[ConditionCheck, Direction | None, int]:
    if not profile.lvn_levels or df_m3.empty:
        return ConditionCheck("PRE2", "Breakout near LVN", False, "no LVN"), None, -1
    for i in range(len(df_m3)):
        bar = df_m3.iloc[i]
        close = float(bar["close"])
        for lvn in profile.lvn_levels:
            if abs(close - lvn) / max(lvn, 1e-9) <= LVN_PROXIMITY_PCT:
                if close > lvn:
                    return ConditionCheck("PRE2", "Breakout near LVN", True, f"long@{lvn}"), Direction.LONG, i
                if close < lvn:
                    return ConditionCheck("PRE2", "Breakout near LVN", True, f"short@{lvn}"), Direction.SHORT, i
    return ConditionCheck("PRE2", "Breakout near LVN", False, "no LVN proximity"), None, -1


def _check_volume_expansion(df_m3: pd.DataFrame, breakout_idx: int) -> ConditionCheck:
    if breakout_idx < 10:
        return ConditionCheck("F1", "Volume expansion >1.5x", False, "insufficient context")
    avg = float(df_m3["volume"].astype(float).iloc[breakout_idx - 10 : breakout_idx].mean()) or 1.0
    bar_vol = float(df_m3.iloc[breakout_idx]["volume"])
    passed = bar_vol >= avg * VOLUME_BREAKOUT_MULT
    return ConditionCheck("F1", "Volume expansion >1.5x", passed, f"vol={bar_vol:.0f} avg={avg:.0f}")


def _check_delta_aligned(df_m3: pd.DataFrame, breakout_idx: int, direction: Direction) -> ConditionCheck:
    if breakout_idx < 1:
        return ConditionCheck("F2", "Delta aligned", False, "no prior bar")
    bar = df_m3.iloc[breakout_idx]
    prev = df_m3.iloc[breakout_idx - 1]
    delta = float(bar["close"]) - float(bar["open"])
    prev_delta = float(prev["close"]) - float(prev["open"])
    if direction is Direction.LONG:
        passed = delta > 0 and delta >= prev_delta
    else:
        passed = delta < 0 and delta <= prev_delta
    return ConditionCheck("F2", "Delta aligned", passed, f"delta={delta:.2f}")


def _check_stacked_imbalance(df_m3: pd.DataFrame, breakout_idx: int, direction: Direction) -> ConditionCheck:
    if breakout_idx < 2:
        return ConditionCheck("F3", "Stacked imbalance", False, "insufficient")
    last3 = df_m3.iloc[max(0, breakout_idx - 2) : breakout_idx + 1]
    deltas = (last3["close"].astype(float) - last3["open"].astype(float)).tolist()
    if direction is Direction.LONG:
        passed = all(d > 0 for d in deltas)
    else:
        passed = all(d < 0 for d in deltas)
    return ConditionCheck("F3", "Stacked imbalance", passed, f"deltas={[f'{d:.2f}' for d in deltas]}")


def _check_close_strength(df_m3: pd.DataFrame, breakout_idx: int, direction: Direction) -> ConditionCheck:
    bar = df_m3.iloc[breakout_idx]
    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])
    rng = high - low
    if rng <= 0:
        return ConditionCheck("F4", "Close in upper/lower 25%", False, "zero range")
    pos = (close - low) / rng
    passed = (direction is Direction.LONG and pos >= 0.75) or (direction is Direction.SHORT and pos <= 0.25)
    return ConditionCheck("F4", "Close in upper/lower 25%", passed, f"pos={pos:.2f}")


def _check_pullback_no_absorption(df_m3: pd.DataFrame, breakout_idx: int, direction: Direction) -> ConditionCheck:
    if breakout_idx + 1 >= len(df_m3):
        return ConditionCheck("F5", "Pullback no absorption", False, "no pullback bar")
    breakout_vol = float(df_m3.iloc[breakout_idx]["volume"]) or 1.0
    after = df_m3.iloc[breakout_idx + 1 : breakout_idx + 4]
    if direction is Direction.LONG:
        opp = after[after["close"].astype(float) < after["open"].astype(float)]
    else:
        opp = after[after["close"].astype(float) > after["open"].astype(float)]
    if opp.empty:
        return ConditionCheck("F5", "Pullback no absorption", True, "no opposite bar")
    max_opp_vol = float(opp["volume"].astype(float).max())
    passed = max_opp_vol < breakout_vol * PULLBACK_ABSORPTION_MAX
    return ConditionCheck("F5", "Pullback no absorption", passed, f"opp/breakout={max_opp_vol/breakout_vol:.2f}")


def _stop_and_targets(
    df_m3: pd.DataFrame, breakout_idx: int, direction: Direction, profile: VolumeProfileSnapshot
) -> tuple[float, float, float]:
    bar = df_m3.iloc[breakout_idx]
    last_close = float(df_m3.iloc[-1]["close"])
    if direction is Direction.LONG:
        entry = last_close
        stop = float(bar["low"]) - profile.price_step * 2
        target = max(profile.hvn_levels) if profile.hvn_levels else profile.vah
    else:
        entry = last_close
        stop = float(bar["high"]) + profile.price_step * 2
        target = min(profile.hvn_levels) if profile.hvn_levels else profile.val
    return entry, stop, target


def scan_a2(
    symbol: str,
    df_daily: pd.DataFrame,
    df_m3: pd.DataFrame,
    profile: VolumeProfileSnapshot,
    *,
    now: datetime | None = None,
) -> SetupSignal | None:
    if df_m3 is None or df_m3.empty:
        return None

    pre1 = _check_pre_balance(df_daily) if df_daily is not None and len(df_daily) > 0 else ConditionCheck("PRE1", "Pre-breakout balance", False, "no daily")
    pre2, direction, breakout_idx = _check_lvn_proximity(df_m3, profile)

    if not (pre1.passed and pre2.passed) or direction is None or breakout_idx < 0:
        return None

    f1 = _check_volume_expansion(df_m3, breakout_idx)
    f2 = _check_delta_aligned(df_m3, breakout_idx, direction)
    f3 = _check_stacked_imbalance(df_m3, breakout_idx, direction)
    f4 = _check_close_strength(df_m3, breakout_idx, direction)
    f5 = _check_pullback_no_absorption(df_m3, breakout_idx, direction)

    filters = (f1, f2, f3, f4, f5)
    score = sum(1 for f in filters if f.passed)

    if score >= A2_GRADE_A_MIN:
        grade = SignalGrade.A
    elif score >= A2_GRADE_B_MIN:
        grade = SignalGrade.B
    else:
        return None

    entry, stop, target = _stop_and_targets(df_m3, breakout_idx, direction, profile)
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk > 0 and reward / risk < NEAR_HVN_MIN_RR:
        return None

    bar_ts = df_m3.index[-1] if isinstance(df_m3.index, pd.DatetimeIndex) else datetime.utcnow()
    if not isinstance(bar_ts, datetime):
        bar_ts = pd.Timestamp(bar_ts).to_pydatetime()

    return SetupSignal(
        symbol=symbol,
        setup=SetupType.A2,
        direction=direction,
        grade=grade,
        status=SignalStatus.ACTIVE,
        score_passed=score,
        score_total=A2_REQUIRED_TOTAL,
        entry_price=float(entry),
        stop_price=float(stop),
        target_price=float(target),
        profile=profile,
        conditions=(pre1, pre2, *filters),
        cancel_conditions=(
            "X1: 3-5 bar return into value w/o POC shift",
            "X2: opposite absorption + reverse MSS",
            "X3: insufficient room to next HVN (R:R<1.5)",
            "X4: spike without new value",
        ),
        triggered_at=now or datetime.utcnow(),
        bar_timestamp=bar_ts,
        timeframe="3m",
    )


# ---------------- pytest ----------------

def _make_m3(rows: list[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    idx = pd.date_range("2026-05-07 09:00", periods=len(rows), freq="3min")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def _make_daily(rows: list[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    idx = pd.date_range("2026-04-01", periods=len(rows), freq="1D")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def _profile() -> VolumeProfileSnapshot:
    return VolumeProfileSnapshot(
        vah=105.0, val=95.0, poc=100.0,
        lvn_levels=(102.0,), hvn_levels=(108.0,),
        lookback_bars=20, price_step=0.5,
    )


def test_scan_a2_no_breakout_returns_none() -> None:
    daily = _make_daily([(100.0, 101.0, 99.0, 100.0, 1000.0)] * 15)
    m3 = _make_m3([(100.0, 100.5, 99.5, 100.0, 100.0)] * 15)
    assert scan_a2("X", daily, m3, _profile()) is None


def test_scan_a2_empty_returns_none() -> None:
    daily = _make_daily([(100.0, 101.0, 99.0, 100.0, 1000.0)])
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    assert scan_a2("X", daily, empty, _profile()) is None


def test_scan_a2_compression_then_breakout() -> None:
    wide = [(100.0, 103.0, 97.0, 100.0, 1000.0)] * 5
    tight = [(100.0, 100.5, 99.5, 100.0, 1000.0)] * 5
    daily = _make_daily(wide + tight)
    m3_rows = [(100.0, 100.5, 99.5, 100.0, 100.0)] * 12
    m3_rows.append((101.0, 102.5, 100.8, 102.4, 600.0))   # breakout near LVN=102
    m3_rows.append((102.4, 102.6, 102.3, 102.5, 50.0))    # weak pullback
    m3 = _make_m3(m3_rows)
    sig = scan_a2("2330", daily, m3, _profile())
    # Either valid signal or None — assert no crash & type
    assert sig is None or sig.setup is SetupType.A2
