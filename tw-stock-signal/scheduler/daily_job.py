"""
Three-stage pre-market pipeline with APScheduler.

Timeline (Asia/Taipei):
  06:55 — refresh_calendar_job : update holiday cache
  07:00 — fetch_job            : scrape raw data → DuckDB (with up to 3 retries)
  07:30 — analyze_job          : compute signals → data/signals_{date}.json
  07:55 — heartbeat_job        : warn via Telegram if analyze not done
  08:00 — notify_job           : send daily report via Telegram

State handoff between jobs: data/job_status.json
  {
    "fetch":   {"trading_date": "YYYY-MM-DD", "completed_at": "...", "stocks": [...], "success_count": N},
    "analyze": {"trading_date": "YYYY-MM-DD", "completed_at": "...", "signal_count": N}
  }

Non-trading days: all jobs check is_trading_day() and exit early.
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings
from scheduler.calendar import is_trading_day, prev_trading_date, refresh_holidays
from scrapers.finmind.price import fetch_adjusted_close
from scrapers.finmind.institutional import fetch_institutional
from scrapers.finmind.margin import fetch_margin
from scrapers.finmind.shareholding import fetch_shareholding
from scrapers.finmind.market_index import fetch_taiex
from scrapers.finmind.universe import fetch_stock_universe
from pipeline.store import (
    init_db,
    upsert_prices, upsert_institutional, upsert_margin,
    upsert_shareholding, upsert_market_index,
    read_prices, read_institutional, read_margin,
    read_shareholding, read_market_index,
)
from strategy.trend import analyze_trend
from strategy.chip import analyze_chip
from strategy.washout_detector import detect_washout
from strategy.signal import build_signal
from strategy.story_builder import build_story
from notifier.report import (
    save_signals, load_signals,
    build_saturday_volume_message, build_sunday_foreign_message,
    build_vol_shrink_message,
)
from notifier.telegram_notifier import (
    send_daily_report, send_error_alert, send_heartbeat_warning,
    send_html_message, send_live_signal,
)

import yaml

_STATUS_FILE = Path(settings.data_dir) / "job_status.json"


# ── Status file helpers ───────────────────────────────────────────────────────

def _read_status() -> dict:
    try:
        if _STATUS_FILE.exists():
            return json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_status(stage: str, data: dict) -> None:
    status = _read_status()
    status[stage] = data
    _STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Universe helpers ──────────────────────────────────────────────────────────

def _load_watchlist() -> list[dict]:
    with open(settings.watchlist_path, encoding="utf-8") as f:
        return yaml.safe_load(f)["stocks"]


async def _get_universe() -> list[dict]:
    if settings.full_market_scan:
        logger.info("[job] Full-market scan — fetching universe from FinMind")
        return await fetch_stock_universe()
    logger.info("[job] Watchlist mode")
    return _load_watchlist()


# ── Per-symbol processing ─────────────────────────────────────────────────────

async def _fetch_one(stock: dict, sem: asyncio.Semaphore) -> str | None:
    """Fetch and persist raw data for one symbol. Returns symbol on success, None on skip."""
    async with sem:
        symbol, name = stock["symbol"], stock["name"]

        price_df, inst_df, margin_df, sh_df = await asyncio.gather(
            fetch_adjusted_close(symbol),
            fetch_institutional(symbol),
            fetch_margin(symbol),
            fetch_shareholding(symbol),
            return_exceptions=True,
        )

        for result, label in [
            (price_df, "price"), (inst_df, "inst"),
            (margin_df, "margin"), (sh_df, "shareholding"),
        ]:
            if isinstance(result, Exception):
                logger.error(f"[{symbol}] {label} fetch failed: {result}")

        if isinstance(price_df, Exception) or (hasattr(price_df, "empty") and price_df.empty):
            logger.warning(f"[{symbol}] Skipping — no price data")
            return None

        latest_close = float(price_df["close"].iloc[-1])
        if latest_close < settings.min_price_filter:
            logger.debug(f"[{symbol}] price {latest_close:.1f} < {settings.min_price_filter} — skipped")
            return None

        try:
            upsert_prices(symbol, price_df)
            if not isinstance(inst_df, Exception):
                upsert_institutional(symbol, inst_df)
            if not isinstance(margin_df, Exception):
                upsert_margin(symbol, margin_df)
            if not isinstance(sh_df, Exception):
                upsert_shareholding(symbol, sh_df)
        except Exception as exc:
            logger.error(f"[{symbol}] DB upsert failed: {type(exc).__name__}: {exc}")
            return None

        return symbol


async def _analyze_one(stock: dict, sem: asyncio.Semaphore) -> object | None:
    """Run strategy on one symbol. Returns Signal or None."""
    async with sem:
        symbol, name = stock["symbol"], stock["name"]
        prices        = read_prices(symbol)
        institutional = read_institutional(symbol)
        margin        = read_margin(symbol)
        shareholding  = read_shareholding(symbol)
        market_idx    = read_market_index(days=10)

        trend = analyze_trend(prices)
        if not trend.has_enough_data:
            logger.debug(f"[{symbol}] Insufficient history for MA240 — skipped")
            return None

        chip    = analyze_chip(institutional, margin, shareholding, market_idx, prices)
        washout = detect_washout(prices)
        story   = build_story(symbol, name, trend, chip, washout)
        signal  = build_signal(symbol, name, trend, chip, washout, story)

        logger.info(f"[{symbol}] {name} | score={signal.abc_score} | {signal.recommendation}")

        # Live push: send immediately when hard conditions pass
        if signal.hard_pass:
            await send_live_signal(signal)

        return signal


# ── Job implementations ───────────────────────────────────────────────────────

async def _do_fetch() -> None:
    """Core fetch logic (called by fetch_job, potentially retried)."""
    init_db()
    universe = await _get_universe()
    if not universe:
        raise RuntimeError("Empty universe — aborting fetch")

    # Fetch TAIEX index once for the whole run
    try:
        taiex_df = await fetch_taiex(days=30)
        if not taiex_df.empty:
            upsert_market_index(taiex_df)
            logger.info(f"[fetch] TAIEX updated: {len(taiex_df)} rows")
    except Exception as exc:
        logger.warning(f"[fetch] TAIEX fetch failed (non-fatal): {exc}")

    logger.info(f"[fetch] Scanning {len(universe)} symbols (concurrency={settings.universe_concurrency})")
    sem = asyncio.Semaphore(settings.universe_concurrency)
    tasks = [_fetch_one(stock, sem) for stock in universe]

    success_symbols: list[str] = []
    completed = 0
    for coro in asyncio.as_completed(tasks):
        result = await coro
        if result is not None:
            success_symbols.append(result)
        completed += 1
        if completed % 200 == 0:
            logger.info(f"[fetch] {completed}/{len(universe)} done, {len(success_symbols)} succeeded")

    logger.info(f"[fetch] Complete: {len(success_symbols)}/{len(universe)} symbols fetched")

    _write_status("fetch", {
        "trading_date":  prev_trading_date().isoformat(),
        "completed_at":  datetime.now().isoformat(),
        "stocks":        universe,
        "success_count": len(success_symbols),
    })


async def fetch_job() -> None:
    """07:00 — Fetch raw market data with retry (up to fetch_retry_attempts times)."""
    if not is_trading_day():
        logger.info("[fetch] Non-trading day — skipped")
        return

    for attempt in range(1, settings.fetch_retry_attempts + 1):
        try:
            logger.info(f"[fetch] Attempt {attempt}/{settings.fetch_retry_attempts}")
            await _do_fetch()
            return
        except Exception as exc:
            logger.error(f"[fetch] Attempt {attempt} failed: {exc}")
            if attempt == settings.fetch_retry_attempts:
                await send_error_alert("fetch_job", str(exc))
                raise
            wait = settings.fetch_retry_delay_secs
            logger.warning(f"[fetch] Retrying in {wait}s...")
            await asyncio.sleep(wait)


async def _do_analyze() -> None:
    """Core analyze logic — no trading-day gate. Used by both analyze_job and on-demand triggers."""
    trading_date = prev_trading_date().isoformat()

    # Wait for fetch_job to complete (up to 45 min, checks every 5 min)
    for wait_round in range(9):
        status = _read_status().get("fetch", {})
        if status.get("trading_date") == trading_date:
            break
        logger.info(f"[analyze] Waiting for fetch_job ({wait_round + 1}/9)...")
        await asyncio.sleep(300)
    else:
        logger.warning("[analyze] fetch_job not completed after 45 min — proceeding with available DB data")

    stocks: list[dict] = _read_status().get("fetch", {}).get("stocks") or await _get_universe()
    if not stocks:
        logger.error("[analyze] No stock list available — aborting analyze")
        return

    logger.info(f"[analyze] Computing signals for {len(stocks)} symbols")
    sem    = asyncio.Semaphore(settings.universe_concurrency * 2)
    tasks  = [_analyze_one(stock, sem) for stock in stocks]
    signals, completed = [], 0

    for coro in asyncio.as_completed(tasks):
        try:
            result = await coro
            if result is not None:
                signals.append(result)
        except Exception as exc:
            logger.error(f"[analyze] Symbol exception: {type(exc).__name__}: {exc}")
        completed += 1
        if completed % 200 == 0:
            logger.info(f"[analyze] {completed}/{len(stocks)} done, {len(signals)} signals")

    logger.info(f"[analyze] Complete: {len(signals)} signals from {len(stocks)} symbols")
    save_signals(signals, trading_date)

    _write_status("analyze", {
        "trading_date": trading_date,
        "completed_at": datetime.now().isoformat(),
        "signal_count": len(signals),
    })


async def analyze_job() -> None:
    """07:30 — Compute signals from DB and persist to JSON."""
    if not is_trading_day():
        logger.info("[analyze] Non-trading day — skipped")
        return
    await _do_analyze()


async def heartbeat_job() -> None:
    """07:55 — Warn via Telegram if analyze_job has not completed for today."""
    if not is_trading_day():
        return

    trading_date = prev_trading_date().isoformat()
    status = _read_status().get("analyze", {})

    if status.get("trading_date") == trading_date:
        logger.info(f"[heartbeat] OK — analyze done at {status.get('completed_at')}")
        return

    detail = (
        f"analyze_job 尚未完成今日運算（{trading_date}）。\n"
        f"上次完成：{status.get('completed_at', '從未')} | "
        f"上次交易日：{status.get('trading_date', '未知')}"
    )
    logger.warning(f"[heartbeat] {detail}")
    await send_heartbeat_warning(detail)


async def notify_job() -> None:
    """08:00 — Send the daily report via Telegram."""
    if not is_trading_day():
        logger.info("[notify] Non-trading day — skipped")
        return

    trading_date = prev_trading_date().isoformat()
    signals = load_signals(trading_date)

    if not signals:
        msg = f"⚠️ <b>08:00 推播失敗</b>\n找不到 {trading_date} 的選股資料（signals 檔案不存在或為空）"
        await send_error_alert("notify_job", f"No signals for {trading_date}")
        return

    logger.info(f"[notify] Sending report: {len(signals)} signals for {trading_date}")
    await send_daily_report(signals)


async def refresh_calendar_job() -> None:
    """06:55 — Refresh holiday cache (runs once daily)."""
    logger.info("[calendar] Refreshing holiday cache")
    await refresh_holidays()


# ── Weekend jobs ──────────────────────────────────────────────────────────────

async def vol_shrink_job() -> None:
    """
    08:15 — 連續五日量縮不破低掃描。
    使用 yfinance 抓資料（獨立於 FinMind pipeline），結果存 CSV 並推播 Telegram。
    股票清單優先從 fetch_job status 讀取，否則重新取得 universe。
    """
    if not is_trading_day():
        logger.info("[vol_shrink] Non-trading day — skipped")
        return

    trading_date = prev_trading_date().isoformat()
    logger.info(f"[vol_shrink] Starting scan for {trading_date}")

    try:
        # 取股票清單（重用 fetch_job 已抓到的清單，避免重複呼叫 FinMind）
        stocks: list[dict] = _read_status().get("fetch", {}).get("stocks") or await _get_universe()
        if not stocks:
            await send_error_alert("vol_shrink_job", "No stock list available")
            return

        logger.info(f"[vol_shrink] Scanning {len(stocks)} symbols with yfinance...")

        from strategy.volume_shrink import scan_stocks, save_result_csv

        # scan_stocks 是同步函式（含 ThreadPoolExecutor）→ 用 executor 避免阻塞事件迴圈
        loop = asyncio.get_running_loop()
        matches = await loop.run_in_executor(
            None,
            lambda: scan_stocks(
                stocks, consecutive=5, threshold=0.10,
                max_workers=5, min_avg_volume_lots=2000,
            ),
        )

        csv_path = save_result_csv(matches, trading_date)
        logger.info(f"[vol_shrink] {len(matches)} matches saved → {csv_path}")

        # 推播 Telegram
        messages = build_vol_shrink_message(matches, trading_date)
        for msg in messages:
            await send_html_message(msg)

        logger.info(f"[vol_shrink] Report sent ({len(messages)} messages)")

    except Exception as exc:
        logger.error(f"[vol_shrink] Job failed: {type(exc).__name__}: {exc}")
        await send_error_alert("vol_shrink_job", str(exc))


async def vol_shrink_full_job() -> None:
    """
    14:40 — 全市場量縮不破低掃描（收盤後）。
    掃描 TWSE 1074 + TPEX 882 ≈ 1956 支，條件：連續5日量縮10% + 低點不破 + 均量>=2000張。
    不管有沒有符合標的都推播結果到 Telegram。
    """
    if not is_trading_day():
        logger.info("[vol_shrink_full] Non-trading day — skipped")
        return

    trading_date = prev_trading_date().isoformat()
    logger.info(f"[vol_shrink_full] Full-market scan for {trading_date}")

    try:
        from scrapers.twse.ticker_list import fetch_full_ticker_list
        from strategy.volume_shrink import scan_stocks, save_result_csv

        tickers = await fetch_full_ticker_list()
        if not tickers:
            await send_error_alert("vol_shrink_full_job", "無法取得全市場代號清單")
            return

        logger.info(f"[vol_shrink_full] Scanning {len(tickers)} symbols...")

        loop = asyncio.get_running_loop()
        matches = await loop.run_in_executor(
            None,
            lambda: scan_stocks(
                tickers, consecutive=5, threshold=0.10,
                max_workers=8, min_avg_volume_lots=2000,
            ),
        )

        csv_path = save_result_csv(matches, trading_date)
        logger.info(f"[vol_shrink_full] {len(matches)} matches → {csv_path}")

        messages = build_vol_shrink_message(matches, trading_date)
        for msg in messages:
            await send_html_message(msg)

        logger.info(f"[vol_shrink_full] Report sent ({len(messages)} messages)")

    except Exception as exc:
        logger.error(f"[vol_shrink_full] Job failed: {type(exc).__name__}: {exc}")
        await send_error_alert("vol_shrink_full_job", str(exc))


async def saturday_volume_job() -> None:
    """Saturday 09:00 — Send top 10 stocks by Friday's trading volume."""
    from scrapers.twse.market_summary import fetch_top_volume

    trading_date = prev_trading_date().isoformat()   # Friday's date
    logger.info(f"[saturday] Fetching volume top 10 for {trading_date}")
    try:
        stocks = await fetch_top_volume(10)
        if not stocks:
            await send_error_alert("saturday_volume_job", "TWSE/TPEX 回傳空資料，請確認 API 是否可用")
            return
        msg = build_saturday_volume_message(stocks, trading_date)
        await send_html_message(msg)
        logger.info(f"[saturday] Volume top 10 sent ({len(stocks)} stocks)")
    except Exception as exc:
        logger.error(f"[saturday] Failed: {exc}")
        await send_error_alert("saturday_volume_job", str(exc))
        raise


async def sunday_foreign_job() -> None:
    """Sunday 09:00 — Send top 10 stocks by Friday's foreign investor net buy."""
    from scrapers.twse.market_summary import fetch_top_foreign_buy

    trading_date = prev_trading_date().isoformat()   # Friday's date
    logger.info(f"[sunday] Fetching foreign buy top 10 for {trading_date}")
    try:
        stocks = await fetch_top_foreign_buy(10, trading_date=trading_date)
        if not stocks:
            await send_error_alert("sunday_foreign_job", "TWSE/TPEX 回傳空資料，請確認 API 是否可用")
            return
        msg = build_sunday_foreign_message(stocks, trading_date)
        await send_html_message(msg)
        logger.info(f"[sunday] Foreign buy top 10 sent ({len(stocks)} stocks)")
    except Exception as exc:
        logger.error(f"[sunday] Failed: {exc}")
        await send_error_alert("sunday_foreign_job", str(exc))
        raise


# ── Public convenience wrapper (used by main.py and run_now.py) ───────────────

async def shortage_radar_job() -> None:
    """
    月末缺貨雷達掃描（每月最後一個交易日 14:50 執行）。
    掃描 watchlist 月營收 YoY 加速標的，推播 Telegram 缺貨報告。
    """
    if not is_trading_day():
        logger.info("[radar] Non-trading day — skipped")
        return

    from calendar import monthrange
    from datetime import date as _date
    today = _date.today()
    # Only run on the last 3 calendar days of the month
    last_day = monthrange(today.year, today.month)[1]
    if today.day < last_day - 2:
        logger.info(f"[radar] Not end-of-month (today={today.day}, last={last_day}) — skipped")
        return

    trading_date = prev_trading_date().isoformat()
    logger.info(f"[radar] Starting shortage radar scan for {trading_date}")

    try:
        import asyncio as _asyncio
        import yaml
        from scrapers.finmind.revenue import fetch_monthly_revenue
        from strategy.shortage_radar import detect_shortage, rank_signals, find_clusters
        from notifier.report import build_shortage_radar_message

        try:
            with open(settings.watchlist_path, encoding="utf-8") as f:
                stocks: list[dict] = yaml.safe_load(f)["stocks"]
        except Exception:
            stocks = await _get_universe()

        logger.info(f"[radar] Scanning {len(stocks)} watchlist symbols")
        sem = _asyncio.Semaphore(3)

        async def _one(stock: dict):
            async with sem:
                df = await fetch_monthly_revenue(stock["symbol"], months=15)
                return stock, df

        results = await _asyncio.gather(*[_one(s) for s in stocks], return_exceptions=True)

        signals = []
        for item in results:
            if isinstance(item, Exception):
                continue
            stock, df = item
            sig = detect_shortage(stock["symbol"], stock["name"], df)
            if sig is not None and sig.score >= 2:
                signals.append(sig)

        ranked = rank_signals(signals)
        clusters = find_clusters(ranked)
        logger.info(f"[radar] {len(ranked)} shortage signals ({sum(1 for s in ranked if s.score >= 4)} 強缺貨)")

        messages = build_shortage_radar_message(ranked, trading_date, len(stocks), clusters)
        for msg in messages:
            await send_html_message(msg)

        logger.info("[radar] Report sent")

    except Exception as exc:
        logger.error(f"[radar] Job failed: {type(exc).__name__}: {exc}")
        await send_error_alert("shortage_radar_job", str(exc))


async def run_pipeline(notify: bool = True) -> None:
    """Run the full pipeline in sequence: fetch → analyze → notify (optional)."""
    await fetch_job()
    await analyze_job()
    if notify:
        await notify_job()


# ── Scheduler factory ─────────────────────────────────────────────────────────

def start_scheduler() -> AsyncIOScheduler:
    tz = settings.timezone
    # misfire_grace_time=3600: if the event loop is temporarily busy when a job
    # should fire, run it anyway as long as we're within 1 hour of the target time.
    scheduler = AsyncIOScheduler(job_defaults={"misfire_grace_time": 3600})

    scheduler.add_job(
        refresh_calendar_job,
        CronTrigger(hour=6, minute=55, timezone=tz),
        id="refresh_calendar", name="Refresh Holiday Cache", replace_existing=True,
    )
    scheduler.add_job(
        fetch_job,
        CronTrigger(hour=7, minute=0, timezone=tz),
        id="fetch_job", name="07:00 Fetch Market Data", replace_existing=True,
    )
    scheduler.add_job(
        analyze_job,
        CronTrigger(hour=7, minute=30, timezone=tz),
        id="analyze_job", name="07:30 Compute Signals", replace_existing=True,
    )
    scheduler.add_job(
        heartbeat_job,
        CronTrigger(hour=7, minute=55, timezone=tz),
        id="heartbeat_job", name="07:55 Heartbeat Check", replace_existing=True,
    )
    scheduler.add_job(
        notify_job,
        CronTrigger(hour=8, minute=0, timezone=tz),
        id="notify_job", name="08:00 Send Telegram Report", replace_existing=True,
    )
    scheduler.add_job(
        vol_shrink_job,
        CronTrigger(hour=8, minute=15, timezone=tz),
        id="vol_shrink_job", name="08:15 量縮不破低掃描（watchlist）", replace_existing=True,
    )
    scheduler.add_job(
        vol_shrink_full_job,
        CronTrigger(hour=14, minute=40, timezone=tz),
        id="vol_shrink_full_job", name="14:40 量縮不破低全市場掃描", replace_existing=True,
    )

    scheduler.add_job(
        shortage_radar_job,
        CronTrigger(hour=14, minute=50, timezone=tz),
        id="shortage_radar_job", name="14:50 缺貨雷達（月末）", replace_existing=True,
    )

    # Weekend jobs
    scheduler.add_job(
        saturday_volume_job,
        CronTrigger(day_of_week="sat", hour=9, minute=0, timezone=tz),
        id="saturday_volume", name="Sat 09:00 Volume Top 10", replace_existing=True,
    )
    scheduler.add_job(
        sunday_foreign_job,
        CronTrigger(day_of_week="sun", hour=9, minute=0, timezone=tz),
        id="sunday_foreign", name="Sun 09:00 Foreign Buy Top 10", replace_existing=True,
    )

    scheduler.start()
    logger.info(
        f"Scheduler started (tz={tz})\n"
        f"  平日: 06:55 / 07:00 / 07:30 / 07:55 / 08:00 / 08:15 / 14:40 / 14:50(月末)\n"
        f"  週六: 09:00 成交量 Top 10\n"
        f"  週日: 09:00 外資買超 Top 10"
    )
    return scheduler
