"""FinMind 基本面資料 fetcher（月營收 + 財報）。

Endpoints (v4)：
  - TaiwanStockMonthRevenue       月營收（含 MoM/YoY）
  - TaiwanStockFinancialStatements 財報（每季 EPS / 毛利 / 淨利）

回傳統一 DataFrame，index = 日期。失敗回 empty。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from backend.finmind_chip import _fetch_dataset


logger = logging.getLogger("finmind-fundamental")


async def fetch_monthly_revenue(
    symbol: str,
    *,
    lookback_months: int = 18,
) -> pd.DataFrame:
    """月營收，最新在最後。

    預設 18 個月是因為要算 YoY（最近 6 個月 + 對應 12 個月前對比 = 至少 18 個月）。
    """
    return await _fetch_dataset(
        "TaiwanStockMonthRevenue",
        symbol,
        lookback_days=max(60, lookback_months * 31 + 15),
    )


async def fetch_financial_statements(
    symbol: str,
    *,
    lookback_days: int = 400,
) -> pd.DataFrame:
    """財報每季更新，預設拉一年多。每筆是 (date, type, value)。"""
    return await _fetch_dataset(
        "TaiwanStockFinancialStatements",
        symbol,
        lookback_days=lookback_days,
    )


__all__ = ["fetch_monthly_revenue", "fetch_financial_statements"]
