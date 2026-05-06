"""
三大法人買賣超 (Institutional net buy/sell)
Dataset: TaiwanStockInstitutionalInvestorsBuySell
Columns kept: date, name (外資/投信/自營商), buy, sell, diff (net)
"""
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from .client import finmind


async def fetch_institutional(symbol: str, days: int = 30) -> pd.DataFrame:
    start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = await finmind.query(
        "TaiwanStockInstitutionalInvestorsBuySell", symbol, start_date=start
    )

    if df.empty:
        logger.warning(f"[institutional] No data for {symbol}")
        return df

    df["date"] = pd.to_datetime(df["date"])
    df["buy"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0)
    df["sell"] = pd.to_numeric(df["sell"], errors="coerce").fillna(0)
    df["net"] = df["buy"] - df["sell"]

    # Normalize English → Chinese names used by chip.py filters
    _NAME_MAP = {
        "Foreign_Investor":    "外資",
        "Foreign_Dealer_Self": "外資自營",
        "Investment_Trust":    "投信",
        "Dealer_self":         "自營商",
        "Dealer_Hedging":      "自營商避險",
    }
    if "name" in df.columns:
        df["name"] = df["name"].replace(_NAME_MAP)

    df = df.sort_values("date").reset_index(drop=True)
    logger.info(f"[institutional] {symbol}: {len(df)} rows")
    return df
