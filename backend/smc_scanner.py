"""SMC Scanner — coordinates Shioaji data fetch with smc_detector.

Public surface:
    SMCScanner.scan_symbol(symbol)  -> list[SMCSignal]
    SMCScanner.run_forever()        -> never returns; iterates watchlist
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

from backend import watchlist as wl_mod
from backend.shioaji_fetcher import shioaji_fetch_daily, shioaji_fetch_m3, reset_login
from backend.smc_detector import SMCSignal, detect_signals, detect_market_structure

logger = logging.getLogger("smc-scanner")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env.local")
_LOG_DIR = _PROJECT_ROOT / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_TZ_TW = ZoneInfo("Asia/Taipei")
_SESSION_OPEN = dtime(9, 0)
_SESSION_CLOSE = dtime(13, 30)
_COOLDOWN_SECONDS = 600          # 10 min — same signal won't re-emit
_SCAN_INTERVAL_SECONDS = 180     # 3 min between full sweeps
_MIN_DAILY_BARS = 20


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_tw() -> datetime:
    return datetime.now(_TZ_TW)


def _in_session(now: Optional[datetime] = None) -> bool:
    now = now or _now_tw()
    if now.weekday() >= 5:
        return False
    return _SESSION_OPEN <= now.time() <= _SESSION_CLOSE


def _parse_watchlist(raw: str | None) -> list[str]:
    if not raw:
        return ["2330", "2317", "2382"]
    return [s.strip() for s in raw.split(",") if s.strip()]


# ── scanner ───────────────────────────────────────────────────────────────────

@dataclass
class SMCScanner:
    """Coordinator that fans out Shioaji fetches to smc_detector."""

    watchlist: list[str]
    daily_swing_n: int = 5
    intraday_swing_n: int = 3
    _cooldown: dict[str, datetime] = None       # type: ignore[assignment]
    _running: bool = False

    @classmethod
    def from_env(cls) -> "SMCScanner":
        watch = _parse_watchlist(os.getenv("SMC_WATCHLIST"))
        inst = cls(watchlist=watch)
        inst._cooldown = {}
        return inst

    def __post_init__(self) -> None:
        if self._cooldown is None:
            self._cooldown = {}

    # ── single-symbol scan ────────────────────────────────────────────────────

    async def scan_symbol(self, symbol: str) -> list[SMCSignal]:
        """Fetch daily + intraday for one symbol and run SMC detection.

        - Daily structure sets the bias.
        - Intraday gives the entry signal.
        - When intraday is empty (post-session), falls back to the daily frame
          so callers still get useful structure context.
        - On Shioaji failure, retries once after a reset_login(); if still
          failing, returns [] and logs the error.
        """
        try:
            return await self._scan_symbol_once(symbol)
        except Exception as exc:
            logger.warning("scan_symbol(%s) first attempt failed: %s", symbol, exc)
            try:
                reset_login()
                return await self._scan_symbol_once(symbol)
            except Exception as exc2:
                self._log_error(f"{symbol}: {exc2!r}")
                return []

    async def _scan_symbol_once(self, symbol: str) -> list[SMCSignal]:
        daily_task = asyncio.create_task(shioaji_fetch_daily(symbol, lookback=60))
        m3_task = asyncio.create_task(shioaji_fetch_m3(symbol))
        daily_df, m3_df = await asyncio.gather(daily_task, m3_task)

        if daily_df is None or len(daily_df) < _MIN_DAILY_BARS:
            # Shioaji 拉空 daily 通常是 session token 默默過期（API 回 401 不會
            # raise，只 log 後回空 df）。raise 讓 scan_symbol 外層 retry 觸發
            # reset_login → 重抓。真的市場異常的話第二次仍會空 → 外層回 []。
            n = 0 if daily_df is None else len(daily_df)
            raise RuntimeError(
                f"{symbol}: insufficient daily bars ({n}); likely stale shioaji session"
            )

        # Daily bias
        daily_struct = detect_market_structure(daily_df, n=self.daily_swing_n)
        daily_bias = daily_struct["structure"]

        # Intraday signals
        if m3_df is not None and not m3_df.empty and len(m3_df) >= _MIN_DAILY_BARS:
            signals = detect_signals(m3_df, symbol, timeframe="3m", n=self.intraday_swing_n)
            tf_used = "3m"
        else:
            signals = detect_signals(daily_df, symbol, timeframe="1D", n=self.daily_swing_n)
            tf_used = "1D"

        # Confluence boost: intraday direction matches daily bias
        boosted: list[SMCSignal] = []
        for s in signals:
            strength = s.strength
            up = s.signal_type.endswith("_UP")
            down = s.signal_type.endswith("_DOWN")
            if (up and daily_bias == "bullish") or (down and daily_bias == "bearish"):
                strength = min(s.strength + 1, 3)
            # CHoCH against existing bias → flag with strength=2
            if s.signal_type.startswith("CHoCH"):
                strength = max(strength, 2)
            # we cannot mutate frozen dataclass; rebuild
            boosted.append(SMCSignal(
                symbol=s.symbol,
                timeframe=s.timeframe,
                signal_type=s.signal_type,
                price=s.price,
                market_structure=daily_bias,        # report daily bias as authoritative
                timestamp=s.timestamp,
                strength=strength,
                demand_zone=s.demand_zone,
                supply_zone=s.supply_zone,
                meta={**s.meta, "tf_used": tf_used, "daily_bias": daily_bias},
            ))

        return boosted

    # ── run-loop ──────────────────────────────────────────────────────────────

    def should_emit(self, signal: SMCSignal, now: Optional[datetime] = None) -> bool:
        """Cooldown gate. Returns True if (symbol, signal_type) is past its cooldown."""
        now = now or _now_tw()
        key = f"{signal.symbol}_{signal.signal_type}"
        last = self._cooldown.get(key)
        if last is None or (now - last) >= timedelta(seconds=_COOLDOWN_SECONDS):
            self._cooldown[key] = now
            return True
        return False

    def _effective_watchlist(self) -> list[str]:
        """每輪重讀當沖 watchlist 檔；空檔回 fallback 到 self.watchlist。

        對應 LESSONS.md §2.7：使用者在 Telegram /wl_add 動態增刪，下一輪 scan 立即生效。
        """
        persistent = wl_mod.load()
        if persistent.entries:
            return list(persistent.symbols)
        return list(self.watchlist)

    async def run_once(self, *, force: bool = False):
        """One pass over the watchlist. Yields (symbol, [signals])."""
        if not force and not _in_session():
            logger.debug("outside session; skipping sweep")
            return
        active = self._effective_watchlist()
        for sym in active:
            try:
                sigs = await self.scan_symbol(sym)
                fresh = [s for s in sigs if self.should_emit(s)]
                yield sym, fresh
            except Exception as exc:
                self._log_error(f"run_once({sym}): {exc!r}")
                yield sym, []

    async def run_forever(self, on_signal=None):
        """Infinite scan loop. `on_signal(symbol, signal, daily_df, m3_df)` is
        awaited for each fresh signal. Pass None to just log.
        """
        self._running = True
        active = self._effective_watchlist()
        source = "day_trade_watchlist.json" if wl_mod.load().entries else "SMC_WATCHLIST env"
        logger.info(
            "smc-scanner started, source=%s, watching: %s", source, ",".join(active)
        )
        while self._running:
            if _in_session():
                async for sym, sigs in self.run_once():
                    for s in sigs:
                        logger.info("signal %s/%s @ %.2f (strength=%d)",
                                    s.symbol, s.signal_type, s.price, s.strength)
                        if on_signal is not None:
                            try:
                                await on_signal(sym, s)
                            except Exception as exc:
                                self._log_error(f"on_signal callback: {exc!r}")
            else:
                logger.debug("market closed; sleeping")
            await asyncio.sleep(_SCAN_INTERVAL_SECONDS)

    def stop(self) -> None:
        self._running = False

    # ── error log ─────────────────────────────────────────────────────────────

    def _log_error(self, msg: str) -> None:
        try:
            ts = _now_tw().strftime("%Y-%m-%d %H:%M:%S")
            with (_LOG_DIR / "smc_error.log").open("a", encoding="utf-8") as fh:
                fh.write(f"[{ts}] {msg}\n")
        except OSError:
            pass
        logger.error(msg)
