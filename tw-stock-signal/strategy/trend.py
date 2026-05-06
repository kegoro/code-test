"""
A指標：240日均線分析
- ma240_value: 當天MA值
- ma240_slope: 均線斜率方向 (up / flat / down)
- state: long_bull / turning_bull / bear
- deduction_value: 扣抵值（240日前的收盤價）
- deduction_drop_imminent: 扣抵值即將從高點下降（逆風消失訊號）
- higher_lows: 近120天底部越來越高（M哥A條件補充）
- higher_highs: 近120天高點越來越高（M哥A條件補充）
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy import stats
from config.settings import settings

MA = settings.ma_period
SLOPE_WINDOW = 20       # days to calculate slope over
SLOPE_UP_THRESH = 0.0001
SLOPE_DOWN_THRESH = -0.0001
FLAT_WINDOW = 40        # days to declare "flat/turning"


@dataclass
class TrendResult:
    ma240_value: float
    ma240_slope: str          # "up" | "flat" | "down"
    state: str                # "long_bull" | "turning_bull" | "bear"
    deduction_value: float
    deduction_drop_imminent: bool
    current_price: float
    has_enough_data: bool
    price_above_ma240: bool   # 硬性條件②：股價站在年線之上
    ma20_slope: str           # 月線斜率 (up/flat/down)
    ma60_slope: str           # 季線斜率 (up/flat/down)
    higher_lows: bool         # 近120天底部越來越高
    higher_highs: bool        # 近120天高點越來越高


def analyze_trend(prices: pd.DataFrame) -> TrendResult:
    """
    prices: DataFrame with columns [date, close], sorted ascending.
    Requires at least MA+SLOPE_WINDOW rows for reliable output.
    """
    closes = prices["close"].values

    if len(closes) < MA + SLOPE_WINDOW:
        return TrendResult(
            ma240_value=float("nan"),
            ma240_slope="unknown",
            state="unknown",
            deduction_value=float("nan"),
            deduction_drop_imminent=False,
            current_price=closes[-1] if len(closes) else float("nan"),
            has_enough_data=False,
            price_above_ma240=False,
            ma20_slope="unknown",
            ma60_slope="unknown",
            higher_lows=False,
            higher_highs=False,
        )

    series = pd.Series(closes)
    ma_series = series.rolling(MA).mean().values
    current_ma = ma_series[-1]
    current_price = closes[-1]

    # 240MA slope
    recent_ma = ma_series[-SLOPE_WINDOW:]
    x = np.arange(SLOPE_WINDOW)
    slope, *_ = stats.linregress(x, recent_ma)
    normalized_slope = slope / current_ma

    if normalized_slope > SLOPE_UP_THRESH:
        ma_slope = "up"
    elif normalized_slope < SLOPE_DOWN_THRESH:
        ma_slope = "down"
    else:
        ma_slope = "flat"

    # Monthly (20d) and quarterly (60d) MA slopes
    ma20_slope = _short_ma_slope(series, 20)
    ma60_slope = _short_ma_slope(series, 60)

    deduction_value = closes[-MA] if len(closes) >= MA else float("nan")
    # Forward-looking: all next 20 deduction values below current → MA240 will keep rising
    deduction_drop = _deduction_will_keep_dropping(closes, MA)

    if ma_slope == "up":
        state = "long_bull"
    elif ma_slope == "flat" or _is_flattening(ma_series):
        state = "turning_bull"
    else:
        state = "bear"

    hl, hh = _check_higher_lows_highs(closes)

    return TrendResult(
        ma240_value=round(current_ma, 2),
        ma240_slope=ma_slope,
        state=state,
        deduction_value=round(float(deduction_value), 2),
        deduction_drop_imminent=deduction_drop,
        current_price=round(current_price, 2),
        has_enough_data=True,
        price_above_ma240=bool(current_price > current_ma),
        ma20_slope=ma20_slope,
        ma60_slope=ma60_slope,
        higher_lows=hl,
        higher_highs=hh,
    )


def _short_ma_slope(series: pd.Series, period: int) -> str:
    ma = series.rolling(period).mean().values
    valid = ma[~np.isnan(ma)]
    if len(valid) < SLOPE_WINDOW:
        return "unknown"
    recent = valid[-SLOPE_WINDOW:]
    x = np.arange(SLOPE_WINDOW)
    slope, *_ = stats.linregress(x, recent)
    ref = valid[-1]
    n = slope / ref if ref else 0
    if n > SLOPE_UP_THRESH:
        return "up"
    if n < SLOPE_DOWN_THRESH:
        return "down"
    return "flat"


def _check_higher_lows_highs(closes: np.ndarray, lookback: int = 120) -> tuple[bool, bool]:
    """
    Splits lookback into 3 equal windows, checks if min/max of each window rises.
    Returns (higher_lows, higher_highs).
    """
    if len(closes) < lookback:
        return False, False
    w = lookback // 3
    w1, w2, w3 = closes[-lookback:-lookback+w], closes[-lookback+w:-lookback+2*w], closes[-lookback+2*w:]
    higher_lows = bool(w3.min() > w2.min() > w1.min())
    higher_highs = bool(w3.max() > w2.max() > w1.max())
    return higher_lows, higher_highs


def _deduction_will_keep_dropping(closes: np.ndarray, ma: int) -> bool:
    """
    True if ALL of the next 20 deduction values are strictly lower than the current one.
    The next-20 deduction values are the closes from (ma-1) to (ma-20) days ago,
    i.e. closes[-ma+1 : -ma+21].  When each one rotates into MA, it replaces the
    current (higher) deduction value → MA240 will keep rising for at least 20 days.
    Requires len(closes) >= ma + 1 (at minimum) and ma > 21.
    """
    if len(closes) < ma + 1 or ma <= 21:
        return False
    current_deduction = closes[-ma]
    # Clamp so we never produce an empty slice when close to array boundary
    end_idx = -ma + 21 if (-ma + 21) < 0 else None
    future_deductions = closes[-ma + 1 : end_idx]
    if len(future_deductions) == 0:
        return False
    return bool(np.all(future_deductions < current_deduction))


def _is_flattening(ma_series: np.ndarray) -> bool:
    """True if MA was declining but is now stabilizing over FLAT_WINDOW days."""
    if len(ma_series) < FLAT_WINDOW * 2:
        return False
    older = ma_series[-FLAT_WINDOW * 2 : -FLAT_WINDOW]
    recent = ma_series[-FLAT_WINDOW:]
    x = np.arange(FLAT_WINDOW)
    old_slope, *_ = stats.linregress(x, older)
    new_slope, *_ = stats.linregress(x, recent)
    return old_slope < 0 and abs(new_slope) < abs(old_slope) * 0.4
