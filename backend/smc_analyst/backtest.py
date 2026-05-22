"""SMC Analyst backtest harness.

Replays historical bars and asks: at each point in time, what would the
analyst have said? For every signal that fires, simulate the trade by
walking forward bar-by-bar to see whether `target` or `stop` was hit first.

Definitions:
    win   = bar reaches `target` before `stop` (or equal to target)
    loss  = bar reaches `stop`  before `target`
    open  = trade never resolved within the simulation horizon

The harness is intentionally simple — no slippage, no commissions, single
entry, no scaling. Its job is to give a rough quality signal on whether
the scoring + setups are even close to producing edge.

Usage:
    python -m backend.smc_analyst.backtest 2330
    python -m backend.smc_analyst.backtest 2330 --days 10 --step 5
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from backend.smc_analyst.context import AnalysisContext, Frame, _atr, _build_liquidity_map
from backend.smc_analyst.setups import ALL_SETUPS
from backend.smc_analyst.setups.base import SetupMatch, passes_hard_gates
from backend.smc_detector import (
    classify_strong_weak, compute_mtf_levels, compute_premium_discount,
    compute_trendlines, detect_market_structure, find_fair_value_gaps,
    find_order_blocks, mark_equal_pivots,
)


logger = logging.getLogger("smc-analyst.backtest")


# ── result types ──────────────────────────────────────────────────────────────

@dataclass
class BacktestSignal:
    timestamp: str
    bar_idx: int
    symbol: str
    setup_name: str
    direction: str
    score: int
    risk_reward: float
    entry: float
    stop: float
    target: float
    outcome: str = "open"      # "win" / "loss" / "open"
    bars_to_resolve: int = -1


@dataclass
class BacktestReport:
    symbol: str
    bars_total: int
    bars_evaluated: int
    signals: list[BacktestSignal] = field(default_factory=list)

    @property
    def fires(self) -> int:
        return len(self.signals)

    @property
    def wins(self) -> int:
        return sum(1 for s in self.signals if s.outcome == "win")

    @property
    def losses(self) -> int:
        return sum(1 for s in self.signals if s.outcome == "loss")

    @property
    def opens(self) -> int:
        return sum(1 for s in self.signals if s.outcome == "open")

    @property
    def resolved(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        if self.resolved == 0:
            return 0.0
        return self.wins / self.resolved

    @property
    def avg_rr(self) -> float:
        if not self.signals:
            return 0.0
        return sum(s.risk_reward for s in self.signals) / len(self.signals)

    @property
    def expectancy(self) -> float:
        """Average R per signal (wins × R - losses × 1) / total."""
        if not self.signals:
            return 0.0
        gain = sum(s.risk_reward for s in self.signals if s.outcome == "win")
        loss = sum(1.0 for s in self.signals if s.outcome == "loss")
        return (gain - loss) / max(1, self.fires)


# ── synthetic context for a bar slice ────────────────────────────────────────

# Match live pipeline window sizes (context.py _LTF_DAYS_M1 = 5 days ≈ 1350 bars).
# Feeding detectors a 5-day window is consistent with production behavior and
# turns per-step cost from O(t) to O(constant).
_LTF_WINDOW = 1500
_MTF_WINDOW = 200


def _build_ctx_from_slice(
    symbol: str,
    ltf_slice: pd.DataFrame,
    daily_df: pd.DataFrame,
    mtf_slice: pd.DataFrame,
    *,
    htf_cache: Optional[dict] = None,
) -> AnalysisContext:
    """Build an AnalysisContext from pre-sliced frames (for replay).

    `htf_cache` (optional) pre-computed daily-level values from a single call
    outside the replay loop: {"struct": dict, "atr": float, "mtf_levels": dict}.
    """
    # Truncate to match live pipeline windows — detectors only look at recent
    # structure (last 14-30 bars for OB/ATR/trendline, last 2 swings for trend).
    if len(ltf_slice) > _LTF_WINDOW:
        ltf_slice = ltf_slice.iloc[-_LTF_WINDOW:]
    if len(mtf_slice) > _MTF_WINDOW:
        mtf_slice = mtf_slice.iloc[-_MTF_WINDOW:]

    if htf_cache is not None:
        htf_struct = htf_cache["struct"]
        htf_atr = htf_cache["atr"]
        mtf_levels = htf_cache["mtf_levels"]
    else:
        htf_struct = detect_market_structure(daily_df, n=5) if not daily_df.empty else \
            {"structure": "ranging", "swing_points": {"swing_highs": [], "swing_lows": []},
             "last_bos": None, "last_choch": None}
        htf_atr = _atr(daily_df, 14)
        mtf_levels = compute_mtf_levels(daily_df)

    mtf_struct = detect_market_structure(mtf_slice, n=5) if not mtf_slice.empty else \
        {"structure": "ranging", "swing_points": {"swing_highs": [], "swing_lows": []},
         "last_bos": None, "last_choch": None}
    ltf_struct = detect_market_structure(ltf_slice, n=10)

    htf = Frame("1D", daily_df, 5, htf_struct, atr=htf_atr)
    mtf = Frame("60m", mtf_slice, 5, mtf_struct, atr=_atr(mtf_slice, 14))
    ltf = Frame("1m", ltf_slice, 10, ltf_struct, atr=_atr(ltf_slice, 14))

    sp_ltf = ltf_struct.get("swing_points", {})
    eq = mark_equal_pivots(sp_ltf, ltf_slice)
    sw = classify_strong_weak(ltf_struct)
    obs = find_order_blocks(ltf_slice, lookback=30, max_count=5)
    fvgs = [f for f in find_fair_value_gaps(ltf_slice) if f["valid"]]
    tl = compute_trendlines(ltf_slice, length=14) if len(ltf_slice) > 30 else None
    pd_zones = compute_premium_discount(sp_ltf, ltf_slice)
    liquidity = _build_liquidity_map(ltf, mtf_levels=mtf_levels, equal_pivots=eq)

    # Reuse a "trend_morning" phase so session_bonus stays positive in replay
    # (otherwise weekends/closed sessions silently strip a Tier-3 point).
    return AnalysisContext(
        symbol=symbol,
        now_tw=ltf_slice.index[-1].to_pydatetime() if hasattr(ltf_slice.index[-1], "to_pydatetime") else datetime.now(),
        session_phase="trend_morning",
        htf=htf, mtf=mtf, ltf=ltf,
        liquidity=liquidity,
        pd_zones=pd_zones,
        mtf_levels=mtf_levels,
        equal_pivots=eq,
        strong_weak=sw,
        active_obs=obs,
        active_fvgs=fvgs,
        trendlines=tl,
        atr_ltf=ltf.atr,
    )


# ── core replay loop ──────────────────────────────────────────────────────────

def _resolve_trade(
    ltf_df: pd.DataFrame,
    *,
    entry_bar: int,
    match: SetupMatch,
    horizon: int = 240,
) -> tuple[str, int]:
    """Walk forward from `entry_bar` up to `horizon` bars; return outcome + bars."""
    n = len(ltf_df)
    high = ltf_df["high"].to_numpy(dtype=float)
    low = ltf_df["low"].to_numpy(dtype=float)
    end = min(n, entry_bar + 1 + horizon)
    for t in range(entry_bar + 1, end):
        if match.direction == "long":
            if low[t] <= match.stop:
                return ("loss", t - entry_bar)
            if high[t] >= match.target:
                return ("win", t - entry_bar)
        else:
            if high[t] >= match.stop:
                return ("loss", t - entry_bar)
            if low[t] <= match.target:
                return ("win", t - entry_bar)
    return ("open", -1)


async def backtest_symbol(
    symbol: str,
    *,
    days: int = 10,
    step: int = 5,
    min_history_bars: int = 240,
    daily_lookback: int = 120,
    fetch_m1=None,
    fetch_daily=None,
) -> BacktestReport:
    """Run the backtest. `step` = how often to re-evaluate (bars). Smaller =
    more thorough but slower.

    `fetch_m1` / `fetch_daily` allow swapping the data source (e.g. crypto via
    ccxt). Default = shioaji_fetcher for TWSE.
    """
    if fetch_m1 is None or fetch_daily is None:
        from backend.shioaji_fetcher import shioaji_fetch_daily, shioaji_fetch_m1
        fetch_m1 = fetch_m1 or shioaji_fetch_m1
        fetch_daily = fetch_daily or shioaji_fetch_daily

    logger.info("Fetching %s history (1m × %d days)…", symbol, days)
    full_m1 = await fetch_m1(symbol, days=days)
    if full_m1 is None or full_m1.empty:
        return BacktestReport(symbol=symbol, bars_total=0, bars_evaluated=0)

    daily_df = await fetch_daily(symbol, lookback=daily_lookback)
    full_mtf = (
        full_m1.resample("60min")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["open"])
    )

    # Daily-derived values never change during replay — compute once.
    htf_cache = {
        "struct": (detect_market_structure(daily_df, n=5) if not daily_df.empty
                   else {"structure": "ranging",
                         "swing_points": {"swing_highs": [], "swing_lows": []},
                         "last_bos": None, "last_choch": None}),
        "atr": _atr(daily_df, 14),
        "mtf_levels": compute_mtf_levels(daily_df),
    }

    # numpy-backed index for O(log n) MTF slicing instead of pandas .loc.
    import numpy as _np
    mtf_index_arr = full_mtf.index.to_numpy()
    ltf_index_arr = full_m1.index.to_numpy()

    n = len(full_m1)
    report = BacktestReport(symbol=symbol, bars_total=n, bars_evaluated=0)

    # de-dupe key per signal so we don't re-record the same setup every step
    last_fire: dict[str, int] = {}     # setup_name → last entry bar
    COOLDOWN = 30                       # bars

    last_log_bar = -1
    for t in range(min_history_bars, n, step):
        report.bars_evaluated += 1
        # LTF slice — only need last _LTF_WINDOW bars (context builder will
        # truncate anyway, but doing it here saves the slice cost too).
        ltf_lo = max(0, t + 1 - _LTF_WINDOW)
        ltf_slice = full_m1.iloc[ltf_lo : t + 1]
        mtf_cutoff = ltf_index_arr[t]
        mtf_hi = int(_np.searchsorted(mtf_index_arr, mtf_cutoff, side="right"))
        mtf_lo = max(0, mtf_hi - _MTF_WINDOW)
        mtf_slice = full_mtf.iloc[mtf_lo:mtf_hi]
        try:
            ctx = _build_ctx_from_slice(
                symbol, ltf_slice, daily_df, mtf_slice, htf_cache=htf_cache,
            )
        except Exception:
            logger.exception("context build failed at bar %d", t)
            continue

        for setup in ALL_SETUPS:
            try:
                m = setup.evaluate(ctx)
            except Exception:
                logger.exception("setup %s failed at bar %d", setup.name, t)
                continue
            if m is None or not passes_hard_gates(m):
                continue
            # cooldown
            if setup.name in last_fire and (t - last_fire[setup.name]) < COOLDOWN:
                continue
            last_fire[setup.name] = t

            outcome, dt = _resolve_trade(full_m1, entry_bar=t, match=m)
            ts = ltf_slice.index[-1]
            report.signals.append(BacktestSignal(
                timestamp=ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts),
                bar_idx=t,
                symbol=symbol,
                setup_name=m.setup_name,
                direction=m.direction,
                score=m.score,
                risk_reward=m.risk_reward,
                entry=m.entry,
                stop=m.stop,
                target=m.target,
                outcome=outcome,
                bars_to_resolve=dt,
            ))

        # Light progress logging.
        if t - last_log_bar >= 200 or t == min_history_bars:
            logger.info("  bar %d / %d  (signals so far: %d)", t, n, len(report.signals))
            last_log_bar = t

    return report


# ── output ────────────────────────────────────────────────────────────────────

def write_report(report: BacktestReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"smc_backtest_{report.symbol}.csv"
    summary_path = out_dir / f"smc_backtest_{report.symbol}_summary.txt"

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(BacktestSignal(
            "x", 0, "x", "x", "x", 0, 0.0, 0.0, 0.0, 0.0)).keys()))
        writer.writeheader()
        for s in report.signals:
            writer.writerow(asdict(s))

    lines = [
        f"SMC Analyst — Backtest Report",
        f"  symbol            : {report.symbol}",
        f"  total bars        : {report.bars_total}",
        f"  bars evaluated    : {report.bars_evaluated}",
        f"  signals fired     : {report.fires}",
        f"  wins              : {report.wins}",
        f"  losses            : {report.losses}",
        f"  open (unresolved) : {report.opens}",
        f"  win rate (resolved): {report.win_rate*100:.1f}%",
        f"  avg R:R           : {report.avg_rr:.2f}",
        f"  expectancy (R/signal): {report.expectancy:+.2f}",
        "",
        "By setup:",
    ]
    by_setup: dict[str, list[BacktestSignal]] = {}
    for s in report.signals:
        by_setup.setdefault(s.setup_name, []).append(s)
    for name, sigs in by_setup.items():
        w = sum(1 for s in sigs if s.outcome == "win")
        l = sum(1 for s in sigs if s.outcome == "loss")
        o = sum(1 for s in sigs if s.outcome == "open")
        wr = w / max(1, w + l) * 100
        avg_rr = sum(s.risk_reward for s in sigs) / len(sigs)
        lines.append(f"  {name:34s}  fires={len(sigs):3d}  W{w} L{l} O{o}  "
                     f"wr={wr:5.1f}%  avgR:R={avg_rr:.2f}")

    summary_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, summary_path


# ── CLI entry ─────────────────────────────────────────────────────────────────

async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="+", help="TWSE symbols, e.g. 2330")
    parser.add_argument("--days", type=int, default=10, help="how many trading days of m1 history")
    parser.add_argument("--step", type=int, default=5, help="re-evaluate every N bars")
    parser.add_argument("--out-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    for sym in args.symbols:
        report = await backtest_symbol(sym, days=args.days, step=args.step)
        csv_path, summary_path = write_report(report, args.out_dir)
        print(summary_path.read_text(encoding="utf-8"))
        print(f"\n→ CSV: {csv_path}")
        print(f"→ Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
