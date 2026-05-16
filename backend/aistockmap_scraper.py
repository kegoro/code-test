"""aistockmap.com 「每日焦點」爬蟲。

只抓首頁 daily 分頁公開可見的內容（不需登入）：
  - 「產業焦點導航」每日 6-7 條題材（標題、描述、產業 tag、是否 Premium 限定）
  - 「智慧產業地圖」上方公開可見的題材卡片

aistockmap 個股清單大多需登入或 Premium，本模組只抓題材層，
個股映射交由 theme_filter 後端用其他資料源補（現階段先列產業 tag）。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import async_playwright

logger = logging.getLogger("aistockmap-scraper")

URL = "https://aistockmap.com/?activeTab=daily"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class FocusItem:
    """一條「產業焦點」題材。"""

    source: str
    date_label: str
    title: str
    description: str
    industry_tags: tuple[str, ...]
    is_premium_locked: bool


@dataclass(frozen=True)
class IndustryCard:
    """首頁公開的產業地圖題材卡片（如「IC 設計｜HPC 與網通 IC」）。"""

    title: str
    company_count: Optional[int]
    description: str


@dataclass(frozen=True)
class DailyDigest:
    """一次抓取的完整快照。"""

    fetched_at: str
    focus_items: tuple[FocusItem, ...]
    industry_cards: tuple[IndustryCard, ...]


# ── DOM 抽取的 JS（在 page context 跑） ────────────────────────────────────────

_EXTRACT_JS = r"""
() => {
  const trim = (s) => (s || '').replace(/\s+/g, ' ').trim();

  // 1. 產業焦點導航
  // 卡片 selector：含 h3.font-bold 且 parent chain 含 source span（text-blue-400 bg-blue-400/10）
  const focusItems = [];
  const seen = new Set();
  const sourceSpans = Array.from(document.querySelectorAll('span'))
    .filter(s => /text-blue-400/.test(s.className || '') && /bg-blue-400/.test(s.className || ''));

  for (const sourceSpan of sourceSpans) {
    // 從 source span 往上爬找含 h3 + button tags 的卡片祖先
    let card = sourceSpan;
    for (let i = 0; i < 6; i++) {
      card = card.parentElement;
      if (!card) break;
      if (card.querySelector('h3') && card.querySelector('button')) break;
    }
    if (!card) continue;
    const sig = trim(card.innerText);
    if (seen.has(sig)) continue;
    seen.add(sig);

    const source = trim(sourceSpan.innerText);
    // date：找 lucide-calendar svg 後的純文字
    const calIcon = card.querySelector('svg.lucide-calendar');
    let dateLabel = '';
    if (calIcon && calIcon.parentElement) {
      dateLabel = trim(calIcon.parentElement.innerText);
    }

    const h3 = card.querySelector('h3');
    const p = card.querySelector('p');
    const title = h3 ? trim(h3.innerText) : '';
    const description = p ? trim(p.innerText) : '';

    const tags = Array.from(card.querySelectorAll('button')).map(b => trim(b.innerText)).filter(Boolean);

    // Premium lock：卡片本身或內層 div 含 blur-sm class（鎖定時 React 會套 .blur-sm）
    let isPremium = false;
    if (/blur-sm/.test(card.className || '')) {
      isPremium = true;
    } else if (card.querySelector('.blur-sm')) {
      isPremium = true;
    }

    if (!title) continue;
    focusItems.push({
      source, date_label: dateLabel, title, description,
      industry_tags: tags, is_premium_locked: isPremium,
    });
  }

  // 2. 公開的產業地圖題材卡片（含「N 家公司」字串）
  // 結構：每張卡有「有新動態」+「N 家公司」+ title + description
  const industryCards = [];
  const seenIndustry = new Set();
  const COUNT_RE = /(\d+)\s*家公司/;
  // 找直接含「N 家公司」的最內層元素
  const allEls = Array.from(document.querySelectorAll('div, span'));
  for (const el of allEls) {
    const txt = el.innerText || '';
    if (!COUNT_RE.test(txt)) continue;
    // 取「N 家公司」span 的祖先卡片（含 h2 或 h3 的 title）
    let card = el;
    for (let i = 0; i < 6 && card; i++) {
      if (card.querySelector && (card.querySelector('h2, h3'))) break;
      card = card.parentElement;
    }
    if (!card) continue;
    const heading = card.querySelector('h2, h3');
    if (!heading) continue;
    const title = trim(heading.innerText);
    if (!title || seenIndustry.has(title)) continue;
    // description = 卡片下緊接 heading 的 p
    const p = card.querySelector('p');
    const description = p ? trim(p.innerText) : '';
    const cm = trim(card.innerText).match(COUNT_RE);
    if (!cm) continue;
    seenIndustry.add(title);
    industryCards.push({
      title, company_count: parseInt(cm[1], 10), description,
    });
  }

  return { focus_items: focusItems, industry_cards: industryCards };
}
"""


async def fetch_daily(timeout_ms: int = 60_000, settle_ms: int = 8_000) -> DailyDigest:
    """打開 aistockmap daily 分頁，等渲染穩定後抽結構化內容。"""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1440, "height": 900},
                locale="zh-TW",
            )
            page = await context.new_page()
            logger.info("goto %s", URL)
            await page.goto(URL, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(settle_ms)

            payload = await page.evaluate(_EXTRACT_JS)
            from datetime import datetime

            fetched_at = datetime.now().isoformat(timespec="seconds")

            focus = tuple(
                FocusItem(
                    source=item["source"],
                    date_label=item["date_label"],
                    title=item["title"],
                    description=item["description"],
                    industry_tags=tuple(item.get("industry_tags") or ()),
                    is_premium_locked=bool(item.get("is_premium_locked")),
                )
                for item in payload.get("focus_items", [])
            )
            cards = tuple(
                IndustryCard(
                    title=item["title"],
                    company_count=item.get("company_count"),
                    description=item.get("description", ""),
                )
                for item in payload.get("industry_cards", [])
            )
            logger.info(
                "extracted: focus=%d, industry_cards=%d", len(focus), len(cards)
            )
            return DailyDigest(
                fetched_at=fetched_at, focus_items=focus, industry_cards=cards
            )
        finally:
            await browser.close()


def fetch_daily_sync(**kwargs) -> DailyDigest:
    """同步版本，方便 CLI 或非 async caller 直接呼叫。"""
    return asyncio.run(fetch_daily(**kwargs))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    digest = fetch_daily_sync()
    print(f"\nfetched_at: {digest.fetched_at}")
    print(f"\n=== 產業焦點（{len(digest.focus_items)} 條） ===")
    for f in digest.focus_items:
        lock = " [Premium]" if f.is_premium_locked else ""
        print(f"  • [{f.source} {f.date_label}] {f.title}{lock}")
        print(f"    {f.description[:80]}...")
        if f.industry_tags:
            print(f"    tags: {', '.join(f.industry_tags)}")
    print(f"\n=== 公開產業卡片（{len(digest.industry_cards)} 張） ===")
    for c in digest.industry_cards:
        print(f"  • {c.title} ({c.company_count} 家)")
