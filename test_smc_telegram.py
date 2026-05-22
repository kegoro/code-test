"""Fire-and-forget SMC report push to Telegram.

Usage:
    python test_smc_telegram.py            # default 2330
    python test_smc_telegram.py 2317
    python test_smc_telegram.py 2330 2317 2382  # multiple symbols

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from .env.local.
For each symbol: runs SMC detection, builds the upgraded HTML report,
sends summary text + HTML attachment to your chat.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from backend.shioaji_fetcher import (
    shioaji_fetch_daily, shioaji_fetch_m1, shioaji_fetch_m3,
)
from backend.smc_detector import SMCSignal, detect_signals
from backend.smc_report import generate_html, render_chart_png
from backend.smc_scanner import SMCScanner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("smc-tg-test")

_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env.local")


def _fmt_zone(z: Optional[dict]) -> str:
    if not z:
        return "—"
    return f"{z['bottom']:.2f}–{z['top']:.2f}"


def _summary(s: SMCSignal) -> str:
    stars = "★" * max(1, min(s.strength, 3))
    return (
        f"📐 SMC 訊號｜{s.symbol}\n"
        f"訊號：{s.signal_type}\n"
        f"時框：{s.timeframe}\n"
        f"價位：{s.price:.2f}\n"
        f"日線結構：{s.market_structure}\n"
        f"需求區：{_fmt_zone(s.demand_zone)}\n"
        f"供給區：{_fmt_zone(s.supply_zone)}\n"
        f"強度：{stars}\n"
        f"⏱ event @ {s.timestamp.strftime('%Y-%m-%d %H:%M')}"
    )


async def _push_one(bot, chat_id: str, symbol: str, *, use_1m: bool = False,
                    days: int = 5) -> None:
    """Run a scanner pass for `symbol` and push results."""
    daily = await shioaji_fetch_daily(symbol, lookback=60)

    if use_1m:
        intraday = await shioaji_fetch_m1(symbol, days=days)
        tf_label = "1m"
        swing_n_for_signal = 10
    else:
        intraday = await shioaji_fetch_m3(symbol)
        tf_label = "3m"
        swing_n_for_signal = 3

    # Direct detection on the intraday frame (skip scanner cooldown for verify run).
    signals: list[SMCSignal] = []
    if intraday is not None and not intraday.empty:
        signals = detect_signals(intraday, symbol, tf_label, n=swing_n_for_signal)
    if not signals and daily is not None and not daily.empty:
        signals = detect_signals(daily, symbol, "1D", n=5)

    m3 = intraday  # variable kept for downstream code reusing the name

    if not signals:
        text = (
            f"📭 {symbol}：目前無 SMC 訊號（結構為 ranging 或資料不足）。\n"
            f"附上含 K 線 + FVG/EQH/Strong-Weak 標記的觀察用報告。"
        )
        await bot.send_message(chat_id=chat_id, text=text)
        # Build a placeholder signal so user can still see the chart.
        placeholder = SMCSignal(
            symbol=symbol,
            timeframe="1D" if (m3 is None or m3.empty) else "3m",
            signal_type="BOS_UP",   # placeholder; ignored visually
            price=float((daily if not daily.empty else m3)["close"].iloc[-1]),
            market_structure="ranging",
            timestamp=(daily.index[-1].to_pydatetime() if not daily.empty else None),  # type: ignore[arg-type]
            strength=1,
            meta={"placeholder": True},
        )
        html = generate_html(placeholder, daily_df=daily, intraday_df=m3,
                             fallback_to_daily=(m3 is None or m3.empty))
        bio = BytesIO(html.encode("utf-8"))
        bio.name = f"smc_{symbol}_observation.html"
        await bot.send_document(chat_id=chat_id, document=bio)
        return

    for s in signals:
        await bot.send_message(chat_id=chat_id, text=_summary(s))

        # 1) Static PNG chart — renders inline in the Telegram chat itself.
        try:
            chart_df = m3 if (m3 is not None and not m3.empty) else daily
            if s.timeframe == "1m":
                internal_n, swing_n, figsize = 5, 15, (20, 7)
            elif s.timeframe in ("3m", "5m"):
                internal_n, swing_n, figsize = 3, 8, (12, 6)
            else:
                internal_n, swing_n, figsize = 5, 12, (12, 6)
            png_bytes = render_chart_png(
                chart_df, signal=s,
                internal_n=internal_n, swing_n=swing_n,
                figsize=figsize, daily_df=daily,
            )
            if png_bytes:
                png_bio = BytesIO(png_bytes)
                png_bio.name = f"smc_{s.symbol}_{s.signal_type}.png"
                await bot.send_photo(chat_id=chat_id, photo=png_bio,
                                     caption=f"{s.symbol}｜{s.signal_type}｜{s.timeframe}")
        except Exception:
            logger.exception("PNG send failed for %s", s.symbol)

        # 2) Interactive HTML (lightweight-charts) with PNG fallback baked in.
        html = generate_html(
            s,
            daily_df=daily,
            intraday_df=m3,
            fallback_to_daily=(s.timeframe == "1D" and (m3 is None or m3.empty)),
        )
        bio = BytesIO(html.encode("utf-8"))
        bio.name = f"smc_{s.symbol}_{s.signal_type}.html"
        await bot.send_document(chat_id=chat_id, document=bio)


async def _run(symbols: list[str], *, use_1m: bool, days: int) -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing in .env.local")
        return 2

    from telegram import Bot
    bot = Bot(token=token)

    tf_label = f"1m × {days} 個交易日" if use_1m else "3m × 今日"
    await bot.send_message(
        chat_id=chat,
        text=(
            "🧪 SMC 報告驗收\n"
            f"時間框架：{tf_label}\n"
            "新增：Internal vs Swing、FVG、EQH/EQL、Strong/Weak\n"
            f"觀察清單：{', '.join(symbols)}"
        ),
    )

    for sym in symbols:
        try:
            await _push_one(bot, chat, sym, use_1m=use_1m, days=days)
        except Exception as exc:
            logger.exception("push %s failed", sym)
            await bot.send_message(chat_id=chat, text=f"⚠ {sym} 推播失敗：{exc!r}")

    await bot.send_message(chat_id=chat, text="✅ 全部推完了。")
    return 0


def main() -> int:
    raw_args = sys.argv[1:] or ["2330"]
    use_1m = False
    days = 5
    args: list[str] = []
    i = 0
    while i < len(raw_args):
        a = raw_args[i]
        if a == "--1m":
            use_1m = True
        elif a == "--3m":
            use_1m = False
        elif a == "--days" and i + 1 < len(raw_args):
            days = int(raw_args[i + 1])
            i += 1
        else:
            args.append(a)
        i += 1
    if not args:
        args = ["2330"]
    return asyncio.run(_run(args, use_1m=use_1m, days=days))


if __name__ == "__main__":
    raise SystemExit(main())
