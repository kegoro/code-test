"""截 AI 分析 HTML 在「全部維度展開」狀態的 PNG，給 UI 確認用。

用法：
    python -m scripts.screenshot_ai_report_expanded \
        --html reports/ai_real_4916_v2.html \
        --out reports/ai_real_4916_v2_expanded.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def screenshot_expanded(html_path: Path, png_path: Path, *, width: int = 1000) -> None:
    url = html_path.resolve().as_uri()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": width, "height": 1400}, device_scale_factor=2)
        page = ctx.new_page()
        page.goto(url)
        try:
            page.wait_for_function(
                "document.querySelector('#chart canvas') !== null",
                timeout=8000,
            )
        except Exception:
            page.wait_for_timeout(2500)
        # 點開 5 個維度
        page.evaluate(
            "document.querySelectorAll('.dim .dim-row').forEach(r => r.click())"
        )
        page.wait_for_timeout(800)
        page.screenshot(path=str(png_path), full_page=True)
        browser.close()
    print(f"✅ 已截圖（展開狀態）：{png_path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", default=str(_PROJECT_ROOT / "reports" / "ai_real_4916_v2.html"))
    parser.add_argument("--out", default=str(_PROJECT_ROOT / "reports" / "ai_real_4916_v2_expanded.png"))
    args = parser.parse_args()
    screenshot_expanded(Path(args.html), Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
