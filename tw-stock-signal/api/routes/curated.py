"""批次查詢多檔股票最新收盤價（從 DuckDB 讀取）。"""
from fastapi import APIRouter
from typing import List
import duckdb
import math

from config.settings import settings

router = APIRouter()


def _conn():
    try:
        return duckdb.connect(str(settings.db_path), read_only=True)
    except Exception:
        return None


@router.post("/batch-prices")
async def batch_prices(symbols: List[str]):
    if not symbols:
        return {}
    try:
        con = _conn()
        if con is None:
            return {}
        placeholders = ", ".join("?" for _ in symbols)
        df = con.execute(
            f"""
            SELECT p.symbol,
                   p.close,
                   p.volume,
                   CAST(p.date AS VARCHAR) AS date,
                   prev.close AS prev_close
            FROM prices p
            INNER JOIN (
                SELECT symbol, MAX(date) AS max_date
                FROM prices WHERE symbol IN ({placeholders})
                GROUP BY symbol
            ) latest ON p.symbol = latest.symbol AND p.date = latest.max_date
            LEFT JOIN (
                SELECT p2.symbol, p2.close, p2.date
                FROM prices p2
                INNER JOIN (
                    SELECT symbol, MAX(date) AS second_date
                    FROM prices
                    WHERE symbol IN ({placeholders})
                      AND date < (SELECT MAX(date) FROM prices WHERE symbol = prices.symbol)
                    GROUP BY symbol
                ) s ON p2.symbol = s.symbol AND p2.date = s.second_date
            ) prev ON p.symbol = prev.symbol
            WHERE p.symbol IN ({placeholders})
            """,
            symbols * 3,
        ).df()
        con.close()

        result = {}
        for _, row in df.iterrows():
            close = float(row["close"]) if row["close"] and not _isnan(row["close"]) else None
            prev = float(row["prev_close"]) if row["prev_close"] and not _isnan(row["prev_close"]) else None
            change = round(close - prev, 2) if close and prev else None
            change_pct = round((change / prev) * 100, 2) if change and prev else None
            result[str(row["symbol"])] = {
                "close": round(close, 2) if close else None,
                "change": change,
                "change_pct": change_pct,
                "date": str(row["date"]),
                "volume": round(float(row["volume"])) if row["volume"] and not _isnan(row["volume"]) else None,
            }
        return result
    except Exception as e:
        return {"_error": str(e)}


def _isnan(v):
    try:
        return math.isnan(v)
    except Exception:
        return False
