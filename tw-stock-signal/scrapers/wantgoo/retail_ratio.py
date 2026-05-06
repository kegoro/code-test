"""
WantGoo 散戶多空比 scraper using Playwright network interception.
Rather than DOM scraping, we intercept the XHR/fetch calls that the
page makes so we get clean JSON regardless of DOM changes.

Target page: https://www.wantgoo.com/stock/{symbol}/major-investors
The page calls internal API endpoints we capture via route interception.
"""
import asyncio
import json
from typing import Any
from playwright.async_api import async_playwright, Response
from playwright_stealth import stealth_async
from loguru import logger
from config.settings import settings


WANTGOO_BASE = "https://www.wantgoo.com"


async def fetch_retail_ratio(symbol: str) -> dict[str, Any]:
    """
    Returns a dict with keys:
      - retail_long_ratio: float (%)
      - retail_short_ratio: float (%)
      - date: str (YYYY-MM-DD)
      - raw: list[dict]  (full API payload, for debugging)
    Returns empty dict on failure.
    """
    captured: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=settings.playwright_headless)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        await stealth_async(page)

        async def handle_response(response: Response):
            url = response.url
            # WantGoo internal API patterns for chip/ratio data
            if (
                "wantgoo.com" in url
                and any(k in url for k in ["major", "chip", "retail", "ratio", "investor"])
                and response.status == 200
            ):
                try:
                    body = await response.json()
                    captured.append({"url": url, "data": body})
                    logger.debug(f"[wantgoo] captured: {url}")
                except Exception:
                    pass

        page.on("response", handle_response)

        url = f"{WANTGOO_BASE}/stock/{symbol}/major-investors"
        try:
            await page.goto(url, timeout=settings.playwright_timeout_ms, wait_until="networkidle")
        except Exception as e:
            logger.warning(f"[wantgoo] navigation timeout for {symbol}: {e}")

        await asyncio.sleep(2)
        await browser.close()

    if not captured:
        logger.warning(f"[wantgoo] No API responses captured for {symbol}")
        return {}

    return _parse_captured(captured, symbol)


def _parse_captured(captured: list[dict], symbol: str) -> dict[str, Any]:
    """
    Parse whatever WantGoo API returned. Structure may vary — we attempt
    to find long/short ratio fields by common key names.
    """
    for item in captured:
        data = item.get("data", {})
        # Try common response shapes
        if isinstance(data, dict):
            ratio = _extract_ratio(data)
            if ratio:
                logger.info(f"[wantgoo] {symbol} retail ratio extracted: {ratio}")
                return ratio
        elif isinstance(data, list) and data:
            ratio = _extract_ratio(data[0] if isinstance(data[0], dict) else {})
            if ratio:
                return ratio

    logger.warning(f"[wantgoo] Could not parse retail ratio for {symbol}. Raw: {json.dumps(captured[0], ensure_ascii=False)[:200]}")
    return {"raw": captured}


def _extract_ratio(d: dict) -> dict | None:
    long_keys = ["retailLong", "retail_long", "longRatio", "long_ratio", "buyRatio"]
    short_keys = ["retailShort", "retail_short", "shortRatio", "short_ratio", "sellRatio"]
    date_keys = ["date", "Date", "tradeDate", "trade_date"]

    long_val = next((d[k] for k in long_keys if k in d), None)
    short_val = next((d[k] for k in short_keys if k in d), None)

    if long_val is None or short_val is None:
        return None

    return {
        "retail_long_ratio": float(long_val),
        "retail_short_ratio": float(short_val),
        "date": next((d[k] for k in date_keys if k in d), None),
        "raw": d,
    }
