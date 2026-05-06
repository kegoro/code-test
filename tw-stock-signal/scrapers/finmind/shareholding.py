"""
股權分佈資料 (Shareholding distribution)
Dataset: TaiwanStockShareholding

Note: FinMind's TaiwanStockShareholding returns foreign investment quota data
(ForeignInvestmentSharesRatio), NOT bracket-level shareholding distribution
(持股分級). The columns required for 大戶持股比例 (HoldingSharesLevel,
HoldingSharesProportion, NumberOfShareholders) are not available on the free tier.

When the expected columns are absent, this function returns an empty DataFrame,
which triggers the exempt path in _shareholding_stats (major_holder_ratio = -1).
"""
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from .client import finmind

RETAIL_LEVEL = "1-999"
REQUIRED_COLS = {"HoldingSharesLevel", "HoldingSharesProportion", "NumberOfShareholders"}


async def fetch_shareholding(symbol: str, days: int = 180) -> pd.DataFrame:
    """
    Returns DataFrame with columns:
      date, major_holder_ratio (float 0-1), shareholder_count (int)
    Sorted ascending by date. One row per report date.
    Returns empty DataFrame when data is unavailable (triggers exempt in H5/B9).
    """
    empty = pd.DataFrame(columns=["date", "major_holder_ratio", "shareholder_count"])
    start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = await finmind.query("TaiwanStockShareholding", symbol, start_date=start)

    if df.empty:
        logger.debug(f"[shareholding] No data for {symbol}")
        return empty

    # Check if the distribution columns exist (not available on free tier)
    if not REQUIRED_COLS.issubset(df.columns):
        available = set(df.columns) - {"date", "stock_id", "stock_name"}
        logger.info(
            f"[shareholding] {symbol}: 持股分級欄位不存在（免費層限制）。"
            f"可用欄位: {available}。H5/B9 自動豁免。"
        )
        return empty

    df["date"] = pd.to_datetime(df["date"])
    df["HoldingSharesProportion"] = pd.to_numeric(
        df["HoldingSharesProportion"], errors="coerce"
    ).fillna(0)
    df["NumberOfShareholders"] = pd.to_numeric(
        df["NumberOfShareholders"], errors="coerce"
    ).fillna(0)

    result = []
    for date, grp in df.groupby("date"):
        retail_mask = grp["HoldingSharesLevel"] == RETAIL_LEVEL
        retail_proportion = grp.loc[retail_mask, "HoldingSharesProportion"].sum()
        major_ratio = max(0.0, (100.0 - retail_proportion) / 100.0)
        total_shareholders = int(grp["NumberOfShareholders"].sum())
        result.append({
            "date": date,
            "major_holder_ratio": round(major_ratio, 4),
            "shareholder_count": total_shareholders,
        })

    out = pd.DataFrame(result).sort_values("date").reset_index(drop=True)
    logger.info(f"[shareholding] {symbol}: {len(out)} report dates")
    return out
