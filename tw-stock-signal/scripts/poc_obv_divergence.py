"""
PoC end-to-end run: HiStock chartdata → OBV/集中度 divergence detector.

Goal:
  Validate the indicator pipeline on real data for two contrasting tickers
  (one trend-stable, one historically weak per LESSONS §3.2) and report:
    - level distribution
    - last 30-day per-day detail
  Without these numbers we cannot calibrate THRESHOLD_MEDIUM / STRONG.

Usage:
    python scripts/poc_obv_divergence.py
    python scripts/poc_obv_divergence.py 2330 2454        # custom symbols
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

from loguru import logger

# Make repo root importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrapers.concentration.histock import HistockConcentration  # noqa: E402
from strategy.obv_divergence import evaluate, summarise            # noqa: E402


DEFAULT_SYMBOLS: tuple[str, ...] = ("2330", "2382")
LOOKBACK_DAYS: int = 180


async def run_one(stock_id: str) -> None:
    """Fetch chartdata, run divergence detector, print summary + last-30 detail."""
    logger.info(f"=== {stock_id} ===")
    src = HistockConcentration()
    try:
        df = await src.get_chartdata(stock_id, days=LOOKBACK_DAYS)
    except Exception as exc:
        logger.error(f"[{stock_id}] fetch failed: {type(exc).__name__}: {exc}")
        return

    if df.empty:
        logger.warning(f"[{stock_id}] empty chartdata")
        return

    logger.info(
        f"[{stock_id}] rows={len(df)} "
        f"range={df['date'].min().date()} → {df['date'].max().date()}"
    )

    points = evaluate(df)
    summary = summarise(points)
    logger.info(
        f"[{stock_id}] LEVELS: weak={summary['weak']} | "
        f"medium={summary['medium']} | strong={summary['strong']} | "
        f"confirmed(K={2})={summary['confirmed']} | total={summary['total']}"
    )

    print(f"\nLast 30 days — {stock_id}")
    print("-" * 110)
    print(f"{'date':<12} {'OBV_slope':>11} {'OBV_z':>7} {'CONC_slope':>12} {'CONC_z':>7} "
          f"{'z?':>3} {'level':>7} {'zone':>9} {'conf':>5}")
    for p in points[-30:]:
        z_flag = "z" if p.used_zscore else "p"
        conf = "Y" if p.confirmed else ""
        print(
            f"{p.date.date()!s:<12} "
            f"{p.obv_slope:>11.2f} {p.obv_slope_z:>7.2f} "
            f"{p.conc_slope:>12.4f} {p.conc_slope_z:>7.2f} "
            f"{z_flag:>3} {p.level.value:>7} {p.price_zone.value:>9} {conf:>5}"
        )
    print()


async def main(symbols: tuple[str, ...]) -> None:
    """Run divergence PoC for each symbol sequentially (rate-limit friendly)."""
    for sid in symbols:
        await run_one(sid)


if __name__ == "__main__":
    args = tuple(sys.argv[1:]) if len(sys.argv) > 1 else DEFAULT_SYMBOLS
    asyncio.run(main(args))
