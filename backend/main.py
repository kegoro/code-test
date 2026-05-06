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
import traceback
from contextlib import asynccontextmanager
from typing import Final

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.footprint_aggregator import (
    DEFAULT_BAR_SECONDS,
    StreamingFootprintAggregator,
)
from backend.mock_tick_generator import DEFAULT_QUEUE_MAXSIZE, MockTickGenerator

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
    state.tick_generator = MockTickGenerator(state.tick_queue)

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
