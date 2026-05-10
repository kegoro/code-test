"""DataSourceRouter — ordered failover between Shioaji and FinMind.

Usage in lifespan:
    router = DataSourceRouter()
    await router.warmup()
    engine = ScannerEngine(symbols=symbols, fetch=router, ...)
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

import pandas as pd

logger = logging.getLogger("data-router")

_DEFAULT_UNHEALTHY_TTL: float = 60.0  # seconds


class _Source:
    """Wrapper around a named fetch callable with health-tracking."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._unhealthy_until: float = 0.0  # monotonic timestamp

    def is_healthy(self) -> bool:
        return time.monotonic() >= self._unhealthy_until

    def mark_unhealthy(self, ttl_seconds: float = _DEFAULT_UNHEALTHY_TTL) -> None:
        self._unhealthy_until = time.monotonic() + ttl_seconds
        logger.warning("source %s marked unhealthy for %.0fs", self.name, ttl_seconds)

    def reset(self) -> None:
        self._unhealthy_until = 0.0


class _ShioajiSource(_Source):
    def __init__(self) -> None:
        super().__init__("shioaji")

    async def warmup(self) -> bool:
        try:
            from backend.shioaji_fetcher import warmup as _sj_warmup
            ok = await _sj_warmup()
            if ok:
                logger.info("Shioaji warmup OK")
            else:
                logger.warning("Shioaji warmup returned False")
            return ok
        except Exception as exc:
            logger.warning("Shioaji warmup failed: %s", exc)
            return False

    async def fetch(self, symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        from backend.shioaji_fetcher import shioaji_fetch
        return await shioaji_fetch(symbol)

    def reset_login(self) -> None:
        try:
            from backend.shioaji_fetcher import reset_login
            reset_login()
        except Exception as exc:
            logger.debug("reset_login error: %s", exc)


class _FinMindSource(_Source):
    def __init__(self) -> None:
        super().__init__("finmind")

    async def warmup(self) -> bool:
        # FinMind is HTTP-based; no persistent login needed.
        return True

    async def fetch(self, symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        from backend.finmind_fetcher import finmind_fetch
        return await finmind_fetch(symbol)


class DataSourceRouter:
    """Callable router that tries sources in priority order with TTL-based cooldown.

    Conforms to ``Callable[[str], Awaitable[tuple[pd.DataFrame, pd.DataFrame]]]``
    so it can be passed directly as ``fetch`` to ``ScannerEngine``.
    """

    def __init__(self, unhealthy_ttl: float = _DEFAULT_UNHEALTHY_TTL) -> None:
        self._unhealthy_ttl = unhealthy_ttl
        self._shioaji = _ShioajiSource()
        self._finmind = _FinMindSource()
        self._sources: list[_ShioajiSource | _FinMindSource] = [
            self._shioaji,
            self._finmind,
        ]

    async def warmup(self) -> None:
        """Try to initialise each source. Failures are logged but never raised."""
        for src in self._sources:
            try:
                ok = await src.warmup()
                if not ok:
                    src.mark_unhealthy(self._unhealthy_ttl)
            except Exception as exc:
                logger.warning("warmup error for %s: %s", src.name, exc)
                src.mark_unhealthy(self._unhealthy_ttl)

        healthy = [s.name for s in self._sources if s.is_healthy()]
        logger.info("data-router healthy sources after warmup: %s", healthy)

    async def __call__(self, symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Fetch data for *symbol*, trying sources in priority order."""
        last_exc: Exception | None = None
        for src in self._sources:
            if not src.is_healthy():
                logger.debug("skipping unhealthy source %s", src.name)
                continue
            try:
                result = await src.fetch(symbol)
                return result
            except Exception as exc:
                logger.warning(
                    "source %s failed for %s (%s); marking unhealthy",
                    src.name, symbol, exc,
                )
                src.mark_unhealthy(self._unhealthy_ttl)
                # If Shioaji failed, attempt reset so it can retry after TTL.
                if isinstance(src, _ShioajiSource):
                    src.reset_login()
                last_exc = exc

        # All sources exhausted — return empty frames rather than crashing.
        logger.error(
            "all data sources failed for %s; last error: %s", symbol, last_exc
        )
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return empty, empty

    def status(self) -> dict:
        """Return health status dict for /health endpoint."""
        return {
            src.name: {
                "healthy": src.is_healthy(),
                "unhealthy_until": src._unhealthy_until,
            }
            for src in self._sources
        }
