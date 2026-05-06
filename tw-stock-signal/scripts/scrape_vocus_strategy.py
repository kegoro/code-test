"""
Scrape M哥 A+B+C strategy articles from Vocus index page.
Uses playwright-stealth to bypass bot detection.
"""
import asyncio
import re
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

INDEX_URL = "https://vocus.cc/article/697b49fcfd897800011e5d98"
DOCS_DIR = Path("docs")
VOCUS_DIR = DOCS_DIR / "vocus"
ARTICLE_URLS_FILE = DOCS_DIR / "article_urls.txt"
FAILED_URLS_FILE = DOCS_DIR / "failed_urls.txt"
SKIPPED_PAID_FILE = DOCS_DIR / "skipped_paid.txt"

# Only trigger paid if these specific paywall patterns appear (NOT just nav text)
PAID_SELECTORS = [
    '[class*="paywall"]',
    '[class*="premium-lock"]',
    '[class*="locked"]',
    '[id*="paywall"]',
]
PAID_TEXT_PATTERNS = [
    "此篇為付費文章",
    "解鎖全文",
    "立即訂閱解鎖",
    "此內容需要付費",
    "付費閱讀全文",
    "需付費才能閱讀",
    "訂閱後可閱讀完整",
]


def sanitize_filename(title: str) -> str:
    title = re.sub(r'[\\/*?:"<>|]', "", title)
    title = title.strip().replace(" ", "_")
    return title[:80] or "untitled"


async def is_paid_content(page) -> bool:
    # Check for paywall CSS selectors
    for sel in PAID_SELECTORS:
        count = await page.locator(sel).count()
        if count > 0:
            return True
    # Check for specific paywall text patterns in the article body only
    try:
        body_text = await page.locator("article, main").first.inner_text()
        for pattern in PAID_TEXT_PATTERNS:
            if pattern in body_text:
                return True
    except Exception:
        pass
    return False


async def get_article_links(page) -> list[str]:
    print(f"Opening index: {INDEX_URL}")
    await page.goto(INDEX_URL, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(5)

    # Scroll to load all content
    for _ in range(8):
        await page.evaluate("window.scrollBy(0, 600)")
        await asyncio.sleep(0.8)

    # Only get links from the article body (not sidebar/nav)
    links = await page.eval_on_selector_all(
        'article a[href*="/article/"], main a[href*="/article/"]',
        'els => els.map(e => e.href)'
    )
    # Filter: only full article URLs (not anchor #heading links), deduplicate
    links = list(dict.fromkeys(
        l for l in links
        if re.match(r'https://vocus\.cc/article/[a-zA-Z0-9]+$', l)
        and l != INDEX_URL
    ))
    print(f"Found {len(links)} article links")
    return links


async def scrape_article(page, url: str) -> tuple[str, str, bool]:
    """Returns (title, content, is_paid)"""
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(3)

    # Scroll to trigger lazy load
    for _ in range(4):
        await page.evaluate("window.scrollBy(0, 600)")
        await asyncio.sleep(0.6)

    title = await page.title()
    title = title.replace(" - vocus", "").replace(" | vocus", "").strip()

    paid = await is_paid_content(page)

    if paid:
        return title, "", True

    # Extract article body text
    content = ""
    for sel in ["article", "main", '[class*="article-body"]', '[class*="content-body"]']:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                text = await el.inner_text()
                if len(text) > 300:
                    content = text
                    break
        except Exception:
            continue

    if not content:
        content = await page.locator("body").inner_text()

    return title, content, False


async def main():
    VOCUS_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-TW",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        await stealth_async(page)

        # Phase 1: get links from article body only
        links = await get_article_links(page)
        ARTICLE_URLS_FILE.write_text("\n".join(links), encoding="utf-8")
        print(f"Saved {len(links)} URLs to {ARTICLE_URLS_FILE}")

        # Phase 2: scrape each article
        saved = []
        failed = []
        skipped = []

        for i, url in enumerate(links, 1):
            print(f"\n[{i}/{len(links)}] {url}")
            try:
                title, content, is_paid = await scrape_article(page, url)

                if is_paid:
                    print(f"  ⊘ PAID - skipping: {title}")
                    skipped.append(f"{url}\t{title}")
                    SKIPPED_PAID_FILE.write_text("\n".join(skipped), encoding="utf-8")

                elif len(content.strip()) < 100:
                    print(f"  ✗ Too short: {title}")
                    failed.append(f"{url}\t{title}\t(too short)")
                    FAILED_URLS_FILE.write_text("\n".join(failed), encoding="utf-8")

                else:
                    filename = sanitize_filename(title) + ".md"
                    filepath = VOCUS_DIR / filename
                    filepath.write_text(
                        f"# {title}\n\nURL: {url}\n\n{content}",
                        encoding="utf-8",
                    )
                    print(f"  ✓ Saved: {filename} ({len(content)} chars)")
                    saved.append(url)

            except Exception as e:
                print(f"  ✗ ERROR: {e}")
                failed.append(f"{url}\t{str(e)[:120]}")
                FAILED_URLS_FILE.write_text("\n".join(failed), encoding="utf-8")

            await asyncio.sleep(2)

        await browser.close()

    print(f"\n{'='*50}")
    print(f"完成！")
    print(f"  ✓ 成功儲存: {len(saved)} 篇")
    print(f"  ⊘ 付費跳過: {len(skipped)} 篇")
    print(f"  ✗ 失敗:     {len(failed)} 篇")
    print(f"{'='*50}")


if __name__ == "__main__":
    asyncio.run(main())
