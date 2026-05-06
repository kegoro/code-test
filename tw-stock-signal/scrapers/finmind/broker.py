"""
券商買賣超資料 (Broker trade summary)
Dataset: TaiwanStockBrokerTradeSummary
"""
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from .client import finmind


async def fetch_broker(symbol: str, days: int = 60) -> pd.DataFrame:
    """
    Returns DataFrame with columns:
      date, broker_id, broker_name, buy, sell, net, buy_price, sell_price
    Sorted ascending by date.
    """
    start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = await finmind.query("TaiwanStockBrokerTradeSummary", symbol, start_date=start)

    if df.empty:
        logger.warning(f"[broker] No data for {symbol}")
        return pd.DataFrame(columns=["date", "broker_id", "broker_name", "buy", "sell", "net", "buy_price", "sell_price"])

    df["date"] = pd.to_datetime(df["date"])

    for col in ("buy", "sell"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    for col in ("buy_price", "sell_price"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0.0

    df["net"] = df["buy"] - df["sell"]

    name_col = next((c for c in ("broker_name", "BrokerName", "name") if c in df.columns), None)
    id_col = next((c for c in ("broker_id", "BrokerID", "broker_id") if c in df.columns), None)

    rename = {}
    if name_col and name_col != "broker_name":
        rename[name_col] = "broker_name"
    if id_col and id_col != "broker_id":
        rename[id_col] = "broker_id"
    if rename:
        df = df.rename(columns=rename)

    if "broker_name" not in df.columns:
        df["broker_name"] = df.get("broker_id", "未知")
    if "broker_id" not in df.columns:
        df["broker_id"] = ""

    keep = ["date", "broker_id", "broker_name", "buy", "sell", "net", "buy_price", "sell_price"]
    keep = [c for c in keep if c in df.columns]
    df = df[keep].sort_values("date").reset_index(drop=True)
    logger.info(f"[broker] {symbol}: {len(df)} rows")
    return df
