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
        ]
        await app.bot.set_my_commands(commands)
        logger.info("registered %d telegram bot commands", len(commands))

    def run(self) -> None:
        Application, CommandHandler = self._telegram_app()
        app = (
            Application.builder()
            .token(_BOT_TOKEN)
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
        app.add_handler(CommandHandler("ai_analyse", self.cmd_ai_analyse))
        app.add_handler(CommandHandler("sim_open", self.cmd_sim_open))
        app.add_handler(CommandHandler("sim_close", self.cmd_sim_close))
        app.add_handler(CommandHandler("sim_status", self.cmd_sim_status))
        app.add_handler(CommandHandler("sim_report", self.cmd_sim_report))

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
