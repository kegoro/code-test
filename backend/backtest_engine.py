"""Vectorised-rolling backtest engine for A1 / A2 setups.

Design principles
-----------------
1. **Zero look-ahead bias**: signals on day *t* see only bars `[..t]`. Entries
   fill at the *open* of `t+1`. Exits use OHLC of the bar they trigger on.
2. **Stop-mode comparison**: every signal is replayed under both `fixed`
   (the scanner's own stop) and `atr` (entry ± ATR_14 × multiplier). The
   resulting trades are tagged `stop_mode` so the report layer can split them.
3. **Daily-fallback compatible**: when intraday is paywalled the scanners are
   driven from daily bars (matching `finmind_fetcher.finmind_fetch`).
4. **Pure data in / records out**: the engine never touches the network. The
   caller passes a `{symbol: df_daily}` dict — `backtest_runner` is responsible
   for fetching + caching.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Final, Literal

import numpy as np
import pandas as pd

from backend.scanner_a1 import scan_a1
from backend.scanner_a2 import scan_a2
from backend.scanner_models import (
    Direction,
    SetupSignal,
    SetupType,
)
from backend.volume_profile import calculate_volume_profile

logger = logging.getLogger("backtest-engine")


# ---------- Config ----------

StopMode = Literal["fixed", "atr", "both"]


@dataclass(frozen=True)
class BacktestConfig:
    symbols: list[str]
    start_date: str                       # ISO "YYYY-MM-DD"
    end_date: str                         # ISO "YYYY-MM-DD"
    setup_types: tuple[str, ...] = ("A1", "A2")
    stop_mode: StopMode = "both"
    initial_capital: float = 1_000_000.0
    risk_per_trade: float = 0.01          # 1% of equity per trade
    max_concurrent: int = 3
    atr_period: int = 14
    atr_multiplier: float = 1.0
    profile_lookback: int = 20
    profile_price_step: float = 0.5
    warmup_bars: int = 30                 # need this many before first signal
    tp1_ratio: float = 0.5                # legacy fallback when VAH/VAL unavailable
    min_grade: str = "A"                  # filter A1 below this grade ("A" | "B")


# ---------- Trade record ----------

@dataclass
class TradeRecord:
    symbol: str
    setup: str                            # "A1" | "A2"
    direction: str                        # "long" | "short"
    grade: str                            # "A" | "B"
    signal_score: int

    entry_date: date
    entry_price: float
    stop_price: float
    tp1_price: float
    tp2_price: float
    stop_mode: str                        # "fixed" | "atr"

    exit_date: date | None = None
    exit_price: float | None = None
    exit_reason: str | None = None        # "TP1" | "TP2" | "SL" | "EOD" | "CANCEL"

    pnl_r: float | None = None
    pnl_pct: float | None = None
    bars_held: int = 0
    ob_confirmed: bool = False             # A1 only: C7d (sweep into valid OB) passed


# ---------- Result ----------

@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list[TradeRecord] = field(default_factory=list)
    daily_equity: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=["date", "equity"]).set_index("date")
    )
    symbols_processed: int = 0
    bars_evaluated: int = 0


# ---------- ATR helper ----------

def _atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder-smoothed-style simple ATR on a daily frame."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


# ---------- Engine ----------

class BacktestEngine:
    """Runs the rolling backtest. Stateless — call `run` per config."""

    def __init__(
        self,
        data: dict[str, pd.DataFrame],
        m3_store: dict[str, pd.DataFrame] | None = None,
    ):
        """`data` maps symbol → daily OHLCV.

        ``m3_store`` (optional) maps symbol → concatenated M3 OHLCV across the
        full backtest window. When provided, the engine slices ``m3_store[sym]``
        up to end-of-day ``t`` and feeds those real M3 bars to the scanners
        instead of the daily-tail pseudo-M3.
        """
        self._data = {s: self._prep(df) for s, df in data.items() if df is not None}
        self._m3_store: dict[str, pd.DataFrame] = {}
        if m3_store:
            for sym, df in m3_store.items():
                if df is None or df.empty:
                    continue
                cleaned = df.copy()
                if not isinstance(cleaned.index, pd.DatetimeIndex):
                    cleaned.index = pd.to_datetime(cleaned.index)
                self._m3_store[sym] = cleaned.sort_index()

    @staticmethod
    def _prep(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df
        df = df.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        return df.dropna(subset=["open", "high", "low", "close"]).astype(
            {"open": float, "high": float, "low": float, "close": float, "volume": float}
        )

    # ---- public ----

    def run(self, config: BacktestConfig) -> BacktestResult:
        result = BacktestResult(config=config)
        start_ts = pd.Timestamp(config.start_date)
        end_ts = pd.Timestamp(config.end_date)

        for symbol in config.symbols:
            df = self._data.get(symbol)
            if df is None or df.empty:
                logger.warning("no data for %s; skipping", symbol)
                continue
            window = df.loc[(df.index >= start_ts - pd.Timedelta(days=120)) & (df.index <= end_ts)]
            if len(window) < config.warmup_bars + 2:
                logger.warning("%s: insufficient bars (%d)", symbol, len(window))
                continue
            self._run_symbol(symbol, window, config, result)
            result.symbols_processed += 1

        result.daily_equity = self._compute_equity_curve(result, config)
        return result

    # ---- per-symbol loop ----

    def _run_symbol(
        self,
        symbol: str,
        df: pd.DataFrame,
        cfg: BacktestConfig,
        result: BacktestResult,
    ) -> None:
        atr = _atr_series(df, cfg.atr_period)
        open_trades: list[TradeRecord] = []
        # iterate days where we have a "next bar" to fill on
        n = len(df)
        start_iter = max(cfg.warmup_bars, cfg.profile_lookback)
        for i in range(start_iter, n - 1):
            today = df.iloc[: i + 1]            # bars up to and including day t
            today_bar = df.iloc[i]
            tomorrow = df.iloc[i + 1]
            tomorrow_date = df.index[i + 1].date()
            result.bars_evaluated += 1

            # 1) Process exits on tomorrow's bar for any open trades
            self._process_exits(open_trades, tomorrow, tomorrow_date)
            open_trades = [t for t in open_trades if t.exit_date is None]

            # 2) Generate signals on bars[..t] only (no look-ahead)
            if len(open_trades) >= cfg.max_concurrent:
                continue
            try:
                profile = calculate_volume_profile(
                    today.tail(cfg.profile_lookback),
                    price_step=cfg.profile_price_step,
                    lookback_bars=cfg.profile_lookback,
                )
            except (ValueError, IndexError) as exc:
                logger.debug("%s @ %s: profile failed: %s", symbol, today.index[-1], exc)
                continue

            df_m3 = self._m3_for(symbol, today.index[-1], cfg)
            signals = self._scan(symbol, today, df_m3, profile, cfg)
            if not signals:
                continue

            # 3) Open trade(s) at tomorrow's open
            for sig in signals:
                if len(open_trades) >= cfg.max_concurrent:
                    break
                # A1 grade filter: drop B-grade A1 signals when min_grade="A".
                if (
                    sig.setup.value == "A1"
                    and cfg.min_grade == "A"
                    and sig.grade.value != "A"
                ):
                    continue
                # A1 must have C7d (ob_confirmed) passed — unconfirmed OBs PF=0.232.
                if sig.setup.value == "A1" and not any(
                    c.code == "C7d" and c.passed for c in sig.conditions
                ):
                    continue
                fill_price = float(tomorrow["open"])
                modes = self._modes_for(cfg.stop_mode)
                for mode in modes:
                    trade = self._build_trade(
                        sig, fill_price, tomorrow_date, mode, atr.iloc[i], cfg
                    )
                    if trade is None:
                        continue
                    open_trades.append(trade)
                    result.trades.append(trade)

        # 4) Force-close anything still open at the final bar
        if open_trades:
            last = df.iloc[-1]
            last_date = df.index[-1].date()
            for trade in open_trades:
                if trade.exit_date is None:
                    self._close(trade, last_date, float(last["close"]), "EOD")

    # ---- helpers ----

    def _m3_for(
        self, symbol: str, today_ts: pd.Timestamp, cfg: BacktestConfig
    ) -> pd.DataFrame:
        """Return real M3 bars up to end-of-day ``today_ts``.

        Falls back to the daily-tail pseudo when no M3 cache is available
        for ``symbol`` or for the requested day.
        """
        store = self._m3_store.get(symbol)
        daily = self._data.get(symbol)
        if store is None or store.empty:
            return daily.loc[:today_ts].tail(cfg.profile_lookback).copy()
        cutoff = pd.Timestamp(today_ts).normalize() + pd.Timedelta(days=1)
        sliced = store.loc[store.index < cutoff]
        if sliced.empty:
            return daily.loc[:today_ts].tail(cfg.profile_lookback).copy()
        # cap at a reasonable lookback so scanners don't drown in months of M3
        max_bars = max(cfg.profile_lookback * 30, 500)
        return sliced.tail(max_bars).copy()

    @staticmethod
    def _modes_for(mode: StopMode) -> tuple[str, ...]:
        if mode == "both":
            return ("fixed", "atr")
        return (mode,)

    @staticmethod
    def _scan(
        symbol: str,
        df_daily: pd.DataFrame,
        df_pseudo_m3: pd.DataFrame,
        profile,
        cfg: BacktestConfig,
    ) -> list[SetupSignal]:
        out: list[SetupSignal] = []
        if "A1" in cfg.setup_types:
            sig = scan_a1(symbol, df_daily, df_pseudo_m3, profile)
            if sig is not None:
                out.append(sig)
        if "A2" in cfg.setup_types:
            sig = scan_a2(symbol, df_daily, df_pseudo_m3, profile)
            if sig is not None:
                out.append(sig)
        return out

    @staticmethod
    def _build_trade(
        sig: SetupSignal,
        fill_price: float,
        entry_date: date,
        stop_mode: str,
        atr_value: float,
        cfg: BacktestConfig,
    ) -> TradeRecord | None:
        direction = "long" if sig.direction is Direction.LONG else "short"

        if stop_mode == "fixed":
            stop = float(sig.stop_price)
        else:  # atr
            if not np.isfinite(atr_value) or atr_value <= 0:
                return None
            offset = atr_value * cfg.atr_multiplier
            stop = fill_price - offset if direction == "long" else fill_price + offset

        risk = abs(fill_price - stop)
        if risk <= 0:
            return None

        target = float(sig.target_price)
        tp2 = target
        # TP1 = VAH (long) / VAL (short) — first volume-profile resistance/support.
        # Fall back to halfway-to-target when VAH/VAL is on the wrong side of entry.
        if direction == "long":
            vah = float(sig.profile.vah)
            tp1 = vah if vah > fill_price and vah < tp2 else fill_price + (tp2 - fill_price) * cfg.tp1_ratio
        else:
            val = float(sig.profile.val)
            tp1 = val if val < fill_price and val > tp2 else fill_price + (tp2 - fill_price) * cfg.tp1_ratio

        ob_confirmed = any(
            c.code == "C7d" and c.passed for c in sig.conditions
        )

        return TradeRecord(
            symbol=sig.symbol,
            setup=sig.setup.value,
            direction=direction,
            grade=sig.grade.value,
            signal_score=sig.score_passed,
            entry_date=entry_date,
            entry_price=fill_price,
            stop_price=stop,
            tp1_price=tp1,
            tp2_price=tp2,
            stop_mode=stop_mode,
            ob_confirmed=ob_confirmed,
        )

    @staticmethod
    def _process_exits(
        open_trades: list[TradeRecord],
        bar: pd.Series,
        bar_date: date,
    ) -> None:
        """Check each open trade against the bar's OHLC.

        Order of checks (worst case for the trade): on a single bar that
        gaps through the stop *and* hits a target we resolve as **stop**
        because we cannot prove the path. This is the conservative choice.
        """
        bar_open = float(bar["open"])
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])

        for t in open_trades:
            if t.exit_date is not None:
                continue
            t.bars_held += 1
            if t.direction == "long":
                # gap-down through stop on open
                if bar_open <= t.stop_price:
                    BacktestEngine._close(t, bar_date, bar_open, "SL")
                    continue
                # intrabar
                hit_sl = bar_low <= t.stop_price
                hit_tp2 = bar_high >= t.tp2_price
                hit_tp1 = bar_high >= t.tp1_price
                if hit_sl:
                    BacktestEngine._close(t, bar_date, t.stop_price, "SL")
                elif hit_tp2:
                    BacktestEngine._close(t, bar_date, t.tp2_price, "TP2")
                elif hit_tp1:
                    BacktestEngine._close(t, bar_date, t.tp1_price, "TP1")
            else:  # short
                if bar_open >= t.stop_price:
                    BacktestEngine._close(t, bar_date, bar_open, "SL")
                    continue
                hit_sl = bar_high >= t.stop_price
                hit_tp2 = bar_low <= t.tp2_price
                hit_tp1 = bar_low <= t.tp1_price
                if hit_sl:
                    BacktestEngine._close(t, bar_date, t.stop_price, "SL")
                elif hit_tp2:
                    BacktestEngine._close(t, bar_date, t.tp2_price, "TP2")
                elif hit_tp1:
                    BacktestEngine._close(t, bar_date, t.tp1_price, "TP1")

    @staticmethod
    def _close(t: TradeRecord, exit_date: date, exit_price: float, reason: str) -> None:
        t.exit_date = exit_date
        t.exit_price = exit_price
        t.exit_reason = reason
        risk = abs(t.entry_price - t.stop_price)
        if t.direction == "long":
            pnl = exit_price - t.entry_price
        else:
            pnl = t.entry_price - exit_price
        t.pnl_r = pnl / risk if risk > 0 else 0.0
        t.pnl_pct = pnl / t.entry_price if t.entry_price > 0 else 0.0

    # ---- equity curve ----

    @staticmethod
    def _compute_equity_curve(result: BacktestResult, cfg: BacktestConfig) -> pd.DataFrame:
        """Equity = capital + Σ (risk_$ × pnl_r) booked on exit_date.

        Each trade risks `cfg.risk_per_trade` of the *initial* capital (fixed
        sizing — keeps the curve interpretable; compounding is a report-layer
        concern).
        """
        if not result.trades:
            idx = pd.date_range(cfg.start_date, cfg.end_date, freq="B")
            return pd.DataFrame(
                {"equity": [cfg.initial_capital] * len(idx)}, index=idx
            )

        risk_dollars = cfg.initial_capital * cfg.risk_per_trade
        rows: list[tuple[date, float]] = []
        for t in result.trades:
            if t.exit_date is None or t.pnl_r is None:
                continue
            rows.append((t.exit_date, risk_dollars * t.pnl_r))
        if not rows:
            idx = pd.date_range(cfg.start_date, cfg.end_date, freq="B")
            return pd.DataFrame({"equity": [cfg.initial_capital] * len(idx)}, index=idx)

        booked = pd.DataFrame(rows, columns=["date", "pnl_dollars"])
        booked["date"] = pd.to_datetime(booked["date"])
        daily = booked.groupby("date")["pnl_dollars"].sum().sort_index()
        idx = pd.date_range(cfg.start_date, cfg.end_date, freq="B")
        cum = daily.reindex(idx, fill_value=0.0).cumsum()
        return pd.DataFrame({"equity": cfg.initial_capital + cum}, index=idx)


# ---------- pytest ----------

def _synthetic_daily(
    start: str = "2024-01-01",
    bars: int = 80,
    seed: int = 7,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start=start, periods=bars)
    drift = rng.normal(0.0005, 0.015, size=bars)
    close = 100.0 * np.cumprod(1.0 + drift)
    open_ = close * (1 + rng.normal(0, 0.003, bars))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, bars)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, bars)))
    vol = rng.integers(1_000, 10_000, size=bars).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def test_engine_no_data_skips_symbol() -> None:
    engine = BacktestEngine({"X": pd.DataFrame()})
    cfg = BacktestConfig(
        symbols=["X"], start_date="2024-01-01", end_date="2024-03-01"
    )
    res = engine.run(cfg)
    assert res.symbols_processed == 0
    assert res.trades == []


def test_engine_runs_without_crash() -> None:
    df = _synthetic_daily(bars=120)
    engine = BacktestEngine({"TEST": df})
    cfg = BacktestConfig(
        symbols=["TEST"],
        start_date=str(df.index[0].date()),
        end_date=str(df.index[-1].date()),
        stop_mode="both",
    )
    res = engine.run(cfg)
    assert res.symbols_processed == 1
    # may or may not produce signals — but must not crash
    for t in res.trades:
        assert t.stop_mode in {"fixed", "atr"}
        assert t.entry_price > 0


def test_pnl_r_long_tp_resolution() -> None:
    t = TradeRecord(
        symbol="T", setup="A1", direction="long", grade="A", signal_score=6,
        entry_date=date(2024, 1, 2), entry_price=100.0, stop_price=98.0,
        tp1_price=101.0, tp2_price=104.0, stop_mode="fixed",
    )
    BacktestEngine._close(t, date(2024, 1, 5), 104.0, "TP2")
    assert t.pnl_r == 2.0
    assert t.exit_reason == "TP2"


def test_pnl_r_short_sl_resolution() -> None:
    t = TradeRecord(
        symbol="T", setup="A2", direction="short", grade="B", signal_score=4,
        entry_date=date(2024, 1, 2), entry_price=100.0, stop_price=102.0,
        tp1_price=99.0, tp2_price=96.0, stop_mode="atr",
    )
    BacktestEngine._close(t, date(2024, 1, 3), 102.0, "SL")
    assert t.pnl_r == -1.0


def test_equity_curve_zero_trades_returns_flat_capital() -> None:
    cfg = BacktestConfig(
        symbols=["X"], start_date="2024-01-01", end_date="2024-01-31"
    )
    res = BacktestResult(config=cfg)
    curve = BacktestEngine._compute_equity_curve(res, cfg)
    assert (curve["equity"] == cfg.initial_capital).all()
