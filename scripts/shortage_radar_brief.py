"""獨立 script — 缺貨雷達：抓 aistockmap → 三階段強度評分 → 推 Telegram。

聚焦雷老闆原則 A「缺貨哲學」，把每日題材照「缺貨→漲價→營收暴衝」因果鏈打強度分，
A 級（真缺貨有定價權且今天剛爆）優先提示加入當沖 watchlist。

用法：
  python scripts/shortage_radar_brief.py [--slot=morning|evening]
  python scripts/shortage_radar_brief.py --demo   # 離線範例，產 HTML 不需網路/telegram

排程同 aistockmap_brief.py（schtasks DAILY）。指定 --slot 會用 alert_state 6h 去重。
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

logger = logging.getLogger("shortage-radar")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# ── 離線 demo 樣本（不需 playwright / telegram）─────────────────────────────────

def _demo_items():
    from backend.aistockmap_scraper import FocusItem

    today = datetime.now().date().isoformat()
    return [
        FocusItem(
            source="工商時報", date_label=today,
            title="矽晶圓供不應求 大廠同步調漲報價",
            description="記憶體與晶圓代工急單湧現，矽晶圓缺貨報價調漲，帶動下游營收暴衝。",
            industry_tags=("矽晶圓", "半導體材料"), is_premium_locked=False,
        ),
        FocusItem(
            source="經濟日報", date_label=today,
            title="ABF 載板傳缺料、交期拉長",
            description="AI 伺服器拉貨急單塞單，ABF 載板供應吃緊、交期延長。",
            industry_tags=("ABF載板", "PCB"), is_premium_locked=False,
        ),
        FocusItem(
            source="財訊", date_label=today,
            title="某電子廠營收創高 惟毛利率下滑引疑慮",
            description="月營收暴增但毛利率下滑，市場質疑是否為過水單。",
            industry_tags=("EMS",), is_premium_locked=False,
        ),
        FocusItem(
            source="產業報告", date_label="2026-04-20",
            title="AI 長期趨勢帶動先進封裝缺貨漲價",
            description="長期結構性需求下，CoWoS 先進封裝持續缺貨、報價走揚。",
            industry_tags=("先進封裝", "CoWoS"), is_premium_locked=True,
        ),
        FocusItem(
            source="公司公告", date_label=datetime.now().date().isoformat(),
            title="某公司召開法人說明會",
            description="公司將於下週召開法說會說明營運展望。",
            industry_tags=(), is_premium_locked=False,
        ),
    ]


def _run_demo() -> int:
    from backend.shortage_radar import format_radar_summary, scan_shortage
    from backend.shortage_radar_report import render

    signals = scan_shortage(_demo_items())
    print("\n" + format_radar_summary(signals) + "\n")

    out_dir = _PROJECT_ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "shortage_radar_demo.html"
    html = render(signals, fetched_at=datetime.now().isoformat(timespec="seconds"))
    out_path.write_text(html, encoding="utf-8")
    logger.info("HTML 報告已寫到 %s", out_path)
    return 0


# ── 線上模式：抓 aistockmap → 評分 → 推 telegram ───────────────────────────────

async def _run(slot: str | None) -> int:
    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env.local")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 未設於 .env.local")
        return 1

    from telegram import Bot

    from backend import alert_state
    from backend.aistockmap_scraper import fetch_daily
    from backend.shortage_radar import format_radar_summary, scan_shortage
    from backend.shortage_radar_report import render

    today = datetime.now().date().isoformat()
    if slot:
        dedup_key = f"shortage_radar:{today}:{slot}"
        if not alert_state.should_push(dedup_key, within_minutes=60 * 6):
            logger.info("已在 6h 內推過 (key=%s)，本次跳過", dedup_key)
            return 0

    logger.info("抓 aistockmap…")
    digest = await fetch_daily()
    signals = scan_shortage(digest.focus_items)
    summary = (
        f"⏰ 缺貨雷達（{slot or 'manual'}, {today}）\n\n"
        + format_radar_summary(signals)
    )

    logger.info("推 telegram…")
    bot = Bot(token=bot_token)
    async with bot:
        await bot.send_message(chat_id=chat_id, text=summary)
        html = render(signals, fetched_at=digest.fetched_at)
        bio = BytesIO(html.encode("utf-8"))
        bio.name = f"shortage_radar_{slot or 'manual'}_{today}.html"
        await bot.send_document(chat_id=chat_id, document=bio)

    if slot:
        alert_state.mark_pushed(dedup_key)
    logger.info("done")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--slot", choices=["morning", "evening"], default=None,
        help="排程 slot 標識（用於 6h dedup）；不指定則強制推送",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="離線範例模式：用內建樣本產 HTML，不需網路/telegram",
    )
    args = parser.parse_args()
    if args.demo:
        sys.exit(_run_demo())
    sys.exit(asyncio.run(_run(args.slot)))


if __name__ == "__main__":
    main()
