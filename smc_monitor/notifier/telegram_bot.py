# ============================================================
#  notifier/telegram_bot.py
#  Telegram Bot 模組：接收指令 + 推播訊號
# ============================================================

import asyncio
import logging
import tempfile
from pathlib import Path
from datetime import datetime

from telegram import Update, Bot, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode

from config.settings import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    MONITOR, USE_TELEGRAPH
)
from core.screenshotter import TVScreenshotter
from core.analyzer import ChartAnalyzer
from web.report_generator import generate_html_report

logger = logging.getLogger(__name__)

# 全域共用（避免重複啟動瀏覽器）
_screenshotter: TVScreenshotter = None
_analyzer = ChartAnalyzer()


async def _get_screenshotter() -> TVScreenshotter:
    global _screenshotter
    if _screenshotter is None:
        _screenshotter = TVScreenshotter()
        await _screenshotter.start()
    return _screenshotter


# ── 上傳 HTML 到 Telegraph ────────────────────────────────────
async def _upload_to_telegraph(html: str, title: str) -> str:
    """上傳 HTML 報告到 Telegraph，回傳可分享連結"""
    try:
        import httpx
        # Telegraph 只接受 HTML 內容（不支援完整 HTML，用 telegraph API）
        # 這裡改用 file.io 或直接回傳內嵌訊息
        # 實際部署建議用 Netlify MCP 上傳
        return ""  # 暫時回傳空值，直接在 Telegram 顯示分析
    except Exception as e:
        logger.error(f"Telegraph upload failed: {e}")
        return ""


# ── 核心：分析股票並推播 ──────────────────────────────────────
async def analyze_and_notify(
    symbol: str,
    chat_id: str,
    bot: Bot,
    interval: str = "1",
    triggered_by: str = "manual"
):
    """截圖 → 分析 → 生成報告 → 推播 Telegram"""

    # 1. 截圖
    await bot.send_message(chat_id, f"📸 正在截取 {symbol} {interval}m 圖表...", parse_mode=ParseMode.HTML)

    try:
        ss = await _get_screenshotter()
        result = await ss.capture(symbol, interval)
        screenshot_path = result["path"]
    except Exception as e:
        await bot.send_message(chat_id, f"❌ 截圖失敗：{e}")
        return

    # 2. Claude 分析
    await bot.send_message(chat_id, "🔍 Claude 分析中...")
    analysis = await _analyzer.analyze(screenshot_path, symbol, interval)
    analysis.timestamp = datetime.now().isoformat()

    # 3. 生成 HTML 報告
    html_report = generate_html_report(analysis)

    # 4. 推播截圖
    with open(screenshot_path, "rb") as f:
        await bot.send_photo(
            chat_id=chat_id,
            photo=InputFile(f, filename=screenshot_path.name),
            caption=_build_caption(analysis),
            parse_mode=ParseMode.HTML,
        )

    # 5. 推播 HTML 報告（作為 .html 文件）
    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(html_report)
        tmp_path = tmp.name

    with open(tmp_path, "rb") as f:
        await bot.send_document(
            chat_id=chat_id,
            document=InputFile(f, filename=f"{symbol}_{interval}m_analysis.html"),
            caption="📊 完整 HTML 分析報告（下載後在瀏覽器開啟）",
        )

    Path(tmp_path).unlink(missing_ok=True)

    # 6. 若有警告訊號，加強提示
    if analysis.has_alert_signal:
        alert_text = _build_alert_text(analysis)
        await bot.send_message(chat_id, alert_text, parse_mode=ParseMode.HTML)

    logger.info(f"[notify] {symbol} {interval}m — signals: {[s.type for s in analysis.signals]}")


def _build_caption(analysis) -> str:
    """Telegram 截圖說明（支援 HTML 格式）"""
    signal_text = " | ".join(
        f"<b>{s.type}</b>({'↑' if s.direction=='bullish' else '↓'})"
        for s in analysis.signals
    ) or "無明確訊號"

    change_emoji = "📉" if analysis.price_change < 0 else "📈"
    struct_emoji = {"bullish":"🟢","bearish":"🔴","ranging":"🟡"}.get(analysis.market_structure,"⚪")

    return (
        f"{struct_emoji} <b>{analysis.symbol}</b> · {analysis.interval}m\n"
        f"{change_emoji} <code>{analysis.current_price:.2f}</code> "
        f"({'+' if analysis.price_change>=0 else ''}{analysis.price_change:.2f} "
        f"/ {'+' if analysis.price_change_pct>=0 else ''}{analysis.price_change_pct:.2f}%)\n\n"
        f"🏷 <b>訊號：</b>{signal_text}\n"
        f"📐 <b>結構：</b>{analysis.market_structure.upper()}\n\n"
        f"💡 {analysis.recommendation[:120]}{'...' if len(analysis.recommendation)>120 else ''}"
    )


def _build_alert_text(analysis) -> str:
    """高優先級訊號的強調通知"""
    sig_names = ", ".join(s.type for s in analysis.signals)
    return (
        f"⚡ <b>訊號觸發 · {analysis.symbol}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"訊號：<b>{sig_names}</b>\n"
        f"當前價：<code>{analysis.current_price:.2f}</code>\n"
        f"結構：{analysis.market_structure.upper()}\n"
        f"━━━━━━━━━━━━━━\n"
        f"⚠️ {analysis.risk_note}"
    )


# ── Telegram Bot 指令處理器 ───────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>SMC Signal Monitor</b> 已就緒\n\n"
        "指令列表：\n"
        "/scan <代碼> [時間框架] — 立即分析\n"
        "/watch <代碼> — 加入監控清單\n"
        "/unwatch <代碼> — 移出監控清單\n"
        "/list — 查看監控清單\n"
        "/mtf <代碼> — 多時間框架分析\n"
        "/status — 系統狀態\n\n"
        "範例：/scan 3481 或 /scan AAPL 5",
        parse_mode=ParseMode.HTML,
    )


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """手動觸發單一股票分析"""
    args = ctx.args
    if not args:
        await update.message.reply_text("用法：/scan <股票代碼> [時間框架]\n範例：/scan 3481 或 /scan AAPL 5")
        return

    symbol = args[0].upper()
    interval = args[1] if len(args) > 1 else "1"

    await analyze_and_notify(
        symbol=symbol,
        chat_id=str(update.effective_chat.id),
        bot=ctx.bot,
        interval=interval,
        triggered_by="manual",
    )


async def cmd_mtf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """多時間框架分析（1m / 5m / 15m）"""
    args = ctx.args
    if not args:
        await update.message.reply_text("用法：/mtf <股票代碼>")
        return

    symbol = args[0].upper()
    await update.message.reply_text(f"🔄 開始多時間框架分析 {symbol}（1m / 5m / 15m）...")

    for interval in ["1", "5", "15"]:
        await analyze_and_notify(
            symbol=symbol,
            chat_id=str(update.effective_chat.id),
            bot=ctx.bot,
            interval=interval,
            triggered_by="mtf",
        )
        await asyncio.sleep(2)


async def cmd_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """動態加入監控清單"""
    args = ctx.args
    if not args:
        await update.message.reply_text("用法：/watch <股票代碼>")
        return
    symbol = args[0].upper()
    if symbol not in MONITOR.watchlist:
        MONITOR.watchlist.append(symbol)
        await update.message.reply_text(f"✅ {symbol} 已加入監控清單（共 {len(MONITOR.watchlist)} 支）")
    else:
        await update.message.reply_text(f"ℹ️ {symbol} 已在監控清單中")


async def cmd_unwatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        return
    symbol = args[0].upper()
    if symbol in MONITOR.watchlist:
        MONITOR.watchlist.remove(symbol)
        await update.message.reply_text(f"🗑 {symbol} 已從監控清單移除")
    else:
        await update.message.reply_text(f"ℹ️ {symbol} 不在監控清單中")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not MONITOR.watchlist:
        await update.message.reply_text("監控清單為空，使用 /watch <代碼> 新增")
        return
    text = "📋 <b>監控清單：</b>\n" + "\n".join(f"• {s}" for s in MONITOR.watchlist)
    text += f"\n\n⏱ 掃描間隔：{MONITOR.scan_interval_sec}秒"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global _screenshotter
    browser_status = "✅ 運行中" if _screenshotter else "💤 待機"
    await update.message.reply_text(
        f"⚙️ <b>系統狀態</b>\n"
        f"瀏覽器：{browser_status}\n"
        f"監控數量：{len(MONITOR.watchlist)} 支\n"
        f"掃描間隔：{MONITOR.scan_interval_sec}s\n"
        f"時間框架：{', '.join(MONITOR.timeframes)}m",
        parse_mode=ParseMode.HTML,
    )


# ── 自動掃描背景任務 ──────────────────────────────────────────
# 記錄最近推播的訊號，避免重複通知
_signal_cooldown: dict = {}  # key: "{symbol}_{signal_type}", value: timestamp


async def auto_scan_loop(bot: Bot):
    """背景定時掃描所有 watchlist 股票"""
    logger.info("[AutoScan] 背景掃描啟動")
    while True:
        try:
            for symbol in list(MONITOR.watchlist):
                for interval in MONITOR.timeframes:
                    try:
                        ss = await _get_screenshotter()
                        result = await ss.capture(symbol, interval)
                        analysis = await _analyzer.analyze(result["path"], symbol, interval)

                        if analysis.has_alert_signal:
                            # 檢查冷卻時間
                            for sig in analysis.signals:
                                key = f"{symbol}_{sig.type}"
                                last = _signal_cooldown.get(key, 0)
                                now = datetime.now().timestamp()

                                if now - last > MONITOR.signal_cooldown_sec:
                                    _signal_cooldown[key] = now
                                    analysis.timestamp = datetime.now().isoformat()
                                    html_report = generate_html_report(analysis)

                                    # 推播截圖
                                    with open(result["path"], "rb") as f:
                                        await bot.send_photo(
                                            chat_id=TELEGRAM_CHAT_ID,
                                            photo=InputFile(f),
                                            caption=_build_caption(analysis),
                                            parse_mode=ParseMode.HTML,
                                        )
                                    await bot.send_message(
                                        chat_id=TELEGRAM_CHAT_ID,
                                        text=_build_alert_text(analysis),
                                        parse_mode=ParseMode.HTML,
                                    )
                                    logger.info(f"[AutoScan] Alert sent: {symbol} {sig.type}")
                                    break  # 同一股票一次只送一個訊號

                        await asyncio.sleep(2)
                    except Exception as e:
                        logger.error(f"[AutoScan] {symbol} {interval}m error: {e}")

        except Exception as e:
            logger.error(f"[AutoScan] Loop error: {e}")

        await asyncio.sleep(MONITOR.scan_interval_sec)


# ── 啟動 Bot ─────────────────────────────────────────────────
def run_bot():
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO,
    )

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 指令
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("scan",    cmd_scan))
    app.add_handler(CommandHandler("mtf",     cmd_mtf))
    app.add_handler(CommandHandler("watch",   cmd_watch))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    app.add_handler(CommandHandler("list",    cmd_list))
    app.add_handler(CommandHandler("status",  cmd_status))

    # 啟動後自動開始背景掃描
    async def post_init(application):
        asyncio.create_task(auto_scan_loop(application.bot))

    app.post_init = post_init

    logger.info("✅ SMC Monitor Bot 啟動中...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run_bot()
