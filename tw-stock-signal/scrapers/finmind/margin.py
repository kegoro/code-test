"""
融資融券餘額 (Margin purchase / short sale balance)
Dataset: TaiwanStockMarginPurchaseShortSale
Columns kept: date, MarginPurchaseBuy, MarginPurchaseSell, MarginPurchaseBalance,
              ShortSaleBuy, ShortSaleSell, ShortSaleBalance
"""
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from .client import finmind


async def fetch_margin(symbol: str, days: int = 30) -> pd.DataFrame:
    start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = await finmind.query(
        "TaiwanStockMarginPurchaseShortSale", symbol, start_date=start
    )

    if df.empty:
        logger.warning(f"[margin] No data for {symbol}")
        return df

    logger.debug(f"[margin] {symbol} columns: {list(df.columns)}")
    df["date"] = pd.to_datetime(df["date"])
    for col in df.columns:
        if col != "date" and col not in ("stock_id", "Note"):
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Normalise to the column names expected by chip.py
    col_map = {
        "MarginPurchaseTodayBalance": "margin_balance",
        "ShortSaleTodayBalance":      "short_balance",
    }
    df = df.rename(columns=col_map)

    df = df.sort_values("date").reset_index(drop=True)
    logger.info(f"[margin] {symbol}: {len(df)} rows")
    return df
