"""
缺貨雷達 — 供需失衡偵測

核心邏輯（雷老闆第五章）：
  只要產業出現「真缺貨」，廠商就能漲價，營收就會暴衝。
  透過月營收 YoY 加速 + 機構驗證，捕捉缺貨初期訊號。

ShortageScore 評分 (1–5)：
  +1  YoY >= 10%
  +1  YoY >= 20%（額外加成）
  +1  本月 YoY > 上月 YoY（加速）
  +1  連續 3 個月 YoY > 20%（持續爆衝）
  +1  近 12 個月營收新高（站上歷史高峰）

建議閾值：
  score >= 4 → 強缺貨訊號 🔴
  score == 3 → 潛在缺貨   🟠
  score == 2 → 觀察中      🟡
  score <= 1 → 不符合      —
"""
from dataclasses import dataclass, field
import pandas as pd

# AI / 半導體供應鏈族群 (可擴充)
SUPPLY_CHAIN_MAP: dict[str, list[str]] = {
    "AI伺服器/ODM":  ["2382", "3231", "4938", "6515", "3017", "3019"],
    "AI散熱":        ["6669", "3296", "4419", "8936"],
    "AI PCB/ABF基板":["3037", "8046", "3044", "2382", "6274"],
    "AI電源":        ["6409", "3003", "1504", "6533"],
    "AI記憶體/HBM":  ["3474", "4960", "5483"],
    "晶圓代工":      ["2330", "2303", "5347"],
    "IC封測":        ["2449", "2454", "3711", "6147"],
    "網路/交換器":    ["3045", "2345", "6415"],
    "CoWoS/先進封裝":["2330", "2408", "3701"],
}

# Reverse map: symbol → sector list
_SYMBOL_SECTOR: dict[str, list[str]] = {}
for _sector, _syms in SUPPLY_CHAIN_MAP.items():
    for _s in _syms:
        _SYMBOL_SECTOR.setdefault(_s, []).append(_sector)


@dataclass
class ShortageSignal:
    symbol: str
    name: str
    latest_period: str          # "YYYY-MM"
    latest_yoy: float           # %
    prev_yoy: float | None      # % (month prior), None if not available
    acceleration: float | None  # latest_yoy - prev_yoy, positive = accelerating
    consecutive_above_20: int   # how many recent months YoY > 20%
    revenue_new_high: bool      # latest revenue = 12-month high
    score: int                  # 1–5
    grade: str                  # "強缺貨" / "潛在缺貨" / "觀察中" / "不符合"
    sectors: list[str] = field(default_factory=list)
    revenue_trend: list[float] = field(default_factory=list)  # last 4 months
    yoy_trend: list[float | None] = field(default_factory=list)


def detect_shortage(
    symbol: str,
    name: str,
    revenue_df: pd.DataFrame,
) -> "ShortageSignal | None":
    """
    Compute shortage signal from a monthly revenue DataFrame.

    `revenue_df` must have columns: period (YYYY-MM), revenue (float), yoy (float|NaN).
    Returns None if not enough data (< 3 months with YoY).
    """
    if revenue_df.empty:
        return None

    df = revenue_df.dropna(subset=["yoy"]).copy()
    if len(df) < 2:
        return None

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else None

    latest_yoy: float = float(latest["yoy"])
    prev_yoy: float | None = float(prev["yoy"]) if prev is not None else None
    acceleration: float | None = (
        latest_yoy - prev_yoy if prev_yoy is not None else None
    )

    # Consecutive months with YoY > 20%
    consecutive_above_20 = 0
    for _, row in df.iloc[::-1].iterrows():
        if float(row["yoy"]) > 20:
            consecutive_above_20 += 1
        else:
            break

    # Revenue new high in trailing 12 months
    all_rev = revenue_df["revenue"].dropna()
    revenue_new_high = bool(
        not all_rev.empty
        and float(latest["revenue"]) >= all_rev.max() - 1e-6
        and len(all_rev) >= 3
    )

    # Scoring
    score = 0
    if latest_yoy >= 10:
        score += 1
    if latest_yoy >= 20:
        score += 1
    if acceleration is not None and acceleration > 0:
        score += 1
    if consecutive_above_20 >= 3:
        score += 1
    if revenue_new_high:
        score += 1
    score = max(1, min(5, score))

    grade = (
        "強缺貨" if score >= 4 else
        "潛在缺貨" if score == 3 else
        "觀察中" if score == 2 else
        "不符合"
    )

    # Last 4 months trend for display
    rev_trend = revenue_df["revenue"].tail(4).tolist()
    yoy_trend_vals = revenue_df["yoy"].tail(4).tolist()

    return ShortageSignal(
        symbol=symbol,
        name=name,
        latest_period=str(latest["period"]),
        latest_yoy=latest_yoy,
        prev_yoy=prev_yoy,
        acceleration=acceleration,
        consecutive_above_20=consecutive_above_20,
        revenue_new_high=revenue_new_high,
        score=score,
        grade=grade,
        sectors=_SYMBOL_SECTOR.get(symbol, []),
        revenue_trend=rev_trend,
        yoy_trend=yoy_trend_vals,
    )


def rank_signals(signals: list[ShortageSignal]) -> list[ShortageSignal]:
    """Sort by score desc, then latest_yoy desc."""
    return sorted(signals, key=lambda s: (s.score, s.latest_yoy), reverse=True)


def find_clusters(signals: list[ShortageSignal]) -> dict[str, list[str]]:
    """
    Return sectors where >= 2 shortage signals co-occur.
    Returns {sector: [symbol, ...]}
    """
    sector_hits: dict[str, list[str]] = {}
    for sig in signals:
        if sig.score < 3:
            continue
        for sec in sig.sectors:
            sector_hits.setdefault(sec, []).append(sig.symbol)
    return {k: v for k, v in sector_hits.items() if len(v) >= 2}
