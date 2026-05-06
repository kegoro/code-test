"""
Content scrapers for Vocus and Threads.

Strategy: network-interception first (captures API JSON directly),
DOM fallback if no API response is captured.

Mirrors the pattern in scrapers/wantgoo/retail_ratio.py.
"""
import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from loguru import logger

from playwright.async_api import async_playwright, Page, Response, TimeoutError as PWTimeout
from playwright_stealth import stealth_async
from config.settings import settings

VOCUS_AUTHOR_URL   = "https://vocus.cc/user/@mystery"
THREADS_PROFILE_URL = "https://www.threads.com/@myeverydayhihi"

_DOCS       = Path("docs")
_VOCUS_DIR  = _DOCS / "vocus"
_THREADS_DIR = _DOCS / "threads"
_FAILED_LOG = _DOCS / "failed_urls.txt"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class VocusArticle:
    url:      str
    title:    str = ""
    date:     str = ""
    content:  str = ""
    is_paid:  bool = False


@dataclass
class ThreadsPost:
    text:      str
    timestamp: str = ""
    post_url:  str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*\n\r\t]', '_', s).strip()[:60] or "untitled"


def _log_failed(url: str, reason: str) -> None:
    _FAILED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_FAILED_LOG, "a", encoding="utf-8") as f:
        f.write(f"{url}\t{reason}\n")


async def _scroll_to_bottom(page: Page, pause: float = 2.5, max_rounds: int = 40) -> int:
    """Scroll until no new content loads. Returns number of scroll rounds."""
    prev_height = 0
    for i in range(max_rounds):
        h = await page.evaluate("document.body.scrollHeight")
        if h == prev_height:
            logger.debug(f"[scroll] Done after {i} rounds (height={h})")
            return i
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(pause)
        prev_height = h
    return max_rounds


async def _new_context(pw):
    browser = await pw.chromium.launch(headless=settings.playwright_headless)
    ctx = await browser.new_context(
        user_agent=_UA,
        viewport={"width": 1440, "height": 900},
        locale="zh-TW",
    )
    return browser, ctx


# ── Vocus Scraper ─────────────────────────────────────────────────────────────

class VocusScraper:
    """
    Two-pass scraper for Vocus:
      Pass 1 — intercept API responses on the author page to collect article metadata + URLs
      Pass 2 — for each URL, scrape full article text (intercept content API or DOM fallback)
    """

    def __init__(self, author_url: str = VOCUS_AUTHOR_URL):
        self.author_url = author_url
        self._api_articles: list[dict] = []   # captured from network

    async def scrape_all(self) -> list[VocusArticle]:
        _VOCUS_DIR.mkdir(parents=True, exist_ok=True)
        articles: list[VocusArticle] = []

        async with async_playwright() as pw:
            browser, ctx = await _new_context(pw)
            page = await ctx.new_page()
            await stealth_async(page)

            # ── Pass 1: collect article URLs ──
            urls = await self._collect_urls(page)
            logger.info(f"[vocus] {len(urls)} article URLs found")

            # ── Pass 2: scrape each article ──
            for i, url in enumerate(urls, 1):
                logger.info(f"[vocus] {i}/{len(urls)} {url}")
                art = await self._scrape_article(page, url)
                if art:
                    articles.append(art)
                    self._save(art)
                await asyncio.sleep(2.5)

            await browser.close()

        return articles

    async def _collect_urls(self, page: Page) -> list[str]:
        captured_urls: list[str] = []

        async def handle_resp(resp: Response):
            url = resp.url
            # Vocus API responses containing article lists
            if any(k in url for k in ("/api/", "vocus.cc/api", "graphql", "/articles", "/posts")):
                try:
                    body = await resp.json()
                    self._extract_urls_from_payload(body, captured_urls)
                except Exception:
                    pass

        page.on("response", handle_resp)

        try:
            await page.goto(self.author_url, wait_until="networkidle",
                            timeout=settings.playwright_timeout_ms)
            await asyncio.sleep(2)
            await _scroll_to_bottom(page, pause=2.0, max_rounds=30)
            await asyncio.sleep(2)
        except PWTimeout:
            logger.warning("[vocus] Timeout on author page")
            _log_failed(self.author_url, "timeout")
        except Exception as exc:
            logger.error(f"[vocus] Author page error: {exc}")
            _log_failed(self.author_url, str(exc))

        # API might not have fired — also extract from DOM
        dom_urls = await self._dom_article_urls(page)
        for u in dom_urls:
            if u not in captured_urls:
                captured_urls.append(u)

        return captured_urls

    def _extract_urls_from_payload(self, payload, out: list[str]) -> None:
        """Recursively scan JSON payload for article URLs."""
        if isinstance(payload, dict):
            # Common API fields
            for key in ("url", "link", "slug", "id", "articleId"):
                val = payload.get(key, "")
                if isinstance(val, str) and "/article/" in val:
                    full = val if val.startswith("http") else f"https://vocus.cc{val}"
                    if full not in out:
                        out.append(full)
                elif isinstance(val, str) and len(val) > 5 and key in ("slug", "id", "articleId"):
                    candidate = f"https://vocus.cc/article/{val}"
                    if candidate not in out:
                        out.append(candidate)
            for v in payload.values():
                if isinstance(v, (dict, list)):
                    self._extract_urls_from_payload(v, out)
        elif isinstance(payload, list):
            for item in payload:
                self._extract_urls_from_payload(item, out)

    async def _dom_article_urls(self, page: Page) -> list[str]:
        urls = []
        seen = set()
        try:
            links = await page.query_selector_all("a[href*='/article/']")
            for link in links:
                href = await link.get_attribute("href")
                if href:
                    full = href if href.startswith("http") else f"https://vocus.cc{href}"
                    if full not in seen:
                        seen.add(full)
                        urls.append(full)
        except Exception as exc:
            logger.debug(f"[vocus] DOM URL extraction: {exc}")
        return urls

    async def _scrape_article(self, page: Page, url: str) -> VocusArticle | None:
        captured_content: list[dict] = []

        async def handle_resp(resp: Response):
            rurl = resp.url
            if any(k in rurl for k in ("/api/", "graphql")) and "article" in rurl.lower():
                try:
                    body = await resp.json()
                    captured_content.append(body)
                except Exception:
                    pass

        page.on("response", handle_resp)

        try:
            await page.goto(url, wait_until="networkidle",
                            timeout=settings.playwright_timeout_ms)
            await asyncio.sleep(1.5)
        except PWTimeout:
            logger.warning(f"[vocus] Timeout: {url}")
            _log_failed(url, "timeout")
            return None
        except Exception as exc:
            logger.error(f"[vocus] Error: {url} — {exc}")
            _log_failed(url, str(exc))
            return None

        # Check paywall
        is_paid = False
        for sel in ["[class*='lock']", "[class*='paywall']", "[class*='subscribe']",
                    "[class*='premium']", ".monetize", "[data-locked]"]:
            try:
                el = await page.query_selector(sel)
                if el:
                    is_paid = True
                    break
            except Exception:
                pass

        # Extract title
        title = await self._extract_text(page, [
            "h1", ".article-title", "[class*='articleTitle']",
            "[class*='title']", "header h1",
        ])

        # Extract date
        date_str = await self._extract_text(page, [
            "time", "[class*='date']", "[class*='publishTime']",
            "[datetime]", "[class*='time']",
        ])

        # Extract content — try article body first
        content = await self._extract_text(page, [
            "[class*='articleBody']", "[class*='article-body']",
            "[class*='content']", "article", ".vocus-content",
            "[class*='richText']", "main",
        ], min_len=200)

        # Fallback: captured API data
        if not content and captured_content:
            content = json.dumps(captured_content, ensure_ascii=False)

        # Last fallback: body text (minus nav)
        if not content:
            try:
                content = await page.inner_text("body")
            except Exception:
                content = ""

        if not title and not content:
            _log_failed(url, "empty")
            return None

        return VocusArticle(
            url=url,
            title=title or url.split("/")[-1],
            date=date_str,
            content=content,
            is_paid=is_paid,
        )

    async def _extract_text(self, page: Page, selectors: list[str], min_len: int = 0) -> str:
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text and len(text) >= min_len:
                        return text
            except Exception:
                continue
        return ""

    def _save(self, art: VocusArticle) -> None:
        article_id = art.url.rstrip("/").split("/")[-1]
        fname = f"{article_id}_{_safe_name(art.title)}.md"
        path = _VOCUS_DIR / fname
        paid_notice = "\n> ⚠️ 付費文章，內容可能不完整\n" if art.is_paid else ""
        md = f"# {art.title}\n\n**日期**: {art.date}\n**URL**: {art.url}\n{paid_notice}\n---\n\n{art.content}\n"
        path.write_text(md, encoding="utf-8")
        logger.info(f"[vocus] Saved → {path.name} ({len(art.content):,} chars)")


# ── Threads Scraper ───────────────────────────────────────────────────────────

class ThreadsScraper:
    """
    Scrapes posts from a Threads public profile.
    Uses network interception to capture the GraphQL/API payload,
    with DOM scroll + extraction as fallback.
    """

    def __init__(self, profile_url: str = THREADS_PROFILE_URL):
        self.profile_url = profile_url
        self._login_wall = False

    async def scrape_all(self) -> list[ThreadsPost]:
        _THREADS_DIR.mkdir(parents=True, exist_ok=True)
        posts: list[ThreadsPost] = []

        async with async_playwright() as pw:
            browser, ctx = await _new_context(pw)
            page = await ctx.new_page()
            await stealth_async(page)

            captured_api: list[dict] = []

            async def handle_resp(resp: Response):
                rurl = resp.url
                if any(k in rurl for k in ("graphql", "/api/", "threads.net/api",
                                            "instagram.com/api", "threads_post")):
                    try:
                        body = await resp.json()
                        captured_api.append({"url": rurl, "body": body})
                    except Exception:
                        pass

            page.on("response", handle_resp)

            try:
                await page.goto(self.profile_url, wait_until="networkidle",
                                timeout=settings.playwright_timeout_ms)
                await asyncio.sleep(3)

                # Detect login wall
                for login_sel in ["input[name='username']", "input[type='password']",
                                   "[href*='/login']", "[class*='login']"]:
                    el = await page.query_selector(login_sel)
                    if el:
                        self._login_wall = True
                        logger.warning("[threads] ⚠️  Login wall detected — scraping visible content only")
                        _log_failed(self.profile_url, "login_wall")
                        break

                # Scroll to load more posts
                await _scroll_to_bottom(page, pause=2.5, max_rounds=40)
                await asyncio.sleep(2)

                # Try API data first
                if captured_api:
                    posts = self._parse_api_data(captured_api)
                    logger.info(f"[threads] {len(posts)} posts from API interception")

                # Fallback: DOM extraction
                if not posts:
                    posts = await self._dom_extract_posts(page)
                    logger.info(f"[threads] {len(posts)} posts from DOM")

            except Exception as exc:
                logger.error(f"[threads] Failed: {exc}")
                _log_failed(self.profile_url, str(exc))
            finally:
                await browser.close()

        if posts:
            self._save(posts)
        return posts

    def _parse_api_data(self, captured: list[dict]) -> list[ThreadsPost]:
        """Recursively search API payloads for post text."""
        posts = []
        seen = set()

        def walk(obj, depth=0):
            if depth > 10:
                return
            if isinstance(obj, dict):
                # Common Threads/Instagram post fields
                text = (
                    obj.get("text_post_app_body", {}).get("text") or
                    obj.get("caption", {}).get("text") if isinstance(obj.get("caption"), dict) else None or
                    obj.get("text") or
                    obj.get("body") or
                    obj.get("message") or
                    ""
                )
                if isinstance(text, str) and len(text.strip()) > 5:
                    t = text.strip()
                    if t not in seen:
                        seen.add(t)
                        posts.append(ThreadsPost(text=t))
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        walk(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item, depth + 1)

        for item in captured:
            walk(item.get("body", {}))

        return posts

    async def _dom_extract_posts(self, page: Page) -> list[ThreadsPost]:
        """DOM fallback — extract visible post text."""
        posts = []
        seen = set()

        # Try multiple selectors that Threads might use
        candidate_selectors = [
            # Threads-specific
            "[data-pressable-container='true'] span[dir='auto']",
            "[class*='x1lliihq'] span",
            "article span[dir='auto']",
            # Generic
            "[role='article'] p",
            "[role='article'] span",
            "main p",
        ]

        for sel in candidate_selectors:
            els = await page.query_selector_all(sel)
            if not els:
                continue
            for el in els:
                try:
                    text = (await el.inner_text()).strip()
                    if (len(text) > 10 and text not in seen and
                            text not in {"Follow", "Following", "Log in", "Sign up",
                                         "Threads", "More", "Like", "Reply", "Repost"}):
                        seen.add(text)
                        posts.append(ThreadsPost(text=text))
                except Exception:
                    continue
            if posts:
                break

        return posts

    def _save(self, posts: list[ThreadsPost]) -> None:
        # Single combined file for all posts
        path = _THREADS_DIR / "threads_posts.md"
        lines = [f"# Threads 貼文 @myeverydayhihi\n\n共 {len(posts)} 則\n\n"]
        for i, p in enumerate(posts, 1):
            lines.append(f"## Post {i}\n\n{p.text}\n\n---\n\n")
        path.write_text("".join(lines), encoding="utf-8")
        logger.info(f"[threads] Saved → {path} ({len(posts)} posts)")

        # Also save as JSON for easier programmatic access
        json_path = _THREADS_DIR / "threads_posts.json"
        data = [{"index": i, "text": p.text} for i, p in enumerate(posts, 1)]
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[threads] JSON saved → {json_path}")

        if self._login_wall:
            (_THREADS_DIR / "LOGIN_WALL_NOTICE.txt").write_text(
                "Threads 偵測到登入牆，只抓取了頁面可見的部分內容。\n"
                "若要完整抓取，請使用已登入的 session cookies。\n",
                encoding="utf-8",
            )
