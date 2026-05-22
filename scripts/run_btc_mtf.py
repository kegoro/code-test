"""Run BTC backtest at non-1m timeframes by pre-resampling 1m → target tf.

Usage:
    python scripts/run_btc_mtf.py 5m
    python scripts/run_btc_mtf.py 15m --days 90
    python scripts/run_btc_mtf.py 1h --days 180
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.crypto_data import crypto_fetch_daily, crypto_fetch_m1
from backend.smc_analyst.backtest import backtest_symbol, write_report

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("smc-btc-mtf")


_TF_TO_PANDAS = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "60min"}


def _make_fetch(tf: str):
    """Return a fetch_m1-shaped coroutine that returns `tf`-resampled bars."""
    pandas_freq = _TF_TO_PANDAS[tf]

    async def fetch(symbol: str, days: int) -> "pd.DataFrame":
        df_1m = await crypto_fetch_m1(symbol, days=days)
        if df_1m is None or df_1m.empty:
            return df_1m
        return (
            df_1m.resample(pandas_freq)
            .agg({"open": "first", "high": "max", "low": "min",
                  "close": "last", "volume": "sum"})
            .dropna(subset=["open"])
        )

    return fetch


async def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("tf", choices=list(_TF_TO_PANDAS))
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--symbol", default="BTC/USDT")
    args = p.parse_args()
    tf = args.tf
    days = args.days
    sym = args.symbol

    os.environ["SMC_SESSION_WINDOW_HOURS"] = "4.0"
    out_dir = Path("reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    safe = sym.replace("/", "_") + f"_{tf}_{days}d"

    t0 = time.time()
    r = await backtest_symbol(
        sym, days=days, step=1,
        fetch_m1=_make_fetch(tf), fetch_daily=crypto_fetch_daily,
    )
    dt = time.time() - t0

    print(f"\n=== {sym} {tf} ({days}d) ===")
    print(f"bars={r.bars_total}  fires={r.fires}  W{r.wins} L{r.losses} O{r.opens}  "
          f"WR={r.win_rate*100:.1f}%  EV={r.expectancy:+.2f}R  "
          f"avgR:R={r.avg_rr:.2f}  time={dt:.1f}s")

    by: dict[str, list] = {}
    for s in r.signals:
        by.setdefault(s.setup_name, []).append(s)
    for name, sigs in sorted(by.items()):
        w = sum(1 for s in sigs if s.outcome == "win")
        l = sum(1 for s in sigs if s.outcome == "loss")
        o = sum(1 for s in sigs if s.outcome == "open")
        wr = w / max(1, w + l) * 100
        evg = sum(s.risk_reward for s in sigs if s.outcome == "win")
        ev = (evg - l) / max(1, len(sigs))
        print(f"  └─ {name:34s} n={len(sigs):3d}  W{w} L{l} O{o}  "
              f"WR={wr:5.1f}%  EV={ev:+.2f}R")

    # Save report under tf-suffixed name without mutating frozen-ish state.
    original = r.symbol
    object.__setattr__(r, "symbol", safe)
    try:
        write_report(r, out_dir)
    finally:
        object.__setattr__(r, "symbol", original)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
