from fastapi import APIRouter, Query
from typing import Optional
import duckdb
import math

from config.settings import settings

router = APIRouter()


def _conn():
    return duckdb.connect(str(settings.db_path), read_only=True)


@router.get("/screener")
async def screener(
    min_price: float = Query(default=10.0, ge=0),
    max_price: float = Query(default=5000.0, ge=0),
    min_volume: float = Query(default=0.0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    try:
        con = _conn()
        df = con.execute(
            """
            SELECT p.symbol, p.close, p.volume, CAST(p.date AS VARCHAR) AS date
            FROM prices p
            INNER JOIN (
                SELECT symbol, MAX(date) AS max_date
                FROM prices
                GROUP BY symbol
            ) latest ON p.symbol = latest.symbol AND p.date = latest.max_date
            WHERE p.close >= ? AND p.close <= ? AND p.volume >= ?
            ORDER BY p.volume DESC
            LIMIT ?
            """,
            [min_price, max_price, min_volume, limit],
        ).df()
        con.close()

        if df.empty:
            return []

        rows = []
        for _, row in df.iterrows():
            close = row.get("close")
            volume = row.get("volume")
            rows.append({
                "symbol": str(row["symbol"]),
                "close": round(float(close), 2) if close and not math.isnan(float(close)) else None,
                "volume": round(float(volume)) if volume and not math.isnan(float(volume)) else None,
                "date": str(row["date"]),
            })
        return rows
    except Exception as e:
        return {"error": str(e)}
