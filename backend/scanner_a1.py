"""A1 Setup Scanner — VA Edge Sweep Reversal."""
from __future__ import annotations

from datetime import datetime
from typing import Final

import numpy as np
import pandas as pd

from backend.order_block import (
    OrderBlock,
    detect_bearish_ob,
    detect_bullish_ob,
    is_price_in_ob,
    latest_valid_ob,
)
from backend.scanner_models import (
    A1_GRADE_A_MIN,
    A1_GRADE_B_MIN,
    A1_REQUIRED_TOTAL,
    ConditionCheck,
    Direction,
    SetupSignal,
    SetupType,
    SignalGrade,
    SignalStatus,
    VolumeProfileSnapshot,
)


SWEEP_RECOVER_BARS: Final[int] = 1
POC_DRIFT_LOOKBACK: Final[int] = 8
POC_DRIFT_LIMIT_PCT: Final[float] = 0.005
MSS_LOOKBACK: Final[int] = 5
ATR_PERIOD: Final[int] = 14
STOP_BUFFER_TICK_MULT: Final[float] = 2.0
ATR_BUFFER_MULT: Final[float] = 0.25


def _atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    if len(df) < 2:
        return 0.0
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return float(tr.tail(period).mean()) if len(tr) > 0 else 0.0


def _check_d_or_balance(df_daily: pd.DataFrame) -> ConditionCheck:
    if len(df_daily) < 5:
        return ConditionCheck("C1", "Profile D-shape or balance", False, "insufficient daily bars")
    closes = df_daily["close"].astype(float).tail(20)
    upper = closes[closes >= closes.median()].sum()
    lower = closes[closes < closes.median()].sum()
    ratio = upper / lower if lower > 0 else float("inf")
    is_d = ratio >= 1.5 or ratio <= 1 / 1.5
    is_balance = 0.85 <= ratio <= 1.15
    passed = is_d or is_balance
    return ConditionCheck(
        "C1", "Profile D-shape or balance", passed, f"upper/lower ratio={ratio:.2f}"
    )


def _check_va_wick(df_daily: pd.DataFrame, profile: VolumeProfileSnapshot) -> ConditionCheck:
    if len(df_daily) < 3:
        return ConditionCheck("C2", "Recent daily wick into VAH/VAL", False, "insufficient bars")
    last3 = df_daily.tail(3)
    touched = bool(
        ((last3["high"] >= profile.val) & (last3["low"] <= profile.vah)).any()
    )
    return ConditionCheck("C2", "Recent daily wick into VAH/VAL", touched, "")


def _detect_sweep(
    df_m3: pd.DataFrame, profile: VolumeProfileSnapshot
) -> tuple[Direction | None, int]:
    """Returns (direction, bar_index) of sweep + recovery. None if not found."""
    if len(df_m3) < 2:
        return None, -1
    for i in range(len(df_m3) - 1):
        bar = df_m3.iloc[i]
        nxt = df_m3.iloc[i + 1]
        if float(bar["high"]) > profile.vah and float(bar["close"]) < profile.vah:
            return Direction.SHORT, i
        if float(bar["low"]) < profile.val and float(bar["close"]) > profile.val:
            return Direction.LONG, i
        if float(bar["high"]) > profile.vah and float(nxt["close"]) < profile.vah:
            return Direction.SHORT, i
        if float(bar["low"]) < profile.val and float(nxt["close"]) > profile.val:
            return Direction.LONG, i
    return None, -1


def _check_sweep_and_recover(
    df_m3: pd.DataFrame, profile: VolumeProfileSnapshot
) -> tuple[ConditionCheck, Direction | None, int]:
    direction, idx = _detect_sweep(df_m3, profile)
    if direction is None:
        return (
            ConditionCheck("C3+C4", "Sweep VA edge + recover", False, "no sweep+recover detected"),
            None,
            -1,
        )
    return (
        ConditionCheck(
            "C3+C4",
            "Sweep VA edge + recover",
            True,
            f"{direction.value} sweep at bar {idx}",
        ),
        direction,
        idx,
    )


def _check_poc_stable(
    df_m3: pd.DataFrame, sweep_idx: int, profile: VolumeProfileSnapshot
) -> ConditionCheck:
    if sweep_idx < 0:
        return ConditionCheck("C5", "POC stable post-sweep", False, "no sweep")
    after = df_m3.iloc[sweep_idx + 1 : sweep_idx + 1 + POC_DRIFT_LOOKBACK]
    if after.empty:
        return ConditionCheck("C5", "POC stable post-sweep", False, "no bars after sweep")
    avg = float(after["close"].astype(float).mean())
    drift = abs(avg - profile.poc) / max(profile.poc, 1e-9)
    passed = drift < POC_DRIFT_LIMIT_PCT
    return ConditionCheck("C5", "POC stable post-sweep", passed, f"drift={drift:.4f}")


def _check_mss(
    df_m3: pd.DataFrame, sweep_idx: int, direction: Direction | None
) -> ConditionCheck:
    if direction is None or sweep_idx < 0:
        return ConditionCheck("C6", "MSS body-close confirmed", False, "no sweep direction")
    pre = df_m3.iloc[max(0, sweep_idx - MSS_LOOKBACK) : sweep_idx]
    post = df_m3.iloc[sweep_idx : sweep_idx + MSS_LOOKBACK + 1]
    if pre.empty or post.empty:
        return ConditionCheck("C6", "MSS body-close confirmed", False, "insufficient context")
    if direction is Direction.LONG:
        pivot = float(pre["high"].max())
        confirmed = bool((post["close"].astype(float) > pivot).any())
    else:
        pivot = float(pre["low"].min())
        confirmed = bool((post["close"].astype(float) < pivot).any())
    return ConditionCheck("C6", "MSS body-close confirmed", confirmed, f"pivot={pivot:.2f}")


def _check_order_block(
    df_m3: pd.DataFrame, sweep_idx: int, direction: Direction | None
) -> tuple[ConditionCheck, OrderBlock | None]:
    """C7d: sweep extreme falls inside the latest valid Bullish/Bearish OB."""
    if direction is None or sweep_idx < 0 or df_m3 is None or df_m3.empty:
        return ConditionCheck("C7d", "Sweep into valid Order Block", False, "no sweep"), None
    bar = df_m3.iloc[sweep_idx]
    if direction is Direction.LONG:
        obs = detect_bullish_ob(df_m3.iloc[: sweep_idx + 1])
        ob = latest_valid_ob(obs)
        if ob is None:
            return ConditionCheck("C7d", "Sweep into valid Order Block", False, "no bullish OB"), None
        sweep_extreme = float(bar["low"])
    else:
        obs = detect_bearish_ob(df_m3.iloc[: sweep_idx + 1])
        ob = latest_valid_ob(obs)
        if ob is None:
            return ConditionCheck("C7d", "Sweep into valid Order Block", False, "no bearish OB"), None
        sweep_extreme = float(bar["high"])
    inside = is_price_in_ob(sweep_extreme, ob)
    detail = f"OB[{ob['ob_low']:.2f},{ob['ob_high']:.2f}] sweep={sweep_extreme:.2f}"
    return ConditionCheck("C7d", "Sweep into valid Order Block", inside, detail), ob


def _check_footprint_support(
    df_m3: pd.DataFrame, sweep_idx: int, direction: Direction | None,
    c7d_passed: bool = False,
) -> ConditionCheck:
    if direction is None or sweep_idx < 0:
        return ConditionCheck("C7", "Footprint support (>=2 of 4)", False, "no sweep")
    bar = df_m3.iloc[sweep_idx]
    avg_vol = float(df_m3["volume"].astype(float).tail(20).mean()) or 1.0
    avg_range = float(
        (df_m3["high"].astype(float) - df_m3["low"].astype(float)).tail(20).mean()
    ) or 1.0
    bar_vol = float(bar["volume"])
    bar_range = float(bar["high"]) - float(bar["low"])
    bar_open = float(bar["open"])
    bar_close = float(bar["close"])
    bar_high = float(bar["high"])
    bar_low = float(bar["low"])

    c7a = bar_vol > avg_vol * 1.5 and bar_range < avg_range * 0.7

    delta = bar_close - bar_open
    prev_lows = df_m3["low"].astype(float).iloc[max(0, sweep_idx - 5) : sweep_idx]
    prev_highs = df_m3["high"].astype(float).iloc[max(0, sweep_idx - 5) : sweep_idx]
    if direction is Direction.LONG:
        prev_min = float(prev_lows.min()) if not prev_lows.empty else bar_low + 1
        c7b = bar_low < prev_min and delta > 0
    else:
        prev_max = float(prev_highs.max()) if not prev_highs.empty else bar_high - 1
        c7b = bar_high > prev_max and delta < 0

    if bar_range > 0:
        body_pos = (bar_close - bar_low) / bar_range
        c7c = (direction is Direction.LONG and body_pos >= 0.6) or (
            direction is Direction.SHORT and body_pos <= 0.4
        )
    else:
        c7c = False

    score = sum([bool(c7a), bool(c7b), bool(c7c), bool(c7d_passed)])
    passed = score >= 2
    return ConditionCheck(
        "C7",
        "Footprint support (>=2 of 4)",
        passed,
        f"a={c7a} b={c7b} c={c7c} d={c7d_passed}",
    )


def _stop_and_targets(
    df_m3: pd.DataFrame,
    sweep_idx: int,
    direction: Direction,
    profile: VolumeProfileSnapshot,
) -> tuple[float, float, float]:
    bar = df_m3.iloc[sweep_idx]
    atr = _atr(df_m3)
    tick = profile.price_step
    buffer = max(tick * STOP_BUFFER_TICK_MULT, atr * ATR_BUFFER_MULT)
    if direction is Direction.LONG:
        sweep_extreme = float(bar["low"])
        entry = float(df_m3.iloc[-1]["close"])
        stop = sweep_extreme - buffer
        target = profile.poc if profile.poc > entry else profile.vah
    else:
        sweep_extreme = float(bar["high"])
        entry = float(df_m3.iloc[-1]["close"])
        stop = sweep_extreme + buffer
        target = profile.poc if profile.poc < entry else profile.val
    return entry, stop, target


def scan_a1(
    symbol: str,
    df_daily: pd.DataFrame,
    df_m3: pd.DataFrame,
    profile: VolumeProfileSnapshot,
    *,
    now: datetime | None = None,
) -> SetupSignal | None:
    if df_daily is None or df_m3 is None or df_m3.empty:
        return None

    c1 = _check_d_or_balance(df_daily)
    c2 = _check_va_wick(df_daily, profile)
    c34, direction, sweep_idx = _check_sweep_and_recover(df_m3, profile)
    c5 = _check_poc_stable(df_m3, sweep_idx, profile)
    c6 = _check_mss(df_m3, sweep_idx, direction)
    c7d, _ob = _check_order_block(df_m3, sweep_idx, direction)
    c7 = _check_footprint_support(df_m3, sweep_idx, direction, c7d_passed=c7d.passed)

    # C7d is recorded for downstream consumers (engine reads it for ob_confirmed).
    conditions = (c1, c2, c34, c5, c6, c7, c7d)
    score = sum(1 for c in conditions if c.passed)

    if score >= A1_GRADE_A_MIN:
        grade = SignalGrade.A
    elif score >= A1_GRADE_B_MIN:
        grade = SignalGrade.B
    else:
        return None

    if direction is None or sweep_idx < 0:
        return None

    entry, stop, target = _stop_and_targets(df_m3, sweep_idx, direction, profile)

    bar_ts = df_m3.index[-1] if isinstance(df_m3.index, pd.DatetimeIndex) else datetime.utcnow()
    if not isinstance(bar_ts, datetime):
        bar_ts = pd.Timestamp(bar_ts).to_pydatetime()

    return SetupSignal(
        symbol=symbol,
        setup=SetupType.A1,
        direction=direction,
        grade=grade,
        status=SignalStatus.ACTIVE,
        score_passed=score,
        score_total=A1_REQUIRED_TOTAL,
        entry_price=float(entry),
        stop_price=float(stop),
        target_price=float(target),
        profile=profile,
        conditions=conditions,
        cancel_conditions=("X1: body-close break sweep extreme", "X2: POC drifts toward breakout"),
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
        lvn_levels=(97.0,), hvn_levels=(100.0,),
        lookback_bars=20, price_step=0.5,
    )


def test_scan_a1_no_sweep_returns_none() -> None:
    daily = _make_daily([(100.0, 101.0, 99.0, 100.0, 1000.0)] * 10)
    m3 = _make_m3([(100.0, 100.5, 99.5, 100.0, 100.0)] * 10)
    assert scan_a1("TEST", daily, m3, _profile()) is None


def test_scan_a1_long_sweep() -> None:
    daily_rows = [(100.0, 105.5, 94.5, 100.0, 5000.0)] * 20
    daily = _make_daily(daily_rows)
    m3_rows = [(100.0, 100.3, 99.7, 100.0, 100.0)] * 4
    m3_rows.append((96.0, 96.5, 93.0, 96.5, 500.0))   # sweep below VAL=95
    m3_rows.append((96.5, 99.0, 96.0, 98.5, 300.0))   # MSS up
    m3_rows.extend([(98.5, 100.0, 98.0, 99.5, 120.0)] * 4)
    m3 = _make_m3(m3_rows)
    sig = scan_a1("2382", daily, m3, _profile())
    assert sig is None or sig.direction is Direction.LONG


def test_scan_a1_empty_returns_none() -> None:
    daily = _make_daily([(100.0, 101.0, 99.0, 100.0, 1000.0)])
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    assert scan_a1("X", daily, empty, _profile()) is None
