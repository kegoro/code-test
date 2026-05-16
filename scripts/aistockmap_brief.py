"""獨立 script — 抓 aistockmap → 過濾 → 推 Telegram。

用途：給 Windows 工作排程器（schtasks）排定 22:00 / 08:30 自動跑，
不依賴 smc_bot 進程是否在跑。每次跑完即退出。

用法：
  python scripts/aistockmap_brief.py [--slot=morning|evening]

如果指定 slot，會用 alert_state 去重：同一天同一 slot 內不會重複推。
不指定就強制推（不去重，方便手動測試）。

設定 Windows 工作排程器（PowerShell，請以系統管理員身份執行）：

  $py = (Get-Command python).Source
  $proj = "C:\\Users\\sfudally\\Desktop\\code test"
  schtasks /create /tn "aistockmap-brief-morning" /tr "`"$py`" `"$proj\\scripts\\aistockmap_brief.py`" --slot=morning" /sc DAILY /st 08:30 /f
  schtasks /create /tn "aistockmap-brief-evening" /tr "`"$py`" `"$proj\\scripts\\aistockmap_brief.py`" --slot=evening" /sc DAILY /st 22:00 /f

刪除：
  schtasks /delete /tn "aistockmap-brief-morning" /f
  schtasks /delete /tn "aistockmap-brief-evening" /f
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger("aistockmap-brief")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env.local")

_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


async def _run(slot: str | None) -> int:
    """跑一次完整流程：抓 → 過濾 → 推 telegram。Returns exit code."""
    if not _BOT_TOKEN or not _CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 未設於 .env.local")
        return 1

    # Lazy imports — 讓 --help 不必等 Playwright 載入
    sys.path.insert(0, str(_PROJECT_ROOT))
    from telegram import Bot

    from backend import alert_state
    from backend.aistockmap_report import render as render_html
    from backend.aistockmap_scraper import fetch_daily
    from backend.theme_filter import filter_focus_items, format_short_summary

    # Dedup — 同一天同一 slot 不重推
    today = datetime.now().date().isoformat()
    if slot:
        dedup_key = f"aistockmap_brief:{today}:{slot}"
        if not alert_state.should_push(dedup_key, within_minutes=60 * 6):
            logger.info("已在 6h 內推過 (key=%s)，本次跳過", dedup_key)
            return 0

    logger.info("抓 aistockmap…")
    digest = await fetch_daily()
    filtered = filter_focus_items(digest.focus_items)
    summary = format_short_summary(filtered)
    summary = (
        f"⏰ 盤前題材簡報（{slot or 'manual'}, {today}）\n\n" + summary
        + "\n\n💡 看完後請挑感興趣的股號加入今日 watchlist：\n  /wl_add 2330 2317 ..."
    )

    logger.info("推 telegram…")
    bot = Bot(token=_BOT_TOKEN)
    async with bot:
        await bot.send_message(chat_id=_CHAT_ID, text=summary)
        html = render_html(digest, filtered)
        bio = BytesIO(html.encode("utf-8"))
        bio.name = f"aistockmap_{slot or 'manual'}_{today}.html"
        await bot.send_document(chat_id=_CHAT_ID, document=bio)

    if slot:
        alert_state.mark_pushed(dedup_key)
    logger.info("done")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--slot",
        choices=["morning", "evening"],
        default=None,
        help="排程 slot 標識（用於 dedup）；不指定則強制推送",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args.slot)))


if __name__ == "__main__":
    main()
