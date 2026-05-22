"""股票代號 → 名稱查詢（用 tw-stock-signal/data/tw_tickers.json）。

啟動時讀一次進 dict，之後 O(1) 查詢。找不到回傳原 symbol。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("ticker-name")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TICKERS_PATH = _PROJECT_ROOT / "tw-stock-signal" / "data" / "tw_tickers.json"

_cache: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        raw = json.loads(_TICKERS_PATH.read_text(encoding="utf-8"))
        tickers = raw.get("tickers", []) if isinstance(raw, dict) else []
        _cache = {
            str(t["symbol"]): str(t.get("name", ""))
            for t in tickers
            if isinstance(t, dict) and t.get("symbol")
        }
        logger.info("loaded %d ticker names from %s", len(_cache), _TICKERS_PATH)
    except FileNotFoundError:
        logger.warning("tw_tickers.json not found at %s — name lookup returns symbol as-is", _TICKERS_PATH)
        _cache = {}
    except Exception as exc:
        logger.warning("failed to load tw_tickers.json: %s", exc)
        _cache = {}
    return _cache


def lookup(symbol: str) -> str:
    """查股票名稱。找不到時回傳原 symbol。"""
    s = str(symbol).strip()
    if not s:
        return s
    return _load().get(s) or s


__all__ = ["lookup"]
