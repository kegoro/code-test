"""FastAPI 入口：Footprint WebSocket 與歷史 API。

架構：
    [MockTickGenerator] → asyncio.Queue → [Dispatcher] → [StreamingFootprintAggregator]
                                                              ↓
                                                       broadcast to WS clients

未來抽換真實資料源時，只需替換 MockTickGenerator，Queue 介面保持不變。

啟動：
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import traceback
from contextlib import asynccontextmanager
from typing import Final

import math
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from fastapi.responses import StreamingResponse

from backend.footprint_aggregator import (
    DEFAULT_BAR_SECONDS,
    StreamingFootprintAggregator,
)
from backend.mock_tick_generator import DEFAULT_QUEUE_MAXSIZE, MockTickGenerator
from backend.scanner_scheduler import ScannerEngine
from backend.backtest_report import BacktestReport
from backend.backtest_runner import DEFAULT_CACHE_DIR, run_backtest

logger = logging.getLogger("footprint-backend")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ============================================================
# 共享狀態
# ============================================================


class AppState:
    """應用層級共享狀態。"""

    def __init__(self) -> None:
        self.tick_queue: asyncio.Queue = asyncio.Queue(maxsize=DEFAULT_QUEUE_MAXSIZE)
        self.aggregator: StreamingFootprintAggregator = StreamingFootprintAggregator(
            bar_seconds=DEFAULT_BAR_SECONDS,
            max_history=500,
        )
        self.ws_clients: set[WebSocket] = set()
        self.ws_lock = asyncio.Lock()
        self.tick_generator: MockTickGenerator | None = None
        self.tasks: list[asyncio.Task] = []
        self.scanner: ScannerEngine | None = None
        self.backtest_status: str = "idle"  # idle | running | ready | error
        self.backtest_error: str | None = None
        self.backtest_report_dict: dict | None = None
        self.backtest_task: asyncio.Task | None = None
        self.backtest_lock: asyncio.Lock = asyncio.Lock()
        self.data_router: "DataSourceRouter | None" = None  # set during lifespan


state = AppState()


# ============================================================
# 背景任務：消費 Queue → 聚合 → 廣播
# ============================================================


async def _broadcast(payload: dict) -> None:
    if not state.ws_clients:
        return
    msg = json.dumps(payload, default=str)
    dead: list[WebSocket] = []
    async with state.ws_lock:
        clients = list(state.ws_clients)
    for ws in clients:
        try:
            await ws.send_text(msg)
        except Exception as exc:  # noqa: BLE001
            logger.debug("client send failed, marking dead: %s", exc)
            dead.append(ws)
    if dead:
        async with state.ws_lock:
            for ws in dead:
                state.ws_clients.discard(ws)


async def _consumer_loop() -> None:
    logger.info("consumer loop started")
    try:
        while True:
            tick = await state.tick_queue.get()
            try:
                current_bar, just_closed = state.aggregator.feed(tick)
            except Exception as exc:  # noqa: BLE001
                print(f"[CRASH] consumer feed: {exc}")
                traceback.print_exc()
                logger.exception("aggregator feed failed: %s", exc)
                continue

            try:
                if just_closed is not None:
                    await _broadcast({"type": "bar_close", "data": just_closed})
                await _broadcast({"type": "bar_update", "data": current_bar})
            except Exception as exc:  # noqa: BLE001
                print(f"[CRASH] consumer broadcast: {exc}")
                traceback.print_exc()
    except asyncio.CancelledError:
        logger.info("consumer loop cancelled")
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"[CRASH] consumer loop: {exc}")
        traceback.print_exc()
        raise


# ============================================================
# 生命週期
# ============================================================


def handle_task_exception(task: asyncio.Task) -> None:
    if not task.cancelled():
        exc = task.exception()
        if exc:
            print(f"[CRASH] task {task.get_name()}: {exc!r}")
            traceback.print_exception(type(exc), exc, exc.__traceback__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.finmind_fetcher import parse_symbols_env
    from backend.data_router import DataSourceRouter

    state.tick_generator = MockTickGenerator(state.tick_queue)

    symbols = parse_symbols_env()
    market_only = os.getenv("SCANNER_MARKET_HOURS_ONLY", "true").lower() != "false"
    logger.info("scanner symbols: %s (market_hours_only=%s)", symbols, market_only)

    router = DataSourceRouter()
    await router.warmup()
    state.data_router = router

    state.scanner = ScannerEngine(
        symbols=symbols, fetch=router, market_hours_only=market_only
    )
    state.scanner.start()

    gen_task = asyncio.create_task(state.tick_generator.run(), name="mock-gen")
    gen_task.add_done_callback(handle_task_exception)
    state.tasks.append(gen_task)

    consumer_task = asyncio.create_task(_consumer_loop(), name="consumer")
    consumer_task.add_done_callback(handle_task_exception)
    state.tasks.append(consumer_task)
    logger.info("backend lifespan startup complete")
    try:
        yield
    finally:
        logger.info("backend lifespan shutdown")
        if state.scanner is not None:
            await state.scanner.stop()
        if state.tick_generator is not None:
            state.tick_generator.stop()
        for t in state.tasks:
            t.cancel()
        for t in state.tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        async with state.ws_lock:
            for ws in list(state.ws_clients):
                try:
                    await ws.close()
                except Exception:  # noqa: BLE001
                    pass
            state.ws_clients.clear()


app = FastAPI(title="Footprint Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# HTTP 端點
# ============================================================


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "footprint-backend"}


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "ws_clients": len(state.ws_clients),
        "queue_size": state.tick_queue.qsize(),
        "history_bars": len(state.aggregator.history()),
        "data_sources": state.data_router.status() if state.data_router else {},
    }


@app.get("/api/footprint/history")
async def footprint_history(
    bars: int = Query(default=200, ge=1, le=1000),
) -> dict[str, object]:
    return {
        "barSeconds": state.aggregator.bar_seconds,
        "bars": state.aggregator.history(n=bars),
        "current": state.aggregator.current(),
    }


# ============================================================
# WebSocket 端點
# ============================================================


@app.websocket("/ws/footprint")
async def ws_footprint(ws: WebSocket) -> None:
    await ws.accept()
    async with state.ws_lock:
        state.ws_clients.add(ws)
    logger.info("WS connected; clients=%d", len(state.ws_clients))

    try:
        snapshot = {
            "type": "snapshot",
            "data": state.aggregator.history(n=200),
        }
        await ws.send_text(json.dumps(snapshot, default=str))
        current = state.aggregator.current()
        if current is not None:
            await ws.send_text(json.dumps({"type": "bar_update", "data": current}, default=str))

        # Keep-alive：等待客戶端訊息（用於偵測斷線）；不依賴客戶端內容
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        logger.info("WS disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.exception("WS error: %s", exc)
    finally:
        async with state.ws_lock:
            state.ws_clients.discard(ws)
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass


# ============================================================
# Scanner endpoints (Phase 5)
# ============================================================


@app.get("/api/scanner/setups")
async def scanner_setups() -> dict[str, object]:
    if state.scanner is None:
        return {"signals": []}
    return {"signals": state.scanner.active_signals()}


@app.get("/api/scanner/setups/{symbol}")
async def scanner_setups_symbol(symbol: str) -> dict[str, object]:
    if state.scanner is None:
        return {"signals": []}
    return {"signals": state.scanner.active_signals(symbol=symbol)}


@app.get("/api/scanner/stream")
async def scanner_stream() -> StreamingResponse:
    if state.scanner is None:
        async def _empty():
            yield "data: {}\n\n"
        return StreamingResponse(_empty(), media_type="text/event-stream")

    queue = state.scanner.subscribe()

    async def event_gen():
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                payload = await queue.get()
                yield f"data: {json.dumps(payload, default=str)}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            state.scanner.unsubscribe(queue) if state.scanner else None

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ============================================================
# Backtest endpoints (P3)
# ============================================================


class BacktestRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["2382", "2330", "2449", "2317", "3231"])
    start: str = "2023-01-01"
    end: str = "2026-05-07"
    stop_mode: str = "fixed"
    setups: list[str] = Field(default_factory=lambda: ["A1", "A2"])
    initial_capital: float = 1_000_000.0
    risk_per_trade: float = 0.005
    refresh: bool = False


def _safe_float(v: object) -> float | None:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _df_to_records(df: pd.DataFrame, *, reset_index: bool = True) -> list[dict]:
    if df is None or df.empty:
        return []
    d = df.reset_index() if reset_index else df.copy()
    for col in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[col]):
            d[col] = d[col].dt.strftime("%Y-%m-%d")
    d = d.replace([np.inf, -np.inf], np.nan).where(pd.notnull(d), None)
    records: list[dict] = []
    for row in d.to_dict(orient="records"):
        clean: dict = {}
        for k, v in row.items():
            if isinstance(v, (pd.Period,)):
                clean[str(k)] = str(v)
            elif isinstance(v, float):
                clean[str(k)] = _safe_float(v)
            else:
                clean[str(k)] = v
        records.append(clean)
    return records


def _report_to_dict(report: BacktestReport) -> dict:
    cfg = report.result.config
    c = report.core
    return {
        "config": {
            "symbols": list(cfg.symbols),
            "start_date": cfg.start_date,
            "end_date": cfg.end_date,
            "setup_types": list(cfg.setup_types),
            "stop_mode": cfg.stop_mode,
            "initial_capital": cfg.initial_capital,
            "risk_per_trade": cfg.risk_per_trade,
        },
        "meta": {
            "symbols_processed": report.result.symbols_processed,
            "bars_evaluated": report.result.bars_evaluated,
        },
        "core": {
            "n_trades": c.n_trades,
            "n_wins": c.n_wins,
            "n_losses": c.n_losses,
            "win_rate": _safe_float(c.win_rate),
            "avg_r": _safe_float(c.avg_r),
            "avg_win_r": _safe_float(c.avg_win_r),
            "avg_loss_r": _safe_float(c.avg_loss_r),
            "profit_factor": _safe_float(c.profit_factor),
            "max_drawdown_pct": _safe_float(c.max_drawdown_pct),
            "max_drawdown_dollars": _safe_float(c.max_drawdown_dollars),
            "sharpe": _safe_float(c.sharpe),
            "calmar": _safe_float(c.calmar),
            "total_return_pct": _safe_float(c.total_return_pct),
            "final_equity": _safe_float(c.final_equity),
        },
        "trades": _df_to_records(report.trades_df, reset_index=False),
        "monthly": _df_to_records(report.monthly_df),
        "setup_breakdown": _df_to_records(report.setup_breakdown),
        "stop_mode_breakdown": _df_to_records(report.stop_mode_breakdown),
        "ob_breakdown": _df_to_records(report.ob_breakdown),
        "equity_curve": _df_to_records(report.equity_curve),
    }


async def _run_backtest_task(req: BacktestRunRequest) -> None:
    try:
        state.backtest_status = "running"
        state.backtest_error = None
        _, report = await run_backtest(
            symbols=req.symbols,
            start=req.start,
            end=req.end,
            stop_mode=req.stop_mode,
            setups=tuple(req.setups),
            initial_capital=req.initial_capital,
            risk_per_trade=req.risk_per_trade,
            cache_dir=Path(DEFAULT_CACHE_DIR),
            refresh=req.refresh,
        )
        state.backtest_report_dict = _report_to_dict(report)
        state.backtest_status = "ready"
        logger.info(
            "backtest done: trades=%d win_rate=%.2f%% PF=%.2f",
            report.core.n_trades,
            (report.core.win_rate or 0) * 100,
            report.core.profit_factor or 0.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("backtest failed: %s", exc)
        state.backtest_status = "error"
        state.backtest_error = str(exc)


@app.post("/api/backtest/run")
async def backtest_run(req: BacktestRunRequest) -> dict[str, object]:
    async with state.backtest_lock:
        if state.backtest_status == "running":
            return {"status": "running", "message": "A backtest is already running."}
        state.backtest_task = asyncio.create_task(
            _run_backtest_task(req), name="backtest-run"
        )
        state.backtest_task.add_done_callback(handle_task_exception)
    return {"status": "running", "config": req.model_dump()}


# ============================================================
# K 線端點 — 從 Shioaji M3 快取回傳歷史 K 線
# ============================================================


@app.get("/api/klines/{symbol}")
async def klines(
    symbol: str,
    days: int = Query(default=5, ge=1, le=30),
) -> dict[str, object]:
    """回傳 symbol 最近 days 天的 M3 K 線（從磁碟快取讀取）。"""
    from backend.shioaji_history_cache import load_cached_m3, concat_history

    history = load_cached_m3(symbol)
    if not history:
        # 快取不存在時嘗試即時抓取
        try:
            from backend.shioaji_history_cache import fetch_history_m3
            history = await fetch_history_m3(symbol, days=days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("klines fetch failed for %s: %s", symbol, exc)
            raise HTTPException(status_code=503, detail=f"no data for {symbol}")

    df = concat_history(history)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"no M3 data for {symbol}")

    # 只取最近 days 個交易日
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days * 2)).date()
    df = df[df.index.date >= cutoff]

    bars = []
    for ts, row in df.iterrows():
        bars.append({
            "timestamp": int(ts.timestamp() * 1000),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
        })

    return {"symbol": symbol, "interval": "M3", "bars": bars}


@app.get("/api/backtest/result")
async def backtest_result() -> dict[str, object]:
    if state.backtest_status == "idle":
        return {"status": "idle", "report": None}
    if state.backtest_status == "running":
        return {"status": "running", "report": None}
    if state.backtest_status == "error":
        raise HTTPException(status_code=500, detail=state.backtest_error or "backtest error")
    return {"status": "ready", "report": state.backtest_report_dict}
