"""
Fetch monthly revenue (月營收) via FinMind TaiwanStockMonthRevenue.

Dataset fields returned:
  date          — 公告日 (YYYY-MM-DD)
  stock_id      — stock code
  country       — "TW"
  revenue       — revenue in thousand TWD (千元)
  revenue_month — 1–12
  revenue_year  — year

Output DataFrame (sorted oldest → newest by period):
  period  — YYYY-MM string  (e.g. "2026-04")
  revenue — float, thousand TWD
  yoy     — float or NaN, YoY % change
  mom     — float or NaN, MoM % change
"""
from datetime import datetime, timedelta
import pandas as pd
from loguru import logger
from .client import finmind

_DATASET = "TaiwanStockMonthRevenue"


async def fetch_monthly_revenue(symbol: str, months: int = 15) -> pd.DataFrame:
    """
    Fetch the most recent `months` monthly revenue records for `symbol`.
    Returns empty DataFrame on failure or insufficient data.
    """
    # Need 12 extra months to compute YoY, so look back months + 14 months
    start = (datetime.today() - timedelta(days=(months + 14) * 31)).strftime("%Y-%m-%d")

    df = await finmind.query(_DATASET, symbol, start_date=start)
    if df.empty:
        logger.debug(f"[revenue] {symbol}: no data from FinMind")
        return pd.DataFrame()

    required = {"revenue", "revenue_month", "revenue_year"}
    if not required.issubset(df.columns):
        logger.warning(f"[revenue] {symbol}: unexpected columns {df.columns.tolist()}")
        return pd.DataFrame()

    df = df.copy()
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
    df["revenue_month"] = pd.to_numeric(df["revenue_month"], errors="coerce").astype("Int64")
    df["revenue_year"] = pd.to_numeric(df["revenue_year"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["revenue", "revenue_month", "revenue_year"])

    df["period"] = df["revenue_year"].astype(str) + "-" + df["revenue_month"].astype(str).str.zfill(2)
    df = df[["period", "revenue"]].drop_duplicates("period").sort_values("period").reset_index(drop=True)

    # YoY: compare same period 12 months ago
    rev_map: dict[str, float] = dict(zip(df["period"], df["revenue"]))

    def _yoy(row) -> float | None:
        y, m = int(row["period"][:4]), int(row["period"][5:])
        prior_y = y - 1
        prior_key = f"{prior_y}-{m:02d}"
        prior = rev_map.get(prior_key)
        if prior and prior != 0:
            return (row["revenue"] - prior) / abs(prior) * 100
        return None

    def _mom(i: int, rows) -> float | None:
        if i == 0:
            return None
        prev = rows.iloc[i - 1]["revenue"]
        cur = rows.iloc[i]["revenue"]
        if prev and prev != 0:
            return (cur - prev) / abs(prev) * 100
        return None

    df["yoy"] = df.apply(_yoy, axis=1)
    df["mom"] = [_mom(i, df) for i in range(len(df))]

    # Keep only the most recent `months` rows
    df = df.tail(months).reset_index(drop=True)

    logger.info(f"[revenue] {symbol}: {len(df)} months | latest={df['period'].iloc[-1] if not df.empty else 'N/A'}")
    return df
