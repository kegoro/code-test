"""ICT/SMC Order Block detection.

A *Bullish OB* is the last bearish candle before a strong bullish displacement
(institutions filling buy orders against late shorts). A *Bearish OB* is the
mirror image.

Operates on any OHLCV frame (daily or intraday). For the backtest's daily
fallback the engine passes a daily window — the same logic applies, just
slower-moving.
"""
from __future__ import annotations

from datetime import date
from typing import Final, TypedDict

import pandas as pd


# --- Detection thresholds ----------------------------------------------------

DISPLACEMENT_RETURN: Final[float] = 0.005     # |close_t / close_{t-1} - 1| > 0.5%
DISPLACEMENT_BODY_POS: Final[float] = 0.70    # bull: body in upper 30% (pos >= 0.7)
                                              # bear: body in lower 30% (pos <= 0.3)
OB_TOLERANCE: Final[float] = 0.002            # ±0.2% padding around OB range
INVALIDATION_LOOKBEHIND: Final[int] = 6       # look at most this many bars back
                                              # for the priming opposite-color bar


class OrderBlock(TypedDict):
    ob_high: float
    ob_low: float
    formed_date: date
    valid: bool


def _body_position(open_: float, high: float, low: float, close: float) -> float:
    """Return close's relative position in [low, high]; 0=at low, 1=at high."""
    rng = high - low
    if rng <= 0:
        return 0.5
    return (close - low) / rng


def detect_bullish_ob(df: pd.DataFrame, lookback: int = 10) -> list[OrderBlock]:
    """Find Bullish Order Blocks within the supplied frame.

    Definition:
    - A "displacement" bar is a strong bullish bar:
      close-vs-prev-close return > 0.5% AND close in upper 30% of [low, high].
    - The Bullish OB is the most recent BEARISH bar before that displacement,
      searched up to `INVALIDATION_LOOKBEHIND` bars back.
    - OB range = that bearish bar's [low, high].
    - Validity: within `lookback` bars *after* formation, no bar's close
      penetrates below the OB low (i.e. the OB has not been mitigated).

    Returns a list of all detected OBs (most recent last).
    """
    if df is None or len(df) < 3:
        return []

    out: list[OrderBlock] = []
    open_ = df["open"].astype(float).to_numpy()
    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    close = df["close"].astype(float).to_numpy()
    idx = df.index

    n = len(df)
    for t in range(1, n):
        prev_close = close[t - 1]
        if prev_close <= 0:
            continue
        ret = close[t] / prev_close - 1.0
        if ret <= DISPLACEMENT_RETURN:
            continue
        if _body_position(open_[t], high[t], low[t], close[t]) < DISPLACEMENT_BODY_POS:
            continue

        # Find the most recent bearish bar before the displacement.
        ob_idx: int | None = None
        for k in range(t - 1, max(-1, t - 1 - INVALIDATION_LOOKBEHIND), -1):
            if close[k] < open_[k]:
                ob_idx = k
                break
        if ob_idx is None:
            continue

        ob_low = float(low[ob_idx])
        ob_high = float(high[ob_idx])

        # Validity: scan `lookback` bars after formation; mitigated if any close < ob_low.
        valid = True
        end = min(n, t + 1 + lookback)
        for j in range(t + 1, end):
            if close[j] < ob_low:
                valid = False
                break

        formed = idx[ob_idx]
        formed_date = formed.date() if hasattr(formed, "date") else formed
        out.append(
            OrderBlock(
                ob_high=ob_high,
                ob_low=ob_low,
                formed_date=formed_date,
                valid=valid,
            )
        )
    return out


def detect_bearish_ob(df: pd.DataFrame, lookback: int = 10) -> list[OrderBlock]:
    """Find Bearish Order Blocks (mirror of `detect_bullish_ob`).

    A bearish OB is the most recent BULLISH bar preceding a strong bearish
    displacement (return < -0.5%, close in lower 30%). Validity = no later
    close above OB high within `lookback` bars.
    """
    if df is None or len(df) < 3:
        return []

    out: list[OrderBlock] = []
    open_ = df["open"].astype(float).to_numpy()
    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    close = df["close"].astype(float).to_numpy()
    idx = df.index

    n = len(df)
    for t in range(1, n):
        prev_close = close[t - 1]
        if prev_close <= 0:
            continue
        ret = close[t] / prev_close - 1.0
        if ret >= -DISPLACEMENT_RETURN:
            continue
        if _body_position(open_[t], high[t], low[t], close[t]) > (1.0 - DISPLACEMENT_BODY_POS):
            continue

        ob_idx: int | None = None
        for k in range(t - 1, max(-1, t - 1 - INVALIDATION_LOOKBEHIND), -1):
            if close[k] > open_[k]:
                ob_idx = k
                break
        if ob_idx is None:
            continue

        ob_low = float(low[ob_idx])
        ob_high = float(high[ob_idx])

        valid = True
        end = min(n, t + 1 + lookback)
        for j in range(t + 1, end):
            if close[j] > ob_high:
                valid = False
                break

        formed = idx[ob_idx]
        formed_date = formed.date() if hasattr(formed, "date") else formed
        out.append(
            OrderBlock(
                ob_high=ob_high,
                ob_low=ob_low,
                formed_date=formed_date,
                valid=valid,
            )
        )
    return out


def is_price_in_ob(price: float, ob: OrderBlock, tolerance: float = OB_TOLERANCE) -> bool:
    """Whether `price` falls inside the OB range, padded by ±tolerance (%)."""
    if ob is None:
        return False
    pad_low = ob["ob_low"] * (1.0 - tolerance)
    pad_high = ob["ob_high"] * (1.0 + tolerance)
    return pad_low <= price <= pad_high


def latest_valid_ob(obs: list[OrderBlock]) -> OrderBlock | None:
    """Return the most recently formed OB that is still valid, or None."""
    for ob in reversed(obs):
        if ob["valid"]:
            return ob
    return None


# ---------------- pytest ----------------


def _frame(rows: list[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-02", periods=len(rows), freq="B")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def test_bullish_ob_detected_after_displacement() -> None:
    rows = [
        (100.0, 101.0, 99.5, 100.5, 1000.0),
        (100.5, 100.8, 99.2, 99.5, 1100.0),   # bearish — candidate OB
        (99.5, 103.0, 99.4, 102.8, 5000.0),   # strong bull displacement (+3.3%)
        (102.8, 103.5, 102.0, 103.2, 1500.0),
    ]
    obs = detect_bullish_ob(_frame(rows), lookback=5)
    assert obs, "expected at least one bullish OB"
    last = obs[-1]
    assert last["ob_low"] == 99.2
    assert last["ob_high"] == 100.8
    assert last["valid"] is True


def test_bullish_ob_invalidated_when_mitigated() -> None:
    rows = [
        (100.0, 101.0, 99.5, 100.5, 1000.0),
        (100.5, 100.8, 99.2, 99.5, 1100.0),
        (99.5, 103.0, 99.4, 102.8, 5000.0),
        (102.8, 103.0, 99.0, 99.0, 1500.0),   # mitigates: close < ob_low(99.2)
    ]
    obs = detect_bullish_ob(_frame(rows), lookback=5)
    assert obs and obs[-1]["valid"] is False


def test_bearish_ob_detected() -> None:
    rows = [
        (100.0, 100.5, 99.5, 100.0, 1000.0),
        (100.0, 101.0, 99.8, 100.8, 1100.0),  # bullish — candidate OB
        (100.8, 101.0, 97.0, 97.2, 5000.0),   # strong bear displacement (-3.6%)
        (97.2, 97.5, 96.5, 97.0, 1500.0),
    ]
    obs = detect_bearish_ob(_frame(rows), lookback=5)
    assert obs and obs[-1]["ob_high"] == 101.0
    assert obs[-1]["ob_low"] == 99.8
    assert obs[-1]["valid"] is True


def test_is_price_in_ob_with_tolerance() -> None:
    ob: OrderBlock = {"ob_high": 100.0, "ob_low": 99.0, "formed_date": date(2024, 1, 2), "valid": True}
    assert is_price_in_ob(99.5, ob)
    assert is_price_in_ob(98.85, ob, tolerance=0.002)   # 99.0 * 0.998 = 98.802
    assert not is_price_in_ob(95.0, ob)


def test_latest_valid_ob_picks_most_recent_valid() -> None:
    obs: list[OrderBlock] = [
        {"ob_high": 100.0, "ob_low": 99.0, "formed_date": date(2024, 1, 2), "valid": False},
        {"ob_high": 105.0, "ob_low": 104.0, "formed_date": date(2024, 1, 5), "valid": True},
        {"ob_high": 110.0, "ob_low": 109.0, "formed_date": date(2024, 1, 8), "valid": False},
    ]
    chosen = latest_valid_ob(obs)
    assert chosen is not None and chosen["ob_high"] == 105.0
