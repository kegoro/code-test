"""Run a 30-day SMC analyst backtest on a watchlist, then push the
HTML + summary text to Telegram.

Usage:
    python run_30day_backtest.py                          # full default
    python run_30day_backtest.py --days 10 --step 5       # smaller / faster
    python run_30day_backtest.py 2330 2454 --days 30      # custom symbols
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv

from backend.smc_analyst.backtest import (
    BacktestReport, backtest_symbol, write_report,
)
from backend.smc_analyst.backtest_report import (
    _aggregate, _per_setup, _per_symbol, generate_backtest_html,
)

_DEFAULT_SYMBOLS = ["2330", "2317", "2382", "2454", "2308"]
_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env.local")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("smc-30d")


def _short_summary(reports: list[BacktestReport]) -> str:
    """Compact text summary for the Telegram preview message."""
    sigs = []
    for r in reports:
        sigs.extend(r.signals)
    agg = _aggregate(reports)
    lines = [
        "🔬 SMC 30 天回測 — 完工",
        f"📊 {agg['fires']} 個訊號  ·  WR {agg['win_rate']*100:.1f}%  ·  "
        f"R:R {agg['avg_rr']:.2f}  ·  期望值 {agg['expectancy']:+.2f}R/訊號",
        f"已結算：{agg['wins']} 勝 / {agg['losses']} 敗 / {agg['opens']} 未結算",
        f"累計 R = {agg['total_R']:+.1f}",
        "",
        "🥇 表現最好 (sorted by expectancy):",
    ]
    setups = _per_setup(sigs)
    for s in setups[:5]:
        if s["fires"] == 0:
            continue
        lines.append(
            f"  • {s['name']:30s}  n={s['fires']:2d}  "
            f"WR={s['win_rate']*100:.0f}%  EV={s['expectancy']:+.2f}R"
        )

    lines += ["", "📈 By Symbol:"]
    for r in _per_symbol(reports):
        lines.append(
            f"  • {r['symbol']}  n={r['fires']:2d}  "
            f"WR={r['win_rate']*100:.0f}%  EV={r['expectancy']:+.2f}R"
        )

    lines += ["", "📎 HTML 報告附件（用 Chrome 開含 equity curve）"]
    return "\n".join(lines)


async def _push_to_telegram(html: str, summary: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        logger.error("TELEGRAM creds missing; skipping push")
        return
    from telegram import Bot
    bot = Bot(token=token)
    await bot.send_message(chat_id=chat, text=summary)
    bio = BytesIO(html.encode("utf-8"))
    bio.name = "smc_backtest_30d.html"
    await bot.send_document(chat_id=chat, document=bio, filename=bio.name)
    logger.info("telegram push complete")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="*", default=_DEFAULT_SYMBOLS)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--step", type=int, default=10)
    parser.add_argument("--out-dir", type=Path, default=Path("reports"))
    parser.add_argument("--no-telegram", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    reports: list[BacktestReport] = []
    for sym in args.symbols:
        logger.info("=== %s (days=%d, step=%d) ===", sym, args.days, args.step)
        r = await backtest_symbol(sym, days=args.days, step=args.step)
        logger.info("  → fires=%d  wins=%d  losses=%d  opens=%d  EV=%+.2fR",
                    r.fires, r.wins, r.losses, r.opens, r.expectancy)
        reports.append(r)
        write_report(r, args.out_dir)

    dt = time.time() - t0
    logger.info("backtest finished in %.1fs", dt)

    html = generate_backtest_html(reports, days_label=f"{args.days} days")
    html_path = args.out_dir / f"smc_backtest_{args.days}d.html"
    html_path.write_text(html, encoding="utf-8")
    logger.info("HTML → %s", html_path)

    summary = _short_summary(reports)
    print("\n" + summary)
    print(f"\nHTML written to {html_path}")

    if not args.no_telegram:
        await _push_to_telegram(html, summary)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
