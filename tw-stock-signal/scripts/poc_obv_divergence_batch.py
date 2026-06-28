"""
Batch OBV × concentration divergence PoC across a watchlist.

Why this script:
  Single-symbol PoC (poc_obv_divergence.py) confirmed 2330/2382 signal
  rates land in a sane band. Before wiring DuckDB + cron we need to know
  whether the distribution stays sane across the 7 contrast tickers from
  LESSONS §3.2 (each with very different historical setup performance) —
  otherwise the indicator might be silently 2330/2382-specific.

Output:
  reports/obv_divergence_batch_{YYYYMMDD}.csv   — one row per symbol
  stdout                                        — per-symbol confirmed days

Usage:
    python scripts/poc_obv_divergence_batch.py
    python scripts/poc_obv_divergence_batch.py 2330 2454 3231
"""
from __future__ import annotations
import asyncio
import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrapers.concentration.histock import HistockConcentration  # noqa: E402
from strategy.obv_divergence import (                              # noqa: E402
    DivergenceLevel,
    DivergencePoint,
    PriceZone,
    evaluate,
    summarise,
)


DEFAULT_SYMBOLS: tuple[str, ...] = (
    "2330",  # 台積電 — LESSONS WR 25.8% EV+0.02
    "2317",  # 鴻海 — LESSONS WR 44.5% EV+0.97 (best)
    "2308",  # 台達電 — LESSONS WR 25.2% EV+0.86
    "2382",  # 廣達 — LESSONS WR 7.7% EV-0.17 (worst)
    "2454",  # 聯發科 — LESSONS WR 42.4% EV+0.69
    "2449",  # 京元電子 — Phase 4 watchlist
    "3231",  # 緯創 — AI 概念
)
LOOKBACK_DAYS: int = 180
REPORTS_DIR: Path = Path(__file__).resolve().parents[1] / "reports"


@dataclass(frozen=True)
class SymbolReport:
    """Per-symbol aggregated batch result."""
    symbol: str
    rows: int
    date_min: str
    date_max: str
    weak: int
    medium: int
    strong: int
    confirmed: int
    last_confirmed_date: str
    last_level: str
    last_zone: str
    error: str = ""


def _confirmed_days(points: list[DivergencePoint]) -> list[str]:
    """Return ISO dates of every confirmed bearish divergence in Premium zone."""
    return [str(p.date.date()) for p in points if p.confirmed]


def _build_report(symbol: str, points: list[DivergencePoint]) -> SymbolReport:
    """Reduce per-day points into one SymbolReport row."""
    if not points:
        return SymbolReport(
            symbol=symbol, rows=0, date_min="", date_max="",
            weak=0, medium=0, strong=0, confirmed=0,
            last_confirmed_date="", last_level="", last_zone="",
        )
    summary = summarise(points)
    confirmed_dates = _confirmed_days(points)
    last = points[-1]
    return SymbolReport(
        symbol=symbol,
        rows=summary["total"],
        date_min=str(points[0].date.date()),
        date_max=str(points[-1].date.date()),
        weak=summary["weak"],
        medium=summary["medium"],
        strong=summary["strong"],
        confirmed=summary["confirmed"],
        last_confirmed_date=confirmed_dates[-1] if confirmed_dates else "",
        last_level=last.level.value,
        last_zone=last.price_zone.value,
    )


async def _run_one(symbol: str) -> tuple[SymbolReport, list[DivergencePoint]]:
    """Fetch + evaluate one symbol, never raising — failures become empty reports."""
    src = HistockConcentration()
    try:
        df = await src.get_chartdata(symbol, days=LOOKBACK_DAYS)
    except Exception as exc:
        logger.error(f"[{symbol}] fetch failed: {type(exc).__name__}: {exc}")
        return (
            SymbolReport(
                symbol=symbol, rows=0, date_min="", date_max="",
                weak=0, medium=0, strong=0, confirmed=0,
                last_confirmed_date="", last_level="", last_zone="",
                error=f"{type(exc).__name__}: {exc}",
            ),
            [],
        )
    if df.empty:
        logger.warning(f"[{symbol}] empty chartdata")
        return _build_report(symbol, []), []
    points = evaluate(df)
    return _build_report(symbol, points), points


def _write_csv(reports: list[SymbolReport], path: Path) -> None:
    """Persist batch results — one row per symbol — for diff against future runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "symbol", "rows", "date_min", "date_max",
        "weak", "medium", "strong", "confirmed",
        "last_confirmed_date", "last_level", "last_zone", "error",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in reports:
            writer.writerow(r.__dict__)


def _print_human(reports: list[SymbolReport], details: dict[str, list[str]]) -> None:
    """Console table — sized to fit a 110-col terminal."""
    print()
    print(f"{'symbol':<8} {'rows':>5} {'weak':>5} {'med':>4} {'strong':>7} "
          f"{'conf':>5} {'last_conf':<12} {'last_lvl':<8} {'last_zone':<9} note")
    print("-" * 110)
    for r in reports:
        note = r.error if r.error else ""
        print(
            f"{r.symbol:<8} {r.rows:>5} {r.weak:>5} {r.medium:>4} {r.strong:>7} "
            f"{r.confirmed:>5} {r.last_confirmed_date:<12} "
            f"{r.last_level:<8} {r.last_zone:<9} {note}"
        )
    print()
    print("Confirmed signal dates (Premium Zone + persist K=2):")
    for sym, dates in details.items():
        if dates:
            print(f"  {sym}: {', '.join(dates)}")
        else:
            print(f"  {sym}: (none)")


async def main(symbols: tuple[str, ...]) -> None:
    """Sequentially run each symbol — HiStock 1.5-3s sleep handles rate-limit."""
    reports: list[SymbolReport] = []
    details: dict[str, list[str]] = {}
    for sym in symbols:
        logger.info(f"=== {sym} ===")
        report, points = await _run_one(sym)
        reports.append(report)
        details[sym] = _confirmed_days(points)
        logger.info(
            f"[{sym}] weak={report.weak} med={report.medium} "
            f"strong={report.strong} confirmed={report.confirmed} "
            f"last={report.last_level}/{report.last_zone}"
        )

    out_path = REPORTS_DIR / f"obv_divergence_batch_{datetime.now():%Y%m%d}.csv"
    _write_csv(reports, out_path)
    logger.info(f"CSV written: {out_path}")
    _print_human(reports, details)


if __name__ == "__main__":
    args = tuple(sys.argv[1:]) if len(sys.argv) > 1 else DEFAULT_SYMBOLS
    asyncio.run(main(args))
