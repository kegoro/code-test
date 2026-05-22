"""FinMind 籌碼面資料 fetcher（三大法人買賣超 + 集中度 + 融資融券）。

Endpoints (v4)：
  - TaiwanStockInstitutionalInvestorsBuySell  三大法人買賣超（buy/sell 股數）
  - TaiwanStockShareholding                   持股分級（集中度）
  - TaiwanStockMarginPurchaseShortSale        融資融券

回傳格式統一為 `pd.DataFrame`，index = 日期（pd.DatetimeIndex），columns 因 dataset 而異。
失敗（包含 paywall / 沒 token）回 empty DataFrame，呼叫端自行判空。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import pandas as pd

from backend.finmind_fetcher import (
    FinMindPaywallError,
    _request_json,
    _to_iso,
    _token,
)


logger = logging.getLogger("finmind-chip")


# ── 共用 helper ──────────────────────────────────────────────────────────────

async def _fetch_dataset(
    dataset: str,
    symbol: str,
    *,
    lookback_days: int,
) -> pd.DataFrame:
    """通用 dataset 拉取。"""
    start = (datetime.now() - timedelta(days=lookback_days)).date()
    params: dict[str, str] = {
        "dataset": dataset,
        "data_id": symbol,
        "start_date": _to_iso(start),
    }
    tok = _token()
    if tok:
        params["token"] = tok

    try:
        payload = await _request_json(params)
    except FinMindPaywallError:
        logger.warning("FinMind %s paywalled for free tier", dataset)
        return pd.DataFrame()
    except Exception as exc:
        logger.warning("FinMind %s fetch failed for %s: %s", dataset, symbol, exc)
        return pd.DataFrame()

    rows = payload.get("data") or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
    return df


# ── public API ────────────────────────────────────────────────────────────────

async def fetch_institutional(symbol: str, *, lookback_days: int = 20) -> pd.DataFrame:
    """三大法人買賣超。每日多 row（外資/投信/自營商）。

    Columns（FinMind 標準）：
      stock_id / name / buy / sell / 其他依 dataset 版本
    name 值通常為：
      - Foreign_Investor
      - Investment_Trust
      - Dealer_self / Dealer_Hedging
    """
    return await _fetch_dataset(
        "TaiwanStockInstitutionalInvestorsBuySell",
        symbol,
        lookback_days=lookback_days,
    )


async def fetch_shareholding(symbol: str, *, lookback_days: int = 60) -> pd.DataFrame:
    """持股分級（集中度趨勢）。FinMind 大約週更，所以 lookback 拉寬一點。"""
    return await _fetch_dataset(
        "TaiwanStockShareholding",
        symbol,
        lookback_days=lookback_days,
    )


async def fetch_margin(symbol: str, *, lookback_days: int = 20) -> pd.DataFrame:
    """融資融券。"""
    return await _fetch_dataset(
        "TaiwanStockMarginPurchaseShortSale",
        symbol,
        lookback_days=lookback_days,
    )


__all__ = [
    "fetch_institutional",
    "fetch_shareholding",
    "fetch_margin",
]
