"""AI 分析 5 維度評分函式（每個獨立、純函式、可單測）。

每個 score_xxx 接受所需的最小資料，回傳 (score: float [0, 100], detail: str)。
尚未實作的維度先回 (None, "TODO Step N")；orchestrator 收到 None 會用 mock fallback。

對應任務：
  - score_technical → Step 3（本檔已實作）
  - score_chip       → Step 4
  - score_news       → Step 5
  - score_fundamental → Step 6
  - score_theme      → Step 7
"""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Optional

import pandas as pd

from backend.aistockmap_scraper import DailyDigest
from backend.finmind_chip import fetch_institutional
from backend.finmind_fundamental import (
    fetch_financial_statements,
    fetch_monthly_revenue,
)
from backend.smc_analyst.context import AnalysisContext
from backend.smc_analyst.setups import ALL_SETUPS
from backend.smc_analyst.setups.base import SetupMatch
from backend.theme_filter import filter_focus_items
from backend.ticker_name import lookup as lookup_ticker_name


logger = logging.getLogger("ai-analysis-scorers")


def _sigmoid_100(value: float, *, scale: float) -> float:
    """把帶正負的 net 量映射到 0-100，中心 50，±scale 約 73/27。

    使用 tanh，避免 sigmoid 極端飽和；結果鎖在 [15, 85] 範圍內保留辨識度。
    """
    if scale <= 0:
        return 50.0
    return max(15.0, min(85.0, 50.0 + 35.0 * math.tanh(value / scale)))


def _log_score_100(value: float, *, min_abs: float, max_abs: float) -> float:
    """對數尺度的買賣超 → 0-100 評分。

    |value| 在 (-min_abs, +min_abs) → 50（中性）
    |value| 達到 ±max_abs → ±35 → 15 或 85
    用 log10 縮放保證大型股不飽和、小型股仍有辨識度。
    """
    if max_abs <= min_abs <= 0:
        return 50.0
    abs_v = abs(value)
    if abs_v <= min_abs:
        # 線性過渡 0..min_abs → 0..(微幅偏移)
        return 50.0 + (value / max(min_abs, 1.0)) * 5.0
    # 對數區間
    log_min = math.log10(min_abs)
    log_max = math.log10(max_abs)
    log_v = math.log10(abs_v)
    t = min(1.0, (log_v - log_min) / max(log_max - log_min, 1e-9))
    return max(15.0, min(85.0, 50.0 + (35.0 if value > 0 else -35.0) * t))


# ── 技術面評分（Step 3） ──────────────────────────────────────────────────────

# 拆分配額（總和 100）
_TECH_PTS_SETUP: float = 40.0   # SMC 7-setup 最佳 match
_TECH_PTS_HTF: float = 25.0     # HTF 結構方向
_TECH_PTS_LTF: float = 20.0     # LTF 短線結構
_TECH_PTS_PD: float = 15.0      # Premium/Discount 位置


def _best_setup_match(ctx: AnalysisContext) -> Optional[SetupMatch]:
    """跑 ALL_SETUPS、取分數最高的 match。不過濾 hard gates / direction policy
    — 評分用要全資訊，跟 pipeline.analyse 的篩選邏輯分開。"""
    best: Optional[SetupMatch] = None
    for setup in ALL_SETUPS:
        try:
            m = setup.evaluate(ctx)
        except Exception:
            logger.exception("scorer: setup %s evaluate failed", setup.name)
            continue
        if m is None:
            continue
        if best is None or m.score > best.score:
            best = m
    return best


def _score_setup_component(match: Optional[SetupMatch]) -> float:
    """SetupMatch.score (0-15) → 0-_TECH_PTS_SETUP。沒命中 → 設保底 35%。"""
    if match is None:
        return _TECH_PTS_SETUP * 0.35
    s = max(0.0, min(15.0, float(match.score)))
    return (s / 15.0) * _TECH_PTS_SETUP


def _score_htf_component(htf_bias: str, direction: Optional[str]) -> float:
    """HTF 趨勢方向加分。direction 為當前 best setup 方向（無則中性）。"""
    if htf_bias == "bullish":
        # bullish HTF 對 long 是 full；對 short 是 0
        if direction == "short":
            return 0.0
        return _TECH_PTS_HTF
    if htf_bias == "bearish":
        if direction == "long":
            return 0.0
        return _TECH_PTS_HTF
    return _TECH_PTS_HTF * 0.5   # ranging → 中性


def _score_ltf_component(ltf_structure: str) -> float:
    """LTF 結構（bullish/bearish/ranging）對短線動能。"""
    if ltf_structure == "bullish":
        return _TECH_PTS_LTF
    if ltf_structure == "bearish":
        return _TECH_PTS_LTF * 0.2
    return _TECH_PTS_LTF * 0.5


def _score_pd_component(pd_zones: Optional[dict], last_close: float) -> float:
    """Discount = full、Equilibrium = half、Premium = 0。"""
    if not pd_zones or last_close <= 0:
        return _TECH_PTS_PD * 0.5
    discount = pd_zones.get("discount") or {}
    premium = pd_zones.get("premium") or {}
    if discount and last_close <= float(discount.get("top", float("inf"))):
        return _TECH_PTS_PD
    if premium and last_close >= float(premium.get("bottom", float("-inf"))):
        return 0.0
    return _TECH_PTS_PD * 0.5


def score_technical(ctx: Optional[AnalysisContext]) -> tuple[Optional[float], str]:
    """技術面評分（0-100）。

    組成：
      40% = 7-setup 最佳分數（線性映射 0-15 → 0-40）
      25% = HTF 趨勢方向（與 best setup direction 對齊才得分）
      20% = LTF 結構動能
      15% = Premium/Discount 位置（Discount 滿分）

    回傳 (score, detail)；ctx=None 時回 (None, "...")。
    """
    if ctx is None:
        return None, "technical: no context"

    best = _best_setup_match(ctx)
    setup_pts = _score_setup_component(best)
    htf_pts = _score_htf_component(
        ctx.htf_bias,
        direction=best.direction if best else None,
    )
    ltf_struct = ctx.ltf.structure.get("structure", "ranging")
    ltf_pts = _score_ltf_component(ltf_struct)
    pd_pts = _score_pd_component(ctx.pd_zones, ctx.last_close)

    total = setup_pts + htf_pts + ltf_pts + pd_pts
    total = max(0.0, min(100.0, total))

    setup_name = best.setup_name if best else "no-setup"
    detail = (
        f"setup={setup_pts:.0f}({setup_name}) "
        f"htf={htf_pts:.0f}({ctx.htf_bias}) "
        f"ltf={ltf_pts:.0f}({ltf_struct}) "
        f"pd={pd_pts:.0f}"
    )
    return total, detail


# ── 籌碼面評分（Step 4） ──────────────────────────────────────────────────────

# 三大法人加權（合計 1.0）
_CHIP_W_FOREIGN: float = 0.60
_CHIP_W_TRUST: float = 0.25
_CHIP_W_DEALER: float = 0.15

# Net buy / sell 標準化尺度（5 日累計 X 股 ≈ ±25 分）
# 用對數縮放避免大型股直接飽和；scale 是 tanh(log10(|x|/min_scale)) 的單位
# 對大型股（如台積電 5d 累計 30M）以及小型股（5d 累計 200K）都能保留辨識度
_CHIP_LOG_MIN: float = 100_000.0   # |net| 低於此值約得 50 分（中性）
_CHIP_LOG_MAX: float = 30_000_000.0  # |net| ≈ 此值得 ~85 分（飽和）

_FOREIGN_KEYS = {"Foreign_Investor", "Foreign_Investor_HKongClose",
                 "外資及陸資", "外資"}
_TRUST_KEYS = {"Investment_Trust", "投信"}


def _classify_institution(name: str) -> Optional[str]:
    """FinMind name 欄位 → 'foreign' / 'trust' / 'dealer' / None。"""
    if not name:
        return None
    if name in _FOREIGN_KEYS or "Foreign" in name or "外資" in name:
        return "foreign"
    if name in _TRUST_KEYS or "Trust" in name or "投信" in name:
        return "trust"
    if "Dealer" in name or "自營" in name:
        return "dealer"
    return None


def _sum_recent_net(df: pd.DataFrame, *, days: int = 5) -> dict[str, float]:
    """把近 N 個交易日的 buy-sell 依機構類別加總。

    Returns dict {"foreign": float, "trust": float, "dealer": float}。缺者填 0。
    """
    if df is None or df.empty:
        return {"foreign": 0.0, "trust": 0.0, "dealer": 0.0}

    cols = {c.lower(): c for c in df.columns}
    name_col = cols.get("name") or cols.get("type")
    buy_col = cols.get("buy")
    sell_col = cols.get("sell")
    if not name_col or not buy_col or not sell_col:
        logger.warning("chip: missing columns; got %s", list(df.columns))
        return {"foreign": 0.0, "trust": 0.0, "dealer": 0.0}

    # 取最後 N 個唯一日期
    if isinstance(df.index, pd.DatetimeIndex):
        latest_dates = sorted(df.index.unique())[-days:]
        recent = df.loc[df.index.isin(latest_dates)]
    else:
        recent = df.tail(days * 5)   # heuristic：4 法人 × N 天

    totals = {"foreign": 0.0, "trust": 0.0, "dealer": 0.0}
    for _, row in recent.iterrows():
        kind = _classify_institution(str(row[name_col]))
        if kind is None:
            continue
        try:
            net = float(row[buy_col]) - float(row[sell_col])
        except (TypeError, ValueError):
            continue
        totals[kind] += net
    return totals


async def score_chip(symbol: str) -> tuple[Optional[float], str]:
    """籌碼面評分（0-100）— 近 5 日三大法人累計買賣超。

    外資 60% / 投信 25% / 自營 15%；每項用 tanh 映射到 15-85。
    """
    df = await fetch_institutional(symbol, lookback_days=15)
    if df.empty:
        return None, "chip: no institutional data (FinMind empty/paywalled)"

    totals = _sum_recent_net(df, days=5)
    foreign_score = _log_score_100(
        totals["foreign"], min_abs=_CHIP_LOG_MIN, max_abs=_CHIP_LOG_MAX,
    )
    trust_score = _log_score_100(
        totals["trust"], min_abs=_CHIP_LOG_MIN, max_abs=_CHIP_LOG_MAX * 0.3,
    )
    dealer_score = _log_score_100(
        totals["dealer"], min_abs=_CHIP_LOG_MIN, max_abs=_CHIP_LOG_MAX * 0.5,
    )

    score = (
        foreign_score * _CHIP_W_FOREIGN
        + trust_score * _CHIP_W_TRUST
        + dealer_score * _CHIP_W_DEALER
    )
    score = max(0.0, min(100.0, score))
    detail = (
        f"foreign={totals['foreign']:,.0f}({foreign_score:.0f}) "
        f"trust={totals['trust']:,.0f}({trust_score:.0f}) "
        f"dealer={totals['dealer']:,.0f}({dealer_score:.0f})"
    )
    return score, detail


# ── 新聞面評分（Step 5） ──────────────────────────────────────────────────────

def _count_direct_hits(symbol: str, name: str, digest: DailyDigest) -> int:
    """股號或股名直接出現在題材標題/描述的次數。"""
    n = 0
    name_meaningful = bool(name and name != symbol and len(name) >= 2)
    for item in digest.focus_items:
        text = f"{item.title} {item.description}"
        if symbol and symbol in text:
            n += 1
            continue
        if name_meaningful and name in text:
            n += 1
    return n


def _market_news_baseline(digest: DailyDigest) -> float:
    """大盤新聞情緒 baseline：題材通過雷老闆 A/B 過濾的比例 → 50-70。"""
    items = digest.focus_items
    if not items:
        return 50.0
    filtered = filter_focus_items(items)
    passed = sum(1 for f in filtered if f.passed)
    ratio = passed / len(items)
    return 50.0 + ratio * 20.0   # 0% 命中 → 50；100% 命中 → 70


async def score_news(
    symbol: str,
    *,
    digest: Optional[DailyDigest] = None,
) -> tuple[Optional[float], str]:
    """新聞面評分（0-100）。

    組成：
      direct_hits >= 2 → 90
      direct_hits == 1 → max(75, baseline + 15)
      direct_hits == 0 → baseline（50-70 由當日大盤命中率決定）

    digest 由 orchestrator 傳入（cache 過避免重複拉 Playwright）。
    """
    if digest is None:
        return None, "news: no aistockmap digest"

    name = lookup_ticker_name(symbol)
    direct = _count_direct_hits(symbol, name, digest)
    baseline = _market_news_baseline(digest)

    if direct >= 2:
        score = 90.0
    elif direct == 1:
        score = max(75.0, baseline + 15.0)
    else:
        score = baseline

    score = max(0.0, min(100.0, score))
    items_total = len(digest.focus_items)
    return score, f"direct_hits={direct} baseline={baseline:.0f} themes={items_total}"


# ── 基本面評分（Step 6） ──────────────────────────────────────────────────────


def _avg_yoy(rev_df: pd.DataFrame, *, months: int = 6) -> Optional[float]:
    """取近 N 個月月營收 YoY（%）平均。

    FinMind TaiwanStockMonthRevenue 沒有現成 YoY 欄位，自己用 (revenue_year,
    revenue_month) 對齊 12 個月前的 revenue 算。資料不足 12 個月 → None。
    """
    if rev_df is None or rev_df.empty:
        return None
    cols = {c.lower(): c for c in rev_df.columns}
    rev_col = cols.get("revenue")
    y_col = cols.get("revenue_year")
    m_col = cols.get("revenue_month")
    if not rev_col or not y_col or not m_col:
        return None

    # 建立 (year, month) → revenue 的對照表
    rev_map: dict[tuple[int, int], float] = {}
    for _, row in rev_df.iterrows():
        try:
            y = int(row[y_col])
            m = int(row[m_col])
            v = float(row[rev_col])
        except (TypeError, ValueError):
            continue
        if v > 0:
            rev_map[(y, m)] = v

    if not rev_map:
        return None

    keys = sorted(rev_map.keys())[-months:]
    yoy_values: list[float] = []
    for y, m in keys:
        prev = rev_map.get((y - 1, m))
        if prev is None or prev <= 0:
            continue
        yoy_values.append((rev_map[(y, m)] / prev - 1.0) * 100.0)

    if not yoy_values:
        return None
    return sum(yoy_values) / len(yoy_values)


def _yoy_to_score(yoy: float) -> float:
    """月營收 YoY% → 0-100 分。

    >= +50%   → 90
    +20~+50%  → 75
    0~+20%    → 60
    -20~0%    → 40
    -50~-20%  → 25
    <= -50%   → 10
    """
    if yoy >= 50:
        return 90.0
    if yoy >= 20:
        return 75.0
    if yoy >= 0:
        return 60.0
    if yoy >= -20:
        return 40.0
    if yoy >= -50:
        return 25.0
    return 10.0


def _latest_eps(fin_df: pd.DataFrame) -> Optional[float]:
    """從 FinancialStatements 取最新一季 EPS。

    FinMind type 欄位可能是 'EPS' / 'eps' / 'BasicEPS'。
    """
    if fin_df is None or fin_df.empty:
        return None
    type_col = next((c for c in fin_df.columns if c.lower() in ("type",)), None)
    val_col = next((c for c in fin_df.columns if c.lower() in ("value",)), None)
    if not type_col or not val_col:
        return None
    mask = fin_df[type_col].astype(str).str.lower().str.contains("eps")
    eps_rows = fin_df[mask].sort_index().tail(1)
    if eps_rows.empty:
        return None
    try:
        return float(eps_rows[val_col].iloc[0])
    except (TypeError, ValueError):
        return None


def _eps_bonus(eps: float) -> float:
    """最新一季 EPS 加分（最多 +10，最低 -10）。"""
    if eps >= 5:
        return 10.0
    if eps >= 2:
        return 5.0
    if eps >= 0:
        return 0.0
    if eps >= -2:
        return -5.0
    return -10.0


async def score_fundamental(symbol: str) -> tuple[Optional[float], str]:
    """基本面評分（0-100）— 月營收 YoY 為主，EPS 微調。

    UI 上是「參考」維度（不入加權），但仍想盡量真實。
    """
    rev_df, fin_df = await asyncio.gather(
        fetch_monthly_revenue(symbol),
        fetch_financial_statements(symbol),
        return_exceptions=True,
    )
    if isinstance(rev_df, Exception):
        rev_df = pd.DataFrame()
    if isinstance(fin_df, Exception):
        fin_df = pd.DataFrame()

    yoy = _avg_yoy(rev_df, months=6)
    if yoy is None:
        return None, f"fundamental: no monthly revenue YoY (cols={list(rev_df.columns)[:6]})"

    base = _yoy_to_score(yoy)
    eps = _latest_eps(fin_df)
    bonus = _eps_bonus(eps) if eps is not None else 0.0

    score = max(0.0, min(100.0, base + bonus))
    return score, (
        f"yoy={yoy:+.1f}% base={base:.0f}"
        + (f" eps={eps:+.2f} bonus={bonus:+.1f}" if eps is not None else " eps=NA")
    )


# ── 題材面評分（Step 7） ──────────────────────────────────────────────────────


def _theme_strength(digest: DailyDigest) -> float:
    """大盤題材氛圍 baseline。industry_cards / focus_items 多 + 雷老闆原則命中
    類別越多 → 題材氛圍越熱。映射到 35-70。"""
    items = digest.focus_items
    if not items:
        return 35.0
    filtered = filter_focus_items(items)
    avg_categories = sum(f.score for f in filtered) / len(filtered)  # 0-5
    cards = len(digest.industry_cards)
    # 三個訊號加總：題材數 / cards 數 / 平均原則類別命中
    heat = 35.0 + min(15.0, len(items) * 2.0)            # 35..65
    heat += min(10.0, cards * 0.5)                         # +0..10
    heat += min(10.0, avg_categories * 3.0)                # +0..10
    return min(85.0, heat)


async def score_theme(
    symbol: str,
    *,
    digest: Optional[DailyDigest] = None,
) -> tuple[Optional[float], str]:
    """題材面評分（0-100）— 與「新聞面」不同視角：

    新聞面看的是「該股是否被當日新聞報導」（事件驅動）。
    題材面看的是「該股所屬題材在當日是否熱」（結構驅動）。

    aistockmap 個股 mapping Premium 鎖定，所以本維度暫用：
      - title 嚴格命中（symbol 或股名出現在 focus_item.title）→ 強加分
      - 否則用大盤題材氛圍 baseline（題材數 + cards 數 + 平均命中類別）

    UI 上是「參考」維度（不入加權），但仍提供有意義的相對訊號。
    """
    if digest is None:
        return None, "theme: no aistockmap digest"

    name = lookup_ticker_name(symbol)
    name_meaningful = bool(name and name != symbol and len(name) >= 2)

    title_hits = 0
    for it in digest.focus_items:
        title = it.title or ""
        if symbol and symbol in title:
            title_hits += 1
            continue
        if name_meaningful and name in title:
            title_hits += 1

    market_heat = _theme_strength(digest)

    if title_hits >= 2:
        score = 90.0
    elif title_hits == 1:
        score = max(80.0, market_heat + 10.0)
    else:
        score = market_heat

    score = max(0.0, min(100.0, score))
    return score, f"title_hits={title_hits} market_heat={market_heat:.0f}"


__all__ = [
    "score_technical",
    "score_chip",
    "score_news",
    "score_fundamental",
    "score_theme",
]
