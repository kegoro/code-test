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
import re
from io import BytesIO
from pathlib import Path
from typing import Optional


# ── secret sanitiser ─────────────────────────────────────────────────────────
# 所有發到 Telegram 的訊息都先過這個函式，把 JWT / 長 base64 / API token
# pattern redact 掉，避免上游 lib（shioaji / FinMind）把 secret 塞進 exception
# 又被我們不小心轉送到 Telegram（已洩漏過一次，見對話 2026-05-20）。

_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
_LONG_BASE64_RE = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")
_PAYLOAD_TOKEN_RE = re.compile(r"'token'\s*:\s*'[^']+'")
_SECRET_KW_RE = re.compile(
    r"(?i)(api[_-]?key|secret[_-]?key|password|token|jwt|bearer)\s*[:=]\s*\S+"
)
# 永豐 PYAPI client string 與身份證號碼（[A-Z]\d{9}）
_PYAPI_CLIENT_RE = re.compile(r"PYAPI/[A-Z]\d{9}(?:/[\w\d.]+)*")
_TW_ID_RE = re.compile(r"\b[A-Z][12]\d{8}\b")


def _sanitize_for_telegram(text: str, *, max_len: int = 500) -> str:
    """把可能含 secret 的字串清乾淨再送 Telegram。"""
    if not text:
        return text
    s = _PAYLOAD_TOKEN_RE.sub("'token': '[REDACTED]'", text)
    s = _JWT_RE.sub("[REDACTED-JWT]", s)
    s = _SECRET_KW_RE.sub(r"\1=[REDACTED]", s)
    s = _PYAPI_CLIENT_RE.sub("PYAPI/[REDACTED-CLIENT]", s)
    s = _TW_ID_RE.sub("[REDACTED-ID]", s)
    s = _LONG_BASE64_RE.sub("[REDACTED-LONG-STRING]", s)
    if len(s) > max_len:
        s = s[:max_len] + "...(詳細錯誤已寫入 server log)"
    return s


def _safe_err(exc: Exception) -> str:
    """Exception 轉成可安全送 Telegram 的字串。"""
    return _sanitize_for_telegram(f"{type(exc).__name__}: {exc}")


def _fmt_lots(vol: int) -> str:
    """成交量（張）格式化：>=1 萬張顯示 X.X萬張，否則 N張。"""
    if vol >= 10000:
        return f"{vol / 10000:.1f}萬張"
    return f"{vol:,}張"

from dotenv import load_dotenv

from backend import alert_state, watchlist as wl_mod
from backend.ai_analysis_orchestrator import analyse as analyse_ai_report
from backend.ai_analysis_report import render_html as render_ai_html
from backend.ai_analysis_screenshot import html_to_png as ai_html_to_png
from backend.aistockmap_report import render as render_aistockmap_html
from backend.aistockmap_scraper import fetch_daily as fetch_aistockmap_daily
from backend.n_pattern_watcher import (
    evaluate_db_approach,
    evaluate_first_beat,
)
from backend.ob_watcher import evaluate_ob_formation
from backend import sim_book
from backend.sim_monitor import check_positions as sim_check_positions
from backend.sim_suggester import suggest as sim_suggest, SuggestionError
from backend.overnight_holders import evaluate as evaluate_overnight
from backend.shioaji_fetcher import (
    shioaji_fetch_daily,
    shioaji_fetch_m3,
    shioaji_scan_gainers,
)
from backend.momentum_scan import scan as run_momentum_scan, MIN_CHANGE_PCT
from backend.momentum_scan import bowl_scan as run_bowl_scan
from backend.potential_scan import (
    scan as run_potential_scan,
    scan_strong as run_strong_scan,
    COND_MARK, DEFAULT_MIN_SCORE, STRONG_PCT,
)
from backend import diamond_score
from backend import pe_valuation
from backend import pullback_check
from backend import mops_fundamentals
from backend.smc_analyst.context import gather_context
from backend.smc_analyst.pipeline import analyse_watchlist
from backend.smc_detector import SMCSignal
from backend.smc_report import generate_html
from backend.smc_scanner import SMCScanner
from backend.theme_filter import filter_focus_items, format_short_summary

logger = logging.getLogger("smc-bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx 每次 getUpdates 都用 INFO 印含 bot token 的 URL（§3.7 精神：log 也不該留 token）
logging.getLogger("httpx").setLevel(logging.WARNING)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env.local")

# 優先讀 SMC_TELEGRAM_BOT_TOKEN（這支 bot 專用，避免跟 tw-stock-signal/main.py
# 用同一個 token 互搶 polling 而 409 Conflict）；沒設就 fallback 舊變數。
_BOT_TOKEN = os.getenv("SMC_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
_CHAT_ID = os.getenv("SMC_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")


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
    """Telegram bot 入口：N 字 / OB watcher cron + 紙上模擬 + AI 分析 +
    aistockmap 題材掃描。

    self.scanner 只給 /smc_scan 對單一股號跑結構分析用。當沖 watchlist 改用
    持久化版本（backend/watchlist.py 對應 data/day_trade_watchlist.json）。
    """

    def __init__(self) -> None:
        if not _BOT_TOKEN or not _CHAT_ID:
            raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set in .env.local")
        self.scanner = SMCScanner.from_env()

    # ── lazy imports so missing libs only fail when bot actually runs ────────

    @staticmethod
    def _telegram_app():
        from telegram.ext import (
            Application, CommandHandler, MessageHandler, filters,
        )
        return Application, CommandHandler, MessageHandler, filters

    # ── per-command handlers ─────────────────────────────────────────────────

    async def cmd_scan(self, update, context):
        args = context.args or []
        if not args:
            await update.message.reply_text("用法：/smc_scan <股票代碼>")
            return
        symbol = args[0].strip()
        await update.message.reply_text(f"掃描中 {symbol} …")

        # 先拉資料自己看大小，才能在沒命中時告訴使用者「資料拉到了 vs 拉不到」
        try:
            daily = await shioaji_fetch_daily(symbol, lookback=60)
        except Exception as exc:
            logger.exception("cmd_scan daily fetch failed for %s", symbol)
            await update.message.reply_text(
                f"{symbol}：日線拉失敗（{_safe_err(exc)}）"
            )
            return
        try:
            m3 = await shioaji_fetch_m3(symbol)
        except Exception:
            m3 = None
        daily_n = 0 if daily is None else len(daily)
        m3_n = 0 if m3 is None else len(m3)

        if daily_n == 0:
            await update.message.reply_text(
                f"{symbol}：日線拉不到（shioaji session 可能死了）。"
                f"\n等 N 字 watcher 下次跑（每 3 分鐘）會自動 re-login，再試一次。"
            )
            return

        signals = await self.scanner.scan_symbol(symbol)
        if not signals:
            await update.message.reply_text(
                f"{symbol}：daily {daily_n} 根 / m3 {m3_n} 根都拉到了，"
                f"但 SMC scanner 沒找到 BOS / CHoCH 訊號。\n\n"
                f"💡 /smc_scan 只找「結構轉折」訊號。想看完整分析（5 維度評分 + K 線）："
                f"\n  /ai_analyse {symbol}"
            )
            return

        for s in signals:
            await self._send_signal(update, s, daily, m3)

    async def cmd_aistockmap(self, update, context):
        """手動觸發 aistockmap 每日題材掃描（雷老闆 A/B 過濾）。"""
        await update.message.reply_text("📰 抓 aistockmap daily 中（約 10s）…")
        try:
            digest = await fetch_aistockmap_daily()
        except Exception as exc:
            logger.exception("aistockmap fetch failed")
            await update.message.reply_text(f"❌ 抓取失敗：{_safe_err(exc)}")
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
            await update.message.reply_text(f"❌ 分析失敗：{_safe_err(exc)}")
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
            single_alerts = [evaluate_first_beat(ctx), evaluate_db_approach(ctx)]
            ob_alerts = evaluate_ob_formation(ctx)
            for alert in [*single_alerts, *ob_alerts]:
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
        """JobQueue 每 3 分鐘呼叫的 callback。盤中才跑（避免盤後浪費 API call）。

        兩件事：
          1. N 字 / OB watcher（first_beat / db_approach / 新 OB 形成）
          2. 紙上模擬部位監控（stop / target 觸發 → 結算 + 推播）
        """
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

        # 紙上模擬部位監控
        try:
            sim_alerts = await sim_check_positions()
        except Exception as exc:
            logger.exception("sim_monitor failed")
            sim_alerts = []
        for alert in sim_alerts:
            try:
                await context.bot.send_message(
                    chat_id=_CHAT_ID, text=alert.to_telegram_text(),
                )
            except Exception as exc:
                logger.warning("send sim exit alert failed: %s", exc)
        if sim_alerts:
            logger.info("sim_monitor closed %d positions", len(sim_alerts))

    # ── 漲幅榜推播（12:30 / 13:00 / 13:30）─────────────────────────────────────
    _GAINER_THRESHOLD = 5.0   # 漲幅門檻 %
    _GAINER_MAX_ROWS = 40     # Telegram 訊息最多列幾檔（其餘只報數量）

    async def _job_gainers(self, context):
        """run_daily 在 12:30 / 13:00 / 13:30 呼叫：掃上市普通股當日漲幅 >= 門檻。"""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        if now.weekday() >= 5:   # 週末不跑（假日靠 market_active 過濾）
            return
        try:
            scan = await shioaji_scan_gainers(self._GAINER_THRESHOLD)
        except Exception as exc:
            logger.warning("gainer scan failed: %s", exc)
            try:
                await context.bot.send_message(
                    chat_id=_CHAT_ID,
                    text=_sanitize_for_telegram(f"⚠️ 漲幅榜掃描失敗：{_safe_err(exc)}"),
                )
            except Exception:
                pass
            return
        if not scan.market_active:   # 假日 / 休市 → 不推誤導訊息
            logger.info("gainer scan: market inactive, skip push")
            return
        try:
            await context.bot.send_message(
                chat_id=_CHAT_ID, text=self._format_gainers(now, scan),
            )
            logger.info("gainer scan pushed: %d gainers", len(scan.gainers))
        except Exception as exc:
            logger.warning("send gainer list failed: %s", exc)

    def _format_gainers(self, now, scan) -> str:
        hhmm = now.strftime("%H:%M")
        head = f"🔥 今日漲幅 ≥{self._GAINER_THRESHOLD:.0f}% 強勢股（上市）{hhmm}"
        if not scan.gainers:
            return f"{head}\n掃 {scan.total_scanned} 檔，目前無漲幅達標個股。"
        lines = [
            head,
            f"共 {len(scan.gainers)} 檔（掃 {scan.total_scanned} 檔上市普通股）",
            "",
        ]
        for g in scan.gainers[: self._GAINER_MAX_ROWS]:
            lines.append(
                f"+{g.change_rate:.2f}% {g.code} {g.name}  "
                f"收 {g.close:,.2f}  量 {_fmt_lots(g.volume)}"
            )
        extra = len(scan.gainers) - self._GAINER_MAX_ROWS
        if extra > 0:
            lines.append(f"…還有 {extra} 檔（已依漲幅排序取前 {self._GAINER_MAX_ROWS}）")
        return "\n".join(lines)

    async def cmd_gainers(self, update, context):
        """手動觸發漲幅榜掃描（內容同 12:30/13:00/13:30 自動推播）。用法：/gainers"""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        await update.message.reply_text("🔍 掃上市漲幅榜中…")
        try:
            scan = await shioaji_scan_gainers(self._GAINER_THRESHOLD)
        except Exception as exc:
            await update.message.reply_text(_safe_err(exc))
            return
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        await update.message.reply_text(self._format_gainers(now, scan))

    # ── 當沖選股篩選 /scan（大盤+漲幅+均線+量能+型態）─────────────────────────
    _SCAN_MAX_ROWS = 15

    async def cmd_daytrade_scan(self, update, context):
        """當沖選股：大盤 + 漲幅≥5% + 均線多頭未發散 + 量能1.5× + 型態加分。用法：/scan"""
        await update.message.reply_text("🎯 當沖選股掃描中…（含逐檔日線分析，約 30 秒）")
        try:
            result = await run_momentum_scan()
        except Exception as exc:
            await update.message.reply_text(_safe_err(exc))
            return
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        await update.message.reply_text(self._format_scan(now, result))

    def _format_scan(self, now, r) -> str:
        hhmm = now.strftime("%m-%d %H:%M")
        mk = "✅" if r.market_ok else "⚠️"
        pct = (r.advancers / (r.scanned or 1)) * 100
        head = [
            f"🎯 當沖選股 /scan  {hhmm}",
            f"大盤：{r.market_state} {mk}（漲 {r.advancers} / 跌 {r.decliners}，占比 {pct:.0f}%）",
            f"漲幅≥{MIN_CHANGE_PCT:.0f}%：{r.raw_gainers} 檔 → 通過四關：{len(r.candidates)} 檔（掃 {r.scanned}）",
        ]
        if not r.market_ok:
            head.append("⚠️ 大盤偏空，依你第 1 條：今日謹慎或不進場")
        if not r.candidates:
            head.append("")
            head.append("四關全過：0 檔。漲幅夠但均線/量能不符，今天可能沒好標的。")
            return "\n".join(head)
        lines = head + [""]
        for idx, c in enumerate(r.candidates[: self._SCAN_MAX_ROWS], 1):
            star = "⭐" * c.score
            lines.append(
                f"{idx}. {c.code} {c.name} +{c.change_rate:.1f}%  量{c.vol_ratio:.1f}× {star}"
            )
            if c.tags:
                lines.append(f"   {' '.join(c.tags)}")
            lines.append(
                f"   月:{c.tf_monthly.trend} 週:{c.tf_weekly.trend} 日:{c.tf_daily.trend}"
            )
        extra = len(r.candidates) - self._SCAN_MAX_ROWS
        if extra > 0:
            lines.append(f"…還有 {extra} 檔（依型態分排序取前 {self._SCAN_MAX_ROWS}）")
        lines.append("")
        lines.append("型態分=糾結+收縮+破20日高+週多頭+月多頭；圖形(三角/杯柄)請自行於 12:30-13:30 判讀")
        return "\n".join(lines)

    # ── 碗型整理+爆量突破 /bowl（不設漲幅門檻，依今日成交量排序深掃）──────────────

    async def cmd_bowl_scan(self, update, context):
        """碗型底部+爆量突破：底部均線糾結 + 今日爆量 + 收破20日高。用法：/bowl"""
        await update.message.reply_text("🥣 碗型+爆量掃描中…（依今日量排序逐檔日線分析，約 30 秒）")
        try:
            result = await run_bowl_scan()
        except Exception as exc:
            await update.message.reply_text(_safe_err(exc))
            return
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        await update.message.reply_text(self._format_bowl(now, result))

    def _format_bowl(self, now, r) -> str:
        hhmm = now.strftime("%m-%d %H:%M")
        mk = "✅" if r.market_ok else "⚠️"
        pct_str = f"（掃 {r.scanned} 檔，依量排序深掃前 {r.deep_analyzed} 檔）"
        head = [
            f"🥟 碗型+爆量 /bowl  {hhmm}",
            f"大盤：{r.market_state} {mk}",
            f"碗型盤整+爆量+突破20日高：{len(r.candidates)} 檔{pct_str}",
        ]
        if not r.candidates:
            head.append("")
            head.append("目前無符合「底部糾結+今日爆量+突破20日高」的個股。")
            return "\n".join(head)
        lines = head + [""]
        for idx, c in enumerate(r.candidates[: self._SCAN_MAX_ROWS], 1):
            star = "⭐" * c.score
            sign = "+" if c.change_rate >= 0 else ""
            lines.append(
                f"{idx}. {c.code} {c.name} {sign}{c.change_rate:.1f}%  量{c.vol_ratio:.1f}× {star}"
            )
            if c.tags:
                lines.append(f"   {' '.join(c.tags)}")
            lines.append(
                f"   月:{c.tf_monthly.trend} 週:{c.tf_weekly.trend} 日:{c.tf_daily.trend}"
            )
        extra = len(r.candidates) - self._SCAN_MAX_ROWS
        if extra > 0:
            lines.append(f"…還有 {extra} 檔（依型態分排序取前 {self._SCAN_MAX_ROWS}）")
        lines.append("")
        lines.append("型態分=碗型盤整+爆量+破20日高(基本3分)+波動收縮+週多頭+月多頭；不設漲幅門檻")
        return "\n".join(lines)

    # ── 潛力股 6 條技術特性 /potential（中大型活躍股計分排名）─────────────────────

    async def cmd_potential_scan(self, update, context):
        """潛力股掃描：6 條技術特性計分。/potential [最低分]（預設 4）。約 1-2 分鐘。"""
        min_score = DEFAULT_MIN_SCORE
        if context.args:
            try:
                min_score = max(1, min(6, int(context.args[0])))
            except ValueError:
                pass
        await update.message.reply_text(
            f"🔭 潛力股掃描中…（中大型活躍股逐檔日線計分，門檻 {min_score} 分，約 1-2 分鐘）"
        )
        try:
            result = await run_potential_scan(min_score)
        except Exception as exc:
            await update.message.reply_text(_safe_err(exc))
            return
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        await update.message.reply_text(self._format_potential(now, result))

    def _format_potential(self, now, r, strong: bool = False) -> str:
        hhmm = now.strftime("%m-%d %H:%M")
        if strong:
            title = f"🚀 強勢股 /strong  {hhmm}"
            pool = f"掃 {r.scanned} 檔漲幅≥{STRONG_PCT:.0f}%，深掃 {r.deep_analyzed} 檔"
            lower = "目前無達標個股，可降門檻：/strong 3"
        else:
            title = f"🔭 潛力股 /potential  {hhmm}"
            pool = f"掃 {r.scanned} 檔，深掃前 {r.deep_analyzed} 活躍股"
            lower = "目前無達標個股，可降門檻：/potential 3"
        head = [
            title,
            "條件 ①量放大 ②均線多頭 ③布林開口 ④斐波回調 ⑤RSI翻揚 ⑥MACD金叉",
            f"≥{r.min_score} 分：{len(r.candidates)} 檔（{pool}）",
        ]
        if not r.candidates:
            head.append("")
            head.append(lower)
            return "\n".join(head)
        lines = head + [""]
        for idx, c in enumerate(r.candidates[: self._SCAN_MAX_ROWS], 1):
            marks = "".join(COND_MARK[x] for x in c.conds)
            fib = f"回調{c.fib_retr*100:.0f}%" if c.fib_retr == c.fib_retr else "回調—"  # NaN check
            pct = f" ▲{c.pct_change:.1f}%" if strong else ""
            lines.append(
                f"{idx}. {c.code} {c.name}  {c.score}分 {marks}{pct}"
            )
            lines.append(
                f"   收{c.close:,.2f} 量{c.vol_ratio:.1f}× RSI{c.rsi:.0f} {fib}"
            )
        extra = len(r.candidates) - self._SCAN_MAX_ROWS
        if extra > 0:
            lines.append(f"…還有 {extra} 檔（依分數→成交值排序取前 {self._SCAN_MAX_ROWS}）")
        lines.append("")
        lines.append("中④=拉回找買點型；中⑥=已啟動追勢型。①②③齊到=量價剛發動")
        return "\n".join(lines)

    # ── 強勢股 6 條技術特性 /strong（當日漲幅≥5% + 計分）─────────────────────────

    async def cmd_strong_scan(self, update, context):
        """強勢股掃描：當日漲幅≥5% 再套 6 條技術特性計分。/strong [最低分]（預設 4）。"""
        min_score = DEFAULT_MIN_SCORE
        if context.args:
            try:
                min_score = max(1, min(6, int(context.args[0])))
            except ValueError:
                pass
        await update.message.reply_text(
            f"🚀 強勢股掃描中…（漲幅≥{STRONG_PCT:.0f}% 活躍股逐檔日線計分，門檻 {min_score} 分）"
        )
        try:
            result = await run_strong_scan(min_score)
        except Exception as exc:
            await update.message.reply_text(_safe_err(exc))
            return
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        await update.message.reply_text(self._format_potential(now, result, strong=True))

    # ── 鑽豹評鑒 /dia ─────────────────────────────────────────────────────────

    async def cmd_diamond(self, update, context):
        """鑽豹評鑒：財報 6 面向 15 分。/dia 2330 [2317…]；無參數=看已記錄高分股。"""
        codes = [c for arg in (context.args or []) for c in re.split(r"[,\s]+", arg) if c]
        if not codes:
            picks = diamond_score.load_picks()
            if not picks:
                await update.message.reply_text(
                    "💎 尚無記錄。用 /dia 2330 評鑒個股，"
                    f"總分 ≥{diamond_score.RECORD_THRESHOLD} 自動記錄。")
                return
            lines = ["💎 鑽豹高分記錄（研究清單）", ""]
            for p in picks[:20]:
                lines.append(f"{p['score']:.0f}/15  {p['code']} {p['name']}  ({p['date']})")
            await update.message.reply_text("\n".join(lines))
            return
        codes = codes[:5]   # FinMind 免費額度保護：一次最多 5 檔
        await update.message.reply_text(f"💎 鑽豹評鑒 {len(codes)} 檔中…（每檔約 3-5 秒）")
        for code in codes:
            try:
                r = await diamond_score.evaluate(code)
            except Exception as exc:
                await update.message.reply_text(f"{code}：{_safe_err(exc)}")
                continue
            await update.message.reply_text(self._format_diamond(r))

    def _format_diamond(self, r) -> str:
        bar = "🟢" if r.score >= 10 else ("🟡" if r.score >= 6 else "🔴")
        lines = [f"💎 {r.code} {r.name} 鑽豹評鑒 {bar} {r.score:.0f} / {r.max_score:.0f}"]
        for it in r.items:
            lines.append(f"{'✅' if it.got == it.max else ('⚠️' if it.got > 0 else '❌')} "
                         f"{it.name} {it.got:.0f}/{it.max:.0f}：{it.note}")
        if r.recorded:
            lines.append("")
            lines.append(f"📌 已記入研究清單（/dia 查看）")
        return "\n".join(lines)

    # ── 本益比合理價 /pe ──────────────────────────────────────────────────────

    async def cmd_fin(self, update, context):
        """鑽豹四刀完整分析:/fin 2330 [2317…](最多 3 檔,每檔約 10 秒)。"""
        codes = [c for arg in (context.args or []) for c in re.split(r"[,\s]+", arg) if c]
        await self._run_fin(update, codes)

    async def cmd_fin_zh(self, update, context):
        """中文觸發:輸入「財報 6442」。"""
        text = update.message.text if update.message else ""
        codes = re.findall(r"\d{4,6}", text)
        await self._run_fin(update, codes)

    async def _run_fin(self, update, codes):
        import asyncio
        from backend import diamond_full
        codes = [c for c in codes if c][: mops_fundamentals._MAX_CODES]
        if not codes:
            await update.message.reply_text(
                "用法:/fin 2330(或直接打「財報 2330」)— 鑽豹四刀完整分析"
                "(第二刀基本面+大猩猩+第一刀進場+第三刀技術+綜合結論)")
            return
        await update.message.reply_text(f"🗡️ 鑽豹四刀分析 {len(codes)} 檔中…(每檔約 10 秒)")
        for code in codes:
            try:
                report = await asyncio.to_thread(diamond_full.analyze, code)
            except Exception as exc:
                await update.message.reply_text(f"{code}:{_safe_err(exc)}")
                continue
            await update.message.reply_text(report)

    async def cmd_pe(self, update, context):
        """合理股價=預估EPS×本益比。/pe 2330 或 /pe 2330 65（自估全年 EPS）。"""
        args = context.args or []
        if not args:
            await update.message.reply_text(
                "用法：/pe 2330（用近4季EPS）或 /pe 2330 65（自估全年EPS=65）")
            return
        code = args[0].strip()
        est = None
        if len(args) >= 2:
            try:
                est = float(args[1])
            except ValueError:
                await update.message.reply_text(f"EPS 看不懂：{args[1]}（要數字）")
                return
        await update.message.reply_text(f"🧮 {code} 本益比估值中…")
        try:
            v = await pe_valuation.evaluate(code, est)
        except Exception as exc:
            await update.message.reply_text(_safe_err(exc))
            return
        await update.message.reply_text(self._format_pe(v))

    def _format_pe(self, v) -> str:
        def f(x, fmt=",.1f"):
            return format(x, fmt) if x == x else "—"
        ind = "、".join(v.industries) if v.industries else "—"
        lines = [
            f"🧮 {v.code} {v.name} 合理價試算",
            f"產業：{ind}",
            f"現價 {f(v.price)}｜目前PE {f(v.per_current)}",
            f"歷史PE（近{f(v.per_years)}年）P25/P50/P75 = "
            f"{f(v.per_p25)} / {f(v.per_p50)} / {f(v.per_p75)}",
            f"EPS：{f(v.eps_used,',.2f')}（{v.eps_source}）"
            + (f"，近4季={f(v.eps_ttm,',.2f')}" if v.eps_source == "自估" else ""),
            "",
            f"合理價 = EPS × 歷史PE：",
            f"  保守(P25) {f(v.fair_low)}",
            f"  合理(P50) {f(v.fair_mid)}",
            f"  樂觀(P75) {f(v.fair_high)}",
        ]
        if v.price == v.price and v.fair_mid == v.fair_mid and v.fair_mid > 0:
            gap = (v.price - v.fair_mid) / v.fair_mid * 100
            lines.append(f"現價 vs 合理價(P50)：{gap:+.1f}%")
        lines.append("")
        lines.append("產業PE無法自動算（FinMind付費牆）；要比同業就對同業跑 /pe")
        return "\n".join(lines)

    # ── 拉回整理 /pullback ────────────────────────────────────────────────────

    async def cmd_pullback(self, update, context):
        """拉回整理檢查（週/月線）。/pullback 2330 …；無參數=鑽豹記錄+watchlist。"""
        codes = [c for arg in (context.args or []) for c in re.split(r"[,\s]+", arg) if c]
        if not codes:
            codes = [p["code"] for p in diamond_score.load_picks()]
            try:
                codes += [e.symbol for e in wl_mod.load().entries]
            except Exception:
                pass
            codes = list(dict.fromkeys(codes))   # 去重保序
        if not codes:
            await update.message.reply_text(
                "沒有標的可查。/pullback 2330 2317 指定，"
                "或先用 /dia、/wl_add 建清單。")
            return
        codes = codes[:15]
        await update.message.reply_text(f"📉 檢查 {len(codes)} 檔拉回整理中…")
        views = await pullback_check.check_many(codes)
        await update.message.reply_text(self._format_pullback(views))

    def _format_pullback(self, views) -> str:
        lines = [
            f"📉 拉回整理檢查（距52週高 {pullback_check.PULL_MIN:.0f}-"
            f"{pullback_check.PULL_MAX:.0f}% + 月線趨勢在 + 近4週整理）",
            "",
        ]
        hits = [v for v in views if v.is_candidate]
        others = [v for v in views if not v.is_candidate]
        for v in hits + others:
            if v.error:
                lines.append(f"▫️ {v.code} {v.name}：{v.error}")
                continue
            mark = "✅" if v.is_candidate else "▫️"
            t = []
            t.append(f"距高 -{v.pull_pct:.1f}%{'✓' if v.dist_ok else ''}")
            mtrend = "月MA6↑" if v.monthly_ma6_up else (
                "價>月MA12" if v.above_monthly_ma12 else "月線轉弱")
            t.append(f"{mtrend}{'✓' if v.trend_ok else '✗'}")
            t.append(f"4週區間{v.consol_range_pct:.1f}%{'✓' if v.consol_ok else '✗'}")
            lines.append(f"{mark} {v.code} {v.name} 收{v.close:,.1f}  " + "｜".join(t))
        if hits:
            lines.append("")
            lines.append(f"✅ 候選 {len(hits)} 檔 — 週/月線圖自行確認型態後再決定")
        return "\n".join(lines)

    # ── ATM×SMC 策略圖 /chart ─────────────────────────────────────────────────

    async def cmd_chart(self, update, context):
        """ATM×SMC 策略圖：當日 M3 疊時段高低/OB/進出場/收針。

        /chart 2330（今日）或 /chart 2330 2026-06-10（指定日）。
        當沖策略圖，只畫單一交易日盤中；開盤未滿 30 分鐘 K 棒不足會擋。
        """
        args = context.args or []
        if args:
            symbol = args[0].strip()
            day = args[1].strip() if len(args) >= 2 else None
        else:
            # 無參數 = 畫 watchlist 第一檔（讓選單點一下就有圖，呼應 menu 設計原則）
            try:
                entries = wl_mod.load().entries
            except Exception:
                entries = []
            if not entries:
                await update.message.reply_text(
                    "用法：/chart 2330（今日）或 /chart 2330 2026-06-10（指定某天）\n"
                    "（watchlist 是空的；先 /wl_add 2330，或直接打 /chart 2330）")
                return
            symbol, day = entries[0].symbol, None
        await update.message.reply_text(f"📈 {symbol} 策略圖生成中…（當日 M3 盤中）")
        try:
            from backend.strategy_chart import generate_chart_png
            png, label = await generate_chart_png(symbol, day)
        except Exception as exc:
            logger.exception("chart failed for %s", symbol)
            await update.message.reply_text(f"❌ 生圖失敗：{_safe_err(exc)}")
            return
        bio = BytesIO(png)
        bio.name = f"chart_{symbol}_{label}.png"
        await update.message.reply_photo(
            photo=bio,
            caption=(f"📈 {symbol} ATM×SMC 策略圖｜{label}\n"
                     "進出場為機械參考、非下單指示（模擬期）"),
        )

    # ── AI 趨勢分析報告（5 維度評分 + 雙 K 線切換） ───────────────────────────

    async def cmd_ai_analyse(self, update, context):
        """產生 AI 趨勢分析 HTML（5 維度評分 + 日線/M3 K 線）。

        用法：/ai_analyse 2330
        技術面接 SMC pipeline，其餘維度暫 mock（後續逐步接 FinMind / aistockmap）。
        """
        args = context.args or []
        if not args:
            await update.message.reply_text("用法：/ai_analyse 2330")
            return
        symbol = args[0].strip()
        await update.message.reply_text(f"🧠 跑 AI 趨勢分析中 {symbol}…")

        try:
            result = await analyse_ai_report(symbol)
        except Exception as exc:
            logger.exception("ai_analyse failed for %s", symbol)
            await update.message.reply_text(f"❌ 分析失敗：{_safe_err(exc)}")
            return

        summary = (
            f"🧠 AI 趨勢分析｜{result.stock_name}（{result.symbol}）\n"
            f"AI 綜合評分：{result.overall_score:.1f}／100 → {result.overall_verdict}\n"
            f"  籌碼面 {result.chip.score:.1f} (45%)\n"
            f"  技術面 {result.technical.score:.1f} (35%)\n"
            f"  新聞面 {result.news.score:.1f} (20%)\n"
            f"  基本面 {result.fundamental.score:.1f} (參考)\n"
            f"  題材面 {result.theme.score:.1f} (參考)"
        )
        await update.message.reply_text(summary)

        try:
            html = render_ai_html(result)
        except Exception as exc:
            logger.exception("ai_analyse render failed for %s", symbol)
            await update.message.reply_text(f"❌ HTML 產生失敗：{_safe_err(exc)}")
            return

        # 1) 先送 PNG（讓你 Telegram 直接看 K 線 + 卡片，不用開瀏覽器）
        try:
            png = await ai_html_to_png(html)
            png_io = BytesIO(png)
            png_io.name = f"ai_analyse_{symbol}.png"
            await update.message.reply_photo(
                photo=png_io,
                caption=f"📊 {result.stock_name} ({result.symbol})｜{result.overall_score:.1f}/100 {result.overall_verdict}",
            )
        except Exception as exc:
            logger.warning("ai_analyse screenshot failed for %s: %s", symbol, exc)

        # 2) 再送 HTML（要互動 / tab 切換時用瀏覽器開）
        try:
            bio = BytesIO(html.encode("utf-8"))
            bio.name = f"ai_analyse_{symbol}.html"
            await update.message.reply_document(document=bio)
        except Exception as exc:
            logger.exception("ai_analyse HTML send failed for %s", symbol)
            await update.message.reply_text(f"❌ HTML 傳送失敗：{_safe_err(exc)}")

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
                logger.exception("overnight_check daily fetch failed for %s", e.symbol)
                lines.append(f"❌ {e.symbol}：抓 daily 失敗（{_safe_err(exc)}）")
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

    # ── 紙上模擬部位（LESSONS §2.7.5）────────────────────────────────────────

    async def cmd_sim_open(self, update, context):
        """開紙上模擬部位（強制紀律守門：R:R/單筆風險/日筆數/方向）。

        兩種模式：
          Auto（推薦）：/sim_open <symbol> <long|short> <entry> <size>
                       Bot 根據 SMC 結構（Bull/Bear OB + ATR）自動建議 stop/target
          Manual：    /sim_open <symbol> <long|short> <entry> <stop> <target> <size> [note...]
                       完全手動指定（給有把握的情境）
        範例：
          /sim_open 3481 long 36.5 1           ← auto（最常用）
          /sim_open 3481 long 36.5 35.9 37.5 1 ← manual
        """
        args = context.args or []

        # 判斷模式：4 個（含 size）= auto / 6+ 個 = manual
        is_auto = len(args) == 4
        is_manual = len(args) >= 6
        if not (is_auto or is_manual):
            await update.message.reply_text(
                "用法：\n"
                "  Auto（推薦）：/sim_open <symbol> <long|short> <entry> <size>\n"
                "    範例：/sim_open 3481 long 36.5 1\n"
                "  Manual：     /sim_open <symbol> <long|short> <entry> <stop> <target> <size>\n"
                "    範例：/sim_open 3481 long 36.5 35.9 37.5 1"
            )
            return

        try:
            symbol = args[0].strip()
            direction = args[1].strip().lower()
            entry = float(args[2])
            if is_auto:
                size = int(args[3])
                # auto 模式：拉 suggester
                try:
                    sug = await sim_suggest(symbol, direction, entry)
                except SuggestionError as exc:
                    await update.message.reply_text(
                        f"⚠️ 自動建議失敗：{_safe_err(exc)}\n"
                        f"→ 改用 manual 模式手動給 stop/target："
                        f"\n  /sim_open {symbol} {direction} {entry} <stop> <target> {size}"
                    )
                    return
                stop = sug.stop
                target = sug.target
                auto_reasoning = sug.reasoning
                note = "auto"
            else:
                stop = float(args[3])
                target = float(args[4])
                size = int(args[5])
                auto_reasoning = ""
                note = " ".join(args[6:]) if len(args) > 6 else "manual"
        except (ValueError, IndexError) as exc:
            await update.message.reply_text(f"⚠️ 參數解析失敗：{_safe_err(exc)}")
            return

        try:
            pos = sim_book.open_position(
                symbol=symbol, direction=direction,
                entry=entry, stop=stop, target=target,
                size=size, note=note,
            )
        except sim_book.SimOpenError as exc:
            await update.message.reply_text(f"⛔ 紀律守門擋下：\n{_safe_err(exc)}")
            return
        except Exception as exc:
            logger.exception("sim_open failed")
            await update.message.reply_text(f"❌ 開倉失敗：{_safe_err(exc)}")
            return

        arrow = "📈" if pos.direction == "long" else "📉"
        mode_tag = "🧠 Auto" if auto_reasoning else "✋ Manual"
        msg = (
            f"✅ 模擬開倉 #{pos.id}  {mode_tag}\n"
            f"{arrow} {pos.symbol} {pos.direction} × {pos.size} 張\n"
            f"  進場 {pos.entry:.2f} / 停損 {pos.stop:.2f} / 目標 {pos.target:.2f}\n"
            f"  風險 {pos.planned_risk_twd:.0f} 元（{pos.planned_risk_twd / 400_000 * 100:.2f}% 資金）\n"
            f"  獎勵 {pos.planned_reward_twd:.0f} 元  R:R {pos.risk_reward:.2f}\n"
        )
        if auto_reasoning:
            msg += f"  📐 {auto_reasoning}\n"
        msg += (
            f"  Bot 會自動監控、觸停損或停利時推播\n"
            f"  覺得不對立刻砍：/sim_close {pos.id}"
        )
        await update.message.reply_text(msg)

    async def cmd_sim_close(self, update, context):
        """手動結算紙上模擬部位。

        用法：/sim_close <id> [price]
        - 不給 price → 用 Shioaji 即時 M3 last close
        - 給 price（例如 38.4）→ 用該價結算
        """
        args = context.args or []
        if not args:
            await update.message.reply_text("用法：/sim_close <id> [price]")
            return
        pos_id = args[0].strip()
        manual_price: Optional[float] = None
        if len(args) >= 2:
            try:
                manual_price = float(args[1])
            except ValueError:
                await update.message.reply_text(f"⚠️ 價格解析失敗：{args[1]!r}")
                return

        # 找到部位（取得 symbol 用來拉市價）
        active = sim_book.list_active()
        pos = next((p for p in active if p.id == pos_id), None)
        if pos is None:
            await update.message.reply_text(f"❌ 找不到 active 部位 id={pos_id}")
            return

        if manual_price is None:
            try:
                m3 = await shioaji_fetch_m3(pos.symbol)
                if m3 is None or m3.empty:
                    await update.message.reply_text(
                        f"⚠️ 拉不到 {pos.symbol} 即時價、請手動給：/sim_close {pos_id} <price>"
                    )
                    return
                manual_price = float(m3["close"].iloc[-1])
            except Exception as exc:
                logger.exception("sim_close fetch price failed")
                await update.message.reply_text(f"❌ 拉價格失敗：{_safe_err(exc)}")
                return

        try:
            closed = sim_book.close_position(
                pos_id, exit_price=manual_price, reason="manual_close",
            )
        except sim_book.SimOpenError as exc:
            await update.message.reply_text(f"❌ {_safe_err(exc)}")
            return

        emoji = "✅" if (closed.pnl_twd or 0) > 0 else "💀"
        await update.message.reply_text(
            f"{emoji} 模擬結算 #{closed.id}\n"
            f"  {closed.symbol} {closed.direction} × {closed.size}\n"
            f"  進場 {closed.entry:.2f} → 出場 {closed.exit_price:.2f}\n"
            f"  損益 {closed.pnl_twd:+.0f} 元（{closed.r_multiple:+.2f}R）\n"
            f"  原因：手動結算"
        )

    async def cmd_sim_status(self, update, context):
        """列今日紙上部位（active + closed）。"""
        active = sim_book.list_active()
        today = sim_book.list_today()
        today_closed = [p for p in today if p.status != "active"]

        lines = ["📋 紙上模擬部位"]
        if active:
            lines.append(f"\n🟢 進行中（{len(active)}）：")
            for p in active:
                lines.append(
                    f"  #{p.id} {p.symbol} {p.direction} ×{p.size}  "
                    f"進場 {p.entry:.2f} / 停損 {p.stop:.2f} / 目標 {p.target:.2f}"
                )
        if today_closed:
            lines.append(f"\n📊 今日已結算（{len(today_closed)}）：")
            for p in today_closed:
                emo = "✅" if (p.pnl_twd or 0) > 0 else "💀"
                lines.append(
                    f"  {emo} #{p.id} {p.symbol} "
                    f"{p.entry:.2f}→{p.exit_price:.2f}  "
                    f"{p.pnl_twd:+.0f} 元（{p.r_multiple:+.2f}R）"
                )

        # 今日筆數提醒
        today_total = len(today)
        lines.append(
            f"\n📐 今日已開 {today_total} / {sim_book.DAILY_OPEN_LIMIT} 筆"
            + ("  ⛔ 已達上限" if today_total >= sim_book.DAILY_OPEN_LIMIT else "")
        )
        if not active and not today_closed:
            lines = ["📋 今日尚無紙上部位"]
        await update.message.reply_text("\n".join(lines))

    async def cmd_sim_report(self, update, context):
        """月度成績單。用法：/sim_report [YYYY-MM]，預設當月。"""
        from datetime import date as _date
        args = context.args or []
        ym = args[0].strip() if args else _date.today().strftime("%Y-%m")
        try:
            stats = sim_book.monthly_stats(ym)
        except Exception as exc:
            await update.message.reply_text(f"❌ 報告產生失敗：{_safe_err(exc)}")
            return

        decided = stats.wins + stats.losses
        # 紀律達標檢查（對應 LESSONS §2.7.5 復實盤條件）
        meet_win = stats.win_rate >= 0.50 and decided >= 20
        meet_ev = stats.expectancy_r > 0 and decided >= 20
        verdict = "✅ 達標、可考慮回實盤" if (meet_win and meet_ev) else (
            f"⏳ 樣本不足（{decided} < 20）" if decided < 20
            else "❌ 未達標、繼續紙上模擬"
        )

        await update.message.reply_text(
            f"📊 紙上模擬成績單 {ym}\n"
            f"  總開倉 {stats.total}（已結算 {decided + stats.manual} / 進行中 {stats.active}）\n"
            f"  ✅ 勝 {stats.wins}  /  💀 敗 {stats.losses}  /  📤 手動 {stats.manual}\n"
            f"  勝率（W/L）：{stats.win_rate:.0%}\n"
            f"  平均 R：{stats.avg_r:+.2f}\n"
            f"  期望值（R/筆）：{stats.expectancy_r:+.2f}\n"
            f"  累計盈虧：{stats.total_pnl_twd:+.0f} 元（含手續費粗估）\n"
            f"\n復實盤條件（LESSONS §2.7.5）：\n"
            f"  勝率 ≥ 50% + 期望值 > 0 + 樣本 ≥ 20\n"
            f"  → {verdict}"
        )

    # ── Andrew TXF 台指期框架 ────────────────────────────────────────────────

    async def cmd_txf(self, update, context):
        """產生今日台指期訊號卡並記錄。用法：/txf <ORH> <ORL>
        例：/txf 22300 22180
        """
        from backend.daily_signal import (
            _get_bias, _make_card, _append_log, refresh_layer_a
        )
        from datetime import date

        args = context.args or []
        if len(args) < 2:
            await update.message.reply_text(
                "用法：/txf <ORH> <ORL>\n"
                "例：/txf 22300 22180\n\n"
                "ORH / ORL 從看盤軟體抄前 30 分鐘高低點"
            )
            return

        try:
            orh = float(args[0])
            orl = float(args[1])
        except ValueError:
            await update.message.reply_text("❌ ORH / ORL 必須是數字")
            return

        if orh <= orl:
            await update.message.reply_text("❌ ORH 必須大於 ORL")
            return

        try:
            bias_a, a1, a2, a3 = _get_bias()
        except RuntimeError as exc:
            await update.message.reply_text(f"❌ Layer A 讀取失敗：{_safe_err(exc)}")
            return

        card = _make_card(orh, orl, orl, bias_a, a1, a2, a3)

        # log to paper_log.csv
        from backend.daily_signal import OR_WINDOW_MIN, STOP_PTS, REWARD_MULT, BIAS_THRESHOLD
        direction = "long" if bias_a >= BIAS_THRESHOLD else ("short" if bias_a <= -BIAS_THRESHOLD else "skip")
        or_range = orh - orl
        target_pts = max(or_range * REWARD_MULT, STOP_PTS * REWARD_MULT)
        _append_log({
            "date":        date.today().isoformat(),
            "bias_a":      bias_a,
            "orh":         orh,
            "orl":         orl,
            "or_range":    round(or_range, 1),
            "direction":   direction,
            "entry":       orh if direction == "long" else (orl if direction == "short" else ""),
            "stop":        round(orh - STOP_PTS, 0) if direction == "long" else (round(orl + STOP_PTS, 0) if direction == "short" else ""),
            "target":      round(orh + target_pts, 0) if direction == "long" else (round(orl - target_pts, 0) if direction == "short" else ""),
            "actual_exit": "",
            "actual_pnl":  "",
            "notes":       "",
        })

        await update.message.reply_text(f"```\n{card}\n```", parse_mode="Markdown")

    async def cmd_txf_result(self, update, context):
        """收盤後記錄今日台指期結果。用法：/txf_result <出場價> [備注]
        例：/txf_result 22270 止損
        """
        from backend.log_result import fill_result, _load, _print_stats
        import io, sys

        args = context.args or []
        if not args:
            await update.message.reply_text(
                "用法：/txf_result <出場價> [備注]\n"
                "例：/txf_result 22270 止損出場"
            )
            return

        try:
            exit_px = float(args[0])
        except ValueError:
            await update.message.reply_text("❌ 出場價必須是數字")
            return

        notes = " ".join(args[1:]) if len(args) > 1 else ""

        # capture print output from fill_result
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            from backend.log_result import fill_result as _fill
            _fill(exit_px, notes)
        except SystemExit:
            pass
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue().strip()
        await update.message.reply_text(f"```\n{output}\n```", parse_mode="Markdown")

    async def cmd_txf_stats(self, update, context):
        """顯示台指期紙上模擬累計統計。"""
        import io, sys

        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            from backend.log_result import show_stats
            show_stats()
        except SystemExit:
            pass
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue().strip()
        if not output:
            output = "（尚無統計資料）"
        await update.message.reply_text(f"```\n{output}\n```", parse_mode="Markdown")

    async def cmd_shortage(self, update, context):
        """缺貨雷達：TWSE 全市場粗篩（量價齊揚，免限流即時）。"""
        import asyncio
        from backend.shortage_radar import twse_rank
        await update.message.reply_text("🛰️ 抓 TWSE 全市場財報中…")
        report = await asyncio.get_event_loop().run_in_executor(None, twse_rank)
        await update.message.reply_text(report)

    async def _job_shortage(self, context):
        """每週一 07:30 推缺貨雷達全市場粗篩。"""
        try:
            import asyncio
            from backend.shortage_radar import twse_rank
            report = await asyncio.get_event_loop().run_in_executor(None, twse_rank)
            await context.bot.send_message(chat_id=_CHAT_ID, text=report)
        except Exception as exc:
            logger.warning("shortage job failed: %s", exc)

    async def _job_blade1(self, context):
        """每日盤後(週一~五 15:00)掃第一刀觀察名單,有新進場訊號才推。"""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        if datetime.now(ZoneInfo("Asia/Taipei")).weekday() >= 5:
            return
        try:
            import asyncio
            from backend import blade1_watcher
            msgs = await asyncio.get_event_loop().run_in_executor(None, blade1_watcher.scan)
            for m in msgs:
                await context.bot.send_message(chat_id=_CHAT_ID, text=m)
        except Exception as exc:
            logger.warning("blade1 job failed: %s", exc)

    async def cmd_blade1(self, update, context):
        """第一刀 watcher:掃觀察名單,列現在有進場訊號的。"""
        import asyncio
        from backend import blade1_watcher
        await update.message.reply_text("🗡️ 掃第一刀觀察名單中…(約 20 秒)")
        report = await asyncio.get_event_loop().run_in_executor(None, blade1_watcher.run_report)
        await update.message.reply_text(report)

    async def _job_hot(self, context):
        """每日盤後(週一~五 14:00)推熱門族群雷達:市場在瘋什麼 + 基本面體檢。"""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        if datetime.now(ZoneInfo("Asia/Taipei")).weekday() >= 5:
            return
        try:
            import asyncio
            from backend import hot_sector
            report = await asyncio.get_event_loop().run_in_executor(None, hot_sector.report)
            await context.bot.send_message(chat_id=_CHAT_ID, text=report)
        except Exception as exc:
            logger.warning("hot_sector job failed: %s", exc)

    async def cmd_hot(self, update, context):
        """熱門族群雷達:今天市場在瘋哪個族群 + 最熱族群基本面體檢。"""
        import asyncio
        from backend import hot_sector
        await update.message.reply_text("🔥 掃今日熱門族群中…(約 30 秒)")
        report = await asyncio.get_event_loop().run_in_executor(None, hot_sector.report)
        await update.message.reply_text(report)

    async def _job_news_radar(self, context):
        """一天多次推播 AI/半導體新聞戰情室,只推「上次後新出現」的缺貨/漲價/營收訊號(Google News RSS)。"""
        try:
            import asyncio
            from backend import news_radar
            report = await asyncio.get_event_loop().run_in_executor(None, news_radar.report_incremental)
            if report:
                await context.bot.send_message(chat_id=_CHAT_ID, text=report)
        except Exception as exc:
            logger.warning("news_radar job failed: %s", exc)

    async def cmd_news(self, update, context):
        """AI/半導體新聞戰情室:近 24h 缺貨/漲價/營收訊號(手動觸發)。"""
        import asyncio
        from backend import news_radar
        await update.message.reply_text("📡 掃 AI/半導體新聞中…(約 10 秒)")
        report = await asyncio.get_event_loop().run_in_executor(None, news_radar.report)
        await update.message.reply_text(report)

    async def cmd_cdp(self, update, context):
        """CDP 逆勢操作四線(AH/NH/NL/AL)。/cdp 2330 AAPL(台股+美股皆可,最多 5 檔)。"""
        from backend import cdp
        codes = [c for arg in (context.args or []) for c in re.split(r"[,\s]+", arg) if c]
        if not codes:
            await update.message.reply_text(
                "用法:/cdp 2330(或 /cdp AAPL)— 由前一交易日高低收算出當沖四線\n"
                "AH 突破 / NH 轉強 / NL 轉弱 / AL 跌破,台股美股皆可,一次最多 5 檔。")
            return
        for code in codes[:5]:
            try:
                msg = await cdp.analyze(code)
            except Exception as exc:
                msg = f"{code}:{_safe_err(exc)}"
            await update.message.reply_text(msg)

    async def _job_morning_report(self, context):
        """07:00 自動推播鑽豹盤前報告。"""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        if datetime.now(ZoneInfo("Asia/Taipei")).weekday() >= 5:
            return
        try:
            from backend.morning_report import generate
            report = generate()
            await context.bot.send_message(chat_id=_CHAT_ID, text=report)
        except Exception as exc:
            logger.warning("morning report job failed: %s", exc)

    async def _job_txf_morning(self, context):
        """08:50 推播今日 Layer A 偏向（開盤前最後確認）。"""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        _tpe = ZoneInfo("Asia/Taipei")
        now = datetime.now(_tpe)
        # 只在週一到週五推
        if now.weekday() >= 5:
            return

        try:
            from backend.daily_signal import _get_bias, refresh_layer_a
            refresh_layer_a()
            bias_a, a1, a2, a3 = _get_bias()
        except Exception as exc:
            logger.warning("txf morning job failed: %s", exc)
            return

        bias_sign = "+" if bias_a > 0 else ""
        bar = "▓" * abs(bias_a) + "░" * (3 - abs(bias_a))
        direction = "多方" if bias_a >= 1 else ("空方" if bias_a <= -1 else "觀望")
        a1_txt = "↓ 美債偏多" if a1 > 0 else "↑ 美債偏空"
        a2_txt = "↓ 美元偏多" if a2 > 0 else "↑ 美元偏空"
        a3_txt = "三指數同紅" if a3 > 0 else ("三指數同綠" if a3 < 0 else "指數分歧")

        msg = (
            f"☀️ 台指期早安 {now.strftime('%m/%d')}\n"
            f"Layer A  bias = {bias_sign}{bias_a}  [{bar}]  → {direction}\n"
            f"  {a1_txt}  ｜  {a2_txt}  ｜  {a3_txt}\n\n"
            f"09:15 後請輸入今日開盤區間：\n"
            f"  /txf <ORH> <ORL>"
        )
        try:
            await context.bot.send_message(chat_id=_CHAT_ID, text=msg)
        except Exception as exc:
            logger.warning("txf morning push failed: %s", exc)

    async def _job_txf_reminder(self, context):
        """09:15 提醒：OR 窗口關閉，可以輸入了。"""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        _tpe = ZoneInfo("Asia/Taipei")
        now = datetime.now(_tpe)
        if now.weekday() >= 5:
            return
        try:
            await context.bot.send_message(
                chat_id=_CHAT_ID,
                text="⏰ OR 窗口關閉（09:15）\n輸入今日高低點 → /txf <ORH> <ORL>",
            )
        except Exception as exc:
            logger.warning("txf reminder push failed: %s", exc)

    # ── sending helpers ──────────────────────────────────────────────────────

    async def _send_signal(self, update, s: SMCSignal, daily, m3) -> None:
        await update.message.reply_text(_summary_text(s))
        html = generate_html(s, daily_df=daily, intraday_df=m3,
                             fallback_to_daily=(s.timeframe == "1D" and (m3 is None or m3.empty)))
        bio = BytesIO(html.encode("utf-8"))
        bio.name = f"smc_{s.symbol}_{s.signal_type}.html"
        await update.message.reply_document(document=bio)

    # ── entrypoint ───────────────────────────────────────────────────────────

    async def _post_init(self, app) -> None:
        from telegram import BotCommand
        # 設計原則（2026-05-20 使用者要求）：
        # Telegram menu「點下去就直接送出指令」，所以只放「無參數可直接執行」
        # 的指令。需要參數的指令（/sim_open /sim_close /ai_analyse /wl_add 等）
        # 從 menu 移除、使用者手動打、避免點到誤送空指令。
        commands = [
            # === 台指期 Andrew 框架 ===
            BotCommand("txf_stats", "📊 台指期紙上模擬累計統計"),
            BotCommand("shortage", "🛰️ 缺貨雷達 — 全市場產業缺貨排行"),
            # === 紙上模擬（最常用）===
            BotCommand("sim_status", "📋 今日紙上部位（active + 已結算）"),
            BotCommand("sim_report", "📊 紙上模擬月度成績單"),
            # === Watchlist 查看 ===
            BotCommand("wl", "📋 顯示當沖 watchlist"),
            BotCommand("wl_clear", "🧹 清空當沖 watchlist"),
            # === 題材 / 隔日沖 / Watcher ===
            BotCommand("aistockmap", "📰 抓 aistockmap 每日題材"),
            BotCommand("overnight_check", "🌙 對 watchlist 跑隔日沖警告"),
            BotCommand("watch_alerts", "👀 立刻跑一輪 N 字 + OB watcher"),
            BotCommand("analyst_scan", "🧠 對 watchlist 跑 7-setup pipeline"),
            BotCommand("gainers", "🔥 今日上市漲幅 ≥5% 強勢股"),
            BotCommand("scan", "🎯 當沖選股(漲幅+均線+量能+型態)"),
            BotCommand("bowl", "🥣 碗型整理+爆量突破(不設漲幅門檻)"),
            BotCommand("potential", "🔭 潛力股6條技術特性(上市+上櫃活躍股計分)"),
            BotCommand("strong", "🚀 強勢股(當日漲幅≥5%)再套6條技術特性計分"),
            BotCommand("dia", "💎 鑽豹高分記錄（/dia 2330 評個股）"),
            BotCommand("fin", "🗡️ 鑽豹四刀分析（/fin 2330 完整體檢）"),
            BotCommand("blade1", "🗡️ 第一刀 watcher（掃觀察名單進場訊號）"),
            BotCommand("hot", "🔥 熱門族群雷達（今天市場在瘋什麼）"),
            BotCommand("pullback", "📉 拉回整理檢查(週/月線)"),
            BotCommand("chart", "📈 ATM×SMC 策略圖(watchlist首檔；/chart 2330指定)"),
            BotCommand("news", "📡 AI/半導體新聞戰情室(缺貨/漲價/營收訊號)"),
        ]
        await app.bot.set_my_commands(commands)
        logger.info("registered %d telegram bot commands", len(commands))

    def run(self) -> None:
        Application, CommandHandler, MessageHandler, filters = self._telegram_app()
        app = (
            Application.builder()
            .token(_BOT_TOKEN)
            # 容忍慢握手：預設 connect_timeout 太短,啟動瞬間網路稍慢就 TimedOut crash
            .connect_timeout(30.0)
            .read_timeout(30.0)
            .write_timeout(30.0)
            .pool_timeout(30.0)
            .get_updates_connect_timeout(30.0)
            .get_updates_read_timeout(30.0)
            .post_init(self._post_init)
            .build()
        )
        app.add_handler(CommandHandler("smc_scan", self.cmd_scan))
        app.add_handler(CommandHandler("aistockmap", self.cmd_aistockmap))
        app.add_handler(CommandHandler("wl", self.cmd_wl))
        app.add_handler(CommandHandler("wl_add", self.cmd_wl_add))
        app.add_handler(CommandHandler("wl_del", self.cmd_wl_del))
        app.add_handler(CommandHandler("wl_clear", self.cmd_wl_clear))
        app.add_handler(CommandHandler("overnight_check", self.cmd_overnight_check))
        app.add_handler(CommandHandler("analyst_scan", self.cmd_analyst_scan))
        app.add_handler(CommandHandler("watch_alerts", self.cmd_watch_alerts))
        app.add_handler(CommandHandler("gainers", self.cmd_gainers))
        app.add_handler(CommandHandler("scan", self.cmd_daytrade_scan))
        app.add_handler(CommandHandler("bowl", self.cmd_bowl_scan))
        app.add_handler(CommandHandler("potential", self.cmd_potential_scan))
        app.add_handler(CommandHandler("strong", self.cmd_strong_scan))
        app.add_handler(CommandHandler("dia", self.cmd_diamond))
        app.add_handler(CommandHandler("pe", self.cmd_pe))
        app.add_handler(CommandHandler("pullback", self.cmd_pullback))
        app.add_handler(CommandHandler("chart", self.cmd_chart))
        app.add_handler(CommandHandler("ai_analyse", self.cmd_ai_analyse))
        app.add_handler(CommandHandler("sim_open", self.cmd_sim_open))
        app.add_handler(CommandHandler("sim_close", self.cmd_sim_close))
        app.add_handler(CommandHandler("sim_status", self.cmd_sim_status))
        app.add_handler(CommandHandler("sim_report", self.cmd_sim_report))
        app.add_handler(CommandHandler("txf", self.cmd_txf))
        app.add_handler(CommandHandler("txf_result", self.cmd_txf_result))
        app.add_handler(CommandHandler("txf_stats", self.cmd_txf_stats))
        app.add_handler(CommandHandler("shortage", self.cmd_shortage))
        app.add_handler(CommandHandler("fin", self.cmd_fin))
        app.add_handler(CommandHandler("blade1", self.cmd_blade1))
        app.add_handler(CommandHandler("hot", self.cmd_hot))
        app.add_handler(CommandHandler("cdp", self.cmd_cdp))
        app.add_handler(CommandHandler("news", self.cmd_news))
        app.add_handler(MessageHandler(filters.Regex(r"^\s*財報"), self.cmd_fin_zh))

        # JobQueue：盤中每 3 分鐘自動跑一次 N 字 watcher（含 dedup）
        if app.job_queue is not None:
            app.job_queue.run_repeating(
                self._job_watcher,
                interval=180,
                first=30,
                name="n-pattern-watcher",
            )
            logger.info("scheduled n-pattern-watcher: every 180s")

            # 漲幅榜：每天 12:30 / 13:00 / 13:30（台北時間）推上市 5%+ 強勢股
            from datetime import time as _dt_time
            from zoneinfo import ZoneInfo
            _tpe = ZoneInfo("Asia/Taipei")
            # 07:00 鑽豹盤前報告
            app.job_queue.run_daily(
                self._job_morning_report,
                time=_dt_time(hour=7, minute=0, tzinfo=_tpe),
            )
            # 台指期早安推播（08:50）
            app.job_queue.run_daily(
                self._job_txf_morning,
                time=_dt_time(hour=8, minute=50, tzinfo=_tpe),
            )
            # 09:15 OR 窗口提醒
            app.job_queue.run_daily(
                self._job_txf_reminder,
                time=_dt_time(hour=9, minute=15, tzinfo=_tpe),
            )
            for _hh, _mm in ((12, 30), (13, 0), (13, 30)):
                app.job_queue.run_daily(
                    self._job_gainers,
                    time=_dt_time(hour=_hh, minute=_mm, tzinfo=_tpe),
                    name=f"gainers-{_hh:02d}{_mm:02d}",
                )
            logger.info("scheduled gainers push: 12:30 / 13:00 / 13:30 (Asia/Taipei)")
            # 每週一 07:30 缺貨雷達產業排行（季資料變動慢，週更即可）
            app.job_queue.run_daily(
                self._job_shortage,
                time=_dt_time(hour=7, minute=30, tzinfo=_tpe),
                days=(0,),
                name="shortage-weekly",
            )
            logger.info("scheduled shortage radar: Mon 07:30 (Asia/Taipei)")
            # 每日盤後 15:00 掃第一刀觀察名單(有新帶量長紅K訊號才推)
            app.job_queue.run_daily(
                self._job_blade1,
                time=_dt_time(hour=15, minute=0, tzinfo=_tpe),
                days=(0, 1, 2, 3, 4),
                name="blade1-daily",
            )
            logger.info("scheduled blade1 watcher: weekdays 15:00 (Asia/Taipei)")
            # 每日盤後 14:00 熱門族群雷達(市場在瘋什麼 + 最熱族群基本面體檢)
            app.job_queue.run_daily(
                self._job_hot,
                time=_dt_time(hour=14, minute=0, tzinfo=_tpe),
                days=(0, 1, 2, 3, 4),
                name="hot-sector-daily",
            )
            logger.info("scheduled hot-sector: weekdays 14:00 (Asia/Taipei)")
            # 一天 5 次(約每 4 小時)推播 AI/半導體新聞戰情室,只推新出現的缺貨/漲價/營收訊號
            # (全球新聞,不分平假日;比照盤前/盤中/美股開盤後時段分布)
            for _hh, _mm in ((7, 15), (11, 0), (15, 0), (19, 0), (23, 0)):
                app.job_queue.run_daily(
                    self._job_news_radar,
                    time=_dt_time(hour=_hh, minute=_mm, tzinfo=_tpe),
                    name=f"news-radar-{_hh:02d}{_mm:02d}",
                )
            logger.info("scheduled news radar: 07:15/11:00/15:00/19:00/23:00 (Asia/Taipei), incremental-only")
        else:
            logger.warning("JobQueue 不可用（pip install 'python-telegram-bot[job-queue]'）")
        logger.info("SMC bot polling …")
        app.run_polling(close_loop=False)


def main() -> None:
    SMCBot().run()


if __name__ == "__main__":
    main()
