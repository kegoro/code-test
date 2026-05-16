"""探勘「產業焦點導航」卡片的 DOM selector 結構。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://aistockmap.com/?activeTab=daily"
OUT = Path(__file__).resolve().parent.parent / "reports" / "aistockmap_focus_dom.json"


async def main() -> None:
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="zh-TW",
        )
        page = await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(8_000)

        result = await page.evaluate(
            r"""() => {
              const trim = (s) => (s || '').replace(/\s+/g, ' ').trim();
              // 找含「鴻海法說看旺 AI 成長」的元素，往上爬找穩定的卡片容器
              const target = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6,div,span,a,p'))
                .find(e => trim(e.innerText) === '鴻海法說看旺 AI 成長');
              if (!target) return { error: 'not found' };
              const path = [];
              let cur = target;
              for (let i = 0; i < 8 && cur; i++) {
                path.push({
                  tag: cur.tagName,
                  cls: cur.className?.toString?.().slice(0, 200) || '',
                  textLen: trim(cur.innerText).length,
                  textPreview: trim(cur.innerText).slice(0, 120),
                });
                cur = cur.parentElement;
              }
              // 取「足夠包整張卡」的祖先（含 source、date、tag）
              cur = target;
              let card = null;
              for (let i = 0; i < 8 && cur; i++) {
                const t = trim(cur.innerText);
                if (t.includes('工商時報') && t.includes('伺服器組裝')) {
                  card = cur;
                  break;
                }
                cur = cur.parentElement;
              }
              if (!card) return { path, error: 'card ancestor not found' };
              return {
                path,
                cardHtml: card.outerHTML.slice(0, 4000),
                cardChildren: Array.from(card.children).map(c => ({
                  tag: c.tagName,
                  cls: c.className?.toString?.().slice(0, 120) || '',
                  text: trim(c.innerText).slice(0, 200),
                })),
              };
            }"""
        )
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {OUT}")
        await b.close()


asyncio.run(main())
