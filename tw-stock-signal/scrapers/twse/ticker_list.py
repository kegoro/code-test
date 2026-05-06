"""
台股全市場代號快取

來源（公開 API，不需 API Key）：
  上市 TWSE: https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL
  上櫃 TPEX: https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes

當日第一次呼叫會打 API，結果快取到 data/tw_tickers.json；
同一天後續呼叫直接讀快取，不重複打 API。
"""
import json
import re
from datetime import date
from pathlib import Path

import httpx
from loguru import logger

from config.settings import settings

_TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
_TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
_CACHE_PATH = Path(settings.data_dir) / "tw_tickers.json"

# 只保留 4–5 位純數字、非 00 開頭的代號
_VALID_SYMBOL = re.compile(r"^[1-9][0-9]{3,4}$")
_SKIP_KW = frozenset(["ETF", "基金", "正2", "反1", "反2", "正1", "債", "REITs", "期貨", "特別股"])


def _is_valid(symbol: str, name: str) -> bool:
    if not _VALID_SYMBOL.match(symbol):
        return False
    if any(kw in name for kw in _SKIP_KW):
        return False
    return True


def _parse_twse(data: list) -> list[dict]:
    """解析 TWSE STOCK_DAY_ALL 回傳，欄位：Code / Name"""
    out = []
    for item in data:
        sym  = str(item.get("Code",  "")).strip()
        name = str(item.get("Name",  "")).strip()
        if _is_valid(sym, name):
            out.append({"symbol": sym, "name": name, "market": "twse"})
    return out


def _parse_tpex(data: list) -> list[dict]:
    """
    解析 TPEX tpex_mainboard_daily_close_quotes 回傳。
    欄位名稱視版本而定，嘗試多個可能鍵值。
    """
    CODE_KEYS = ["SecuritiesCompanyCode", "Code", "代號"]
    NAME_KEYS = ["CompanyName", "Name", "公司簡稱"]

    out = []
    for item in data:
        sym  = next((str(item.get(k,"")).strip() for k in CODE_KEYS if item.get(k)), "")
        name = next((str(item.get(k,"")).strip() for k in NAME_KEYS if item.get(k)), "")
        if _is_valid(sym, name):
            out.append({"symbol": sym, "name": name, "market": "otc"})
    return out


async def fetch_full_ticker_list(force_refresh: bool = False) -> list[dict]:
    """
    回傳 [{symbol, name, market}] 的全市場清單（上市 + 上櫃）。
    force_refresh=True 忽略快取，重新打 API。
    """
    today = date.today().isoformat()

    # ── 讀快取 ──────────────────────────────────────────────────────────────
    if not force_refresh and _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            if cached.get("date") == today:
                tickers = cached["tickers"]
                logger.info(f"[ticker_list] Cache hit ({today}): {len(tickers)} tickers")
                return tickers
        except Exception as exc:
            logger.warning(f"[ticker_list] Cache read failed: {exc}")

    # ── 打 API ──────────────────────────────────────────────────────────────
    tickers: list[dict] = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        # 上市
        try:
            r = await client.get(_TWSE_URL)
            r.raise_for_status()
            twse_list = _parse_twse(r.json())
            tickers.extend(twse_list)
            logger.info(f"[ticker_list] TWSE: {len(twse_list)} stocks")
        except Exception as exc:
            logger.error(f"[ticker_list] TWSE fetch failed: {exc}")

        # 上櫃
        try:
            r = await client.get(_TPEX_URL)
            r.raise_for_status()
            tpex_list = _parse_tpex(r.json())
            tickers.extend(tpex_list)
            logger.info(f"[ticker_list] TPEX: {len(tpex_list)} stocks")
        except Exception as exc:
            logger.error(f"[ticker_list] TPEX fetch failed: {exc}")

    if not tickers:
        logger.error("[ticker_list] Both APIs failed — returning empty list")
        return []

    # ── 寫快取 ──────────────────────────────────────────────────────────────
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(
        json.dumps({"date": today, "tickers": tickers}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"[ticker_list] Cached {len(tickers)} tickers → {_CACHE_PATH}")
    return tickers
