"""AI 趨勢分析引擎 — 5 維度評分計算（先用 mock，逐步接真實資料）。

對應 LESSONS §2.7（當沖題材白名單）+ §2.8（SMC 可信 setup）+ 雷老闆 5 原則。

5 維度 + 權重（對應使用者提供的 UI 截圖）：
  - 籌碼面 45%  → FinMind 三大法人 / 集中度 / 融資融券（TODO 接資料）
  - 技術面 35%  → SMC pipeline N-Pattern + EMA/RSI/量價（TODO 部份接資料）
  - 新聞面 20%  → aistockmap 題材熱度 + 新聞情緒（TODO 接資料）
  - 基本面（參考，不入加權）→ FinMind 月營收 / 毛利率 / EPS（TODO）
  - 題材面（參考，不入加權）→ aistockmap 題材分類（TODO）

設計目標：先把資料管道 + UI 跑通，數據都先回固定 mock，之後逐項換掉。
評分 0-100，整體分為 偏多 ≥ 65、中性 35-65、偏空 < 35。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd


logger = logging.getLogger("ai-analysis-engine")


# ── 維度權重（影響整體 score；參考維度權重設 0） ──────────────────────────────

_WEIGHT_CHIP: float = 0.45
_WEIGHT_TECH: float = 0.35
_WEIGHT_NEWS: float = 0.20
# 基本面 + 題材面：UI 顯示「參考」，不計入加權

_OVERALL_BULL: float = 65.0
_OVERALL_BEAR: float = 35.0


@dataclass(frozen=True)
class DimensionScore:
    """單一維度評分。score 範圍 0-100。"""
    score: float
    weight_pct: int        # 顯示用整數百分比（45 / 35 / 20 / 0）
    is_reference: bool     # True 時 UI 顯示「參考」字樣 + 灰色
    detail: str = ""       # 可選：詳細說明（hover 用，先不顯示）


@dataclass(frozen=True)
class AIAnalysisResult:
    """完整分析結果。supplied to HTML renderer."""
    symbol: str
    stock_name: str
    last_close: float
    pct_change_daily: float            # 近 3 個月期間變化 %
    overall_score: float               # 加權整體分數（0-100）
    overall_verdict: str               # "偏多" / "中性" / "偏空"
    chip: DimensionScore
    technical: DimensionScore
    news: DimensionScore
    fundamental: DimensionScore        # is_reference=True
    theme: DimensionScore              # is_reference=True
    analysed_at: datetime
    daily_df: Optional[pd.DataFrame] = field(default=None, repr=False)   # 3 個月日線
    m3_df: Optional[pd.DataFrame] = field(default=None, repr=False)      # 當日 M3 盤中


def _verdict(score: float) -> str:
    if score >= _OVERALL_BULL:
        return "偏多"
    if score <= _OVERALL_BEAR:
        return "偏空"
    return "中性"


def _compute_overall(
    chip: float, technical: float, news: float
) -> float:
    """加權平均（基本面/題材面為參考，不入計算）。"""
    return chip * _WEIGHT_CHIP + technical * _WEIGHT_TECH + news * _WEIGHT_NEWS


def _pct_change_window(daily_df: Optional[pd.DataFrame]) -> float:
    """3 個月期間的累計變化 %。資料不足回 0。"""
    if daily_df is None or len(daily_df) < 2:
        return 0.0
    first = float(daily_df["close"].iloc[0])
    last = float(daily_df["close"].iloc[-1])
    if first <= 0:
        return 0.0
    return (last / first - 1.0) * 100.0


def mock_dimension_scores(symbol: str) -> tuple[float, float, float, float, float]:
    """5 維度的 mock 分數，供尚未實作真實 scorer 的維度 fallback。

    Symbol-aware 簡單變化，方便視覺化多檔差異。
    回傳順序：(chip, tech, news, fund, theme)
    """
    seed = sum(ord(c) for c in symbol)
    chip = 60.0 + (seed % 35)                # 60-94
    tech = 55.0 + ((seed * 3) % 35)          # 55-89
    news = 60.0 + ((seed * 7) % 30)          # 60-89
    fund = 50.0 + ((seed * 11) % 40)         # 50-89
    theme = 50.0 + ((seed * 13) % 40)        # 50-89
    return chip, tech, news, fund, theme


# 舊名（向後相容，內部用）
_mock_dimension_scores = mock_dimension_scores


def build_result(
    *,
    symbol: str,
    stock_name: str,
    daily_df: Optional[pd.DataFrame],
    m3_df: Optional[pd.DataFrame],
    scores: Optional[tuple[float, float, float, float, float]] = None,
    details: Optional[tuple[str, str, str, str, str]] = None,
) -> AIAnalysisResult:
    """組裝 AIAnalysisResult。

    Args:
      symbol: 股票代號（e.g. "4916"）
      stock_name: 股票名稱（e.g. "事欣科"）
      daily_df: 近 3 個月日線（index = timestamp，columns = open/high/low/close[/volume]）
      m3_df: 當日盤中 M3（同上，可為 None）
      scores: (chip, tech, news, fund, theme)；None 時用 mock
      details: 對應 5 維度的 scorer detail 字串（給 UI 點開展開用）；None 時用空字串
    """
    if scores is None:
        chip_s, tech_s, news_s, fund_s, theme_s = _mock_dimension_scores(symbol)
    else:
        chip_s, tech_s, news_s, fund_s, theme_s = scores

    if details is None:
        d_chip = d_tech = d_news = d_fund = d_theme = ""
    else:
        d_chip, d_tech, d_news, d_fund, d_theme = details

    overall = _compute_overall(chip_s, tech_s, news_s)

    last_close = 0.0
    if daily_df is not None and not daily_df.empty:
        last_close = float(daily_df["close"].iloc[-1])

    return AIAnalysisResult(
        symbol=symbol,
        stock_name=stock_name,
        last_close=last_close,
        pct_change_daily=_pct_change_window(daily_df),
        overall_score=round(overall, 1),
        overall_verdict=_verdict(overall),
        chip=DimensionScore(score=round(chip_s, 1), weight_pct=45, is_reference=False, detail=d_chip),
        technical=DimensionScore(score=round(tech_s, 1), weight_pct=35, is_reference=False, detail=d_tech),
        news=DimensionScore(score=round(news_s, 1), weight_pct=20, is_reference=False, detail=d_news),
        fundamental=DimensionScore(score=round(fund_s, 1), weight_pct=0, is_reference=True, detail=d_fund),
        theme=DimensionScore(score=round(theme_s, 1), weight_pct=0, is_reference=True, detail=d_theme),
        analysed_at=datetime.now(),
        daily_df=daily_df,
        m3_df=m3_df,
    )


__all__ = [
    "DimensionScore",
    "AIAnalysisResult",
    "build_result",
    "mock_dimension_scores",
]
