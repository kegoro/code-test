"""
缺貨雷達 — 供需失衡偵測

核心邏輯（雷老闆第五、六章）：
  供需失衡 → 廠商漲價 → 營收暴衝（第五章）
  「由上而下」：龍頭股法說提到缺貨/滿載 → 二線業者同步受惠（第六章）
  台灣上市公司是全球供應鏈中間財：
    龍頭（Tier 1）產能滿載 → 訂單轉移二線（Tier 2）→ 二線股更飛

ShortageScore 基礎評分 (1–5)：
  +1  YoY >= 10%
  +1  YoY >= 20%（額外加成）
  +1  本月 YoY > 上月 YoY（加速）
  +1  連續 3 個月 YoY > 20%（持續爆衝）
  +1  近 12 個月營收新高（站上歷史高峰）

瀑布加分（cascade_bonus）：
  Tier 2 股票在同族群中，Tier 1 龍頭也觸發強缺貨（score≥4）→ +1
  → 最終 score 上限 6，grade 升至「龍頭瀑布」

建議閾值：
  score >= 5 → 龍頭瀑布（Tier2最強訊號）⚡
  score == 4 → 強缺貨    🔴
  score == 3 → 潛在缺貨  🟠
  score == 2 → 觀察中    🟡
  score <= 1 → 不符合    —
"""
from dataclasses import dataclass, field
import pandas as pd

# ── 供應鏈族群分層表 ──────────────────────────────────────────────────────────
# 格式：{族群名: {"tier1": [...], "tier2": [...]}}
# Tier 1 = 龍頭股（產能滿載時訂單外溢）
# Tier 2 = 二線業者（受益於訂單轉移，彈性更大）

SUPPLY_CHAIN: dict[str, dict[str, list[str]]] = {
    "晶圓代工": {
        "tier1": ["2330"],                          # 台積電
        "tier2": ["2303", "5347", "3034"],          # 聯電/世界先進/台灣美光
    },
    "IC封測": {
        "tier1": ["2454"],                          # 聯發科(設計→帶動封測)
        "tier2": ["2449", "3711", "6147", "8163"],  # 京元電/日月光/頎邦/矽格
    },
    "AI伺服器/ODM": {
        "tier1": ["2382", "3231"],                  # 廣達/緯創
        "tier2": ["4938", "6515", "3017", "3019"],  # 和碩/英業達/奇鋐/富瑩
    },
    "AI散熱": {
        "tier1": ["6669"],                          # 緯穎（伺服器散熱龍頭）
        "tier2": ["3296", "4419", "8936", "3317"],  # 亞泰/新光鋼/特力/訊凱
    },
    "AI PCB/ABF基板": {
        "tier1": ["3037"],                          # 欣興
        "tier2": ["8046", "3044", "6274", "2382"],  # 南電/健鼎/台燿/廣達
    },
    "AI電源/被動元件": {
        "tier1": ["2327"],                          # 國巨
        "tier2": ["6409", "1504", "2492", "3003"],  # 旭隼/正隆/華新科/昱捷
    },
    "AI記憶體/HBM": {
        "tier1": ["2330"],                          # 台積電 HBM 封裝
        "tier2": ["3474", "4960", "5483", "8150"],  # 華亞科/力成/南茂/南電
    },
    "網路/交換器": {
        "tier1": ["2454"],                          # 聯發科（網路晶片）
        "tier2": ["3045", "2345", "6415"],          # 台灣大/智邦/和欣
    },
    "面板/顯示IC": {
        "tier1": ["2408"],                          # 友達
        "tier2": ["3034", "4961", "3014", "2049"],  # 聯詠/天鈺/聯陽/上銀
    },
    "傳統貨運/海運": {
        "tier1": ["2603"],                          # 長榮
        "tier2": ["2609", "2615", "2637"],          # 陽明/萬海/慧洋-KY
    },
    "鋼鐵": {
        "tier1": ["2002"],                          # 中鋼
        "tier2": ["2006", "2015", "2022"],          # 東和鋼鐵/豐興/中鴻
    },
    "成衣/紡織": {
        "tier1": ["1477"],                          # 聚陽
        "tier2": ["1440", "1476", "1514"],          # 南紡/儒鴻/台達化
    },
}

# 展平：symbol → {tier, sectors}
_SYMBOL_META: dict[str, dict] = {}
for _sector, _tiers in SUPPLY_CHAIN.items():
    for _tier_name, _syms in _tiers.items():
        for _s in _syms:
            if _s not in _SYMBOL_META:
                _SYMBOL_META[_s] = {"tier": _tier_name, "sectors": []}
            _SYMBOL_META[_s]["sectors"].append(_sector)

# Flat sector list (backward-compat with existing code)
SUPPLY_CHAIN_MAP: dict[str, list[str]] = {
    sector: d["tier1"] + d["tier2"]
    for sector, d in SUPPLY_CHAIN.items()
}

# Tier 1 set for fast lookup
_TIER1_SYMBOLS: set[str] = {
    s for d in SUPPLY_CHAIN.values() for s in d["tier1"]
}


@dataclass
class ShortageSignal:
    symbol: str
    name: str
    latest_period: str          # "YYYY-MM"
    latest_yoy: float           # %
    prev_yoy: float | None      # % (month prior)
    acceleration: float | None  # latest_yoy - prev_yoy
    consecutive_above_20: int   # months with YoY > 20% (consecutive from latest)
    revenue_new_high: bool      # latest revenue = 12-month high
    score: int                  # 1–6 (6 = cascade bonus)
    grade: str                  # 龍頭瀑布/強缺貨/潛在缺貨/觀察中/不符合
    tier: str = ""              # "tier1" | "tier2" | ""
    sectors: list[str] = field(default_factory=list)
    revenue_trend: list[float] = field(default_factory=list)
    yoy_trend: list[float | None] = field(default_factory=list)
    cascade_bonus: bool = False  # True if Tier1 peer also triggered


def detect_shortage(
    symbol: str,
    name: str,
    revenue_df: pd.DataFrame,
) -> "ShortageSignal | None":
    """
    Compute shortage signal from monthly revenue DataFrame.
    Columns required: period (YYYY-MM), revenue (float), yoy (float|NaN).
    Returns None if < 2 months with valid YoY.
    """
    if revenue_df.empty:
        return None

    df = revenue_df.dropna(subset=["yoy"]).copy()
    if len(df) < 2:
        return None

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    latest_yoy: float = float(latest["yoy"])
    prev_yoy: float = float(prev["yoy"])
    acceleration: float = latest_yoy - prev_yoy

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

    # Base scoring
    score = 0
    if latest_yoy >= 10:
        score += 1
    if latest_yoy >= 20:
        score += 1
    if acceleration > 0:
        score += 1
    if consecutive_above_20 >= 3:
        score += 1
    if revenue_new_high:
        score += 1
    score = max(1, min(5, score))

    meta = _SYMBOL_META.get(symbol, {})
    tier = meta.get("tier", "")
    sectors = meta.get("sectors", [])

    grade = _grade(score, cascade=False)

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
        tier=tier,
        sectors=sectors,
        revenue_trend=revenue_df["revenue"].tail(4).tolist(),
        yoy_trend=revenue_df["yoy"].tail(4).tolist(),
    )


def _grade(score: int, cascade: bool) -> str:
    if cascade and score >= 5:
        return "龍頭瀑布"
    if score >= 4:
        return "強缺貨"
    if score == 3:
        return "潛在缺貨"
    if score == 2:
        return "觀察中"
    return "不符合"


def apply_cascade_bonus(signals: list[ShortageSignal]) -> list[ShortageSignal]:
    """
    「龍頭報喜，概念股全上揚」（第六章）：
    若 Tier 1 龍頭股在同族群已達強缺貨（score≥4），
    同族群 Tier 2 股票加 +1 分（上限 6），grade 升至「龍頭瀑布」。
    Mutates signals in-place, also returns the list.
    """
    # Build set of sectors where Tier1 is already strong
    tier1_hot_sectors: set[str] = set()
    for sig in signals:
        if sig.tier == "tier1" and sig.score >= 4:
            tier1_hot_sectors.update(sig.sectors)

    for sig in signals:
        if sig.tier == "tier2":
            overlap = set(sig.sectors) & tier1_hot_sectors
            if overlap:
                sig.cascade_bonus = True
                sig.score = min(6, sig.score + 1)
                sig.grade = _grade(sig.score, cascade=True)

    return signals


def rank_signals(signals: list[ShortageSignal]) -> list[ShortageSignal]:
    """Sort: cascade_bonus desc → score desc → latest_yoy desc."""
    return sorted(
        signals,
        key=lambda s: (s.cascade_bonus, s.score, s.latest_yoy),
        reverse=True,
    )


def find_clusters(signals: list[ShortageSignal]) -> dict[str, list[str]]:
    """
    Return sectors where >= 2 shortage signals co-occur (score >= 3).
    Returns {sector: [symbol, ...]}
    """
    sector_hits: dict[str, list[str]] = {}
    for sig in signals:
        if sig.score < 3:
            continue
        for sec in sig.sectors:
            sector_hits.setdefault(sec, []).append(sig.symbol)
    return {k: v for k, v in sector_hits.items() if len(v) >= 2}
