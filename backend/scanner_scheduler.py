"""Scanner scheduler — periodic A1/A2 scan with dedup and SSE broadcast."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from backend.no_trade_guard import is_market_open
from backend.scanner_a1 import scan_a1
from backend.scanner_a2 import scan_a2
from backend.scanner_models import (
    DEDUP_WINDOW_MINUTES,
    SCAN_INTERVAL_SECONDS,
    SetupSignal,
    SignalStatus,
)
from backend.volume_profile import calculate_volume_profile

logger = logging.getLogger("scanner-scheduler")


DataFetcher = Callable[[str], Awaitable[tuple[pd.DataFrame, pd.DataFrame]]]
NotifyFn = Callable[[SetupSignal], Awaitable[None]]
SymbolsSource = Callable[[], list[str]]


class ScannerEngine:
    """Periodic scanner with dedup cache + invalidation.

    Symbol set can be either:
      - 靜態：傳 symbols=[...]，每輪固定掃這些
      - 動態：傳 symbols_source=callable，每輪呼叫一次取最新清單
              （對應 LESSONS.md §2.7 當沖 watchlist：UI 動態增刪要立即生效）
    若 symbols_source 提供，會 override 靜態 symbols。
    若 symbols_source 回空 list，則該輪 skip（避免掃全市場誤觸發）。
    """

    def __init__(
        self,
        symbols: list[str],
        fetch: DataFetcher,
        on_signal: NotifyFn | None = None,
        *,
        interval_seconds: int = SCAN_INTERVAL_SECONDS,
        market_hours_only: bool = True,
        symbols_source: SymbolsSource | None = None,
    ) -> None:
        self.symbols = symbols
        self.fetch = fetch
        self.on_signal = on_signal
        self.interval = interval_seconds
        self.market_hours_only = market_hours_only
        self.symbols_source = symbols_source

        self._active: dict[str, SetupSignal] = {}        # dedup_key -> signal
        self._dedup_ts: dict[str, datetime] = {}
        self._sse_queues: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # ----- public -----

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._loop(), name="scanner-loop")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    def active_signals(self, symbol: str | None = None) -> list[dict[str, Any]]:
        signals = list(self._active.values())
        if symbol:
            signals = [s for s in signals if s.symbol == symbol]
        return [s.to_dict() for s in signals]

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._sse_queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._sse_queues.remove(q)
        except ValueError:
            pass

    # ----- internal -----

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        dead = []
        for q in self._sse_queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    def _current_symbols(self) -> list[str]:
        """每輪取「現在該掃哪些 symbol」。動態 source 優先。"""
        if self.symbols_source is not None:
            try:
                dyn = list(self.symbols_source())
                return dyn
            except Exception as exc:  # noqa: BLE001
                logger.warning("symbols_source failed, fallback to static: %s", exc)
        return list(self.symbols)

    async def _loop(self) -> None:
        mode = "dynamic" if self.symbols_source else "static"
        logger.info(
            "scanner loop started: %s mode, init=%d symbols, %ds interval",
            mode, len(self.symbols), self.interval,
        )
        while not self._stop.is_set():
            try:
                if not self.market_hours_only or is_market_open(datetime.now()):
                    await self._scan_once()
                else:
                    logger.debug("market closed, skipping scan")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("scan iteration failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
                break
            except asyncio.TimeoutError:
                continue

    async def _scan_one(self, symbol: str) -> SetupSignal | None:
        try:
            df_daily, df_m3 = await self.fetch(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fetch failed for %s: %s", symbol, exc)
            return None
        if df_m3 is None or df_m3.empty or len(df_m3) < 20:
            return None
        try:
            profile = calculate_volume_profile(df_m3, price_step=0.5, lookback_bars=min(20, len(df_m3)))
        except Exception as exc:  # noqa: BLE001
            logger.debug("profile failed for %s: %s", symbol, exc)
            return None

        sig = scan_a1(symbol, df_daily, df_m3, profile)
        if sig is None:
            sig = scan_a2(symbol, df_daily, df_m3, profile)
        return sig

    async def _scan_once(self) -> None:
        async with self._lock:
            symbols = self._current_symbols()
            if not symbols:
                logger.debug("scan skipped: empty symbol set (watchlist 空？)")
                return
            results = await asyncio.gather(
                *(self._scan_one(s) for s in symbols), return_exceptions=False
            )
            now = datetime.now()
            for sig in results:
                if sig is None:
                    continue
                key = sig.dedup_key
                last = self._dedup_ts.get(key)
                if last and now - last < timedelta(minutes=DEDUP_WINDOW_MINUTES):
                    continue
                self._active[key] = sig
                self._dedup_ts[key] = now
                await self._broadcast({"type": "signal", "data": sig.to_dict()})
                if self.on_signal is not None:
                    try:
                        await self.on_signal(sig)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("notify failed: %s", exc)

            await self._expire_stale(now)

    async def _expire_stale(self, now: datetime) -> None:
        expired = []
        for key, sig in list(self._active.items()):
            ts = self._dedup_ts.get(key, sig.triggered_at)
            if now - ts > timedelta(minutes=DEDUP_WINDOW_MINUTES * 2):
                expired.append(key)
        for key in expired:
            sig = self._active.pop(key)
            self._dedup_ts.pop(key, None)
            await self._broadcast(
                {"type": "expire", "data": sig.with_status(SignalStatus.EXPIRED).to_dict()}
            )
