"""
Taiwan Weighted Index (TAIEX) daily close prices.
Dataset: TaiwanStockPrice with data_id = "TAIEX"
Used for: detecting contrarian foreign buy on weak market days.
"""
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from .client import finmind


async def fetch_taiex(days: int = 30) -> pd.DataFrame:
    """
    Returns DataFrame [date, taiex_close, taiex_pct_change] sorted ascending.
    taiex_pct_change: daily % change of the index (e.g. -0.015 = -1.5%).
    """
    start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = await finmind.query("TaiwanStockPrice", "TAIEX", start_date=start)

    if df.empty:
        logger.warning("[market_index] No TAIEX data")
        return pd.DataFrame(columns=["date", "taiex_close", "taiex_pct_change"])

    df["date"] = pd.to_datetime(df["date"])
    df["taiex_close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df[["date", "taiex_close"]].sort_values("date").reset_index(drop=True)
    df["taiex_pct_change"] = df["taiex_close"].pct_change()
    logger.info(f"[market_index] TAIEX: {len(df)} rows")
    return df
