"""把 AI 分析 HTML 截成 PNG（給使用者預覽 UI 用，不用開瀏覽器）。

用法：
    python -m scripts.screenshot_ai_report
    python -m scripts.screenshot_ai_report --html reports/ai_analysis_demo.html --out reports/ai_analysis_demo.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def screenshot(html_path: Path, png_path: Path, *, width: int = 1000, full_page: bool = True) -> None:
    url = html_path.resolve().as_uri()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": width, "height": 1200},
            device_scale_factor=2,
        )
        page = ctx.new_page()
        page.goto(url)
        # 等 lightweight-charts 從 CDN 載完 + K 線 paint
        try:
            page.wait_for_function(
                "document.querySelector('#chart canvas') !== null",
                timeout=8000,
            )
        except Exception:
            page.wait_for_timeout(2500)
        page.wait_for_timeout(800)
        page.screenshot(path=str(png_path), full_page=full_page)
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="截 AI 分析 HTML 為 PNG")
    parser.add_argument("--html", default=str(_PROJECT_ROOT / "reports" / "ai_analysis_demo.html"))
    parser.add_argument("--out", default=str(_PROJECT_ROOT / "reports" / "ai_analysis_demo.png"))
    parser.add_argument("--width", type=int, default=1000)
    args = parser.parse_args()

    html_path = Path(args.html)
    if not html_path.exists():
        print(f"❌ HTML 不存在：{html_path}")
        return 1
    out = Path(args.out)
    screenshot(html_path, out, width=args.width)
    print(f"✅ 已截圖：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
