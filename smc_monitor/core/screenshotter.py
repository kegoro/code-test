# ============================================================
#  core/screenshotter.py
#  TradingView 自動截圖模組（Playwright）
# ============================================================

import asyncio
import time
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from config.settings import TV_BASE_URL, TV_USERNAME, TV_PASSWORD

SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# TradingView Interval mapping
INTERVAL_MAP = {
    "1":  "1",
    "5":  "5",
    "15": "15",
    "30": "30",
    "60": "60",   # 1H
    "D":  "1D",
    "W":  "1W",
}

class TVScreenshotter:
    """
    無頭瀏覽器開啟 TradingView，截取指定股票圖表截圖。
    
    特色：
    - 自動等待圖表完全渲染（偵測 canvas 元素）
    - 移除廣告/彈窗干擾
    - 裁切只保留圖表區域（去除工具列）
    - 支援多時間框架同時截圖
    - 截圖帶有 timestamp 自動命名
    """

    def __init__(self):
        self._browser = None
        self._context = None
        self._page = None
        self._logged_in = False

    async def start(self):
        """啟動瀏覽器（整個 session 只啟動一次）"""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",  # 防止被偵測為 bot
            ]
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="zh-TW",
        )
        self._page = await self._context.new_page()

        # 如果有帳號，自動登入（解鎖更多指標）
        if TV_USERNAME and TV_PASSWORD:
            await self._login()

    async def _login(self):
        """登入 TradingView（支援自訂指標與 Webhook Alert）"""
        page = self._page
        await page.goto("https://www.tradingview.com/signin/", wait_until="networkidle")
        await page.fill('input[name="username"]', TV_USERNAME)
        await page.fill('input[name="password"]', TV_PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        self._logged_in = True

    async def capture(self, symbol: str, interval: str = "1") -> dict:
        """
        截取指定股票、時間框架的圖表。
        
        Returns:
            {
                "symbol": "3481",
                "interval": "1",
                "path": Path("screenshots/3481_1m_20260514_1053.png"),
                "timestamp": "2026-05-14T10:53:00",
                "url": "https://www.tradingview.com/chart/...",
            }
        """
        page = self._page
        tv_interval = INTERVAL_MAP.get(str(interval), "1")

        # 台股加 TWSE: prefix；美股直接用代碼
        if symbol.isdigit():
            tv_symbol = f"TWSE:{symbol}"
        elif symbol.upper().endswith(".TW"):
            tv_symbol = f"TWSE:{symbol[:-3]}"
        else:
            tv_symbol = symbol.upper()   # AAPL, TSLA, etc.

        url = f"https://www.tradingview.com/chart/?symbol={tv_symbol}&interval={tv_interval}"
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # 等待圖表 canvas 渲染完成
        await self._wait_for_chart(page)

        # 關閉各種干擾彈窗
        await self._dismiss_popups(page)

        # 截取整個圖表區域（去除左側工具列和頂部導覽）
        clip = await self._get_chart_bounds(page)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{symbol}_{tv_interval}m_{timestamp}.png"
        filepath = SCREENSHOT_DIR / filename

        await page.screenshot(path=str(filepath), clip=clip, type="png")

        return {
            "symbol": symbol,
            "interval": interval,
            "path": filepath,
            "timestamp": datetime.now().isoformat(),
            "url": url,
        }

    async def capture_multi_timeframe(self, symbol: str, intervals: list = ["1", "5", "15"]) -> list:
        """同時截取多個時間框架"""
        results = []
        for interval in intervals:
            try:
                result = await self.capture(symbol, interval)
                results.append(result)
                await asyncio.sleep(1.5)  # 避免過快請求
            except Exception as e:
                print(f"[Screenshotter] {symbol} {interval}m 截圖失敗: {e}")
        return results

    async def _wait_for_chart(self, page, timeout=15000):
        """等待 TradingView 圖表 canvas 完全載入"""
        try:
            # 等待主圖 canvas 出現
            await page.wait_for_selector(
                'canvas[class*="chart"]',
                timeout=timeout
            )
            # 額外等待 K 線渲染（TV 是非同步繪製）
            await asyncio.sleep(3)
        except PWTimeout:
            # 如果超時就直接截圖（可能還是有部分資料）
            await asyncio.sleep(2)

    async def _dismiss_popups(self, page):
        """關閉各種彈出視窗"""
        dismiss_selectors = [
            '[data-name="accept-cookies"]',
            'button:has-text("Accept")',
            'button:has-text("Got it")',
            '[aria-label="Close"]',
            '.tv-dialog__close',
        ]
        for sel in dismiss_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    await asyncio.sleep(0.3)
            except Exception:
                pass

    async def _get_chart_bounds(self, page) -> dict:
        """取得圖表區域的邊界框（排除工具列）"""
        try:
            # 嘗試取得圖表容器的邊界
            chart_el = page.locator('.chart-container').first
            box = await chart_el.bounding_box()
            if box:
                return {
                    "x": box["x"],
                    "y": box["y"],
                    "width": box["width"],
                    "height": box["height"],
                }
        except Exception:
            pass

        # Fallback: 截全頁面，裁掉左側工具列（約 45px）和頂部導覽（約 52px）
        return {"x": 45, "y": 52, "width": 1395, "height": 848}

    async def stop(self):
        """關閉瀏覽器"""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()
