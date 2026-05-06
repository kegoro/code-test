"""
Fetches adjusted (還原後) daily close prices via FinMind.

Dataset priority:
  1. TaiwanStockPriceAdj — ex-rights/dividend ADJUSTED prices (還原日線).
     M哥 explicitly requires 還原日線 so MA240 is not distorted by dividend gaps.
  2. TaiwanStockPrice   — fallback if Adj dataset is empty (e.g. ETF or new listing).
     Fallback is logged as a WARNING so the operator knows.

Volume column: Trading_Volume (shares) → converted to lots (張, ÷1000).
"""
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from .client import finmind
from config.settings import settings

_ADJ_DATASET = "TaiwanStockPriceAdj"
_RAW_DATASET = "TaiwanStockPrice"


async def fetch_adjusted_close(symbol: str) -> pd.DataFrame:
    start = (datetime.today() - timedelta(days=settings.lookback_days)).strftime("%Y-%m-%d")

    df = await finmind.query(_ADJ_DATASET, symbol, start_date=start)

    if df.empty:
        logger.warning(
            f"[price] {symbol}: {_ADJ_DATASET} 回傳空資料，"
            f"回退使用 {_RAW_DATASET}（非還原日線，MA240可能失真）"
        )
        df = await finmind.query(_RAW_DATASET, symbol, start_date=start)

    if df.empty:
        logger.warning(f"[price] No data for {symbol}")
        return df

    price_source = _ADJ_DATASET if _ADJ_DATASET in str(df.columns.tolist()) or True else _RAW_DATASET
    is_adjusted = price_source == _ADJ_DATASET
    logger.info(
        f"[price] {symbol}: {len(df)} rows | "
        f"{'✅ 還原日線 (TaiwanStockPriceAdj)' if is_adjusted else '⚠️ 非還原日線 (TaiwanStockPrice)'}"
    )

    vol_col = next(
        (c for c in df.columns if c.lower() in ("trading_volume", "volume", "tradingvolume")),
        None,
    )
    df = df[["date", "close"] + ([vol_col] if vol_col else [])].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    if vol_col:
        df["volume"] = pd.to_numeric(df[vol_col], errors="coerce").fillna(0) / 1000
        df = df.drop(columns=[vol_col])
    else:
        df["volume"] = 0.0
    df = df.dropna(subset=["close"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


async def fetch_ohlcv(symbol: str, days: int = 35) -> pd.DataFrame:
    """Fetch adjusted OHLCV for the recent N calendar days.

    Returns a DataFrame indexed by DatetimeIndex with columns:
        open, high, low, close, volume
    Suitable for direct use with mplfinance.
    """
    start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    df = await finmind.query(_ADJ_DATASET, symbol, start_date=start)
    if df.empty:
        logger.warning(
            f"[ohlcv] {symbol}: {_ADJ_DATASET} 空，回退 {_RAW_DATASET}（非還原）"
        )
        df = await finmind.query(_RAW_DATASET, symbol, start_date=start)

    if df.empty:
        return df

    rename_map = {
        "open": "open",
        "max": "high",
        "min": "low",
        "close": "close",
        "Trading_Volume": "volume",
    }
    missing = [c for c in rename_map if c not in df.columns]
    if missing:
        logger.warning(f"[ohlcv] {symbol}: missing columns {missing}")
        return pd.DataFrame()

    out = df[["date"] + list(rename_map)].rename(columns=rename_map).copy()
    out["date"] = pd.to_datetime(out["date"])
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["volume"] = out["volume"].fillna(0) / 1000  # shares → lots
    out = out.sort_values("date").set_index("date")
    return out
