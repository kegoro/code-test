"""FinMind 財報抓取：損益表、資產負債表、現金流量表。"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from loguru import logger

from .client import finmind


def _start(years: int) -> str:
    return (date.today() - timedelta(days=years * 365 + 30)).isoformat()


async def fetch_income_statement(symbol: str, years: int = 5) -> pd.DataFrame:
    df = await finmind.query("TaiwanStockFinancialStatements", symbol, _start(years))
    if df.empty:
        logger.warning(f"[fundamental] {symbol} 損益表為空")
    return df


async def fetch_balance_sheet(symbol: str, years: int = 5) -> pd.DataFrame:
    df = await finmind.query("TaiwanStockBalanceSheet", symbol, _start(years))
    if df.empty:
        logger.warning(f"[fundamental] {symbol} 資產負債表為空")
    return df


async def fetch_cash_flow(symbol: str, years: int = 5) -> pd.DataFrame:
    df = await finmind.query("TaiwanStockCashFlowsStatement", symbol, _start(years))
    if df.empty:
        logger.warning(f"[fundamental] {symbol} 現金流量表為空")
    return df


async def fetch_dividend(symbol: str, years: int = 5) -> pd.DataFrame:
    return await finmind.query("TaiwanStockDividend", symbol, _start(years))


def pivot_statement(df: pd.DataFrame) -> pd.DataFrame:
    """把 FinMind 的長格式 (date,type,value) 轉成寬格式 (date × type)。"""
    if df.empty or not {"date", "type", "value"}.issubset(df.columns):
        return pd.DataFrame()
    wide = df.pivot_table(
        index="date", columns="type", values="value", aggfunc="first"
    )
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()
