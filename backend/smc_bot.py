"""SMC Telegram bot.

Commands
--------
  /smc_scan <code>   immediate single-stock SMC scan + HTML report
  /smc_watch <code>  add a code to the live watchlist (in-memory)
  /smc_unwatch <code>
  /smc_list          show current watchlist
  /smc_start         start the 3-min background scanner
  /smc_stop          stop the background scanner
  /aistockmap        manually scan aistockmap.com daily themes
                     (filtered by 雷老闆 A/B 原則, returns short list + HTML)

當沖 watchlist 指令（持久化到 data/day_trade_watchlist.json）
  /wl              show persistent day-trade watchlist
  /wl_add 2330 2317  add symbols (空白或逗號分隔)
  /wl_del 2330     remove a symbol
  /wl_clear        clear all
  /overnight_check 對 watchlist 跑隔日沖警告（簡化版：前日 >5% + 今開 >2%）

當沖 7-setup 分析（含 N 字 setup）
  /analyst_scan    跑 smc_analyst pipeline，回每個標的最佳 TradeIdea
  /watch_alerts    跑 N 字 watcher：first_beat（開盤後）+ db_approach（盤中）
                   也會由 JobQueue 自動每 3 分鐘跑一次（盤中時段內）

Requires .env.local: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import asyncio
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from backend import alert_state, watchlist as wl_mod
from backend.aistockmap_report import render as render_aistockmap_html
from backend.aistockmap_scraper import fetch_daily as fetch_aistockmap_daily
from backend.n_pattern_watcher import (
    evaluate_db_approach,
    evaluate_first_beat,
)
from backend.overnight_holders import evaluate as evaluate_overnight
from backend.shioaji_fetcher import shioaji_fetch_daily, shioaji_fetch_m3
from backend.smc_analyst.context import gather_context
from backend.smc_analyst.pipeline import analyse_watchlist
from backend.smc_detector import SMCSignal
from backend.smc_report import generate_html
from backend.smc_scanner import SMCScanner
from backend.theme_filter import filter_focus_items, format_short_summary

logger = logging.getLogger("smc-bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env.local")

_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ── text formatting ──────────────────────────────────────────────────────────

def _fmt_zone(z: Optional[dict]) -> str:
    if not z:
        return "—"
    return f"{z['bottom']:.2f}–{z['top']:.2f}"


def _summary_text(s: SMCSignal) -> str:
    stars = "★" * max(1, min(s.strength, 3))
    dz = _fmt_zone(s.demand_zone)
    sz = _fmt_zone(s.supply_zone)
    return (
        f"📐 SMC訊號｜{s.symbol}\n"
        f"訊號：{s.signal_type}\n"
        f"時框：{s.timeframe}\n"
        f"價位：{s.price:.2f}\n"
        f"日線結構：{s.market_structure}\n"
        f"需求區：{dz}\n"
        f"供給區：{sz}\n"
        f"強度：{stars}"
    )


# ── bot wiring ───────────────────────────────────────────────────────────────

class SMCBot:
    """Thin telegram-bot wrapper around SMCScanner."""

    def __init__(self) -> None:
        if not _BOT_TOKEN or not _CHAT_ID:
            raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set in .env.local")
        self.scanner = SMCScanner.from_env()
        self._bg_task: Optional[asyncio.Task] = None

    # ── lazy imports so missing libs only fail when bot actually runs ────────

    @staticmethod
    def _telegram_app():
        from telegram.ext import (
            Application, CommandHandler,
        )
        return Application, CommandHandler

    # ── per-command handlers ─────────────────────────────────────────────────

    async def cmd_scan(self, update, context):
        args = context.args or []
        if not args:
            await update.message.reply_text("用法：/smc_scan <股票代碼>")
            return
        symbol = args[0].strip()
        await update.message.reply_text(f"掃描中 {symbol} …")
        signals = await self.scanner.scan_symbol(symbol)
        if not signals:
            await update.message.reply_text(f"{symbol}：無 SMC 訊號（或資料不足）")
            return
        daily = await shioaji_fetch_daily(symbol, lookback=60)
        m3 = await shioaji_fetch_m3(symbol)
        for s in signals:
            await self._send_signal(update, s, daily, m3)

    async def cmd_watch(self, update, context):
        args = context.args or []
        if not args:
            await update.message.reply_text("用法：/smc_watch <股票代碼>")
            return
        sym = args[0].strip()
        if sym in self.scanner.watchlist:
            await update.message.reply_text(f"{sym} 已在監控清單。")
            return
        self.scanner.watchlist.append(sym)
        await update.message.reply_text(f"已加入監控：{sym}")

    async def cmd_unwatch(self, update, context):
        args = context.args or []
        if not args:
            await update.message.reply_text("用法：/smc_unwatch <股票代碼>")
            return
        sym = args[0].strip()
        try:
            self.scanner.watchlist.remove(sym)
            await update.message.reply_text(f"已移除：{sym}")
        except ValueError:
            await update.message.reply_text(f"{sym} 不在監控清單。")

    async def cmd_list(self, update, context):
        wl = ", ".join(self.scanner.watchlist) or "（空）"
        running = "running" if self._bg_task and not self._bg_task.done() else "stopped"
        await update.message.reply_text(f"監控清單：{wl}\n背景掃描：{running}")

    async def cmd_start(self, update, context):
        if self._bg_task and not self._bg_task.done():
            await update.message.reply_text("背景掃描已在執行。")
            return
        # capture telegram bot for the closure
        bot = context.bot

        async def on_signal(symbol: str, s: SMCSignal):
            try:
                daily = await shioaji_fetch_daily(symbol, lookback=60)
                m3 = await shioaji_fetch_m3(symbol)
            except Exception:
                daily, m3 = None, None
            await self._push_signal(bot, s, daily, m3)

        self._bg_task = asyncio.create_task(self.scanner.run_forever(on_signal=on_signal))
        await update.message.reply_text("背景掃描已啟動（每 180s 一輪，09:00–13:30 才掃）")

    async def cmd_stop(self, update, context):
        self.scanner.stop()
        if self._bg_task:
            await asyncio.sleep(0)
        await update.message.reply_text("背景掃描已停止。")

    async def cmd_aistockmap(self, update, context):
        """手動觸發 aistockmap 每日題材掃描（雷老闆 A/B 過濾）。"""
        await update.message.reply_text("📰 抓 aistockmap daily 中（約 10s）…")
        try:
            digest = await fetch_aistockmap_daily()
        except Exception as exc:
            logger.exception("aistockmap fetch failed")
            await update.message.reply_text(f"❌ 抓取失敗：{exc}")
            return
        filtered = filter_focus_items(digest.focus_items)
        summary = format_short_summary(filtered)
        # 末尾提示：請使用者把感興趣股號加進 watchlist
        summary += (
            "\n\n💡 看完後請挑感興趣的股號加入今日 watchlist：\n"
            "  /wl_add 2330 2317 ..."
        )
        await update.message.reply_text(summary)
        html = render_aistockmap_html(digest, filtered)
        bio = BytesIO(html.encode("utf-8"))
        bio.name = f"aistockmap_{digest.fetched_at.replace(':', '-')}.html"
        await update.message.reply_document(document=bio)

    # ── 當沖 watchlist（持久化版，跟 in-memory /smc_watch 分開）────────────────

    async def cmd_wl(self, update, context):
        wl = wl_mod.load()
        if not wl.entries:
            await update.message.reply_text("📋 當沖 watchlist 是空的。\n用 /wl_add 2330 2317 加標的")
            return
        lines = [f"📋 當沖 watchlist（{len(wl.entries)} 檔，更新於 {wl.updated_at}）："]
        for i, e in enumerate(wl.entries, 1):
            note = f" — {e.note}" if e.note else ""
            lines.append(f"  {i}. {e.symbol}{note}")
        lines.append("\n指令：/wl_add <股號> | /wl_del <股號> | /wl_clear | /overnight_check")
        await update.message.reply_text("\n".join(lines))

    async def cmd_wl_add(self, update, context):
        args = context.args or []
        symbols = wl_mod.parse_symbols_arg(args)
        if not symbols:
            await update.message.reply_text("用法：/wl_add 2330 2317 2454（空白或逗號分隔）")
            return
        _, added = wl_mod.add(symbols)
        if added:
            await update.message.reply_text(
                f"✅ 已加入：{', '.join(added)}\n目前 watchlist：{', '.join(wl_mod.load().symbols)}"
            )
        else:
            await update.message.reply_text(
                f"ℹ️ {', '.join(symbols)} 已存在或無新增。\n目前 watchlist：{', '.join(wl_mod.load().symbols)}"
            )

    async def cmd_wl_del(self, update, context):
        args = context.args or []
        symbols = wl_mod.parse_symbols_arg(args)
        if not symbols:
            await update.message.reply_text("用法：/wl_del 2330")
            return
        _, removed = wl_mod.remove(symbols)
        if removed:
            await update.message.reply_text(f"🗑 已移除：{', '.join(removed)}")
        else:
            await update.message.reply_text(f"ℹ️ {', '.join(symbols)} 不在 watchlist。")

    async def cmd_wl_clear(self, update, context):
        n = wl_mod.clear()
        await update.message.reply_text(f"🧹 已清空 watchlist（共 {n} 檔）")

    # ── smc_analyst pipeline + N 字 watcher ─────────────────────────────────

    async def cmd_analyst_scan(self, update, context):
        """跑 smc_analyst 7-setup pipeline（含 N 字 setup），回 TradeIdea 列表。"""
        wl = wl_mod.load()
        if not wl.entries:
            await update.message.reply_text(
                "⚠️ watchlist 是空的，先用 /wl_add 加標的（或會 fallback 到 SMC_WATCHLIST env）"
            )
        await update.message.reply_text("🧠 跑 smc_analyst pipeline 中（每檔約 5-10s）…")
        try:
            ideas = await analyse_watchlist()
        except Exception as exc:
            logger.exception("analyst_scan failed")
            await update.message.reply_text(f"❌ 分析失敗：{exc}")
            return
        if not ideas:
            await update.message.reply_text("📭 目前沒有任何標的通過 7-setup hard gates")
            return
        await update.message.reply_text(f"✅ 命中 {len(ideas)} 個 TradeIdea：")
        for idea in ideas:
            try:
                await update.message.reply_text(idea.telegram_text())
            except Exception as exc:
                logger.warning("send TradeIdea failed for %s: %s", idea.symbol, exc)

    async def cmd_watch_alerts(self, update, context):
        """手動觸發 N 字 watcher（first_beat + db_approach）對 watchlist 跑一輪。"""
        await update.message.reply_text("👀 跑 N 字 watcher 中…")
        bot = context.bot
        n = await self._run_watcher_pass(bot, force_send=True, manual=True)
        if n == 0:
            await update.message.reply_text("📭 目前沒有命中任何 first_beat / db_approach")

    async def _run_watcher_pass(
        self, bot, *, force_send: bool = False, manual: bool = False
    ) -> int:
        """對 watchlist 跑 first_beat + db_approach，命中即推 telegram。

        force_send=True 時略過 dedup（手動測試用）。
        Returns 推出去的訊息數。
        """
        wl = wl_mod.load()
        if not wl.entries:
            return 0
        sent = 0
        for entry in wl.entries:
            try:
                ctx = await gather_context(entry.symbol)
            except Exception as exc:
                logger.warning("gather_context failed for %s: %s", entry.symbol, exc)
                continue
            for alert in (evaluate_first_beat(ctx), evaluate_db_approach(ctx)):
                if alert is None:
                    continue
                key = alert.dedup_key()
                if not force_send and not alert_state.should_push(key, within_minutes=60):
                    logger.debug("alert dedup'd: %s", key)
                    continue
                try:
                    await bot.send_message(chat_id=_CHAT_ID, text=alert.to_telegram_text())
                    if not force_send:
                        alert_state.mark_pushed(key)
                    sent += 1
                except Exception as exc:
                    logger.warning("send alert failed (%s): %s", key, exc)
        if manual and sent > 0:
            try:
                await bot.send_message(chat_id=_CHAT_ID, text=f"📣 推了 {sent} 則 watcher 警示")
            except Exception:
                pass
        return sent

    async def _job_watcher(self, context):
        """JobQueue 每 3 分鐘呼叫的 callback。盤中才跑（避免盤後浪費 API call）。"""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        if now.weekday() >= 5:
            return
        if not (9 <= now.hour < 14):
            return
        n = await self._run_watcher_pass(context.bot)
        if n > 0:
            logger.info("scheduled watcher pushed %d alerts", n)

    async def cmd_overnight_check(self, update, context):
        """對 watchlist 逐檔跑隔日沖警告。"""
        wl = wl_mod.load()
        if not wl.entries:
            await update.message.reply_text("⚠️ watchlist 是空的，先用 /wl_add 加標的")
            return
        await update.message.reply_text(
            f"🔍 跑隔日沖檢查中（{len(wl.entries)} 檔，門檻：前日 >5%、今開 >2%）…"
        )
        lines = ["📊 隔日沖檢查結果："]
        for e in wl.entries:
            try:
                daily = await shioaji_fetch_daily(e.symbol, lookback=5)
            except Exception as exc:
                lines.append(f"❌ {e.symbol}：抓 daily 失敗（{exc}）")
                continue
            # today_open：盤中取 m3 第一根，盤後 fallback 用 daily 最後一根的 open
            today_open = None
            try:
                m3 = await shioaji_fetch_m3(e.symbol)
                if m3 is not None and not m3.empty:
                    open_col = next((c for c in m3.columns if c.lower() == "open"), None)
                    if open_col:
                        today_open = float(m3[open_col].iloc[0])
            except Exception:
                pass
            verdict = evaluate_overnight(e.symbol, daily, today_open=today_open)
            lines.append(verdict.to_telegram_line())
        await update.message.reply_text("\n".join(lines))

    # ── sending helpers ──────────────────────────────────────────────────────

    async def _send_signal(self, update, s: SMCSignal, daily, m3) -> None:
        await update.message.reply_text(_summary_text(s))
        html = generate_html(s, daily_df=daily, intraday_df=m3,
                             fallback_to_daily=(s.timeframe == "1D" and (m3 is None or m3.empty)))
        bio = BytesIO(html.encode("utf-8"))
        bio.name = f"smc_{s.symbol}_{s.signal_type}.html"
        await update.message.reply_document(document=bio)

    async def _push_signal(self, bot, s: SMCSignal, daily, m3) -> None:
        text = _summary_text(s)
        try:
            await bot.send_message(chat_id=_CHAT_ID, text=text)
            html = generate_html(s, daily_df=daily, intraday_df=m3,
                                 fallback_to_daily=(s.timeframe == "1D" and (m3 is None or m3.empty)))
            bio = BytesIO(html.encode("utf-8"))
            bio.name = f"smc_{s.symbol}_{s.signal_type}.html"
            await bot.send_document(chat_id=_CHAT_ID, document=bio)
        except Exception as exc:
            logger.error("telegram push failed: %s", exc)

    # ── entrypoint ───────────────────────────────────────────────────────────

    def run(self) -> None:
        Application, CommandHandler = self._telegram_app()
        app = Application.builder().token(_BOT_TOKEN).build()
        app.add_handler(CommandHandler("smc_scan", self.cmd_scan))
        app.add_handler(CommandHandler("smc_watch", self.cmd_watch))
        app.add_handler(CommandHandler("smc_unwatch", self.cmd_unwatch))
        app.add_handler(CommandHandler("smc_list", self.cmd_list))
        app.add_handler(CommandHandler("smc_start", self.cmd_start))
        app.add_handler(CommandHandler("smc_stop", self.cmd_stop))
        app.add_handler(CommandHandler("aistockmap", self.cmd_aistockmap))
        app.add_handler(CommandHandler("wl", self.cmd_wl))
        app.add_handler(CommandHandler("wl_add", self.cmd_wl_add))
        app.add_handler(CommandHandler("wl_del", self.cmd_wl_del))
        app.add_handler(CommandHandler("wl_clear", self.cmd_wl_clear))
        app.add_handler(CommandHandler("overnight_check", self.cmd_overnight_check))
        app.add_handler(CommandHandler("analyst_scan", self.cmd_analyst_scan))
        app.add_handler(CommandHandler("watch_alerts", self.cmd_watch_alerts))

        # JobQueue：盤中每 3 分鐘自動跑一次 N 字 watcher（含 dedup）
        if app.job_queue is not None:
            app.job_queue.run_repeating(
                self._job_watcher,
                interval=180,
                first=30,
                name="n-pattern-watcher",
            )
            logger.info("scheduled n-pattern-watcher: every 180s")
        else:
            logger.warning("JobQueue 不可用（pip install 'python-telegram-bot[job-queue]'）")
        logger.info("SMC bot polling …")
        app.run_polling(close_loop=False)


def main() -> None:
    SMCBot().run()


if __name__ == "__main__":
    main()
