"""Run a SMC backtest on crypto (default BTC/USDT) via ccxt + Binance.

Mirrors run_30day_backtest.py but swaps the data layer and switches the
n_pattern session window from TWSE-date-based to a rolling N-hour window.

Usage:
    python run_btc_backtest.py                              # default 30d
    python run_btc_backtest.py --days 14 --step 5
    python run_btc_backtest.py BTC/USDT ETH/USDT --days 30
    python run_btc_backtest.py --session-hours 6            # wider N-pattern window
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

from backend.crypto_data import crypto_fetch_daily, crypto_fetch_m1
from backend.smc_analyst.backtest import (
    BacktestReport, backtest_symbol, write_report,
)

_DEFAULT_SYMBOLS = ["BTC/USDT"]
_DEFAULT_SESSION_HOURS = 4.0  # mirror TWSE session length

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("smc-btc-backtest")


def _summary(reports: list[BacktestReport]) -> str:
    lines = ["", "=" * 70, "SMC Crypto Backtest — Summary", "=" * 70]
    for r in reports:
        lines.append(
            f"{r.symbol:12s}  bars={r.bars_total:>6d}  fires={r.fires:>3d}  "
            f"W{r.wins:>3d} L{r.losses:>3d} O{r.opens:>3d}  "
            f"WR={r.win_rate*100:5.1f}%  EV={r.expectancy:+.2f}R  "
            f"avgR:R={r.avg_rr:.2f}"
        )
        by_setup: dict[str, list] = {}
        for s in r.signals:
            by_setup.setdefault(s.setup_name, []).append(s)
        for name, sigs in sorted(by_setup.items()):
            w = sum(1 for s in sigs if s.outcome == "win")
            ll = sum(1 for s in sigs if s.outcome == "loss")
            o = sum(1 for s in sigs if s.outcome == "open")
            wr = w / max(1, w + ll) * 100
            ev_gain = sum(s.risk_reward for s in sigs if s.outcome == "win")
            ev_loss = sum(1.0 for s in sigs if s.outcome == "loss")
            ev = (ev_gain - ev_loss) / max(1, len(sigs))
            lines.append(
                f"  └─ {name:34s} n={len(sigs):>3d}  W{w} L{ll} O{o}  "
                f"WR={wr:5.1f}%  EV={ev:+.2f}R"
            )
    lines.append("=" * 70)
    return "\n".join(lines)


def _gate(reports: list[BacktestReport]) -> tuple[bool, str]:
    """Step 2 gate: pass if any symbol has WR > 45% AND EV > 0 on resolved trades."""
    for r in reports:
        if r.resolved < 5:
            continue
        if r.win_rate > 0.45 and r.expectancy > 0:
            return True, (
                f"{r.symbol}: WR={r.win_rate*100:.1f}% EV={r.expectancy:+.2f}R "
                f"(n={r.fires}) — PASS"
            )
    worst = max(reports, key=lambda r: r.expectancy, default=None)
    if worst is None:
        return False, "no signals fired"
    return False, (
        f"best {worst.symbol}: WR={worst.win_rate*100:.1f}% "
        f"EV={worst.expectancy:+.2f}R — FAIL (need WR>45% & EV>0)"
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="*", default=_DEFAULT_SYMBOLS,
                        help='ccxt symbol(s), e.g. "BTC/USDT" "ETH/USDT"')
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--step", type=int, default=5,
                        help="evaluate every N bars (smaller = thorougher, slower)")
    parser.add_argument("--session-hours", type=float, default=_DEFAULT_SESSION_HOURS,
                        help="rolling window (hours) for N-pattern session")
    parser.add_argument("--out-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Switch n_pattern from TWSE-date mode → rolling N-hour mode for crypto
    os.environ["SMC_SESSION_WINDOW_HOURS"] = str(args.session_hours)
    logger.info("SMC_SESSION_WINDOW_HOURS=%s (rolling window for N-pattern)",
                args.session_hours)

    t0 = time.time()
    reports: list[BacktestReport] = []
    for sym in args.symbols:
        logger.info("=== %s (days=%d, step=%d) ===", sym, args.days, args.step)
        r = await backtest_symbol(
            sym, days=args.days, step=args.step,
            fetch_m1=crypto_fetch_m1, fetch_daily=crypto_fetch_daily,
        )
        logger.info(
            "  → bars=%d  fires=%d  W%d L%d O%d  WR=%.1f%%  EV=%+.2fR",
            r.bars_total, r.fires, r.wins, r.losses, r.opens,
            r.win_rate * 100, r.expectancy,
        )
        reports.append(r)
        safe_name = sym.replace("/", "_")
        # write_report uses report.symbol; temporarily swap to filesystem-safe form
        original = r.symbol
        object.__setattr__(r, "symbol", safe_name)
        try:
            write_report(r, args.out_dir)
        finally:
            object.__setattr__(r, "symbol", original)

    dt = time.time() - t0
    logger.info("backtest finished in %.1fs", dt)

    print(_summary(reports))
    passed, msg = _gate(reports)
    print()
    print(f"GATE: {msg}")
    print(f"→ next step: {'STEP 2 (Testnet wiring)' if passed else 'STOP / iterate'}")
    return 0 if passed else 0  # exit 0 either way; gate decision is informational


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
