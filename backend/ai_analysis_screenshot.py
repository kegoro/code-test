"""HTML → PNG（Playwright async），給 Telegram bot 直接附圖用。

跟 scripts/screenshot_ai_report.py（CLI sync 版）功能相同，但用 async API，
適合在 telegram bot async handler 裡呼叫。
"""
from __future__ import annotations

import logging

from playwright.async_api import async_playwright


logger = logging.getLogger("ai-analysis-screenshot")


async def html_to_png(
    html_str: str,
    *,
    width: int = 1000,
    chart_timeout_ms: int = 8000,
) -> bytes:
    """渲染 HTML 後等 #chart 的 canvas 出現再截圖（full_page）。

    Playwright headless 啟動 + 載 lightweight-charts CDN，整體約 3-6 秒。
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            ctx = await browser.new_context(
                viewport={"width": width, "height": 1400},
                device_scale_factor=2,
            )
            page = await ctx.new_page()
            await page.set_content(html_str, wait_until="domcontentloaded")
            try:
                await page.wait_for_function(
                    "document.querySelector('#chart canvas') !== null",
                    timeout=chart_timeout_ms,
                )
            except Exception:
                # CDN 載不到時 fallback：稍微等再截，至少有 score 卡片
                await page.wait_for_timeout(2500)
            await page.wait_for_timeout(800)   # 等 chart paint
            return await page.screenshot(full_page=True)
        finally:
            await browser.close()


__all__ = ["html_to_png"]
