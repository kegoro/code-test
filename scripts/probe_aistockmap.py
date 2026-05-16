"""一次性探勘 script：用 Playwright 抓 aistockmap.com daily 分頁，
存 HTML / 截圖 / 結構摘要到 reports/，給人類眼睛驗證實際資料形狀。

用法：
  python scripts/probe_aistockmap.py
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from playwright.async_api import async_playwright

logger = logging.getLogger("probe-aistockmap")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

URL = "https://aistockmap.com/?activeTab=daily"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "reports"
OUT_DIR.mkdir(exist_ok=True)


async def probe() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="zh-TW",
        )
        page = await context.new_page()

        xhr_log: list[dict] = []

        async def on_response(resp):
            try:
                if resp.request.resource_type in {"xhr", "fetch"}:
                    xhr_log.append(
                        {
                            "url": resp.url,
                            "status": resp.status,
                            "method": resp.request.method,
                            "ct": resp.headers.get("content-type", ""),
                        }
                    )
            except Exception as exc:
                logger.warning("xhr log err: %s", exc)

        page.on("response", on_response)

        logger.info("goto %s", URL)
        await page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(8_000)

        try:
            await page.wait_for_selector("body", timeout=10_000)
        except Exception:
            pass

        html = await page.content()
        (OUT_DIR / "aistockmap_dump.html").write_text(html, encoding="utf-8")
        logger.info("dumped HTML (%d chars)", len(html))

        await page.screenshot(path=str(OUT_DIR / "aistockmap_dump.png"), full_page=True)
        logger.info("dumped screenshot")

        text_summary = await page.evaluate(
            """() => {
                const trim = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const root = document.querySelector('main') || document.body;
                return {
                    title: document.title,
                    h1: Array.from(document.querySelectorAll('h1,h2,h3')).map(e => trim(e.innerText)).filter(Boolean).slice(0, 50),
                    cards_text_sample: Array.from(root.querySelectorAll('div, section, article'))
                        .map(e => trim(e.innerText))
                        .filter(t => t.length > 20 && t.length < 400)
                        .slice(0, 80),
                    anchors: Array.from(document.querySelectorAll('a[href]'))
                        .map(a => ({text: trim(a.innerText), href: a.getAttribute('href')}))
                        .filter(a => a.text)
                        .slice(0, 80),
                };
            }"""
        )
        (OUT_DIR / "aistockmap_dump.json").write_text(
            json.dumps(text_summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(
            "dumped summary: title=%r headings=%d cards=%d",
            text_summary.get("title"),
            len(text_summary.get("h1", [])),
            len(text_summary.get("cards_text_sample", [])),
        )

        (OUT_DIR / "aistockmap_xhr.json").write_text(
            json.dumps(xhr_log, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("xhr endpoints captured: %d", len(xhr_log))

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(probe())
