"""Volume Profile calculation (VAH / VAL / POC / LVN / HVN)."""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from backend.scanner_models import VolumeProfileSnapshot


VALUE_AREA_RATIO = 0.70


def _bin_price(price: float, step: float) -> float:
    return round(round(price / step) * step, 10)


def _build_histogram(
    df: pd.DataFrame, price_step: float
) -> dict[float, float]:
    """Distribute each bar's volume across [low, high] in price_step bins."""
    hist: dict[float, float] = defaultdict(float)
    for row in df.itertuples(index=False):
        low = float(row.low)
        high = float(row.high)
        vol = float(row.volume)
        if vol <= 0 or high < low:
            continue
        lo_bin = _bin_price(low, price_step)
        hi_bin = _bin_price(high, price_step)
        if hi_bin < lo_bin:
            lo_bin, hi_bin = hi_bin, lo_bin
        n_bins = int(round((hi_bin - lo_bin) / price_step)) + 1
        if n_bins <= 1:
            hist[lo_bin] += vol
            continue
        share = vol / n_bins
        for i in range(n_bins):
            level = round(lo_bin + i * price_step, 10)
            hist[level] += share
    return hist


def _value_area(
    sorted_levels: list[float],
    volumes: list[float],
    poc_idx: int,
    target: float,
) -> tuple[float, float]:
    """Expand around POC until cumulative volume >= target."""
    lo = hi = poc_idx
    cum = volumes[poc_idx]
    n = len(sorted_levels)
    while cum < target and (lo > 0 or hi < n - 1):
        up = volumes[hi + 1] if hi < n - 1 else -1.0
        dn = volumes[lo - 1] if lo > 0 else -1.0
        if up >= dn and hi < n - 1:
            hi += 1
            cum += volumes[hi]
        elif lo > 0:
            lo -= 1
            cum += volumes[lo]
        else:
            break
    return sorted_levels[lo], sorted_levels[hi]


def _peaks(
    sorted_levels: list[float],
    volumes: list[float],
    *,
    invert: bool,
) -> tuple[float, ...]:
    if len(volumes) < 3:
        return ()
    arr = np.asarray(volumes, dtype=float)
    if invert:
        max_v = arr.max() if arr.size else 0.0
        signal = max_v - arr
    else:
        signal = arr
    if signal.max() <= 0:
        return ()
    padded = np.concatenate(([0.0], signal, [0.0]))
    prominence = signal.max() * 0.10
    idx, _ = find_peaks(padded, prominence=prominence)
    idx = [i - 1 for i in idx if 0 < i <= len(signal)]
    return tuple(sorted_levels[i] for i in idx)


def calculate_volume_profile(
    df: pd.DataFrame,
    price_step: float = 0.5,
    lookback_bars: int = 20,
) -> VolumeProfileSnapshot:
    """Compute VAH/VAL/POC and LVN/HVN over the last `lookback_bars` bars."""
    if df is None or len(df) == 0:
        raise ValueError("df is empty")
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"df missing columns: {sorted(missing)}")
    if price_step <= 0:
        raise ValueError("price_step must be > 0")
    if lookback_bars <= 0:
        raise ValueError("lookback_bars must be > 0")

    window = df.tail(lookback_bars)
    hist = _build_histogram(window, price_step)
    if not hist:
        raise ValueError("no volume in window")

    sorted_levels = sorted(hist.keys())
    volumes = [hist[p] for p in sorted_levels]
    total = sum(volumes)
    poc_idx = int(np.argmax(volumes))
    poc = sorted_levels[poc_idx]

    val, vah = _value_area(sorted_levels, volumes, poc_idx, total * VALUE_AREA_RATIO)

    hvn_levels = _peaks(sorted_levels, volumes, invert=False)
    lvn_levels = _peaks(sorted_levels, volumes, invert=True)

    return VolumeProfileSnapshot(
        vah=float(vah),
        val=float(val),
        poc=float(poc),
        lvn_levels=lvn_levels,
        hvn_levels=hvn_levels,
        lookback_bars=lookback_bars,
        price_step=price_step,
    )


# ---------------- pytest unit tests ----------------

def _make_df(bars: Iterable[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        list(bars), columns=["open", "high", "low", "close", "volume"]
    )


def test_poc_at_dominant_price() -> None:
    bars = [(100.0, 100.5, 99.5, 100.0, 1000.0)] * 10 + [
        (105.0, 105.5, 104.5, 105.0, 50.0)
    ] * 10
    snap = calculate_volume_profile(_make_df(bars), price_step=0.5, lookback_bars=20)
    assert 99.5 <= snap.poc <= 100.5


def test_value_area_covers_70pct() -> None:
    rng = np.random.default_rng(42)
    bars = []
    for _ in range(50):
        mid = 100.0 + rng.normal(0, 1.0)
        bars.append((mid, mid + 0.5, mid - 0.5, mid, float(rng.integers(100, 1000))))
    snap = calculate_volume_profile(_make_df(bars), price_step=0.5, lookback_bars=50)
    assert snap.val <= snap.poc <= snap.vah
    assert snap.vah - snap.val > 0


def test_empty_df_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        calculate_volume_profile(_make_df([]))


def test_missing_columns_raises() -> None:
    import pytest

    df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]})
    with pytest.raises(ValueError):
        calculate_volume_profile(df)


def test_invalid_params_raise() -> None:
    import pytest

    bars = [(100.0, 100.5, 99.5, 100.0, 1000.0)]
    df = _make_df(bars)
    with pytest.raises(ValueError):
        calculate_volume_profile(df, price_step=0)
    with pytest.raises(ValueError):
        calculate_volume_profile(df, lookback_bars=0)


def test_hvn_includes_poc_region() -> None:
    bars = (
        [(100.0, 100.5, 99.5, 100.0, 2000.0)] * 8
        + [(102.0, 102.5, 101.5, 102.0, 200.0)] * 4
        + [(104.0, 104.5, 103.5, 104.0, 1500.0)] * 8
    )
    snap = calculate_volume_profile(_make_df(bars), price_step=0.5, lookback_bars=20)
    assert len(snap.hvn_levels) >= 1
