"""
PoC probe (round 2): hit HiStock's chart-data AJAX endpoint directly.

URL pattern discovered in chips.aspx line 890:
    /stock/chip/chartdata.aspx?no={sid}&m={comma-separated-metric-keys}

Known metric keys (from the same script):
  dailyk, close, volume,
  mean5, mean10, mean20, mean60, mean120, mean240,
  mean5volume, mean20volume,
  broker1, broker3, broker5, broker10,   # 主力買賣超 (1/3/5/10 day)
  chip1,   chip3,   chip5,   chip10,     # 籌碼差
  focus1,  focus3,  focus5,  focus10     # 籌碼集中度 (1/3/5/10 day)

Usage:
    python scripts/probe_histock_api.py [stock_id]
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from typing import Final

import httpx
from loguru import logger


_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_OUT_DIR: Final[Path] = _REPO_ROOT / "scripts" / "poc_data"

_ENDPOINT: Final[str] = "https://histock.tw/stock/chip/chartdata.aspx"
_METRICS: Final[str] = "close,volume,focus1,focus3,focus5,focus10,broker1,chip1"

_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    # Referer is often required for AJAX endpoints — supply the parent page.
    "Referer": "https://histock.tw/stock/chips.aspx",
    "X-Requested-With": "XMLHttpRequest",
}


async def main(stock_id: str) -> None:
    """Hit chartdata.aspx once and print full response for inspection."""
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    url = f"{_ENDPOINT}?no={stock_id}&m={_METRICS}"

    logger.info(f"GET {url}")
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # Inject stock_id into Referer per HiStock's likely check.
            headers = {**_HEADERS, "Referer": f"https://histock.tw/stock/chips.aspx?no={stock_id}"}
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.error(f"HTTP error: {type(exc).__name__}: {exc}")
        return

    body = resp.text
    out_path = _OUT_DIR / f"histock_api_{stock_id}.txt"
    out_path.write_text(body, encoding="utf-8")
    logger.info(
        f"HTTP {resp.status_code} | content-type={resp.headers.get('content-type')!r} | "
        f"{len(body):>7,} bytes | saved → {out_path.relative_to(_REPO_ROOT)}"
    )

    preview = body[:600].replace("\n", " ")
    logger.info(f"PREVIEW (first 600 chars): {preview}")


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else "2330"
    asyncio.run(main(sid))
