"""Mock tick feeder for the Quant Terminal microstructure pipeline.

Run locally with:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

The Next.js client points to ws://localhost:8000 by default; override with
the NEXT_PUBLIC_TICK_WS_URL env var.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Final

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

logger = logging.getLogger("tick-feeder")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="Quant Terminal Tick Feeder")

# Per-symbol seed prices so different symbols look different in the UI.
SYMBOL_BASE_PRICES: Final[dict[str, float]] = {
    "2382": 285.0,
    "2449": 142.0,
    "2330": 1085.0,
    "3231": 122.5,
    "2317": 198.0,
    "6515": 720.0,
}
DEFAULT_BASE_PRICE: Final[float] = 240.0

MIN_INTERVAL: Final[float] = 0.1
MAX_INTERVAL: Final[float] = 0.5
MAX_PRICE_NOISE: Final[float] = 1.5


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "tick-feeder"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _make_tick(symbol: str, base_price: float) -> dict[str, object]:
    noise = random.uniform(-MAX_PRICE_NOISE, MAX_PRICE_NOISE)
    return {
        "symbol": symbol,
        "price": round(base_price + noise, 2),
        "volume": random.randint(1, 50),
        "is_buy": random.random() > 0.5,
        "timestamp": int(time.time() * 1000),
    }


@app.websocket("/ws/ticks/{symbol}")
async def stream_ticks(ws: WebSocket, symbol: str) -> None:
    await ws.accept()
    base_price = SYMBOL_BASE_PRICES.get(symbol, DEFAULT_BASE_PRICE)
    logger.info("WS open symbol=%s base=%.2f", symbol, base_price)

    sent = 0
    try:
        while True:
            interval = random.uniform(MIN_INTERVAL, MAX_INTERVAL)
            await asyncio.sleep(interval)
            tick = _make_tick(symbol, base_price)
            await ws.send_json(tick)
            sent += 1
    except WebSocketDisconnect:
        logger.info("WS close symbol=%s sent=%d", symbol, sent)
    except Exception as exc:  # noqa: BLE001
        logger.exception("WS error symbol=%s: %s", symbol, exc)
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
