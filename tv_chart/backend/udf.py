"""TradingView UDF (Universal Data Feed) HTTP protocol implementation.

Spec reference: TradingView Charting Library docs → "UDF". This module exposes
the seven endpoints that the standard Datafeed JS adapter expects:

    GET /datafeed/config         — feature flags, supported resolutions
    GET /datafeed/time           — server UTC seconds
    GET /datafeed/search         — symbol search
    GET /datafeed/symbols        — symbol info
    GET /datafeed/history        — OHLCV bars for a window
    GET /datafeed/marks          — annotation marks on bars
    GET /datafeed/timescale_marks — long-form marks under the time axis

All responses are JSON in the column-major shapes UDF specifies.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Final, Optional

from fastapi import APIRouter, Query

from tv_chart.backend.data import (
    SUPPORTED_RESOLUTIONS,
    fetch_bars,
    fetch_full_for_marks,
)
from tv_chart.backend.marks import build_marks

logger = logging.getLogger("tv-chart.udf")

router = APIRouter(prefix="/datafeed", tags=["udf"])

# ── symbol universe ───────────────────────────────────────────────────────────
# Tiny static list for now; expand from tw_tickers.json later if you want fuzzy
# search across the entire TWSE.

_DEFAULT_WATCHLIST: Final[tuple[tuple[str, str], ...]] = (
    ("2330", "Taiwan Semiconductor (TSMC)"),
    ("2317", "Hon Hai Precision (Foxconn)"),
    ("2382", "Quanta Computer"),
    ("2454", "MediaTek"),
    ("2308", "Delta Electronics"),
    ("2891", "CTBC Financial"),
    ("2412", "Chunghwa Telecom"),
    ("2881", "Fubon Financial"),
)


def _watchlist() -> list[tuple[str, str]]:
    """Read SMC_WATCHLIST from env if set, else fall back to the default list."""
    env_val = os.getenv("SMC_WATCHLIST")
    if not env_val:
        return list(_DEFAULT_WATCHLIST)
    seen: set[str] = set()
    items: list[tuple[str, str]] = []
    for code in env_val.split(","):
        code = code.strip()
        if not code or code in seen:
            continue
        seen.add(code)
        # match against default list for the description, else generic
        desc = next((d for c, d in _DEFAULT_WATCHLIST if c == code),
                    f"TWSE {code}")
        items.append((code, desc))
    return items or list(_DEFAULT_WATCHLIST)


def _symbol_info(symbol: str, description: str) -> dict:
    """One symbol's metadata as TV expects."""
    return {
        "name": symbol,
        "ticker": symbol,
        "full_name": f"TWSE:{symbol}",
        "description": description,
        "type": "stock",
        "session": "0900-1330",          # TWSE regular session, Asia/Taipei
        "timezone": "Asia/Taipei",
        "exchange": "TWSE",
        "listed_exchange": "TWSE",
        "minmov": 1,
        "pricescale": 100,               # 2 decimal places
        "has_intraday": True,
        "has_daily": True,
        "has_weekly_and_monthly": True,
        "intraday_multipliers": ["1", "3", "5", "15", "30", "60"],
        "supported_resolutions": list(SUPPORTED_RESOLUTIONS),
        "data_status": "streaming",      # we'll start with snapshot; flip later
        "currency_code": "TWD",
    }


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/config")
async def config() -> dict:
    """Server feature flags. TV reads this on init to know what to enable."""
    return {
        "supported_resolutions": list(SUPPORTED_RESOLUTIONS),
        "supports_group_request": False,
        "supports_marks": True,
        "supports_search": True,
        "supports_timescale_marks": False,
        "supports_time": True,
        "exchanges": [
            {"value": "TWSE", "name": "Taiwan Stock Exchange", "desc": "TWSE"},
        ],
        "symbols_types": [
            {"name": "Stock", "value": "stock"},
        ],
    }


@router.get("/time")
async def server_time() -> int:
    """Server UNIX seconds — TV uses this to detect clock drift."""
    return int(time.time())


@router.get("/search")
async def search(
    query: str = Query("", description="symbol substring"),
    type: str = Query("", description="symbol type filter"),
    exchange: str = Query("", description="exchange filter"),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict]:
    """Substring search over the watchlist."""
    q = query.strip().lower()
    out: list[dict] = []
    for code, desc in _watchlist():
        if q and q not in code.lower() and q not in desc.lower():
            continue
        out.append({
            "symbol": code,
            "full_name": f"TWSE:{code}",
            "description": desc,
            "exchange": "TWSE",
            "ticker": code,
            "type": "stock",
        })
        if len(out) >= limit:
            break
    return out


@router.get("/symbols")
async def symbols(symbol: str = Query(..., description="symbol code or full_name")) -> dict:
    """Return symbol info. TV calls this when a chart is loading."""
    raw = symbol.strip()
    code = raw.split(":")[-1]
    desc = next((d for c, d in _watchlist() if c == code), f"TWSE {code}")
    return _symbol_info(code, desc)


@router.get("/history")
async def history(
    symbol: str = Query(..., description="symbol code"),
    resolution: str = Query(..., description='"1", "3", "1D", "D"'),
    from_: int = Query(..., alias="from", description="UNIX seconds, inclusive"),
    to: int = Query(..., description="UNIX seconds, inclusive"),
    countback: Optional[int] = Query(None, description="alternative to `from`"),
) -> dict:
    """Return bars for [from, to]. UDF expects column-major arrays."""
    code = symbol.strip().split(":")[-1]
    if resolution not in SUPPORTED_RESOLUTIONS:
        return {"s": "error", "errmsg": f"unsupported resolution: {resolution}"}
    try:
        slice_ = await fetch_bars(code, resolution, from_, to)
    except Exception as exc:
        logger.exception("/history failed for %s @ %s", code, resolution)
        return {"s": "error", "errmsg": repr(exc)}
    return slice_.to_udf()


@router.get("/marks")
async def marks(
    symbol: str = Query(...),
    resolution: str = Query(...),
    from_: int = Query(..., alias="from"),
    to: int = Query(...),
) -> dict:
    """SMC event annotations to render on the chart."""
    code = symbol.strip().split(":")[-1]
    if resolution not in SUPPORTED_RESOLUTIONS:
        return {"id": [], "time": [], "color": [], "text": [],
                "label": [], "labelFontColor": [], "minSize": []}
    try:
        df = await fetch_full_for_marks(code, resolution)
    except Exception as exc:
        logger.exception("/marks fetch failed for %s @ %s", code, resolution)
        return {"id": [], "time": [], "color": [], "text": [],
                "label": [], "labelFontColor": [], "minSize": []}

    swing_n = 5 if resolution in ("D", "1D") else (10 if resolution == "1" else 8)
    payload = build_marks(df, swing_n=swing_n)

    # Drop marks that fall outside the visible range (TV will discard them
    # anyway, but trimming keeps the payload small).
    keep = [i for i, t in enumerate(payload["time"]) if from_ <= t <= to]
    if len(keep) == len(payload["time"]):
        return payload
    return {k: [payload[k][i] for i in keep] for k in payload}


@router.get("/cdp")
async def cdp_levels(symbol: str = Query(..., description="symbol code, e.g. 2330 / AAPL")) -> dict:
    """CDP 逆勢四線(AH/NH/CDP/NL/AL)給前端畫水平線用。

    複用 backend.cdp 的取數 + 計算;取數失敗回 {"s":"error"}。
    """
    from backend.cdp import CDPDataError, fetch_levels, levels_payload

    code = symbol.strip().split(":")[-1]
    try:
        lv, _open, _last = await fetch_levels(code)
    except CDPDataError as exc:
        return {"s": "error", "errmsg": str(exc), "symbol": code}
    except Exception as exc:
        logger.exception("/cdp failed for %s", code)
        return {"s": "error", "errmsg": repr(exc), "symbol": code}
    return {
        "s": "ok",
        "symbol": code,
        "prev_date": lv.prev_date,
        "levels": levels_payload(lv),
    }


@router.get("/timescale_marks")
async def timescale_marks() -> list[dict]:
    """Optional long-form marks below the time axis. Empty for now."""
    return []
