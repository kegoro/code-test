"""
Telegram Bot — 互動查詢 + 排程整合

使用者傳任何訊息即觸發查詢：
  "2330"        → 直接用代號查
  "台積電"       → 搜尋名稱後取第一符合代號
  "2317 鴻海"   → 混合也可以
  /help          → 使用說明
  /today         → 今日選股報告（無報告時自動執行分析）

架構：Application.run_polling() 為事件迴圈主人；
      APScheduler 在 post_init 裡啟動，共用同一 loop。
"""
import asyncio
import json
import re
import time
from pathlib import Path
from loguru import logger
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler, MessageHandler,
    ContextTypes, filters,
)
from telegram.constants import ParseMode

from config.settings import settings
from scrapers.finmind.financials import (
    fetch_income_statement, fetch_balance_sheet, fetch_cash_flow, pivot_statement,
)
from strategy.fundamental import build_fundamental_report, format_fundamental_report

_SYMBOL_RE = re.compile(r"\b([1-9][0-9]{3,4})\b")


def _ok(x) -> bool:
    """Return True if x is a non-empty DataFrame (not an Exception)."""
    return not isinstance(x, Exception) and hasattr(x, "empty") and not x.empty
_CACHE_FILE = Path(settings.data_dir) / "universe_cache.json"
_CACHE_TTL  = 86400   # 24 h

_SLOPE = {"up": "↑", "flat": "→", "down": "↓", "unknown": "?"}
_STATE = {
    "long_bull":    "長線多頭",
    "turning_bull": "轉折向上⭐",
    "bear":         "空頭趨勢",
    "unknown":      "資料不足",
}
_REC_EMOJI = {
    "積極佈局":         "🟢",
    "即將轉多-優先觀察": "⭐",
    "觀察等待":         "🟡",
    "謹慎觀察":         "🔵",
    "排除":             "🔴",
}

# In-memory cache, backed by disk
_universe_cache: list[dict] = []
_universe_loaded_at: float = 0.0


def _load_disk_cache() -> tuple[list[dict], float]:
    """Load universe from disk cache. Returns (stocks, saved_at) or ([], 0)."""
    try:
        if _CACHE_FILE.exists():
            payload = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            return payload.get("stocks", []), float(payload.get("saved_at", 0))
    except Exception as exc:
        logger.warning(f"[bot] Failed to read universe disk cache: {exc}")
    return [], 0.0


def _save_disk_cache(stocks: list[dict]) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps({"saved_at": time.time(), "stocks": stocks}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning(f"[bot] Failed to write universe cache: {exc}")


async def _fetch_twse_fallback() -> list[dict]:
    """Fallback: fetch all stocks from TWSE + TPEX OpenAPI."""
    import httpx
    _VALID = re.compile(r"^[1-9][0-9]{3,4}$")
    stocks: list[dict] = []

    urls = [
        ("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", "twse",
         "Code", "Name"),
        ("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes", "otc",
         "SecuritiesCompanyCode", "CompanyName"),
    ]
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                  headers={"User-Agent": "Mozilla/5.0"}) as client:
        for url, market, code_field, name_field in urls:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                for item in resp.json():
                    sym  = str(item.get(code_field) or "").strip()
                    name = str(item.get(name_field) or "").strip()
                    if _VALID.match(sym) and not sym.startswith("00") and name:
                        stocks.append({"symbol": sym, "name": name, "market": market})
            except Exception as exc:
                logger.warning(f"[bot] TWSE fallback ({market}) failed: {exc}")

    return stocks


async def _get_universe() -> list[dict]:
    global _universe_cache, _universe_loaded_at

    # Hot in-memory cache
    if _universe_cache and (time.time() - _universe_loaded_at) < _CACHE_TTL:
        return _universe_cache

    # Warm disk cache
    disk_stocks, disk_saved_at = _load_disk_cache()
    if disk_stocks and (time.time() - disk_saved_at) < _CACHE_TTL:
        _universe_cache    = disk_stocks
        _universe_loaded_at = disk_saved_at
        logger.info(f"[bot] Universe loaded from disk: {len(disk_stocks)} stocks")
        return _universe_cache

    # Fetch fresh data
    stocks: list[dict] = []
    try:
        from scrapers.finmind.universe import fetch_stock_universe
        stocks = await fetch_stock_universe()
        logger.info(f"[bot] Universe fetched from FinMind: {len(stocks)} stocks")
    except Exception as exc:
        logger.warning(f"[bot] FinMind universe failed, trying TWSE fallback: {exc}")

    if not stocks:
        stocks = await _fetch_twse_fallback()
        logger.info(f"[bot] Universe fetched from TWSE fallback: {len(stocks)} stocks")

    if stocks:
        _universe_cache     = stocks
        _universe_loaded_at = time.time()
        _save_disk_cache(stocks)
    elif disk_stocks:
        # Use stale disk cache rather than empty
        logger.warning("[bot] All sources failed — using stale disk cache")
        _universe_cache     = disk_stocks
        _universe_loaded_at = time.time()

    return _universe_cache


def _lookup_multi(text: str, universe: list[dict], max_results: int = 3) -> list[dict]:
    """
    Returns matching stocks:
    - Exact symbol match → exactly 1 result (or a synthetic entry if not in universe)
    - Partial name/symbol match → up to max_results results
    """
    text = text.strip()
    m = _SYMBOL_RE.search(text)
    if m:
        sym = m.group(1)
        for s in universe:
            if s["symbol"] == sym:
                return [s]
        return [{"symbol": sym, "name": sym, "market": "unknown"}]

    text_lower = text.lower()
    matches = [
        s for s in universe
        if text_lower in s["name"].lower() or text_lower in s["symbol"]
    ]
    return matches[:max_results]


# ── Format helpers ────────────────────────────────────────────────────────────

def _chip_line(c: dict) -> str:
    consec = c["foreign_consecutive_buy_days"]
    if consec >= 6:   return f"外資連買{consec}天🔥"
    if consec >= 3:   return f"外資連買{consec}天✅"
    if consec > 0:    return f"外資買{consec}天"
    if consec < 0:    return f"外資連賣{abs(consec)}天⚠️"
    if c["has_inst_buy_last5d"]: return "投信近期買超"
    return "無明顯法人"


def _extras(t: dict, c: dict, w: dict) -> list[str]:
    tags = []
    if w["b2_breakout"]:               tags.append("B2突破🚀")
    if w["detected"]:                  tags.append("洗盤中🧹")
    if w["accumulation_on_decline"]:   tags.append("量縮吸籌📦")
    if t["deduction_drop_imminent"]:   tags.append("扣抵將降📉")
    if c["margin_confluence"]:         tags.append("融資合流🤝")
    if c["contrarian_on_weak_market"]: tags.append("逆勢🔥")
    return tags


def _format_signal_card(symbol: str, name: str, signal) -> str:
    """
    統一格式卡片：
    [emoji] [代號] [名稱]  分數:[X]/10
    [年線狀態] | [外資狀態]
    [特殊標籤]（選用）
    [建議]
    ── 詳細 ──
    股價 [X] ｜ 年線 [X]
    ...
    """
    t, c, w = signal.A_trend, signal.B1_chip, signal.washout
    e        = _REC_EMOJI.get(signal.recommendation, "⚪")
    state_zh = _STATE.get(t["state"], "?")
    above    = "✅年線上" if t["price_above_ma240"] else "❌年線下"
    slope    = _SLOPE.get(t["ma240_slope"], "?")
    chip     = _chip_line(c)
    tags     = _extras(t, c, w)
    hard     = "\n".join(f"  • {f}" for f in signal.failed_conditions) \
               if signal.failed_conditions else "  全部通過 ✅"

    ma20 = _SLOPE.get(t["ma20_slope"], "?")
    ma60 = _SLOPE.get(t["ma60_slope"], "?")

    vol_str = f"{c['avg_volume_5d']:.0f}" if c['avg_volume_5d'] >= 0 else "N/A"
    mh_str  = f"{c['major_holder_ratio']*100:.1f}%" if c['major_holder_ratio'] >= 0 else "N/A（豁免）"

    header = (
        f"{e} <b>{symbol} {name}</b>  分數:{signal.abc_score}/10\n"
        f"{above} {state_zh}{slope} | {chip}\n"
    )
    if tags:
        header += f"{'  '.join(tags)}\n"
    header += f"<code>{signal.recommendation}</code>"

    detail = (
        f"\n\n<b>── 詳細 ──</b>\n"
        f"股價 <b>{t['current_price']}</b> ｜ 年線 {t['ma240_value']}\n"
        f"月線MA20{ma20} ｜ 季線MA60{ma60}\n"
        f"扣抵值 {t['deduction_value']} ｜ "
        f"{'20日將下降 ✅' if t['deduction_drop_imminent'] else '未達下降標準'}\n"
        f"外資近5日 {c['net_foreign_5d']:,} ｜ 投信近5日 {c['net_trust_5d']:,}\n"
        f"融資餘額 {c['margin_balance_latest']:,} 張 ({c['margin_trend']})\n"
        f"均量 {vol_str} 張 ｜ 大戶持股 {mh_str}\n"
        f"\n<b>硬性條件：</b>\n{hard}\n"
        f"\n<i>{signal.story}</i>"
    )
    return header + detail


def _format_today_report(signals: list, trading_date: str) -> list[str]:
    """
    統一格式日報：
    📊 今日選股報告 [日期]
    🟢 買進區 X檔  /  🟡 觀察 X檔  /  🔵 謹慎 X檔
    [清單]
    """
    from datetime import date as dt
    weekdays = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    try:
        wd = weekdays[dt.fromisoformat(trading_date).weekday()]
    except Exception:
        wd = ""

    buy      = [s for s in signals if s.recommendation in ("積極佈局", "即將轉多-優先觀察")]
    watch    = [s for s in signals if s.recommendation == "觀察等待"]
    caution  = [s for s in signals if s.recommendation == "謹慎觀察"]
    excluded = len(signals) - len(buy) - len(watch) - len(caution)

    buy.sort(key=lambda s: -s.abc_score)
    watch.sort(key=lambda s: -s.abc_score)
    caution.sort(key=lambda s: -s.abc_score)

    lines = [
        f"📊 <b>今日選股報告 {trading_date}（{wd}）</b>",
        f"掃描 {len(signals):,} 檔 | "
        f"🟢 買進 <b>{len(buy)}</b> | 🟡 觀察 <b>{len(watch)}</b> | "
        f"🔵 謹慎 <b>{len(caution)}</b> | 🔴 排除 {excluded:,}",
        "",
    ]

    if buy:
        lines.append(f"<b>🟢 買進區（{len(buy)} 檔）</b>")
        for s in buy:
            e = _REC_EMOJI.get(s.recommendation, "🟢")
            c = s.B1_chip
            chip = _chip_line(c)
            lines.append(
                f"{e} <code>{s.symbol}</code> {s.name}  {s.abc_score}/10\n"
                f"   {'✅' if s.A_trend['price_above_ma240'] else '❌'}"
                f"{_STATE.get(s.A_trend['state'],'?')} | {chip}"
            )
        lines.append("")

    if watch:
        top = min(10, len(watch))
        lines.append(f"<b>🟡 觀察等待（{len(watch)} 檔，顯示前 {top}）</b>")
        for s in watch[:top]:
            lines.append(f"  <code>{s.symbol}</code> {s.name}  {s.abc_score}/10")
        if len(watch) > top:
            lines.append(f"  ...及其他 {len(watch)-top} 檔")
        lines.append("")

    if caution:
        top = min(5, len(caution))
        lines.append(f"<b>🔵 謹慎觀察（{len(caution)} 檔，顯示前 {top}）</b>")
        for s in caution[:top]:
            lines.append(f"  <code>{s.symbol}</code> {s.name}  {s.abc_score}/10")
        if len(caution) > top:
            lines.append(f"  ...及其他 {len(caution)-top} 檔")

    # Split to stay within Telegram's 4096-char limit
    messages, chunk, size = [], [], 0
    for line in lines:
        if size + len(line) + 1 > 3800:
            messages.append("\n".join(chunk))
            chunk, size = [], 0
        chunk.append(line)
        size += len(line) + 1
    if chunk:
        messages.append("\n".join(chunk))
    return messages


# ── Full analysis pipeline (on-demand) ───────────────────────────────────────

async def _analyze_stock(symbol: str, name: str) -> str:
    from scrapers.finmind.price import fetch_adjusted_close
    from scrapers.finmind.institutional import fetch_institutional
    from scrapers.finmind.margin import fetch_margin
    from scrapers.finmind.shareholding import fetch_shareholding
    from scrapers.finmind.market_index import fetch_taiex
    from strategy.trend import analyze_trend
    from strategy.chip import analyze_chip
    from strategy.washout_detector import detect_washout
    from strategy.signal import build_signal
    from strategy.story_builder import build_story
    import pandas as pd

    results = await asyncio.gather(
        fetch_adjusted_close(symbol),
        fetch_institutional(symbol, days=60),
        fetch_margin(symbol),
        fetch_shareholding(symbol, days=180),
        fetch_taiex(days=30),
        return_exceptions=True,
    )
    price_df, inst_df, margin_df, sh_df, taiex_df = results

    if not _ok(price_df):
        return f"❌ <b>{symbol} {name}</b>\n無法取得股價資料（代號有誤或 FinMind 暫無資料）"

    trend = analyze_trend(price_df)
    if not trend.has_enough_data:
        return f"⚠️ <b>{symbol} {name}</b>\n歷史資料不足（需 260+ 個交易日），無法計算年線"

    inst  = inst_df   if not isinstance(inst_df, Exception) else pd.DataFrame(columns=["date","name","net"])
    marg  = margin_df if not isinstance(margin_df, Exception) else pd.DataFrame(columns=["date","margin_balance","short_balance"])
    sh    = sh_df     if not isinstance(sh_df, Exception) else None
    mi    = taiex_df  if not isinstance(taiex_df, Exception) else None

    chip    = analyze_chip(inst, marg, sh, mi, price_df)
    washout = detect_washout(price_df)
    story   = build_story(symbol, name, trend, chip, washout)
    signal  = build_signal(symbol, name, trend, chip, washout, story)
    return _format_signal_card(symbol, name, signal)


# ── Telegram handlers ─────────────────────────────────────────────────────────

async def _cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📊 <b>台股 ABC 選股 Bot</b>\n\n"
        "直接輸入股票代號或名稱即可查詢：\n"
        "  <code>2330</code>   → 台積電完整分析\n"
        "  <code>台積電</code> → 中文名稱也可以\n"
        "  <code>鴻海</code>   → 部分名稱也行\n\n"
        "指令：\n"
        "  /today              → 今日選股報告（無報告時自動分析）\n"
        "  /history &lt;代號&gt;  → 三層基本面分析（健康度/競爭力/估值）\n"
        "  /radar [N]          → 缺貨雷達：掃描月營收 YoY 加速標的\n"
        "  /help               → 這則說明",
        parse_mode=ParseMode.HTML,
    )


async def _run_analyze_from_db() -> list:
    """
    Run analyze directly from whatever is in the DB — no fetch-wait loop.
    Used by /today so the bot doesn't block for 45 min.
    """
    from scheduler.daily_job import _analyze_one
    from scheduler.calendar import prev_trading_date
    from notifier.report import save_signals
    from pipeline.store import read_prices
    import asyncio

    trading_date = prev_trading_date().isoformat()
    universe     = await _get_universe()

    # Keep only symbols that already have price data in the DB
    have_data = []
    for stock in universe:
        try:
            df = read_prices(stock["symbol"])
            if not df.empty:
                have_data.append(stock)
        except Exception:
            pass

    if not have_data:
        return []

    logger.info(f"[bot] /today: analyzing {len(have_data)} symbols from DB")
    sem     = asyncio.Semaphore(8)
    tasks   = [_analyze_one(stock, sem) for stock in have_data]
    signals = []
    for coro in asyncio.as_completed(tasks):
        try:
            result = await coro
            if result is not None:
                signals.append(result)
        except Exception as exc:
            logger.debug(f"[bot] analyze_one skipped: {exc}")

    save_signals(signals, trading_date)
    return signals


async def _cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from scheduler.calendar import prev_trading_date
    from notifier.report import load_signals

    trading_date = prev_trading_date().isoformat()
    signals = load_signals(trading_date)

    if not signals:
        wait_msg = await update.message.reply_text(
            f"⏳ 尚無 {trading_date} 的報告，正在從資料庫分析中…\n"
            f"（約需 1-3 分鐘，請稍候）",
            parse_mode=ParseMode.HTML,
        )
        try:
            signals = await _run_analyze_from_db()
        except Exception as exc:
            logger.error(f"[bot] auto analyze failed: {exc}")
            await wait_msg.edit_text(
                f"❌ 自動分析失敗：<code>{exc}</code>\n"
                f"請確認 fetch 步驟是否完成（需先有資料庫資料）",
                parse_mode=ParseMode.HTML,
            )
            return

        if not signals:
            await wait_msg.edit_text(
                f"⚠️ 資料庫中無股價資料。\n"
                f"請先執行：<code>python main.py --no-notify</code> 抓取資料",
                parse_mode=ParseMode.HTML,
            )
            return

        await wait_msg.delete()

    for msg in _format_today_report(signals, trading_date):
        if msg.strip():
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.4)

    # Send detail cards for 積極佈局 stocks
    buy_signals = [s for s in signals if s.recommendation in ("積極佈局", "即將轉多-優先觀察")]
    for sig in buy_signals[:5]:   # cap at 5 to avoid flooding
        await update.message.reply_text(
            _format_signal_card(sig.symbol, sig.name, sig),
            parse_mode=ParseMode.HTML,
        )
        await asyncio.sleep(0.5)


async def _cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """三層基本面分析：/history 2330 或 /history 台積電"""
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "用法：<code>/history &lt;代號或名稱&gt;</code>\n"
            "範例：<code>/history 2330</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    text = " ".join(args).strip()
    thinking = await update.message.reply_text(
        f"📚 三層基本面分析：<code>{text}</code> …（約 10 秒）",
        parse_mode=ParseMode.HTML,
    )
    try:
        universe = await _get_universe()
        matches = _lookup_multi(text, universe)
        if not matches:
            await thinking.edit_text(f"❓ 找不到「{text}」", parse_mode=ParseMode.HTML)
            return
        if len(matches) > 1:
            choices = "\n".join(f"  • <code>{s['symbol']}</code> {s['name']}" for s in matches)
            await thinking.edit_text(
                f"🔎 多筆結果，請輸入完整代號：\n{choices}", parse_mode=ParseMode.HTML
            )
            return

        stock = matches[0]
        inc, bal, cf, price = await asyncio.gather(
            fetch_income_statement(stock["symbol"]),
            fetch_balance_sheet(stock["symbol"]),
            fetch_cash_flow(stock["symbol"]),
            fetch_adjusted_close(stock["symbol"]),
            return_exceptions=True,
        )


        if not _ok(inc) or not _ok(bal) or not _ok(cf):
            await thinking.edit_text(
                f"⚠️ <b>{stock['symbol']} {stock['name']}</b>\n財報資料不足，無法執行三層分析",
                parse_mode=ParseMode.HTML,
            )
            return

        current_price = float(price["close"].iloc[-1]) if _ok(price) and "close" in price.columns else 0.0
        report = build_fundamental_report(
            stock["symbol"], stock["name"],
            pivot_statement(inc), pivot_statement(bal), pivot_statement(cf),
            current_price,
        )
        await thinking.edit_text(format_fundamental_report(report), parse_mode=ParseMode.HTML)
    except Exception as exc:
        logger.error(f"[bot] /history '{text}' failed: {exc}")
        await thinking.edit_text(
            f"❌ 分析失敗：<code>{exc}</code>", parse_mode=ParseMode.HTML
        )


async def _cmd_radar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /radar [N]  — 缺貨雷達掃描。
    掃描 watchlist（預設）或最近一次 fetch_job 的股票清單，找月營收 YoY 加速標的。
    N = 掃描股票數量上限（預設 60，最大 200）。
    """
    import yaml
    from scrapers.finmind.revenue import fetch_monthly_revenue
    from strategy.shortage_radar import detect_shortage, rank_signals, find_clusters
    from notifier.report import build_shortage_radar_message
    from scheduler.calendar import prev_trading_date

    # parse optional N argument
    args = context.args or []
    try:
        max_symbols = min(int(args[0]), 200) if args else 60
    except (ValueError, IndexError):
        max_symbols = 60

    thinking = await update.message.reply_text(
        f"📡 <b>缺貨雷達啟動中…</b>\n掃描 watchlist 月營收（最多 {max_symbols} 檔）",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Load watchlist
        try:
            with open(settings.watchlist_path, encoding="utf-8") as f:
                stocks: list[dict] = yaml.safe_load(f)["stocks"]
        except Exception:
            stocks = await _get_universe()

        stocks = stocks[:max_symbols]
        await thinking.edit_text(
            f"📡 <b>缺貨雷達掃描中…</b> 共 {len(stocks)} 檔，逐一抓取月營收…",
            parse_mode=ParseMode.HTML,
        )

        sem = asyncio.Semaphore(3)  # 免費 tier 限制
        scan_date = prev_trading_date().isoformat()

        async def _fetch_one_revenue(stock: dict):
            async with sem:
                df = await fetch_monthly_revenue(stock["symbol"], months=15)
                return stock, df

        tasks = [_fetch_one_revenue(s) for s in stocks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        shortage_signals = []
        for item in results:
            if isinstance(item, Exception):
                continue
            stock, rev_df = item
            sig = detect_shortage(stock["symbol"], stock["name"], rev_df)
            if sig is not None and sig.score >= 2:  # 只保留觀察中以上
                shortage_signals.append(sig)

        ranked = rank_signals(shortage_signals)
        clusters = find_clusters(ranked)

        await thinking.delete()
        messages = build_shortage_radar_message(
            ranked, scan_date, len(stocks), clusters
        )
        for msg in messages:
            if msg.strip():
                await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
                await asyncio.sleep(0.4)

    except Exception as exc:
        logger.error(f"[bot] /radar failed: {exc}")
        await thinking.edit_text(
            f"❌ 缺貨雷達掃描失敗：<code>{exc}</code>", parse_mode=ParseMode.HTML
        )


async def _on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if not text:
        return

    thinking = await update.message.reply_text(
        f"🔍 查詢中：<code>{text}</code>…", parse_mode=ParseMode.HTML
    )
    try:
        universe = await _get_universe()
        matches  = _lookup_multi(text, universe)

        if not matches:
            await thinking.edit_text(
                f"❓ 找不到「{text}」\n"
                f"請輸入 4-5 位數字代號或中文名稱（如 <code>2330</code> 或 <code>台積電</code>）",
                parse_mode=ParseMode.HTML,
            )
            return

        if len(matches) > 1:
            choices = "\n".join(
                f"  • <code>{s['symbol']}</code> {s['name']}" for s in matches
            )
            await thinking.edit_text(
                f"🔎 找到 {len(matches)} 個符合「{text}」的股票，請輸入完整代號查詢：\n{choices}",
                parse_mode=ParseMode.HTML,
            )
            return

        stock  = matches[0]
        result = await _analyze_stock(stock["symbol"], stock["name"])
        await thinking.edit_text(result, parse_mode=ParseMode.HTML)

        try:
            from scrapers.finmind.price import fetch_ohlcv
            from notifier.chart import render_kline_with_fib
            ohlc = await fetch_ohlcv(stock["symbol"], days=45)
            if not ohlc.empty:
                out = Path(settings.data_dir) / "charts" / f"{stock['symbol']}.png"
                await asyncio.to_thread(
                    render_kline_with_fib,
                    ohlc, stock["symbol"], stock["name"], out,
                )
                with out.open("rb") as f:
                    await update.message.reply_photo(
                        photo=f,
                        caption=f"{stock['symbol']} {stock['name']} 近月 K 線 + Fibonacci 回調",
                    )
        except Exception as chart_exc:
            logger.warning(f"[bot] chart render failed for {stock['symbol']}: {chart_exc}")
    except Exception as exc:
        logger.error(f"[bot] Query '{text}' failed: {exc}")
        await thinking.edit_text(
            f"❌ 分析時發生錯誤：<code>{exc}</code>", parse_mode=ParseMode.HTML
        )


# ── Scheduler wiring ──────────────────────────────────────────────────────────

async def _post_init(app: Application) -> None:
    from scheduler.daily_job import start_scheduler
    scheduler = start_scheduler()
    app.bot_data["scheduler"] = scheduler
    logger.info("[bot] APScheduler started inside PTB event loop")
    # Pre-warm universe cache in background so first query is instant
    asyncio.create_task(_get_universe())


async def _post_shutdown(app: Application) -> None:
    scheduler = app.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[bot] APScheduler stopped")


# ── Application factory ───────────────────────────────────────────────────────

async def _post_init_bot_only(app: Application) -> None:
    asyncio.create_task(_get_universe())


def build_application(with_scheduler: bool = False) -> Application:
    builder = Application.builder().token(settings.telegram_bot_token)
    if with_scheduler:
        builder = builder.post_init(_post_init).post_shutdown(_post_shutdown)
    else:
        builder = builder.post_init(_post_init_bot_only)
    app = builder.build()
    app.add_handler(CommandHandler("help",    _cmd_help))
    app.add_handler(CommandHandler("start",   _cmd_help))
    app.add_handler(CommandHandler("today",   _cmd_today))
    app.add_handler(CommandHandler("history", _cmd_history))
    app.add_handler(CommandHandler("radar",   _cmd_radar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))
    return app
