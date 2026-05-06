"""
Single-call market summary scrapers.

Volume (Saturday):
  TWSE — STOCK_DAY_ALL OpenAPI (returns latest trading day, all listed stocks)
  TPEX — tpex_mainboard_daily_close_quotes OpenAPI (same)

Foreign buy (Sunday):
  TWSE — TWT44U 外資買賣超彙總表 (requires date param, returns only stocks with non-zero activity)
  TPEX — no reliable JSON endpoint available; TWSE alone covers the top 10

Verified field names 2025-04-17:
  STOCK_DAY_ALL  : Code, Name, TradeVolume(shares, no commas), ClosingPrice
  TPEX volume    : SecuritiesCompanyCode, CompanyName, TradingShares, Close
  TWT44U data row: [category, code, name, buy_shares, sell_shares, net_shares]  (comma-formatted)
"""
import re
import httpx
import pandas as pd
from loguru import logger

_TWSE_VOLUME_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
_TPEX_VOLUME_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
_TWSE_INST_BASE  = "https://www.twse.com.tw/fund/TWT44U"   # 外資買賣超彙總表

_VALID_STOCK = re.compile(r"^[1-9][0-9]{3,4}$")


def _to_int(val) -> int:
    try:
        return int(str(val).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0


def _to_float(val) -> float:
    try:
        s = str(val).replace(",", "").strip()
        return float(s) if s and s not in ("--", "-", "") else 0.0
    except (ValueError, TypeError):
        return 0.0


async def _get(url: str, **params) -> object:
    async with httpx.AsyncClient(
        timeout=20, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    ) as client:
        resp = await client.get(url, params=params or None)
        resp.raise_for_status()
        return resp.json()


# ── Volume ranking (Saturday) ─────────────────────────────────────────────────

async def fetch_top_volume(n: int = 10) -> list[dict]:
    """
    Top-N stocks by trading volume on the most recent trading day.
    Volume unit: 張 (= TradeVolume shares ÷ 1000).
    Sources: TWSE STOCK_DAY_ALL + TPEX tpex_mainboard_daily_close_quotes.
    """
    rows: list[dict] = []

    # TWSE 上市
    try:
        data = await _get(_TWSE_VOLUME_URL)
        before = len(rows)
        for item in data:
            symbol = str(item.get("Code", "")).strip()
            if not _VALID_STOCK.match(symbol):
                continue
            rows.append({
                "symbol": symbol,
                "name":   item.get("Name", "").strip(),
                "volume": _to_int(item.get("TradeVolume", 0)) // 1000,
                "close":  _to_float(item.get("ClosingPrice", 0)),
                "market": "twse",
            })
        logger.info(f"[market_summary] TWSE volume: {len(rows) - before} stocks")
    except Exception as exc:
        logger.warning(f"[market_summary] TWSE STOCK_DAY_ALL failed: {exc}")

    # TPEX 上櫃
    try:
        data = await _get(_TPEX_VOLUME_URL)
        before = len(rows)
        for item in data:
            symbol = str(item.get("SecuritiesCompanyCode") or item.get("Code") or "").strip()
            if not _VALID_STOCK.match(symbol):
                continue
            rows.append({
                "symbol": symbol,
                "name":   str(item.get("CompanyName") or item.get("Name") or "").strip(),
                "volume": _to_int(item.get("TradingShares") or item.get("TradeVolume") or 0) // 1000,
                "close":  _to_float(item.get("Close") or item.get("ClosingPrice") or 0),
                "market": "otc",
            })
        logger.info(f"[market_summary] TPEX volume: {len(rows) - before} stocks")
    except Exception as exc:
        logger.warning(f"[market_summary] TPEX volume failed: {exc}")

    if not rows:
        return []

    df = pd.DataFrame(rows)
    df = df[df["close"] >= 10]
    df = df.sort_values("volume", ascending=False).head(n)
    return df.to_dict("records")


# ── Foreign buy ranking (Sunday) ──────────────────────────────────────────────

async def fetch_top_foreign_buy(n: int = 10, trading_date: str | None = None) -> list[dict]:
    """
    Top-N stocks by foreign investor net buy on the given trading date.
    trading_date: YYYY-MM-DD (defaults to most recent trading day via calendar.prev_trading_date).
    Unit: 張 (= net_shares ÷ 1000).
    Source: TWSE TWT44U (外資買賣超彙總表).
    Note: TWT44U only lists stocks with non-zero foreign activity — perfect for top-10 ranking.
    """
    if trading_date is None:
        from scheduler.calendar import prev_trading_date
        trading_date = prev_trading_date().isoformat()

    date_str = trading_date.replace("-", "")    # YYYYMMDD for TWSE param
    rows: list[dict] = []

    # TWSE 上市 — TWT44U
    try:
        payload = await _get(_TWSE_INST_BASE, response="json", date=date_str, selectType="All")
        if payload.get("stat") != "OK":
            logger.warning(f"[market_summary] TWT44U stat={payload.get('stat')} for {date_str}")
        else:
            # Each row is an array: [category, code, name, buy_shares, sell_shares, net_shares]
            for row in payload.get("data", []):
                if len(row) < 6:
                    continue
                symbol = str(row[1]).strip()
                if not _VALID_STOCK.match(symbol):
                    continue
                rows.append({
                    "symbol":      symbol,
                    "name":        str(row[2]).strip(),
                    "foreign_net": _to_int(row[5]) // 1000,    # shares → 張
                    "market":      "twse",
                })
            logger.info(f"[market_summary] TWT44U: {len(rows)} stocks for {trading_date}")
    except Exception as exc:
        logger.warning(f"[market_summary] TWSE TWT44U failed: {exc}")

    if not rows:
        return []

    df = pd.DataFrame(rows)
    df = df.sort_values("foreign_net", ascending=False).head(n)
    return df.to_dict("records")
