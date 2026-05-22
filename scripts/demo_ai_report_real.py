"""端到端 demo：跑真實的 5 維度評分 + 真實資料（Shioaji / FinMind / aistockmap）。

跟 demo_ai_report.py 不同：
  - demo_ai_report.py：純合成資料、固定分數，用於 UI 預覽
  - demo_ai_report_real.py：呼叫 ai_analysis_orchestrator.analyse() 跑完整流程

aistockmap 跑 Playwright 約 10 秒；Shioaji 需登入。任何一項失敗會 fallback 到 mock。

用法：
    python -m scripts.demo_ai_report_real            # 預設 2330
    python -m scripts.demo_ai_report_real 4916
    python -m scripts.demo_ai_report_real 2330 --out reports/ai_real.html
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from backend.ai_analysis_orchestrator import analyse
from backend.ai_analysis_report import render_html


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def _run(symbol: str, out: Path) -> None:
    print(f"🧠 跑 AI 分析 {symbol} …（約 10-20 秒，看 aistockmap / Shioaji 反應）")
    result = await analyse(symbol)

    print(f"\n✅ 股票：{result.stock_name} ({result.symbol})")
    print(f"   末價：{result.last_close:.2f}  期間漲跌：{result.pct_change_daily:+.2f}%")
    print(f"   AI 綜合評分：{result.overall_score:.1f} → {result.overall_verdict}")
    print(f"   籌碼面 {result.chip.score:.1f}")
    print(f"   技術面 {result.technical.score:.1f}")
    print(f"   新聞面 {result.news.score:.1f}")
    print(f"   基本面 {result.fundamental.score:.1f}（參考）")
    print(f"   題材面 {result.theme.score:.1f}（參考）")

    html = render_html(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"\n📄 HTML：{out}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", nargs="?", default="2330")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    out = Path(args.out) if args.out else _PROJECT_ROOT / "reports" / f"ai_real_{args.symbol}.html"
    asyncio.run(_run(args.symbol, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
