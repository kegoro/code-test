"""
Fetches the full Taiwan stock universe (上市 + 上櫃, ~1700 stocks).

Sources:
  Primary  — FinMind TaiwanStockInfo  (single call, full list with type/name)
  Secondary — TWSE OpenAPI TWTB4U     (single call, full-delivery exclusion list)

Filters applied:
  1. type must be "twse" or "otc"  (drops ETF, warrants, bonds)
  2. symbol must be 4–5 pure digits  (drops anything with letters)
  3. symbol must not start with "00"  (drops ETF symbols: 0050, 00878, etc.)
  4. name must not contain known non-stock keywords
  5. 全額交割股 excluded via TWSE (best-effort, skipped on failure)
"""
import re
import httpx
import pandas as pd
from loguru import logger
from .client import finmind

_VALID_STOCK = re.compile(r"^[1-9][0-9]{3,4}$")   # 4–5 digits, not starting with 0
_SKIP_KEYWORDS = frozenset(["ETF", "基金", "正2", "反1", "反2", "正1", "債", "REITs", "房產", "期貨"])
_TWSE_FULL_DELIVERY_URL = "https://openapi.twse.com.tw/v1/exchangeReport/TWTB4U"


async def fetch_stock_universe() -> list[dict]:
    """
    Returns [{symbol, name, market}] for all normal tradeable stocks.
    market is "twse" (上市) or "otc" (上櫃).
    """
    df = await finmind.query_dataset("TaiwanStockInfo")
    if df.empty:
        logger.error("[universe] TaiwanStockInfo returned empty")
        return []

    stocks = _filter_dataframe(df)
    logger.info(f"[universe] {len(stocks)} stocks after basic filter")

    try:
        full_delivery = await _fetch_full_delivery_set()
        # Sanity check: TWSE typically lists <100 full-delivery stocks.
        # If the returned set is abnormally large the endpoint returned wrong data — skip.
        if len(full_delivery) > 200:
            logger.warning(
                f"[universe] Full-delivery set suspiciously large ({len(full_delivery)}) "
                f"— skipping filter to avoid wrongly excluding normal stocks"
            )
        else:
            before = len(stocks)
            stocks = [s for s in stocks if s["symbol"] not in full_delivery]
            excluded = before - len(stocks)
            if excluded:
                logger.info(f"[universe] Excluded {excluded} full-delivery stocks")
    except Exception as exc:
        logger.warning(f"[universe] Full-delivery filter skipped: {exc}")

    logger.info(f"[universe] Final universe: {len(stocks)} stocks")
    return stocks


def _filter_dataframe(df: pd.DataFrame) -> list[dict]:
    results = []
    for _, row in df.iterrows():
        symbol = str(row.get("stock_id", "")).strip()
        name = str(row.get("stock_name", "")).strip()
        market = str(row.get("type", "")).lower()

        if market not in ("twse", "otc", "上市", "上櫃"):
            continue
        if not _VALID_STOCK.match(symbol):
            continue
        if any(kw in name for kw in _SKIP_KEYWORDS):
            continue

        results.append({
            "symbol": symbol,
            "name": name,
            "market": "twse" if market in ("twse", "上市") else "otc",
        })
    return results


async def _fetch_full_delivery_set() -> set[str]:
    """TWSE 全額交割股清單 — single HTTP call, no new package dependencies."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_TWSE_FULL_DELIVERY_URL)
        resp.raise_for_status()
        data = resp.json()
    return {str(item.get("Code", "")).strip() for item in data if item.get("Code")}
