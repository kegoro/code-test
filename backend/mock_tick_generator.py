"""Mock Tick 產生器。

每 100ms 產生一筆符合 Shioaji 規格的 RawTick，推入共用 asyncio.Queue。
未來抽換為真實 Shioaji 來源時，只需建立另一個產生器使用相同的 Queue 介面。

欄位與 src/types/footprint.ts RawTick 介面完全一致。
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

logger = logging.getLogger(__name__)

# ============================================================
# 設定
# ============================================================

DEFAULT_TICK_INTERVAL_SEC: Final[float] = 0.1
DEFAULT_QUEUE_MAXSIZE: Final[int] = 1000

TICK_TYPE_ASK: Final[int] = 1
TICK_TYPE_BID: Final[int] = 2

# 隨機遊走參數
PRICE_STEP: Final[float] = 0.5  # 單步最大波動
TREND_BIAS: Final[float] = 0.05  # 微弱趨勢（>0 偏多）


@dataclass
class MockSymbolConfig:
    code: str
    base_price: float
    tick_size: float = 1.0
    bias: float = TREND_BIAS  # 該商品的買壓/賣壓微偏


DEFAULT_SYMBOLS: Final[list[MockSymbolConfig]] = [
    MockSymbolConfig(code="TXFF4", base_price=21000.0, tick_size=1.0, bias=0.06),
]


# ============================================================
# 產生器
# ============================================================


class MockTickGenerator:
    """非同步 Mock Tick 產生器。

    使用方式：
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        gen = MockTickGenerator(queue, symbols=[...])
        task = asyncio.create_task(gen.run())
    """

    def __init__(
        self,
        queue: asyncio.Queue,
        symbols: list[MockSymbolConfig] | None = None,
        interval_sec: float = DEFAULT_TICK_INTERVAL_SEC,
    ) -> None:
        self._queue = queue
        self._symbols = symbols or list(DEFAULT_SYMBOLS)
        self._interval = interval_sec
        self._prices: dict[str, float] = {s.code: s.base_price for s in self._symbols}
        self._bid_total: dict[str, int] = {s.code: 0 for s in self._symbols}
        self._ask_total: dict[str, int] = {s.code: 0 for s in self._symbols}
        self._cum_volume: dict[str, int] = {s.code: 0 for s in self._symbols}
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        logger.info(
            "MockTickGenerator started: %d symbols, interval=%.3fs",
            len(self._symbols),
            self._interval,
        )
        try:
            while not self._stop.is_set():
                for sym in self._symbols:
                    tick = self._next_tick(sym)
                    await self._enqueue(tick)
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            logger.info("MockTickGenerator cancelled")
            raise
        finally:
            logger.info("MockTickGenerator stopped")

    async def _enqueue(self, tick: dict) -> None:
        try:
            self._queue.put_nowait(tick)
        except asyncio.QueueFull:
            # 滿溢時丟最舊的，保留最新（適合即時行情）
            try:
                _ = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(tick)
            except asyncio.QueueFull:
                logger.warning("queue still full after eviction; dropping tick")

    def _next_tick(self, sym: MockSymbolConfig) -> dict:
        # 隨機遊走 + 微弱趨勢
        drift = random.uniform(-PRICE_STEP, PRICE_STEP) + sym.bias * PRICE_STEP
        new_price = self._prices[sym.code] + drift
        # 量化到 tick_size
        new_price = round(new_price / sym.tick_size) * sym.tick_size
        self._prices[sym.code] = new_price

        volume = random.randint(1, 5)

        # tick_type 帶微弱買方偏移
        if random.random() < 0.5 + sym.bias:
            tick_type = TICK_TYPE_ASK  # 外盤（買方主動）
            self._ask_total[sym.code] += volume
        else:
            tick_type = TICK_TYPE_BID  # 內盤（賣方主動）
            self._bid_total[sym.code] += volume

        self._cum_volume[sym.code] += volume

        now_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        return {
            "code": sym.code,
            "datetime": now_iso,
            "price": new_price,
            "volume": volume,
            "total_volume": self._cum_volume[sym.code],
            "tick_type": tick_type,
            "bid_side_total_vol": self._bid_total[sym.code],
            "ask_side_total_vol": self._ask_total[sym.code],
        }
