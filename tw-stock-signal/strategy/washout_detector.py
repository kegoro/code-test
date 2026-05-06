"""
洗盤 / 量縮吸籌 / B2突破偵測器

detect_washout(): 橫盤量縮（主力清洗浮額）+ B2突破訊號
  - Volume shrinkage (量縮) relative to recent average
  - Price not making new lows (橫盤)
  - B2: last 10 days quiet, then today breakout volume

detect_accumulation_on_decline(): 量縮下跌型吸籌（Feature 5）
  - 連續 N 日以上成交量低於20日均量50%
  - 股價下跌但未破前低（主力製造恐慌同時悄悄吃貨）
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd


VOLUME_QUIET_RATIO = 0.4        # volume < 40% of 20-day avg = "quiet" (washout)
PRICE_FLAT_RANGE = 0.06         # price within 6% range over 10 days = "flat"
ACCUMULATION_VOL_RATIO = 0.50   # volume < 50% of 20-day avg during decline
ACCUMULATION_MIN_DAYS = 5       # min consecutive quiet days for accumulation

B2_QUIET_RATIO = 0.30           # B2: prior 10 days volume < 30% of 20d avg
B2_BREAKOUT_RATIO = 1.50        # B2: today volume > 150% of 20d avg


@dataclass
class WashoutResult:
    is_washout: bool
    volume_ratio: float            # current vol / 20d avg
    price_range_pct: float         # (max-min)/mid over 10d
    description: str
    accumulation_on_decline: bool  # 量縮下跌型吸籌
    accum_quiet_days: int          # consecutive quiet days detected
    b2_breakout: bool              # B2: 量縮後突然放量突破


def detect_washout(prices: pd.DataFrame) -> WashoutResult:
    """
    prices: DataFrame [date, close, volume?], sorted ascending
    """
    closes = prices["close"].values
    volumes = prices["volume"].values if "volume" in prices.columns else None

    if len(closes) < 20:
        return WashoutResult(
            False, float("nan"), float("nan"), "資料不足",
            accumulation_on_decline=False, accum_quiet_days=0,
            b2_breakout=False,
        )

    # Price range check (10-day)
    recent_closes = closes[-10:]
    price_range = (recent_closes.max() - recent_closes.min()) / (recent_closes.mean() + 1e-9)
    price_flat = price_range < PRICE_FLAT_RANGE

    # Volume check
    vol_ratio = float("nan")
    vol_quiet = False
    if volumes is not None and len(volumes) >= 20:
        avg_vol = np.mean(volumes[-20:-1])
        current_vol = volumes[-1]
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else float("nan")
        vol_quiet = vol_ratio < VOLUME_QUIET_RATIO

    not_new_low = closes[-1] >= np.min(closes[-20:]) * 0.97

    is_washout = price_flat and not_new_low and (vol_quiet or np.isnan(vol_ratio))

    # B2 breakout detection
    b2 = _detect_b2_breakout(volumes)

    # Accumulation on decline detection
    accum, accum_days = _detect_accumulation_on_decline(closes, volumes)

    desc_parts = []
    if price_flat:
        desc_parts.append(f"橫盤整理(±{price_range*100:.1f}%)")
    if vol_quiet:
        desc_parts.append(f"量縮至均量{vol_ratio*100:.0f}%")
    if not_new_low:
        desc_parts.append("未破近低點")
    if b2:
        desc_parts.append("B2量縮後突破放量")
    if accum:
        desc_parts.append(f"量縮下跌吸籌({accum_days}日)")

    return WashoutResult(
        is_washout=is_washout,
        volume_ratio=round(vol_ratio, 3) if not np.isnan(vol_ratio) else float("nan"),
        price_range_pct=round(price_range, 4),
        description="，".join(desc_parts) if desc_parts else "無明顯洗盤特徵",
        accumulation_on_decline=accum,
        accum_quiet_days=accum_days,
        b2_breakout=b2,
    )


def _detect_b2_breakout(volumes: np.ndarray | None) -> bool:
    """
    B2 dynamic signal:
      - The prior 10 days (days -11 to -2) all had volume < 30% of 20-day avg
      - Today (day -1) volume > 150% of 20-day avg
    This is the "賣壓消失後突然放量" that signals the real move beginning.
    """
    if volumes is None or len(volumes) < 22:
        return False

    # Compute baseline from BEFORE the quiet+today window so quiet days don't depress avg
    baseline = volumes[:-11]
    avg_vol = np.mean(baseline[-20:]) if len(baseline) >= 1 else 0.0
    if avg_vol <= 0:
        return False

    today_vol = volumes[-1]
    prior_10 = volumes[-11:-1]

    prior_quiet = bool(np.all(prior_10 < avg_vol * B2_QUIET_RATIO))
    today_breakout = bool(today_vol > avg_vol * B2_BREAKOUT_RATIO)

    return prior_quiet and today_breakout


def _detect_accumulation_on_decline(
    closes: np.ndarray,
    volumes: np.ndarray | None,
) -> tuple[bool, int]:
    """
    量縮下跌型吸籌：
    條件一: 近 N 日(N>=5) 成交量均低於20日均量的50%（量縮）
    條件二: 股價整體仍在下跌方向（slope < 0）
    條件三: 股價未跌破近60日最低點（主力有在守）
    """
    if volumes is None or len(closes) < 25 or len(volumes) < 25:
        return False, 0

    avg_vol_20 = np.mean(volumes[-20:])
    if avg_vol_20 <= 0:
        return False, 0

    # Count consecutive quiet days from the end
    quiet_days = 0
    for v in reversed(volumes[-20:]):
        if v < avg_vol_20 * ACCUMULATION_VOL_RATIO:
            quiet_days += 1
        else:
            break

    if quiet_days < ACCUMULATION_MIN_DAYS:
        return False, 0

    # Price must be in a declining pattern
    window = closes[-quiet_days - 5:]
    if len(window) < 3:
        return False, 0
    slope = np.polyfit(np.arange(len(window)), window, 1)[0]
    price_declining = slope < 0

    # But not breaking the 60-day low
    min_60 = np.min(closes[-min(60, len(closes)):])
    not_breaking_low = closes[-1] >= min_60 * 0.97

    is_accum = bool(price_declining) and bool(not_breaking_low)
    return is_accum, quiet_days
