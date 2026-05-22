"""Demo AI 分析報告 — 產出 HTML 給使用者預覽外觀。

無需任何 API token：用合成資料模擬「事欣科 (4916)」截圖中的數字。
之後接到 Shioaji / FinMind 真實資料時，只需把 build_demo_data() 換掉即可。

用法：
    python -m scripts.demo_ai_report
    python -m scripts.demo_ai_report --out reports/ai_demo.html
    python -m scripts.demo_ai_report --symbol 2330 --name "台積電"

預設輸出：reports/ai_analysis_demo.html
"""
from __future__ import annotations

import argparse
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from backend.ai_analysis_engine import build_result
from backend.ai_analysis_report import render_html


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _synth_daily(
    *,
    days: int = 64,
    start_price: float = 67.7,
    end_price: float = 74.40,
    seed: int = 4916,
) -> pd.DataFrame:
    """合成近 days 天的日線 OHLCV，整體從 start → end（接近圖中 +9.90%）。"""
    rng = random.Random(seed)
    closes: list[float] = []
    base = start_price
    drift = (end_price - start_price) / days
    for i in range(days):
        # 主漂移 + 隨機波動，最後一根接近 end_price
        noise = rng.uniform(-1.5, 1.5)
        if i == days - 1:
            base = end_price
        else:
            base = max(1.0, base + drift + noise)
        closes.append(round(base, 2))

    rows = []
    now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    # 從 days 個交易日前算起（簡化：用日曆日，跳週末）
    cursor = now - timedelta(days=days)
    for i, c in enumerate(closes):
        cursor = cursor + timedelta(days=1)
        # 跳過週末
        while cursor.weekday() >= 5:
            cursor = cursor + timedelta(days=1)
        prev = closes[i - 1] if i > 0 else c
        open_p = round(prev + rng.uniform(-0.6, 0.6), 2)
        high = round(max(open_p, c) + rng.uniform(0.1, 1.4), 2)
        low = round(min(open_p, c) - rng.uniform(0.1, 1.4), 2)
        volume = rng.randint(3_000_000, 12_000_000)
        rows.append({
            "open": open_p, "high": high, "low": low, "close": c,
            "volume": volume,
        })
    idx = pd.DatetimeIndex([
        (now - timedelta(days=days)) + timedelta(days=i + 1)
        for i in range(days)
    ])
    df = pd.DataFrame(rows, index=idx)
    df.index.name = "timestamp"
    return df


def _synth_m3(
    *,
    bars: int = 90,
    base_price: float = 74.40,
    seed: int = 49160,
) -> pd.DataFrame:
    """合成今日 M3 盤中（09:00 起算 90 根 = 4.5 小時）。"""
    rng = random.Random(seed)
    now = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    rows = []
    price = base_price * 0.985
    for i in range(bars):
        ts = now + timedelta(minutes=i * 3)
        # 上下震 + 慢慢拉
        drift = (base_price - price) * 0.05
        price = max(1.0, price + drift + rng.uniform(-0.18, 0.20))
        open_p = round(price - rng.uniform(-0.10, 0.10), 2)
        high = round(max(open_p, price) + rng.uniform(0.02, 0.16), 2)
        low = round(min(open_p, price) - rng.uniform(0.02, 0.16), 2)
        close = round(price, 2)
        vol = rng.randint(40_000, 220_000)
        rows.append({
            "open": open_p, "high": high, "low": low, "close": close,
            "volume": vol,
        })
    idx = pd.DatetimeIndex([
        now + timedelta(minutes=i * 3) for i in range(bars)
    ])
    df = pd.DataFrame(rows, index=idx)
    df.index.name = "timestamp"
    return df


def _scores_matching_screenshot() -> tuple[float, float, float, float, float]:
    """完全對應使用者提供的截圖（事欣科 4916）的分數。"""
    # 籌碼面 90 / 技術面 75 / 新聞面 85 / 基本面 80 / 題材面 70
    return (90.0, 75.0, 85.0, 80.0, 70.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 AI 分析 HTML 預覽")
    parser.add_argument("--symbol", default="4916")
    parser.add_argument("--name", default="事欣科")
    parser.add_argument(
        "--out",
        default=str(_PROJECT_ROOT / "reports" / "ai_analysis_demo.html"),
    )
    parser.add_argument(
        "--screenshot-exact", action="store_true", default=True,
        help="使用截圖一模一樣的分數（90/75/85/80/70）",
    )
    args = parser.parse_args()

    daily = _synth_daily()
    m3 = _synth_m3(base_price=float(daily["close"].iloc[-1]))

    scores = _scores_matching_screenshot() if args.screenshot_exact else None
    result = build_result(
        symbol=args.symbol,
        stock_name=args.name,
        daily_df=daily,
        m3_df=m3,
        scores=scores,
    )

    html = render_html(result)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    print(f"✅ 已產生 demo HTML: {out_path}")
    print(f"   股票：{result.stock_name} ({result.symbol})")
    print(f"   末價：{result.last_close:.2f}  期間漲跌：{result.pct_change_daily:+.2f}%")
    print(f"   AI 綜合評分：{result.overall_score:.1f} → {result.overall_verdict}")
    print(f"   籌碼面 {result.chip.score:.1f} ({result.chip.weight_pct}%)")
    print(f"   技術面 {result.technical.score:.1f} ({result.technical.weight_pct}%)")
    print(f"   新聞面 {result.news.score:.1f} ({result.news.weight_pct}%)")
    print(f"   基本面 {result.fundamental.score:.1f} (參考)")
    print(f"   題材面 {result.theme.score:.1f} (參考)")
    print(f"\n📄 用瀏覽器開啟以上 HTML 即可預覽")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
