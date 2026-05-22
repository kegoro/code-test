"""AI 分析編排器 — 拉資料、呼叫 5 個 scorer、組裝 AIAnalysisResult。

把 cmd_ai_analyse 從 smc_bot 抽出來的 pure-async 函式，方便：
  - Telegram bot 呼叫
  - 將來的 batch 排程
  - 單元測試（mock scorers）

每個 scorer 失敗或回 None 時 → fallback 用 mock_dimension_scores 對應槽位。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import pandas as pd

from backend.ai_analysis_engine import (
    AIAnalysisResult,
    build_result,
    mock_dimension_scores,
)
from backend.ai_analysis_scorers import (
    score_chip,
    score_fundamental,
    score_news,
    score_technical,
    score_theme,
)
from backend.aistockmap_scraper import DailyDigest, fetch_daily as fetch_aistockmap_daily
from backend.shioaji_fetcher import shioaji_fetch_daily, shioaji_fetch_m3
from backend.smc_analyst.context import AnalysisContext, gather_context
from backend.ticker_name import lookup as lookup_ticker_name


logger = logging.getLogger("ai-analysis-orchestrator")


# aistockmap 抓一次很慢（~10s Playwright），module-level cache TTL 1 小時
_AISTOCKMAP_TTL_SECONDS = 3600
_aistockmap_cache: Optional[tuple[float, DailyDigest]] = None


async def _cached_aistockmap_digest() -> Optional[DailyDigest]:
    global _aistockmap_cache
    now = time.time()
    if _aistockmap_cache is not None:
        ts, cached = _aistockmap_cache
        if now - ts < _AISTOCKMAP_TTL_SECONDS:
            return cached
    try:
        digest = await fetch_aistockmap_daily()
        _aistockmap_cache = (now, digest)
        return digest
    except Exception as exc:
        logger.warning("aistockmap fetch failed: %s", exc)
        # 如果有舊 cache 就回舊的，至少不要全空
        return _aistockmap_cache[1] if _aistockmap_cache else None


async def _safe_fetch_daily(symbol: str) -> Optional[pd.DataFrame]:
    try:
        df = await shioaji_fetch_daily(symbol, lookback=64)
        return df if df is not None and not df.empty else None
    except Exception as exc:
        logger.warning("daily fetch failed for %s: %s", symbol, exc)
        return None


async def _safe_fetch_m3(symbol: str) -> Optional[pd.DataFrame]:
    try:
        df = await shioaji_fetch_m3(symbol)
        return df if df is not None and not df.empty else None
    except Exception as exc:
        logger.warning("m3 fetch failed for %s: %s", symbol, exc)
        return None


async def _safe_gather_context(symbol: str) -> Optional[AnalysisContext]:
    try:
        return await gather_context(symbol)
    except Exception as exc:
        logger.warning("gather_context failed for %s: %s", symbol, exc)
        return None


async def _resolve_scores(
    symbol: str,
    *,
    ctx: Optional[AnalysisContext],
    aistockmap_digest: Optional[DailyDigest],
) -> tuple[
    tuple[float, float, float, float, float],
    tuple[str, str, str, str, str],
]:
    """組裝完整 5 維度分數 + detail。每個 scorer 回 None → 用 mock fallback。

    回傳 (scores, details)，scores 順序 = (chip, tech, news, fund, theme)，
    details 同順序，是 scorer 的解釋字串（供 UI 點開明細用）。
    """
    mock_chip, mock_tech, mock_news, mock_fund, mock_theme = mock_dimension_scores(symbol)

    tech, tech_detail = score_technical(ctx)

    chip_r, news_r, fund_r, theme_r = await asyncio.gather(
        score_chip(symbol),
        score_news(symbol, digest=aistockmap_digest),
        score_fundamental(symbol),
        score_theme(symbol, digest=aistockmap_digest),
        return_exceptions=True,
    )

    def _unpack(result, label) -> tuple[Optional[float], str]:
        if isinstance(result, Exception):
            logger.warning("%s scorer raised: %s", label, result)
            return None, f"{label}: exception {result}"
        return result

    chip, chip_detail = _unpack(chip_r, "chip")
    news, news_detail = _unpack(news_r, "news")
    fund, fund_detail = _unpack(fund_r, "fundamental")
    theme, theme_detail = _unpack(theme_r, "theme")

    logger.info(
        "scorer detail for %s: %s | %s | %s | %s | %s",
        symbol, tech_detail, chip_detail, news_detail, fund_detail, theme_detail,
    )

    scores = (
        chip if chip is not None else mock_chip,
        tech if tech is not None else mock_tech,
        news if news is not None else mock_news,
        fund if fund is not None else mock_fund,
        theme if theme is not None else mock_theme,
    )
    details = (chip_detail, tech_detail, news_detail, fund_detail, theme_detail)
    return scores, details


async def analyse(symbol: str) -> AIAnalysisResult:
    """產生完整 AIAnalysisResult。K 線拉 Shioaji；context 拉 gather_context；
    aistockmap 走 1 小時 cache；5 維度逐項算分（失敗 fallback mock）。"""
    name = lookup_ticker_name(symbol)

    daily, m3, ctx, aistockmap = await asyncio.gather(
        _safe_fetch_daily(symbol),
        _safe_fetch_m3(symbol),
        _safe_gather_context(symbol),
        _cached_aistockmap_digest(),
    )

    scores, details = await _resolve_scores(
        symbol, ctx=ctx, aistockmap_digest=aistockmap,
    )
    return build_result(
        symbol=symbol,
        stock_name=name,
        daily_df=daily,
        m3_df=m3,
        scores=scores,
        details=details,
    )


__all__ = ["analyse"]
