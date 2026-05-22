"""Standalone SMC end-to-end test.

Run:
    python test_smc.py [SYMBOL]

Defaults to 2330 (TSMC). Pulls daily + 3-minute bars via the existing
Shioaji fetcher, runs SMC detection, prints every signal, and writes a
single HTML report to reports/smc_test.html.

Graceful behaviour:
- If Shioaji is unreachable or returns empty intraday data (e.g. after-hours
  on a holiday), falls back to the daily frame.
- If both frames are empty, prints a clear diagnostic and exits non-zero.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from backend.shioaji_fetcher import shioaji_fetch_daily, shioaji_fetch_m3
from backend.smc_detector import (
    detect_market_structure,
    detect_signals,
    find_demand_zones,
    find_supply_zones,
    find_swing_points,
)
from backend.smc_report import generate_html

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("smc-test")

_REPORTS_DIR = Path(__file__).resolve().parent / "reports"
_REPORTS_DIR.mkdir(exist_ok=True)


async def _run(symbol: str) -> int:
    logger.info("fetching %s daily…", symbol)
    daily = await shioaji_fetch_daily(symbol, lookback=60)
    logger.info("fetching %s 3m…", symbol)
    m3 = await shioaji_fetch_m3(symbol)

    if daily is None or daily.empty:
        logger.error("no daily data for %s — abort", symbol)
        return 2

    using_intraday = m3 is not None and not m3.empty and len(m3) >= 20
    target_df = m3 if using_intraday else daily
    tf = "3m" if using_intraday else "1D"
    n = 3 if using_intraday else 5

    sp = find_swing_points(target_df, n=n)
    ms = detect_market_structure(target_df, n=n)
    dz = find_demand_zones(target_df, sp)
    sz = find_supply_zones(target_df, sp)
    signals = detect_signals(target_df, symbol, timeframe=tf, n=n)

    print(f"\n=== SMC report for {symbol} ({tf}) ===")
    print(f"bars             : {len(target_df)}")
    print(f"swing highs/lows : {len(sp['swing_highs'])} / {len(sp['swing_lows'])}")
    print(f"structure        : {ms['structure']}")
    print(f"last BOS         : {ms['last_bos']}")
    print(f"last CHoCH       : {ms['last_choch']}")
    print(f"demand zones     : {len(dz)} ({sum(1 for z in dz if z['valid'])} valid)")
    print(f"supply zones     : {len(sz)} ({sum(1 for z in sz if z['valid'])} valid)")
    print(f"emitted signals  : {len(signals)}")
    for s in signals:
        print(f"  • {s.signal_type} @ {s.price:.2f}  ts={s.timestamp}  strength={s.strength}")

    # Build at least one signal for the HTML report, even when nothing fired.
    from backend.smc_detector import SMCSignal

    if signals:
        signal_for_report = signals[-1]
    else:
        signal_for_report = SMCSignal(
            symbol=symbol,
            timeframe=tf,
            signal_type="BOS_UP" if ms["structure"] == "bullish" else "BOS_DOWN",
            price=float(target_df["close"].iloc[-1]),
            market_structure=ms["structure"],
            timestamp=target_df.index[-1].to_pydatetime() if hasattr(target_df.index[-1], "to_pydatetime") else target_df.index[-1],
            strength=1,
            demand_zone=next((z for z in dz if z["valid"]), None),
            supply_zone=next((z for z in sz if z["valid"]), None),
            meta={"last_close": float(target_df["close"].iloc[-1]),
                  "synthetic": True},
        )

    html = generate_html(
        signal_for_report,
        daily_df=daily,
        intraday_df=m3,
        fallback_to_daily=not using_intraday,
    )
    out = _REPORTS_DIR / "smc_test.html"
    out.write_text(html, encoding="utf-8")
    print(f"\nHTML written → {out}")
    return 0


def main() -> int:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "2330"
    try:
        return asyncio.run(_run(symbol))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
